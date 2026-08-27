"""Deterministic audit for raw API or materialized YOLO training snapshots."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import cv2

try:
    from .dataset_exporter import materialize
except ImportError:  # Support direct ``python training/dataset_audit.py`` execution.
    from dataset_exporter import materialize


IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".webp"})
SPLITS = ("train", "val", "test")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _dhash(gray: Any) -> str:
    resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = resized[:, 1:] > resized[:, :-1]
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def _hamming(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _class_names(snapshot: Path, manifest: dict[str, Any]) -> dict[int, str]:
    names: dict[int, str] = {}
    data_yaml = snapshot / "data.yaml"
    if data_yaml.is_file():
        in_names = False
        for raw_line in data_yaml.read_text(encoding="utf-8").splitlines():
            if raw_line.strip() == "names:":
                in_names = True
                continue
            if not in_names:
                continue
            if raw_line and not raw_line[0].isspace():
                break
            stripped = raw_line.strip()
            if not stripped or ":" not in stripped:
                continue
            index, label = stripped.split(":", 1)
            try:
                names[int(index.strip())] = label.strip().strip("'\"")
            except ValueError:
                continue
    if names:
        return names
    labels = sorted({str(item.get("label") or "").strip() for item in manifest.get("samples", []) if item.get("label")})
    return {index: label for index, label in enumerate(labels)}


def _manifest_image_sources(manifest: dict[str, Any]) -> dict[tuple[str, str], str]:
    """Recreate materialized image stems so source-level leakage is measurable."""
    if manifest.get("schemaVersion") == 3:
        sources: dict[tuple[str, str], str] = {}
        for item in manifest.get("frames", []):
            if not isinstance(item, dict):
                continue
            split = str(item.get("split") or "")
            image_path = str(item.get("imagePath") or "")
            source_id = str(item.get("sourceId") or "")
            if split in SPLITS and image_path and source_id:
                sources[(split, Path(image_path).stem)] = source_id
        return sources
    grouped: dict[tuple[str, str, int | None, str], list[dict[str, Any]]] = defaultdict(list)
    for item in manifest.get("samples", []):
        if not isinstance(item, dict):
            continue
        split = str(item.get("split") or "")
        if split not in SPLITS:
            continue
        key = (
            str(item.get("mediaPath") or ""),
            str(item.get("mediaKind") or ""),
            item.get("frameTimestampMs"),
            split,
        )
        grouped[key].append(item)

    sources: dict[tuple[str, str], str] = {}
    for (*_, split), items in grouped.items():
        ordered = sorted(items, key=lambda item: str(item.get("sampleId") or ""))
        sample_ids = [str(item.get("sampleId") or "") for item in ordered]
        stem = sample_ids[0]
        if len(sample_ids) > 1:
            digest = hashlib.sha256("|".join(sample_ids).encode("utf-8")).hexdigest()[:20]
            stem = f"source-{digest}"
        source_ids = sorted({str(item.get("sourceId") or "") for item in ordered if item.get("sourceId")})
        sources[(split, stem)] = source_ids[0] if len(source_ids) == 1 else "|".join(source_ids)
    return sources


def _audit_materialized_dataset(
    snapshot: Path,
    manifest: dict[str, Any],
    report_name: str,
    near_duplicate_distance: int,
    prior_median_percent: float | None,
) -> dict[str, Any]:
    class_names = _class_names(snapshot, manifest)
    image_sources = _manifest_image_sources(manifest)

    images: list[dict[str, Any]] = []
    per_class: Counter[str] = Counter()
    per_source: dict[str, dict[str, Any]] = {}
    split_stats = {split: {"images": 0, "boxes": 0, "negatives": 0, "sources": 0} for split in SPLITS}
    bbox_areas: list[float] = []
    edge_touch_count = 0
    missing_label_files: list[str] = []
    invalid_annotations: list[dict[str, str]] = []
    unreadable_images: list[str] = []

    for split in SPLITS:
        image_dir = snapshot / "images" / split
        if not image_dir.is_dir():
            continue
        for image_path in sorted(path for path in image_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES):
            relative = image_path.relative_to(snapshot).as_posix()
            label_path = snapshot / "labels" / split / f"{image_path.stem}.txt"
            source_id = image_sources.get((split, image_path.stem), f"unmapped:{relative}")
            box_count = 0
            annotation_line_count = 0
            label_exists = label_path.is_file()
            if not label_exists:
                missing_label_files.append(relative)
            else:
                for line_number, raw_line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
                    line = raw_line.strip()
                    if not line:
                        continue
                    annotation_line_count += 1
                    fields = line.split()
                    try:
                        if len(fields) != 5:
                            raise ValueError("expected five YOLO fields")
                        class_id = int(fields[0])
                        if class_id not in class_names:
                            raise ValueError(f"unknown class id {class_id}")
                        center_x, center_y, width, height = (float(value) for value in fields[1:])
                        if class_id < 0 or width <= 0 or height <= 0:
                            raise ValueError("class and dimensions must be positive")
                        if not all(math.isfinite(value) for value in (center_x, center_y, width, height)):
                            raise ValueError("coordinates must be finite")
                        left, top = center_x - width / 2.0, center_y - height / 2.0
                        right, bottom = center_x + width / 2.0, center_y + height / 2.0
                        if left < -1e-6 or top < -1e-6 or right > 1.000001 or bottom > 1.000001:
                            raise ValueError("box falls outside normalized image bounds")
                    except (TypeError, ValueError) as error:
                        invalid_annotations.append({"path": label_path.relative_to(snapshot).as_posix(), "line": str(line_number), "reason": str(error)})
                        continue
                    label = class_names.get(class_id, f"class_{class_id}")
                    area = width * height
                    bbox_areas.append(area)
                    per_class[label] += 1
                    box_count += 1
                    if left <= 1e-6 or top <= 1e-6 or right >= 0.999999 or bottom >= 0.999999:
                        edge_touch_count += 1

            gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            if gray is None:
                unreadable_images.append(relative)
                resolution = None
                perceptual_hash = None
            else:
                resolution = f"{gray.shape[1]}x{gray.shape[0]}"
                perceptual_hash = _dhash(gray)
            record = {
                "path": relative,
                "split": split,
                "sourceId": source_id,
                "boxes": box_count,
                "negative": label_exists and annotation_line_count == 0,
                "sha256": _sha256(image_path),
                "dhash": perceptual_hash,
                "resolution": resolution,
            }
            images.append(record)
            split_stats[split]["images"] += 1
            split_stats[split]["boxes"] += box_count
            if record["negative"]:
                split_stats[split]["negatives"] += 1
            source = per_source.setdefault(source_id, {"images": 0, "boxes": 0, "splits": set()})
            source["images"] += 1
            source["boxes"] += box_count
            source["splits"].add(split)

    for split in SPLITS:
        split_stats[split]["sources"] = sum(1 for source in per_source.values() if split in source["splits"])

    hashes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in images:
        hashes[item["sha256"]].append(item)
    exact_groups = [
        {"sha256": digest, "images": [item["path"] for item in group], "splits": sorted({item["split"] for item in group})}
        for digest, group in sorted(hashes.items()) if len(group) > 1
    ]

    near_pairs: list[dict[str, Any]] = []
    readable = [item for item in images if item["dhash"] is not None]
    for index, left in enumerate(readable):
        for right in readable[index + 1:]:
            if left["sha256"] == right["sha256"]:
                continue
            distance = _hamming(left["dhash"], right["dhash"])
            if distance <= near_duplicate_distance:
                near_pairs.append({"left": left["path"], "right": right["path"], "distance": distance})

    resolution_counts = Counter(item["resolution"] for item in images if item["resolution"])
    source_leakage = [
        {"sourceId": source_id, "splits": sorted(details["splits"])}
        for source_id, details in sorted(per_source.items()) if len(details["splits"]) > 1
    ]
    exact_split_leakage = [group for group in exact_groups if len(group["splits"]) > 1]
    negative_count = sum(1 for item in images if item["negative"])
    bucket_counts = {
        "smallLt1Pct": sum(area < 0.01 for area in bbox_areas),
        "medium1To10Pct": sum(0.01 <= area < 0.10 for area in bbox_areas),
        "largeGte10Pct": sum(area >= 0.10 for area in bbox_areas),
    }
    percentiles = {
        f"p{percentile}": round(value, 10) if (value := _percentile(bbox_areas, percentile)) is not None else None
        for percentile in (0, 10, 25, 50, 75, 90, 100)
    }
    serialized_sources = {
        source_id: {"images": details["images"], "boxes": details["boxes"], "splits": sorted(details["splits"])}
        for source_id, details in sorted(per_source.items())
    }
    median_percent = (percentiles["p50"] * 100.0) if percentiles["p50"] is not None else None
    reconciliation = None if prior_median_percent is None or median_percent is None else {
        "priorDocumentedMedianPercent": prior_median_percent,
        "verifiedMedianPercent": round(median_percent, 8),
        "differencePercentagePoints": round(median_percent - prior_median_percent, 8),
    }
    return {
        "schemaVersion": 1,
        "snapshot": report_name,
        "origin": manifest.get("origin"),
        "trainingProfile": manifest.get("profile"),
        "requiredClasses": manifest.get("requiredClasses") if isinstance(manifest.get("requiredClasses"), list) else [],
        "summary": {
            "imageCount": len(images),
            "bboxCount": len(bbox_areas),
            "classCount": len(per_class),
            "sourceCount": len(per_source),
            "negativeImageCount": negative_count,
            "negativeRatio": round(negative_count / len(images), 6) if images else 0.0,
            "edgeTouchCount": edge_touch_count,
            "missingLabelFileCount": len(missing_label_files),
            "invalidAnnotationCount": len(invalid_annotations),
            "unreadableImageCount": len(unreadable_images),
        },
        "perClass": dict(sorted(per_class.items())),
        "perSource": serialized_sources,
        "splits": split_stats,
        "bboxAreas": {"buckets": bucket_counts, "percentiles": percentiles},
        "evidenceReconciliation": reconciliation,
        "resolutions": dict(sorted(resolution_counts.items())),
        "duplicates": {
            "exactGroups": exact_groups,
            "nearDuplicateDistance": near_duplicate_distance,
            "nearPairs": near_pairs,
        },
        "leakage": {"sourcesAcrossSplits": source_leakage, "exactDuplicatesAcrossSplits": exact_split_leakage},
        "qualityIssues": {
            "missingLabelFiles": missing_label_files,
            "invalidAnnotations": invalid_annotations,
            "unreadableImages": unreadable_images,
        },
    }


def audit_dataset(
    snapshot_dir: Path,
    near_duplicate_distance: int = 5,
    prior_median_percent: float | None = None,
) -> dict[str, Any]:
    """Audit either a raw API snapshot or an already-materialized snapshot.

    API exports contain only ``manifest.json`` and immutable ``media/*``. They
    are materialized inside an isolated temporary directory, audited there,
    and removed automatically. Existing materialized snapshots are scanned in
    place without mutation.
    """
    snapshot = snapshot_dir.resolve()
    if not snapshot.is_dir():
        raise FileNotFoundError(f"Dataset snapshot does not exist: {snapshot}")
    manifest_path = snapshot / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Dataset snapshot has no manifest.json: {snapshot}")
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_version = manifest.get("schemaVersion")
    if schema_version not in {2, 3}:
        raise ValueError("Unsupported training manifest version")

    if schema_version == 3:
        if manifest.get("datasetKind") != "LOCAL_VIDEO_REVIEWED" or manifest.get("reviewStatus") != "REVIEWED":
            raise ValueError("Local-video snapshot is not fully reviewed")
        if not isinstance(manifest.get("frames"), list) or not manifest["frames"]:
            raise ValueError("Reviewed local-video manifest has no frames")

    has_materialized_images = any((snapshot / "images" / split).is_dir() for split in SPLITS)
    if has_materialized_images:
        return _audit_materialized_dataset(snapshot, manifest, snapshot.name, near_duplicate_distance, prior_median_percent)

    with tempfile.TemporaryDirectory(prefix="sentriai-dataset-audit-") as directory:
        materialized = materialize(manifest_path, Path(directory))
        return _audit_materialized_dataset(materialized, manifest, snapshot.name, near_duplicate_distance, prior_median_percent)


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    origin = report.get("origin") or {}
    origin_text = origin.get("archiveName") or origin.get("kind") or "Không có metadata nguồn"
    exact_count = len(report["duplicates"]["exactGroups"])
    near_count = len(report["duplicates"]["nearPairs"])
    source_leakage_count = len(report["leakage"]["sourcesAcrossSplits"])
    lines = [
        f"# Audit dataset `{report['snapshot']}`",
        "",
        f"Snapshot: `{report['snapshot']}`  ",
        f"Nguồn khai báo: `{origin_text}`",
        "",
        "## Kết quả định lượng",
        "",
        "| Chỉ số | Giá trị |",
        "| --- | ---: |",
        f"| Ảnh | {summary['imageCount']} |",
        f"| Bounding box | {summary['bboxCount']} |",
        f"| Nguồn | {summary['sourceCount']} |",
        f"| Ảnh negative/hard-negative | {summary['negativeImageCount']} ({summary['negativeRatio'] * 100:.2f}%) |",
        f"| Box chạm mép ảnh | {summary['edgeTouchCount']} |",
        f"| Exact duplicate groups | {exact_count} |",
        f"| Near-duplicate pairs (dHash ≤ {report['duplicates']['nearDuplicateDistance']}) | {near_count} |",
        f"| Source xuất hiện ở nhiều split | {source_leakage_count} |",
        "",
        "## Split",
        "",
        "| Split | Ảnh | Box | Negative | Nguồn |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for split in SPLITS:
        values = report["splits"][split]
        lines.append(f"| {split} | {values['images']} | {values['boxes']} | {values['negatives']} | {values['sources']} |")
    buckets = report["bboxAreas"]["buckets"]
    percentiles = report["bboxAreas"]["percentiles"]
    class_summary = ", ".join(f"{label}: {count}" for label, count in report["perClass"].items()) or "Không có bbox hợp lệ"
    lines.extend([
        "",
        "## Phân bố kích thước bbox",
        "",
        f"- Nhỏ hơn 1% diện tích ảnh: {buckets['smallLt1Pct']}",
        f"- Từ 1% đến dưới 10%: {buckets['medium1To10Pct']}",
        f"- Từ 10% trở lên: {buckets['largeGte10Pct']}",
        f"- Median diện tích chuẩn hóa: {(percentiles['p50'] or 0) * 100:.5f}%",
        "",
        "## Provenance và class mapping",
        "",
        f"- Loại nguồn trong manifest: `{origin.get('kind') or 'không khai báo'}`.",
        f"- Archive trong manifest: `{origin.get('archiveName') or 'không khai báo'}`.",
        f"- Training profile: `{report.get('trainingProfile') or 'không khai báo'}`.",
        f"- Phân bố class đo từ label files: {class_summary}.",
        "",
    ])
    source_mapping = origin.get("sourceLabelMap") if isinstance(origin.get("sourceLabelMap"), dict) else {}
    if source_mapping:
        for source_label, mapping in sorted(source_mapping.items()):
            if isinstance(mapping, dict):
                lines.append(
                    f"- Mapping nguồn `{source_label}` → `{mapping.get('label') or 'không khai báo'}` / `{mapping.get('baseClass') or 'không khai báo'}`."
                )
    else:
        lines.append("- Manifest không khai báo `origin.sourceLabelMap`.")
    required_classes = report.get("requiredClasses") or []
    if required_classes:
        for item in required_classes:
            if isinstance(item, dict):
                lines.append(f"- Class contract `{item.get('label')}` / `{item.get('baseClass')}`.")
    else:
        lines.append("- Manifest không đóng băng `requiredClasses`; class được suy ra từ samples theo quy tắc tương thích snapshot cũ.")

    duplicate_evidence = (
        f"Phát hiện {exact_count} exact duplicate group và {near_count} near-duplicate pair ở ngưỡng dHash {report['duplicates']['nearDuplicateDistance']}."
        if exact_count or near_count
        else f"Không phát hiện exact duplicate hoặc near-duplicate ở ngưỡng dHash {report['duplicates']['nearDuplicateDistance']}."
    )
    leakage_evidence = (
        f"Phát hiện {source_leakage_count} source xuất hiện ở nhiều split."
        if source_leakage_count
        else "Không phát hiện sourceId xuất hiện ở nhiều split."
    )
    negative_evidence = (
        "Không có ảnh negative, nên dataset không cung cấp evidence để định lượng false-positive rate trên cảnh không có target."
        if summary["negativeImageCount"] == 0
        else f"Có {summary['negativeImageCount']} ảnh negative ({summary['negativeRatio'] * 100:.2f}%); report không suy đoán các ảnh này bao phủ background category nào."
    )
    edge_evidence = (
        f"Có {summary['edgeTouchCount']} bbox chạm mép ảnh; đây là danh sách ưu tiên cho kiểm tra clipping thủ công."
        if summary["edgeTouchCount"]
        else "Không có bbox chạm mép ảnh theo tọa độ annotation."
    )
    lines.extend([
        "",
        "## Kết luận từ evidence",
        "",
        f"- Có {summary['sourceCount']} sourceId phân biệt trong manifest/materialized output. Chỉ số này không tự chứng minh số camera, phiên quay hoặc time block độc lập.",
        f"- Có {buckets['smallLt1Pct']} bbox dưới 1%, {buckets['medium1To10Pct']} bbox từ 1% đến dưới 10%, và {buckets['largeGte10Pct']} bbox từ 10% diện tích ảnh trở lên.",
        f"- {negative_evidence}",
        f"- {edge_evidence}",
        f"- {duplicate_evidence}",
        f"- {leakage_evidence}",
    ])
    reconciliation = report.get("evidenceReconciliation")
    if reconciliation:
        lines.extend([
            "",
            "## Đối soát số liệu median",
            "",
            f"Tài liệu trước đó ghi `{reconciliation['priorDocumentedMedianPercent']:.2f}%`. Audit deterministic từ chính snapshot này xác minh `{reconciliation['verifiedMedianPercent']:.5f}%`; chênh lệch `{reconciliation['differencePercentagePoints']:.5f}` điểm phần trăm. Giá trị đã xác minh thay thế số cũ.",
        ])
    lines.extend([
        "",
        "## Phạm vi kết luận",
        "",
        "Công cụ chỉ đo metadata, annotation và đặc trưng ảnh có thể kiểm chứng. Nó không suy đoán loại background, mức độ gần/xa hay tính đúng nghĩa của bbox từ pixel; các nội dung đó cần người review thủ công.",
        "",
        "Report này không tự gán dataset là golden validation set hoặc domain match; quyết định đó cần protocol đánh giá và provenance bổ sung ngoài các trường hiện có.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--near-duplicate-distance", type=int, default=5)
    parser.add_argument("--prior-median-percent", type=float)
    args = parser.parse_args()
    if not 0 <= args.near_duplicate_distance <= 64:
        parser.error("--near-duplicate-distance must be between 0 and 64")
    report = audit_dataset(args.snapshot, args.near_duplicate_distance, args.prior_median_percent)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
