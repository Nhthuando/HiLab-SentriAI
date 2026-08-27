"""Build a review-only multiclass hard-case extension from reviewed train/val frames.

The selector evaluates the generic YOLO model and the current supplemental
reach-stacker model against reviewed labels.  It never reads the locked test
split.  Native frames and all proposal boxes remain PENDING_REVIEW and are not
eligible for training until a separate human-review finalization step.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import cv2
from ultralytics import YOLO

from evaluation.golden_dataset import difference_hash, hash_distance
from evaluation.metrics import iou
from stream.native_video_frames import NativeVideoFrameLoader
from training.local_video_dataset import (
    CLASS_NAMES,
    CLASS_TO_ID,
    create_cvat_archive,
    write_dataset_index_files,
)


BASE_CLASSES = frozenset({"person", "bicycle", "car", "motorcycle", "truck"})
CUSTOM_CLASSES = frozenset({"reach_stacker"})
SUPPORTED_CLASSES = BASE_CLASSES | CUSTOM_CLASSES
LOCKED_TEST_SOURCE = "lm06-rain-independent-test"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_yolo_labels(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        fields = raw_line.split()
        if not fields:
            continue
        if len(fields) != 5:
            raise ValueError(f"invalid YOLO row {path}:{line_number}")
        class_id = int(fields[0])
        if not 0 <= class_id < len(CLASS_NAMES):
            raise ValueError(f"invalid class id {class_id} in {path}:{line_number}")
        center_x, center_y, width, height = (float(value) for value in fields[1:])
        bbox = [
            center_x - width / 2,
            center_y - height / 2,
            center_x + width / 2,
            center_y + height / 2,
        ]
        if not all(-1e-6 <= value <= 1.000001 for value in bbox) or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise ValueError(f"invalid normalized box in {path}:{line_number}")
        bbox = [max(0.0, min(1.0, value)) for value in bbox]
        items.append({"class": CLASS_NAMES[class_id], "bbox": bbox, "source": "reviewed_projection"})
    return items


def _write_yolo_labels(path: Path, items: Sequence[Mapping[str, Any]]) -> None:
    rows: list[str] = []
    for item in items:
        bbox = [float(value) for value in item["bbox"]]
        center_x = (bbox[0] + bbox[2]) / 2
        center_y = (bbox[1] + bbox[3]) / 2
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        rows.append(
            f"{CLASS_TO_ID[str(item['class'])]} {center_x:.8f} {center_y:.8f} {width:.8f} {height:.8f}"
        )
    path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")


def _predict(
    model_path: Path,
    frames: Sequence[Mapping[str, Any]],
    image_root: Path,
    *,
    allowed_classes: frozenset[str],
    forced_class: str | None,
    device: str,
    image_size: int,
    batch: int,
) -> dict[str, list[dict[str, Any]]]:
    model = YOLO(str(model_path.resolve()))
    output: dict[str, list[dict[str, Any]]] = {str(frame["frameId"]): [] for frame in frames}
    chunk_size = max(batch, batch * 2)
    for offset in range(0, len(frames), chunk_size):
        chunk = frames[offset:offset + chunk_size]
        paths = [str(image_root / str(frame["candidatePath"])) for frame in chunk]
        kwargs: dict[str, Any] = {
            "source": paths,
            "batch": batch,
            "imgsz": image_size,
            "conf": 0.001,
            "iou": 0.70,
            "max_det": 100,
            "device": device,
            "verbose": False,
        }
        if str(device).casefold() != "cpu":
            kwargs["quantize"] = 16
        results = model.predict(**kwargs)
        for frame, result in zip(chunk, results, strict=True):
            detections: list[dict[str, Any]] = []
            boxes = getattr(result, "boxes", None)
            height, width = result.orig_shape
            if boxes is not None:
                for xyxy, confidence, raw_class in zip(
                    boxes.xyxy.cpu().tolist(),
                    boxes.conf.cpu().tolist(),
                    boxes.cls.cpu().tolist(),
                    strict=True,
                ):
                    model_name = str(result.names[int(raw_class)])
                    class_name = forced_class or model_name
                    if class_name not in allowed_classes:
                        continue
                    detections.append({
                        "class": class_name,
                        "bbox": [
                            max(0.0, min(1.0, xyxy[0] / width)),
                            max(0.0, min(1.0, xyxy[1] / height)),
                            max(0.0, min(1.0, xyxy[2] / width)),
                            max(0.0, min(1.0, xyxy[3] / height)),
                        ],
                        "confidence": float(confidence),
                        "source": "custom" if forced_class else "base",
                    })
            output[str(frame["frameId"])] = detections
        print(json.dumps({
            "event": "inference_progress",
            "model": model_path.name,
            "processed": min(len(frames), offset + len(chunk)),
            "total": len(frames),
        }), flush=True)
    del model
    return output


def evaluate_hard_cases(
    frames: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    confidence: float = 0.25,
    iou_threshold: float = 0.50,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Return per-class metrics and per-frame FN/low-confidence details."""
    counters = {name: {"tp": 0, "fp": 0, "fn": 0, "gt": 0} for name in CLASS_NAMES}
    frame_details: dict[str, dict[str, Any]] = {}
    for frame in frames:
        frame_id = str(frame["frameId"])
        truths = list(frame["groundTruth"])
        candidates = list(predictions.get(frame_id, ()))
        details: list[dict[str, Any]] = []
        for class_name in CLASS_NAMES:
            class_truths = [item for item in truths if item["class"] == class_name]
            class_predictions = sorted(
                [item for item in candidates if item["class"] == class_name],
                key=lambda item: -float(item.get("confidence", 0.0)),
            )
            counters[class_name]["gt"] += len(class_truths)
            eligible = [item for item in class_predictions if float(item.get("confidence", 0.0)) >= confidence]
            matched_truths: set[int] = set()
            for prediction in eligible:
                best_index = None
                best_overlap = iou_threshold
                for truth_index, truth in enumerate(class_truths):
                    if truth_index in matched_truths:
                        continue
                    overlap = iou(prediction["bbox"], truth["bbox"])
                    if overlap >= best_overlap:
                        best_overlap = overlap
                        best_index = truth_index
                if best_index is None:
                    counters[class_name]["fp"] += 1
                else:
                    matched_truths.add(best_index)
                    counters[class_name]["tp"] += 1
            counters[class_name]["fn"] += len(class_truths) - len(matched_truths)

            for truth_index, truth in enumerate(class_truths):
                overlaps = [
                    (iou(prediction["bbox"], truth["bbox"]), float(prediction.get("confidence", 0.0)))
                    for prediction in class_predictions
                ]
                best_overlap, best_confidence = max(overlaps, default=(0.0, 0.0))
                if truth_index not in matched_truths:
                    reason = "low_confidence" if best_overlap >= iou_threshold and best_confidence < confidence else "false_negative"
                    details.append({
                        "class": class_name,
                        "reason": reason,
                        "bbox": truth["bbox"],
                        "bestIoU": round(best_overlap, 6),
                        "bestConfidence": round(best_confidence, 6),
                    })
        frame_details[frame_id] = {
            "hardObjects": details,
            "hardClasses": sorted({str(item["class"]) for item in details}),
        }

    metrics: dict[str, Any] = {}
    for class_name in CLASS_NAMES:
        counts = counters[class_name]
        precision = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else None
        recall = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else None
        f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
        metrics[class_name] = {
            **counts,
            "precision": round(precision, 6) if precision is not None else None,
            "recall": round(recall, 6) if recall is not None else None,
            "f1": round(f1, 6) if f1 is not None else None,
            "modelSupported": class_name in SUPPORTED_CLASSES,
        }
    return metrics, frame_details


