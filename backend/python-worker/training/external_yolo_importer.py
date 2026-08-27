"""Safely filter a local Roboflow/YOLO archive into an immutable snapshot.

Large community archives are scanned in place. Only canonical reach-stacker
positives and a bounded set of confusing-equipment hard negatives are copied;
the archive's augmented split is rebuilt by pre-augmentation source.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import yaml

EVENT_PREFIX = "SENTRIAI_EXTERNAL_DATASET "
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 8 * 1024 * 1024 * 1024
MAX_ENTRY_BYTES = 256 * 1024 * 1024
MAX_SELECTED_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 500
TARGET_LABEL = "Xe nâng container"
TARGET_BASE_CLASS = "reach_stacker"
TARGET_ALIASES = frozenset({"stacker", "reach stacker", "reach-stacker", "reach_stacker"})
HARD_NEGATIVE_CLASSES = frozenset({
    "container crane", "dump truck", "excavator", "mobile crane", "straddle carrier",
})
HARD_NEGATIVE_SHARE = 0.30
DEFAULT_LABEL_MAP = {
    alias: {"label": TARGET_LABEL, "baseClass": TARGET_BASE_CLASS}
    for alias in sorted(TARGET_ALIASES)
}
_ROBOFLOW_AUGMENTED_STEM = re.compile(r"^(?P<source>.+)\.rf\.[^.]+$", re.IGNORECASE)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_stream(stream: Any) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"Unsafe archive entry: {name}")
    return path.as_posix()


def _read_entries(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    entries: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = _safe_name(info.filename)
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError(f"Archive links are not allowed: {name}")
        if info.file_size > MAX_ENTRY_BYTES:
            raise ValueError(f"Archive entry exceeds the 256 MiB safety limit: {name}")
        if info.file_size > 1024 * 1024:
            ratio = info.file_size / max(1, info.compress_size)
            if ratio > MAX_COMPRESSION_RATIO:
                raise ValueError(f"Archive entry has an unsafe compression ratio: {name}")
        if name in entries:
            previous = entries[name]
            if max(previous.file_size, info.file_size) > 1024 * 1024:
                raise ValueError(f"Large duplicate archive entry is not allowed: {name}")
            if archive.read(previous) != archive.read(info):
                raise ValueError(f"Conflicting duplicate archive entry: {name}")
            continue
        total += info.file_size
        if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ValueError("Archive exceeds the 8 GiB metadata safety limit")
        entries[name] = info
    return entries


def _names(dataset_config: dict[str, Any]) -> dict[int, str]:
    raw_names = dataset_config.get("names")
    if isinstance(raw_names, list):
        names = {index: str(value).strip() for index, value in enumerate(raw_names)}
    elif isinstance(raw_names, dict):
        names = {int(index): str(value).strip() for index, value in raw_names.items()}
    else:
        raise ValueError("data.yaml must define class names")
    if not names or any(not value for value in names.values()):
        raise ValueError("data.yaml contains an empty class name")
    return names


def _number(value: str, context: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value in {context}") from exc
    if not math.isfinite(number):
        raise ValueError(f"Non-finite numeric value in {context}")
    return number


def _bbox(values: list[str], context: str) -> tuple[int, dict[str, float]]:
    if len(values) < 5:
        raise ValueError(f"Annotation has too few values in {context}")
    class_value = _number(values[0], context)
    if class_value < 0 or class_value != int(class_value):
        raise ValueError(f"Annotation class is invalid in {context}")
    class_id = int(class_value)
    coordinates = [_number(value, context) for value in values[1:]]
    if len(coordinates) == 4:
        center_x, center_y, width, height = coordinates
        x, y = center_x - width / 2, center_y - height / 2
    elif len(coordinates) >= 6 and len(coordinates) % 2 == 0:
        xs, ys = coordinates[0::2], coordinates[1::2]
        x, y = min(xs), min(ys)
        width, height = max(xs) - x, max(ys) - y
    else:
        raise ValueError(f"Annotation is neither YOLO bbox nor polygon in {context}")
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < width <= 1 and 0 < height <= 1 and x + width <= 1 and y + height <= 1):
        raise ValueError(f"Annotation bbox is outside the normalized image in {context}")
    return class_id, {"x": round(x, 8), "y": round(y, 8), "w": round(width, 8), "h": round(height, 8)}


def _image_entries(entries: dict[str, zipfile.ZipInfo]) -> list[str]:
    images: list[str] = []
    for name in entries:
        parts = PurePosixPath(name).parts
        if len(parts) != 3 or parts[0] not in {"train", "valid", "test"} or parts[1] != "images":
            continue
        if PurePosixPath(name).suffix.casefold() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        images.append(name)
    if not images:
        raise ValueError("Archive contains no supported image files")
    return sorted(images)


def _label_path(image_path: str) -> str:
    image = PurePosixPath(image_path)
    return PurePosixPath(image.parts[0], "labels", f"{image.stem}.txt").as_posix()


def _source_key(image_path: str) -> str:
    image = PurePosixPath(image_path)
    match = _ROBOFLOW_AUGMENTED_STEM.match(image.stem)
    if match:
        return match.group("source")
    # Identically named files in different original splits are not assumed to
    # be the same source unless Roboflow's augmentation suffix proves it.
    return f"{image.parts[0]}:{image.stem}"


def _assign_source_splits(sources: Iterable[str]) -> dict[str, str]:
    ordered = sorted(set(sources), key=lambda value: (_sha256_bytes(value.encode("utf-8")), value))
    count = len(ordered)
    if count == 0:
        return {}
    if count == 1:
        return {ordered[0]: "train"}
    if count == 2:
        return {ordered[0]: "train", ordered[1]: "val"}
    test_count = max(1, round(count * 0.10))
    val_count = max(1, round(count * 0.10))
    if test_count + val_count >= count:
        test_count = val_count = 1
    train_end = count - val_count - test_count
    return {
        source: "train" if index < train_end else ("val" if index < count - test_count else "test")
        for index, source in enumerate(ordered)
    }


def _choose_hard_negatives(candidates: list[dict[str, Any]], positive_image_count: int) -> list[dict[str, Any]]:
    if not candidates or positive_image_count <= 0:
        return []
    desired = max(1, round(positive_image_count * HARD_NEGATIVE_SHARE / (1 - HARD_NEGATIVE_SHARE)))
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        by_source[candidate["sourceKey"]].append(candidate)
    for records in by_source.values():
        records.sort(key=lambda item: (_sha256_bytes(item["imagePath"].encode("utf-8")), item["imagePath"]))
    source_order = sorted(by_source, key=lambda value: (_sha256_bytes(value.encode("utf-8")), value))
    selected: list[dict[str, Any]] = []
    variant = 0
    while len(selected) < min(desired, len(candidates)):
        added = False
        for source in source_order:
            records = by_source[source]
            if variant < len(records):
                selected.append(records[variant])
                added = True
                if len(selected) >= desired:
                    break
        if not added:
            break
        variant += 1
    return selected


def _write_atomic(path: Path, text: str) -> None:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False)
    try:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        Path(handle.name).replace(path)
    finally:
        if not handle.closed:
            handle.close()
        Path(handle.name).unlink(missing_ok=True)


def _copy_entry_atomic(archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path) -> None:
    if target.is_file():
        with target.open("rb") as existing:
            if _sha256_stream(existing) == target.stem:
                return
        raise ValueError(f"Immutable media collision for {target.name}")
    temporary = target.with_name(f".{target.name}.{os.getpid()}.part")
    try:
        with archive.open(info) as source, temporary.open("xb") as destination:
            while chunk := source.read(1024 * 1024):
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def import_external_yolo_archive(archive_path: Path, output_root: Path) -> dict[str, Any]:
    """Filter a local YOLO archive and return an immutable reach-stacker snapshot."""
    source = archive_path.resolve()
    if not source.is_file() or source.suffix.casefold() != ".zip":
        raise ValueError("External dataset must be an existing .zip archive")

    with zipfile.ZipFile(source) as archive:
        entries = _read_entries(archive)
        config_info = entries.get("data.yaml")
        if not config_info:
            raise ValueError("Archive must contain data.yaml at its root")
        try:
            config = yaml.safe_load(archive.read(config_info)) or {}
        except yaml.YAMLError as exc:
            raise ValueError("data.yaml is invalid") from exc
        if not isinstance(config, dict):
            raise ValueError("data.yaml must contain an object")
        names = _names(config)
        target_class_ids = {
            class_id for class_id, name in names.items() if name.casefold() in TARGET_ALIASES
        }
        if not target_class_ids:
            raise ValueError("Archive does not define a supported Reach Stacker class")

        records: list[dict[str, Any]] = []
        for image_path in _image_entries(entries):
            label_path = _label_path(image_path)
            if label_path not in entries:
                raise ValueError(f"Image is missing annotation file: {image_path}")
            label_content = archive.read(entries[label_path]).decode("utf-8-sig")
            target_boxes: list[dict[str, float]] = []
            class_names: set[str] = set()
            for index, raw_line in enumerate(label_content.splitlines()):
                line = raw_line.strip()
                if not line:
                    continue
                parts = line.split()
                if not parts:
                    continue
                try:
                    class_id = int(parts[0])
                except ValueError as exc:
                    raise ValueError(
                        f"Annotation class must be an integer in {label_path}:{index + 1}"
                    ) from exc
                source_label = names.get(class_id)
                if source_label is None:
                    raise ValueError(f"Annotation class {class_id} is absent from data.yaml")
                class_names.add(source_label)
                if class_id in target_class_ids:
                    _, box = _bbox(parts, f"{label_path}:{index + 1}")
                    target_boxes.append(box)
            records.append({
                "imagePath": image_path,
                "sourceKey": _source_key(image_path),
                "targetBoxes": target_boxes,
                "classNames": sorted(class_names),
            })

        positive_records = [record for record in records if record["targetBoxes"]]
        if not positive_records:
            raise ValueError("Archive has no Reach Stacker annotations")
        positive_sources = {record["sourceKey"] for record in positive_records}
        negative_candidates = [
            record for record in records
            if not record["targetBoxes"]
            and record["sourceKey"] not in positive_sources
            and any(name.casefold() in HARD_NEGATIVE_CLASSES for name in record["classNames"])
        ]
        negative_records = _choose_hard_negatives(negative_candidates, len(positive_records))
        positive_splits = _assign_source_splits(positive_sources)
        negative_splits = _assign_source_splits(record["sourceKey"] for record in negative_records)

        config_identity = _sha256_bytes(archive.read(config_info))[:12]
        archive_namespace = _sha256_bytes(f"{source.name}:{config_identity}".encode("utf-8"))[:12]
        selected = [*positive_records, *negative_records]
        selected_bytes = sum(entries[record["imagePath"]].file_size for record in selected)
        if selected_bytes > MAX_SELECTED_UNCOMPRESSED_BYTES:
            raise ValueError("Filtered dataset exceeds the 2 GiB selected-media safety limit")

        image_metadata: dict[str, dict[str, str]] = {}
        for record in selected:
            info = entries[record["imagePath"]]
            with archive.open(info) as stream:
                media_hash = _sha256_stream(stream)
            extension = PurePosixPath(record["imagePath"]).suffix.casefold()
            image_metadata[record["imagePath"]] = {
                "sha256": media_hash,
                "mediaPath": f"media/{media_hash}{extension}",
            }

        samples: list[dict[str, Any]] = []
        for record in positive_records:
            metadata = image_metadata[record["imagePath"]]
            source_id = f"external:{archive_namespace}:{record['sourceKey']}"
            for index, box in enumerate(record["targetBoxes"]):
                samples.append({
                    "sampleId": f"external-{metadata['sha256'][:20]}-{index}",
                    "label": TARGET_LABEL,
                    "baseClass": TARGET_BASE_CLASS,
                    "sourceId": source_id,
                    "mediaKind": "IMAGE",
                    "frameTimestampMs": None,
                    "bbox": box,
                    "mediaPath": metadata["mediaPath"],
                    "mediaSha256": metadata["sha256"],
                    "split": positive_splits[record["sourceKey"]],
                })

        negative_media: list[dict[str, Any]] = []
        for record in negative_records:
            metadata = image_metadata[record["imagePath"]]
            reason_classes = sorted(
                name for name in record["classNames"] if name.casefold() in HARD_NEGATIVE_CLASSES
            )
            negative_media.append({
                "negativeId": f"negative-{metadata['sha256'][:20]}",
                "sourceId": f"external:{archive_namespace}:{record['sourceKey']}",
                "mediaKind": "IMAGE",
                "frameTimestampMs": None,
                "mediaPath": metadata["mediaPath"],
                "mediaSha256": metadata["sha256"],
                "split": negative_splits[record["sourceKey"]],
                "reasonClasses": reason_classes,
            })

        snapshot = {
            "schemaVersion": 2,
            "requiredClasses": [{"label": TARGET_LABEL, "baseClass": TARGET_BASE_CLASS}],
            "samples": sorted(samples, key=lambda item: item["sampleId"]),
            "negativeMedia": sorted(negative_media, key=lambda item: item["negativeId"]),
        }
        content_hash = _sha256_bytes(_canonical_json(snapshot).encode("utf-8"))
        directory = output_root.resolve() / content_hash
        media_dir = directory / "media"
        directory.mkdir(parents=True, exist_ok=True)
        media_dir.mkdir(exist_ok=True)
        copied_hashes: set[str] = set()
        for record in selected:
            metadata = image_metadata[record["imagePath"]]
            if metadata["sha256"] in copied_hashes:
                continue
            _copy_entry_atomic(archive, entries[record["imagePath"]], directory / metadata["mediaPath"])
            copied_hashes.add(metadata["sha256"])

    all_records = [*samples, *negative_media]
    source_splits: dict[str, set[str]] = defaultdict(set)
    for record in all_records:
        source_splits[record["sourceId"]].add(record["split"])
    leakage_count = sum(len(splits) > 1 for splits in source_splits.values())
    manifest = directory / "manifest.json"
    manifest_data = {
        **snapshot,
        "contentHash": content_hash,
        "origin": {
            "kind": "external_yolo_archive",
            "archiveName": source.name,
            "sourceLabelMap": DEFAULT_LABEL_MAP,
            "license": (config.get("roboflow") or {}).get("license") if isinstance(config.get("roboflow"), dict) else None,
            "inputImageCount": len(records),
            "selectedPositiveImageCount": len(positive_records),
            "selectedPositiveBoxCount": len(samples),
            "selectedNegativeImageCount": len(negative_media),
            "preAugmentationPositiveSourceCount": len(positive_sources),
            "sourceSplitPolicy": "sha256_ordered_80_10_10_by_preaugmentation_source",
        },
    }
    if manifest.is_file():
        existing = json.loads(manifest.read_text(encoding="utf-8"))
        if existing.get("contentHash") != content_hash:
            raise ValueError("Immutable dataset directory has conflicting manifest")
    else:
        _write_atomic(manifest, json.dumps(manifest_data, ensure_ascii=False, indent=2))
    return {
        "contentHash": content_hash,
        "directory": str(directory),
        "manifestPath": str(manifest),
        "sampleCount": len(samples),
        "positiveImageCount": len({sample["mediaPath"] for sample in samples}),
        "negativeImageCount": len(negative_media),
        "sourceCount": len(source_splits),
        "sourceLeakageCount": leakage_count,
        "splits": {split: sum(1 for sample in samples if sample["split"] == split) for split in ("train", "val", "test")},
        "negativeSplits": {split: sum(1 for item in negative_media if item["split"] == split) for split in ("train", "val", "test")},
        "labels": [TARGET_LABEL],
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: external_yolo_importer.py <archive-path> <datasets-root>")
    result = import_external_yolo_archive(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"{EVENT_PREFIX}{json.dumps(result, ensure_ascii=False)}", flush=True)