def _frame_score(frame: Mapping[str, Any], metrics: Mapping[str, Mapping[str, Any]]) -> float:
    score = 0.0
    for item in frame.get("hardObjects", []):
        class_name = str(item["class"])
        class_metrics = metrics[class_name]
        recall = class_metrics.get("recall")
        recall_weight = 1.0 + (1.0 - float(recall)) * 4.0 if recall is not None else 2.0
        rarity_weight = 1.0 / math.sqrt(max(1, int(class_metrics.get("gt") or 0)))
        reason_weight = 2.0 if item["reason"] == "false_negative" else 1.0
        score += reason_weight * recall_weight + rarity_weight
    return round(score, 6)


def select_balanced_frames(
    frames: Sequence[Mapping[str, Any]],
    metrics: Mapping[str, Mapping[str, Any]],
    *,
    target: int = 120,
    minimum: int = 100,
    minimum_gap_ms: int = 30_000,
    minimum_hash_distance: int = 1,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Select hard frames by low-recall class while suppressing temporal duplicates."""
    if not 0 < minimum <= target <= 200:
        raise ValueError("selection must satisfy 0 < minimum <= target <= 200")
    candidates = [{**dict(frame), "selectionScore": _frame_score(frame, metrics)} for frame in frames]
    candidates.sort(key=lambda frame: (-float(frame["selectionScore"]), str(frame["frameId"])))
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    removals = Counter()

    def add(frame: dict[str, Any], *, fallback: bool = False) -> bool:
        frame_id = str(frame["frameId"])
        if frame_id in selected_ids:
            return False
        same_source = [item for item in selected if item["sourceId"] == frame["sourceId"]]
        if any(abs(int(item["timestampMs"]) - int(frame["timestampMs"])) < minimum_gap_ms for item in same_source):
            removals["temporalNearDuplicate"] += 1
            return False
        if any(
            abs(int(item["timestampMs"]) - int(frame["timestampMs"])) <= minimum_gap_ms * 2
            and hash_distance(str(item["perceptualHash"]), str(frame["perceptualHash"])) < minimum_hash_distance
            for item in same_source
        ):
            removals["perceptualNearDuplicate"] += 1
            return False
        if fallback:
            frame["selectionFallback"] = True
        selected.append(frame)
        selected_ids.add(frame_id)
        return True

    active_classes = [
        name for name in CLASS_NAMES
        if int(metrics[name].get("gt") or 0) > 0
    ]
    active_classes.sort(key=lambda name: (float(metrics[name]["recall"]) if metrics[name]["recall"] is not None else 1.0, name))
    quota = max(8, target // max(1, len(active_classes)))
    for class_name in active_classes:
        added = 0
        for frame in candidates:
            if class_name not in frame.get("hardClasses", ()):
                continue
            if add(frame):
                added += 1
            if added >= quota or len(selected) >= target:
                break

    validation_target = min(20, sum(frame["split"] == "val" for frame in candidates))
    for frame in candidates:
        if len(selected) >= target or sum(item["split"] == "val" for item in selected) >= validation_target:
            break
        if frame["split"] == "val" and frame.get("hardObjects"):
            add(frame)

    for frame in candidates:
        if len(selected) >= target:
            break
        if frame.get("hardObjects"):
            add(frame)

    if len(selected) < minimum:
        fallback = sorted(
            candidates,
            key=lambda frame: (
                -sum(1 for truth in frame["groundTruth"] if metrics[str(truth["class"])].get("recall") is not None),
                str(frame["frameId"]),
            ),
        )
        for frame in fallback:
            if len(selected) >= minimum:
                break
            add(frame, fallback=True)
    if len(selected) < minimum:
        raise RuntimeError(f"deduplication left only {len(selected)} frames; minimum is {minimum}")
    return sorted(selected, key=lambda frame: (str(frame["split"]), str(frame["sourceId"]), int(frame["timestampMs"]))), dict(removals)


def merge_prelabels(
    ground_truth: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
    *,
    confidence: float = 0.15,
    duplicate_iou: float = 0.50,
) -> list[dict[str, Any]]:
    """Keep reviewed projections and add non-overlapping supported model proposals."""
    merged = [dict(item) for item in ground_truth]
    for prediction in sorted(predictions, key=lambda item: -float(item.get("confidence", 0.0))):
        if prediction["class"] not in SUPPORTED_CLASSES or float(prediction.get("confidence", 0.0)) < confidence:
            continue
        if any(
            existing["class"] == prediction["class"]
            and iou(existing["bbox"], prediction["bbox"]) >= duplicate_iou
            for existing in merged
        ):
            continue
        merged.append(dict(prediction))
    return merged


def build_multiclass_review_package(
    reviewed_snapshot: Path,
    existing_package: Path,
    video_root: Path,
    ffmpeg_path: Path,
    base_model_path: Path,
    custom_model_path: Path,
    output_directory: Path,
    *,
    dataset_id: str = "BAI-KIEM-MISSED-REACH-NATIVE-V2-MULTICLASS",
    target: int = 120,
    device: str = "0",
    batch: int = 8,
) -> dict[str, Any]:
    snapshot = reviewed_snapshot.resolve()
    existing = existing_package.resolve()
    output = output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"review package already exists: {output}")
    source_manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    if source_manifest.get("schemaVersion") != 3 or source_manifest.get("reviewStatus") != "REVIEWED":
        raise ValueError("multiclass hard-case selection requires a finalized reviewed snapshot")
    eligible_source_ids = {
        str(source["sourceId"])
        for source in source_manifest.get("sources", [])
        if str(source.get("sourceId")) != LOCKED_TEST_SOURCE
    }
    frames = [
        dict(frame) for frame in source_manifest.get("frames", [])
        if frame.get("split") in {"train", "val"} and str(frame.get("sourceId")) in eligible_source_ids
    ]
    if not frames or any(frame.get("split") == "test" for frame in frames):
        raise ValueError("eligible reviewed train/val frames are missing or contaminated")
    if any(str(frame.get("sourceId")) == LOCKED_TEST_SOURCE for frame in frames):
        raise ValueError("locked test source is forbidden")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=str(output.parent)))
    shutil.copytree(existing, temporary, dirs_exist_ok=True)
    candidate_root = temporary / ".native-candidates"
    candidate_root.mkdir()
    loader = NativeVideoFrameLoader(source_manifest, video_root, ffmpeg_path=ffmpeg_path, cache_frames=False)
    try:
        for index, frame in enumerate(frames, start=1):
            frame_id = str(frame["frameId"])
            image = loader(frame)
            height, width = image.shape[:2]
            if (width, height) != (2592, 1520):
                raise RuntimeError(f"native frame {frame_id} is {width}x{height}, expected 2592x1520")
            ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            if not ok:
                raise RuntimeError(f"cannot encode native frame {frame_id}")
            candidate_path = candidate_root / f"{frame_id}.jpg"
            candidate_path.write_bytes(encoded.tobytes())
            frame["candidatePath"] = candidate_path.relative_to(temporary).as_posix()
            frame["perceptualHash"] = difference_hash(image)
            frame["nativeSha256"] = _sha256_file(candidate_path)
            frame["groundTruth"] = _load_yolo_labels(snapshot / str(frame["labelsPath"]))
            if index % 20 == 0 or index == len(frames):
                print(json.dumps({"event": "native_extract_progress", "processed": index, "total": len(frames)}), flush=True)
    finally:
        loader.close()

    base_predictions = _predict(
        base_model_path, frames, temporary, allowed_classes=BASE_CLASSES,
        forced_class=None, device=device, image_size=960, batch=batch,
    )
    custom_predictions = _predict(
        custom_model_path, frames, temporary, allowed_classes=CUSTOM_CLASSES,
        forced_class="reach_stacker", device=device, image_size=896, batch=batch,
    )
    predictions = {
        str(frame["frameId"]): [
            *base_predictions[str(frame["frameId"])],
            *custom_predictions[str(frame["frameId"])],
        ]
        for frame in frames
    }
    metrics, frame_details = evaluate_hard_cases(frames, predictions)
    for frame in frames:
        frame.update(frame_details[str(frame["frameId"])])
    selected, duplicate_removals = select_balanced_frames(frames, metrics, target=target)

    annotation_manifest_path = temporary / "annotation-manifest.json"
    annotation_manifest = json.loads(annotation_manifest_path.read_text(encoding="utf-8"))
    old_frame_count = len(annotation_manifest["frames"])
    records = list(annotation_manifest["frames"])
    audit_manifest_path = temporary / "manifest.json"
    audit_manifest = json.loads(audit_manifest_path.read_text(encoding="utf-8"))
    samples = list(audit_manifest.get("samples", []))
    negative_media = list(audit_manifest.get("negativeMedia", []))
    source_lookup = {str(source["sourceId"]): source for source in source_manifest.get("sources", [])}
    new_sources: dict[str, dict[str, Any]] = {}
    prelabel_counts = Counter()
    model_prelabel_counts = Counter()
    hard_class_counts = Counter()
    hard_reason_counts = Counter()

    for frame in selected:
        source_id = str(frame["sourceId"])
        split = str(frame["split"])
        block_source_id = f"multiclass-{source_id}-{split}"
        new_frame_id = f"multiclass-{frame['frameId']}"
        image_relative = f"images/{split}/{new_frame_id}.jpg"
        label_relative = f"labels/{split}/{new_frame_id}.txt"
        destination = temporary / image_relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temporary / str(frame["candidatePath"])), destination)
        prelabels = merge_prelabels(frame["groundTruth"], predictions[str(frame["frameId"])])
        label_path = temporary / label_relative
        label_path.parent.mkdir(parents=True, exist_ok=True)
        _write_yolo_labels(label_path, prelabels)
        for item in prelabels:
            prelabel_counts[str(item["class"])] += 1
            if item.get("source") in {"base", "custom"}:
                model_prelabel_counts[str(item["class"])] += 1
        hard_class_counts.update(frame["hardClasses"])
        hard_reason_counts.update(str(item["reason"]) for item in frame["hardObjects"])
        record = {
            "frameId": new_frame_id,
            "sourceId": block_source_id,
            "parentSourceId": source_id,
            "duplicateGroup": f"multiclass-{frame['duplicateGroup']}-{split}",
            "role": "positive",
            "timestampMs": int(frame["timestampMs"]),
            "requestedTimestampMs": int(frame.get("requestedTimestampMs", frame["timestampMs"])),
            "split": split,
            "imagePath": image_relative,
            "labelsPath": label_relative,
            "sha256": _sha256_file(destination),
            "perceptualHash": frame["perceptualHash"],
            "proposalCount": len(prelabels),
            "reviewedProjectionCount": len(frame["groundTruth"]),
            "modelOnlyProposalCount": sum(item.get("source") in {"base", "custom"} for item in prelabels),
            "hardClasses": frame["hardClasses"],
            "hardObjects": frame["hardObjects"],
            "selectionScore": frame["selectionScore"],
            "originalResolution": [2592, 1520],
            "reviewStatus": "PENDING_REVIEW",
        }
        records.append(record)
        if prelabels:
            for box_index, item in enumerate(prelabels):
                bbox = [float(value) for value in item["bbox"]]
                samples.append({
                    "sampleId": f"{new_frame_id}-box-{box_index:03d}",
                    "label": str(item["class"]),
                    "baseClass": str(item["class"]),
                    "sourceId": block_source_id,
                    "parentSourceId": source_id,
                    "mediaKind": "IMAGE",
                    "frameTimestampMs": int(frame["timestampMs"]),
                    "bbox": {"x": bbox[0], "y": bbox[1], "w": bbox[2] - bbox[0], "h": bbox[3] - bbox[1]},
                    "mediaPath": image_relative,
                    "mediaSha256": record["sha256"],
                    "split": split,
                })
        else:
            negative_media.append({
                "negativeId": f"{new_frame_id}-empty",
                "sourceId": block_source_id,
                "parentSourceId": source_id,
                "mediaKind": "IMAGE",
                "frameTimestampMs": int(frame["timestampMs"]),
                "mediaPath": image_relative,
                "mediaSha256": record["sha256"],
                "split": split,
                "reasonClasses": ["multiclass_hard_review"],
            })
        source = source_lookup[source_id]
        details = new_sources.setdefault(block_source_id, {
            "sourceId": block_source_id,
            "parentSourceId": source_id,
            "sourceFile": source["sourceFile"],
            "duplicateGroup": f"multiclass-{frame['duplicateGroup']}-{split}",
            "role": "positive",
            "fps": source.get("fps"),
            "width": 2592,
            "height": 1520,
            "acceptedFrames": 0,
            "ranges": [],
        })
        details["acceptedFrames"] += 1
        details["ranges"].append({"startMs": int(frame["timestampMs"]), "endMs": int(frame["timestampMs"]), "split": split})

    shutil.rmtree(candidate_root)
    annotation_manifest.update({
        "datasetId": dataset_id,
        "reviewStatus": "PENDING_REVIEW",
        "proposalWarning": (
            "All boxes are review assistance only. Review every supported class and every visible object. "
            "No locked-test frame was used and this package is forbidden for training until finalized."
        ),
        "lockedTestUsed": False,
        "sourceArtifacts": {
            "baseModelSha256": _sha256_file(base_model_path.resolve()),
            "customModelSha256": _sha256_file(custom_model_path.resolve()),
            "reviewedSnapshotContentHash": source_manifest["contentHash"],
        },
        "sources": [*annotation_manifest.get("sources", []), *new_sources.values()],
        "frames": records,
    })
    annotation_manifest_path.write_text(json.dumps(annotation_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    audit_manifest.update({
        "profile": "MULTICLASS_HARD_REVIEW_V2_PENDING_REVIEW",
        "requiredClasses": [{"label": name, "baseClass": name} for name in CLASS_NAMES],
        "samples": samples,
        "negativeMedia": negative_media,
        "origin": {
            "kind": "validation_false_negative_plus_balanced_multiclass_native_review",
            "reviewStatus": "PENDING_REVIEW",
            "inputContentHash": source_manifest["contentHash"],
            "lockedTestUsed": False,
            "baseModelSha256": _sha256_file(base_model_path.resolve()),
            "customModelSha256": _sha256_file(custom_model_path.resolve()),
            "existingMissedReachFrameCount": old_frame_count,
            "selectedNativeFrameCount": len(selected),
            "duplicateRemovals": duplicate_removals,
        },
    })
    audit_without_hash = {key: value for key, value in audit_manifest.items() if key != "contentHash"}
    audit_manifest["contentHash"] = hashlib.sha256(
        json.dumps(audit_without_hash, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    audit_manifest_path.write_text(json.dumps(audit_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with (temporary / "review.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "frameId", "sourceId", "parentSourceId", "timestampMs", "split", "role",
            "imagePath", "labelsPath", "proposalCount", "hardClasses", "reviewStatus", "reviewerNotes",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = {key: record.get(key, "") for key in fields}
            if isinstance(row["hardClasses"], list):
                row["hardClasses"] = "|".join(row["hardClasses"])
            writer.writerow(row)
    write_dataset_index_files(temporary, records, CLASS_NAMES)

    selection_report = {
        "schemaVersion": 1,
        "datasetId": dataset_id,
        "evaluationScope": {"splits": ["train", "val"], "frameCount": len(frames), "lockedTestUsed": False},
        "referenceThresholds": {"confidence": 0.25, "iou": 0.50, "prelabelConfidence": 0.15},
        "modelSupport": {
            "base": sorted(BASE_CLASSES),
            "custom": sorted(CUSTOM_CLASSES),
            "unsupported": sorted(set(CLASS_NAMES) - SUPPORTED_CLASSES),
        },
        "metrics": metrics,
        "selection": {
            "target": target,
            "selected": len(selected),
            "splitCounts": dict(sorted(Counter(str(frame["split"]) for frame in selected).items())),
            "sourceCounts": dict(sorted(Counter(str(frame["sourceId"]) for frame in selected).items())),
            "hardClassFrameCounts": dict(sorted(hard_class_counts.items())),
            "hardReasonCounts": dict(sorted(hard_reason_counts.items())),
            "duplicateRemovals": duplicate_removals,
            "frameIds": [str(frame["frameId"]) for frame in selected],
        },
    }
    (temporary / "hard-case-selection.json").write_text(
        json.dumps(selection_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    summary = {
        "datasetId": dataset_id,
        "totalFrameCount": len(records),
        "existingMissedReachCropCount": old_frame_count,
        "multiclassNativeFrameCount": len(selected),
        "splitCounts": dict(sorted(Counter(str(record["split"]) for record in records).items())),
        "nativePrelabelCounts": dict(sorted(prelabel_counts.items())),
        "nativeModelOnlyPrelabelCounts": dict(sorted(model_prelabel_counts.items())),
        "nativeResolution": [2592, 1520],
        "lockedTestUsed": False,
        "reviewStatus": "PENDING_REVIEW",
        "trainingStarted": False,
    }
    (temporary / "build-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    archive = create_cvat_archive(output, output.with_name(f"{output.name}-cvat.zip"))
    return {**summary, "directory": str(output), "cvatArchive": str(archive)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-snapshot", type=Path, required=True)
    parser.add_argument("--existing-package", type=Path, required=True)
    parser.add_argument("--video-root", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--custom-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", type=int, default=120)
    parser.add_argument("--device", default="0")
    parser.add_argument("--batch", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(build_multiclass_review_package(
        args.reviewed_snapshot, args.existing_package, args.video_root, args.ffmpeg,
        args.base_model, args.custom_model, args.output, target=args.target,
        device=args.device, batch=args.batch,
    ), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
