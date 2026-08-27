"""Pre-label the isolated CVAT locked-test task for exhaustive human review.

This utility runs only after an annotation helper has been trained and selected
without locked-test data. It never exports locked images or labels into a YOLO
dataset and never evaluates detection metrics on the locked task.
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from training.cvat_annotation_assist import (
    CANONICAL_CLASSES,
    DEFAULT_HELPER_THRESHOLDS,
    FORBIDDEN_HELPER_CLASSES,
    _client,
    _configure_low_resource_process,
    _ensure_rectangle_contract,
    _intersection_over_union,
    _sha256_file,
    _task_state,
    _utc_now,
    _write_json,
    audit_frame_indices,
    canonical_shape_hash,
    class_agnostic_nms,
)


LOCKED_REVIEW_THRESHOLDS = {
    "person": 0.35,
    "car": 0.25,
    "truck": 0.25,
    "forklift": 0.20,
    "reach_stacker": 0.20,
    "bicycle": 0.30,
    "motorcycle": 0.30,
    "bus": 0.50,
}
BASE_FALLBACK_CLASSES = frozenset({"bicycle", "motorcycle", "bus"})
BASE_RAW_CONFIDENCE = 0.12


@dataclass(frozen=True)
class LockedPrelabelConfig:
    package: Path
    output: Path
    base_model: Path
    base_url: str = "http://localhost:8080"
    train_task_id: int = 9
    locked_task_id: int = 10

    @property
    def artifact_root(self) -> Path:
        return self.output.resolve() / "locked-review"


def validate_frame_mapping(
    package_frames: Sequence[Mapping[str, Any]],
    meta_frames: Sequence[Mapping[str, Any]],
) -> None:
    if len(package_frames) != len(meta_frames):
        raise ValueError(
            f"locked package/CVAT frame count differs: {len(package_frames)} != {len(meta_frames)}"
        )
    for index, (package_frame, meta_frame) in enumerate(zip(package_frames, meta_frames, strict=True)):
        resolution = package_frame.get("originalResolution")
        if not isinstance(resolution, Sequence) or isinstance(resolution, (str, bytes)) or len(resolution) != 2:
            raise ValueError(f"locked package has invalid resolution at frame {index}")
        expected = (
            str(package_frame.get("imagePath", "")),
            int(resolution[0]),
            int(resolution[1]),
        )
        actual = (
            str(meta_frame.get("name", "")),
            int(meta_frame.get("width", 0)),
            int(meta_frame.get("height", 0)),
        )
        if actual != expected:
            raise ValueError(f"locked package/CVAT mapping differs at frame {index}: {actual} != {expected}")


def filter_locked_proposals(
    proposals: Sequence[Mapping[str, Any]],
    *,
    frame_index: int | None = None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for raw in proposals:
        item = dict(raw)
        class_name = str(item.get("class", ""))
        confidence = float(item.get("confidence", 0.0))
        bbox = item.get("bbox")
        threshold = LOCKED_REVIEW_THRESHOLDS.get(class_name)
        if threshold is None or confidence < threshold:
            continue
        if not isinstance(bbox, Sequence) or isinstance(bbox, (str, bytes)) or len(bbox) != 4:
            raise ValueError("locked proposal bbox must contain four values")
        values = [float(value) for value in bbox]
        if not (0.0 <= values[0] < values[2] <= 1.0 and 0.0 <= values[1] < values[3] <= 1.0):
            raise ValueError("locked proposal bbox must be normalized and non-empty")
        # Locked frames 127-199 come from the night camera. Its timestamp is
        # burned into the top-left strip and otherwise looks like a row of
        # truck/container edges to the small detector.
        if frame_index is not None and frame_index >= 127 and values[0] < 0.30 and values[3] <= 0.12:
            continue
        # In this fixed high-angle locked set, truck proposals wider than 32%
        # are rows of static containers. Actual tractor-trailers remain well
        # below that width even in the nearest camera positions.
        if class_name == "truck" and values[2] - values[0] > 0.32:
            continue
        item["bbox"] = values
        filtered.append(item)
    return class_agnostic_nms(filtered, iou_threshold=0.45)


def merge_domain_and_base_candidates(
    helper_candidates: Sequence[Mapping[str, Any]],
    base_candidates: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Prefer the task-9-trained helper when generic COCO labels overlap it."""
    helper_kept = class_agnostic_nms(helper_candidates, iou_threshold=0.45)
    base_kept = class_agnostic_nms(base_candidates, iou_threshold=0.45)
    fallback = [
        candidate
        for candidate in base_kept
        if not any(
            _intersection_over_union(candidate["bbox"], domain["bbox"]) >= 0.30
            for domain in helper_kept
        )
    ]
    return class_agnostic_nms([*helper_kept, *fallback], iou_threshold=0.45)


def build_prediction_shapes(
    predictions: Mapping[str, Sequence[Mapping[str, Any]]],
    meta_frames: Sequence[Mapping[str, Any]],
    label_ids: Mapping[str, int],
) -> list[dict[str, Any]]:
    shapes: list[dict[str, Any]] = []
    for raw_frame, items in predictions.items():
        frame = int(raw_frame)
        if frame < 0 or frame >= len(meta_frames):
            raise ValueError(f"prediction targets invalid locked frame {frame}")
        width = int(meta_frames[frame].get("width", 0))
        height = int(meta_frames[frame].get("height", 0))
        if width <= 0 or height <= 0:
            raise ValueError(f"locked frame {frame} has invalid dimensions")
        for item in items:
            class_name = str(item.get("class", ""))
            if class_name not in label_ids or class_name in FORBIDDEN_HELPER_CLASSES:
                raise ValueError(f"prediction uses unsupported locked-test class {class_name!r}")
            bbox = item.get("bbox")
            if not isinstance(bbox, Sequence) or isinstance(bbox, (str, bytes)) or len(bbox) != 4:
                raise ValueError("locked proposal bbox must contain four values")
            x1, y1, x2, y2 = (float(value) for value in bbox)
            if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
                raise ValueError("locked proposal bbox must be normalized and non-empty")
            shapes.append({
                "type": "rectangle",
                "frame": frame,
                "label_id": int(label_ids[class_name]),
                "points": [x1 * width, y1 * height, x2 * width, y2 * height],
                "occluded": False,
                "outside": False,
                "z_order": 0,
                "rotation": 0.0,
                "attributes": [],
                "source": "auto",
            })
    shapes.sort(key=lambda shape: (int(shape["frame"]), int(shape["label_id"]), shape["points"]))
    return shapes


def verify_preapply_guards(
    *,
    expected_train_hash: str,
    live_train_hash: str,
    expected_locked_hash: str,
    live_locked_hash: str,
    expected_checkpoint_hash: str,
    live_checkpoint_hash: str,
) -> None:
    if live_train_hash != expected_train_hash:
        raise RuntimeError("CVAT task 9 changed after helper training; refusing locked-test write")
    if live_locked_hash != expected_locked_hash:
        raise RuntimeError("CVAT task 10 changed after snapshot; refusing locked-test write")
    if live_checkpoint_hash != expected_checkpoint_hash:
        raise RuntimeError("annotation-helper checkpoint changed after snapshot; refusing locked-test write")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validated_training_evidence(config: LockedPrelabelConfig) -> tuple[dict[str, Any], dict[str, Any], Path]:
    training_snapshot_path = config.output / "snapshot" / "task-9-snapshot.json"
    training_receipt_path = config.output / "training-receipt.json"
    checkpoint = config.output / "checkpoint" / "annotation-helper-best.pt"
    if not training_snapshot_path.is_file() or not training_receipt_path.is_file() or not checkpoint.is_file():
        raise FileNotFoundError("completed 1000-frame helper evidence is missing")
    training_snapshot = _load_json(training_snapshot_path)
    training_receipt = _load_json(training_receipt_path)
    if bool(training_receipt.get("lockedTaskUsed")) or bool(training_receipt.get("activated")):
        raise ValueError("helper receipt violates the annotation-only locked-data boundary")
    checkpoint_hash = _sha256_file(checkpoint)
    if checkpoint_hash != str(training_receipt.get("checkpointSha256", "")):
        raise ValueError("helper checkpoint hash differs from its training receipt")
    return training_snapshot, training_receipt, checkpoint


def snapshot_locked_task(config: LockedPrelabelConfig) -> dict[str, Any]:
    training_snapshot, training_receipt, checkpoint = _validated_training_evidence(config)
    manifest_path = config.package / "annotation-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("locked package annotation-manifest.json is missing")
    manifest = _load_json(manifest_path)
    package_frames = manifest.get("frames")
    if manifest.get("classes") != list(CANONICAL_CLASSES) or not isinstance(package_frames, list):
        raise ValueError("locked package class/frame contract differs from V9")

    client = _client(config.base_url)
    train_state = _task_state(client, config.train_task_id)
    locked_state = _task_state(client, config.locked_task_id)
    train_shapes = _ensure_rectangle_contract(train_state["annotations"])
    locked_shapes = _ensure_rectangle_contract(locked_state["annotations"])
    if locked_shapes:
        raise ValueError("CVAT task 10 must be empty before the pre-label snapshot")
    train_hash = canonical_shape_hash(train_shapes)
    if train_hash != str(training_snapshot.get("fullShapeHash", "")):
        raise RuntimeError("CVAT task 9 changed after the 1000-frame training snapshot")
    meta_frames = locked_state["meta"].get("frames", [])
    validate_frame_mapping(package_frames, meta_frames)
    actual_classes = [str(item.get("name")) for item in locked_state["labels"]]
    if actual_classes != list(CANONICAL_CLASSES):
        raise ValueError("CVAT task 10 label contract differs from V9")

    locked_hash = canonical_shape_hash(locked_shapes)
    snapshot = {
        "stage": "locked-snapshot-complete",
        "createdAt": _utc_now(),
        "trainTaskId": config.train_task_id,
        "trainTaskShapeCount": len(train_shapes),
        "trainTaskShapeHash": train_hash,
        "trainingDatasetContentHash": training_receipt.get("datasetContentHash"),
        "lockedTaskId": config.locked_task_id,
        "lockedTaskShapeCount": 0,
        "lockedTaskShapeHash": locked_hash,
        "lockedPackageManifestSha256": _sha256_file(manifest_path),
        "checkpoint": str(checkpoint),
        "checkpointSha256": _sha256_file(checkpoint),
        "meta": locked_state["meta"],
        "labels": locked_state["labels"],
        "jobs": locked_state["jobs"],
        "annotations": locked_state["annotations"],
        "lockedTaskUsedForTraining": False,
        "eligibleForTraining": False,
    }
    root = config.artifact_root
    _write_json(root / "snapshot" / "task-10-snapshot.json", snapshot)
    rollback = {
        "version": int(locked_state["annotations"].get("version", 0)),
        "tags": [],
        "shapes": [],
        "tracks": [],
    }
    _write_json(root / "snapshot" / "rollback-payload.json", rollback)
    receipt = {
        key: snapshot[key]
        for key in (
            "stage", "createdAt", "trainTaskId", "trainTaskShapeCount", "trainTaskShapeHash",
            "lockedTaskId", "lockedTaskShapeCount", "lockedTaskShapeHash",
            "lockedPackageManifestSha256", "checkpointSha256", "lockedTaskUsedForTraining",
            "eligibleForTraining",
        )
    }
    receipt["frameCount"] = len(package_frames)
    _write_json(root / "snapshot-receipt.json", receipt)
    return receipt


def _append_result_candidates(
    candidates: list[dict[str, Any]],
    result: Any,
    *,
    allowed_classes: set[str],
    minimums: Mapping[str, float],
    source: str,
) -> None:
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return
    names = getattr(result, "names", {})
    class_ids = boxes.cls.detach().cpu().tolist()
    confidences = boxes.conf.detach().cpu().tolist()
    normalized_boxes = boxes.xyxyn.detach().cpu().tolist()
    for class_id, confidence, bbox in zip(class_ids, confidences, normalized_boxes, strict=True):
        class_index = int(class_id)
        if isinstance(names, Mapping):
            class_name = str(names.get(class_index, ""))
        else:
            class_name = str(names[class_index]) if 0 <= class_index < len(names) else ""
        confidence = float(confidence)
        if class_name not in allowed_classes or confidence < float(minimums.get(class_name, 1.0)):
            continue
        values = [max(0.0, min(1.0, float(value))) for value in bbox]
        if values[2] <= values[0] or values[3] <= values[1]:
            continue
        candidates.append({
            "class": class_name,
            "confidence": confidence,
            "bbox": values,
            "source": source,
        })


def predict_locked_task(config: LockedPrelabelConfig) -> dict[str, Any]:
    root = config.artifact_root
    snapshot = _load_json(root / "snapshot" / "task-10-snapshot.json")
    training_manifest = _load_json(config.output / "dataset" / "annotation-assist-manifest.json")
    manifest = _load_json(config.package / "annotation-manifest.json")
    frames = manifest.get("frames", [])
    validate_frame_mapping(frames, snapshot["meta"].get("frames", []))
    _, _, checkpoint = _validated_training_evidence(config)
    if _sha256_file(checkpoint) != str(snapshot.get("checkpointSha256", "")):
        raise RuntimeError("helper checkpoint changed after locked snapshot")
    if config.base_model.name.casefold() != "yolo11n.pt" or not config.base_model.is_file():
        raise ValueError("locked fallback must use the local official yolo11n.pt checkpoint")

    helper_classes = [str(name) for name in training_manifest.get("classes", [])]
    allowed_helper = set(helper_classes).difference(FORBIDDEN_HELPER_CLASSES)
    _configure_low_resource_process()
    import cv2
    import torch
    from ultralytics import YOLO

    cv2.setNumThreads(1)
    torch.set_num_threads(1)
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    device: int | str = 0 if torch.cuda.is_available() else "cpu"
    helper = YOLO(str(checkpoint))
    base = YOLO(str(config.base_model.resolve()))
    predictions: dict[str, list[dict[str, Any]]] = {}
    class_counts: Counter[str] = Counter()
    started = time.monotonic()
    helper_minimums = {name: DEFAULT_HELPER_THRESHOLDS.get(name, 0.20) for name in allowed_helper}
    base_minimums = {name: BASE_RAW_CONFIDENCE for name in BASE_FALLBACK_CLASSES}
    for frame_index, frame in enumerate(frames):
        source_image = config.package / str(frame["imagePath"])
        if not source_image.is_file():
            raise FileNotFoundError(f"locked source image is missing: {source_image}")
        helper_result = helper.predict(
            source=str(source_image), imgsz=896, conf=0.08, iou=0.45,
            agnostic_nms=True, max_det=100, device=device, verbose=False,
        )[0]
        base_result = base.predict(
            source=str(source_image), imgsz=896, conf=BASE_RAW_CONFIDENCE, iou=0.45,
            classes=[1, 3, 5], agnostic_nms=True, max_det=100, device=device, verbose=False,
        )[0]
        helper_candidates: list[dict[str, Any]] = []
        base_candidates: list[dict[str, Any]] = []
        _append_result_candidates(
            helper_candidates, helper_result, allowed_classes=allowed_helper,
            minimums=helper_minimums, source="task9-helper",
        )
        _append_result_candidates(
            base_candidates, base_result, allowed_classes=set(BASE_FALLBACK_CLASSES),
            minimums=base_minimums, source="official-yolo11n-fallback",
        )
        kept = merge_domain_and_base_candidates(helper_candidates, base_candidates)
        predictions[str(frame_index)] = kept
        for item in kept:
            class_counts[str(item["class"])] += 1
        if frame_index == 0 or (frame_index + 1) % 25 == 0 or frame_index + 1 == len(frames):
            print(f"locked prelabel predict {frame_index + 1}/{len(frames)}", flush=True)
    receipt = {
        "stage": "locked-prediction-complete",
        "createdAt": _utc_now(),
        "lockedTaskId": config.locked_task_id,
        "frameCount": len(frames),
        "proposalCount": sum(class_counts.values()),
        "classCounts": dict(sorted(class_counts.items())),
        "helperRawThresholds": helper_minimums,
        "baseRawThresholds": base_minimums,
        "crossClassNmsIou": 0.45,
        "checkpointSha256": _sha256_file(checkpoint),
        "elapsedSeconds": round(time.monotonic() - started, 2),
        "lockedTaskUsedForTraining": False,
        "eligibleForTraining": False,
    }
    _write_json(root / "predictions-low-threshold.json", {"receipt": receipt, "frames": predictions})
    _write_json(root / "prediction-receipt.json", receipt)
    return receipt


def filter_locked_task(config: LockedPrelabelConfig) -> dict[str, Any]:
    root = config.artifact_root
    raw = _load_json(root / "predictions-low-threshold.json")
    filtered_frames: dict[str, list[dict[str, Any]]] = {}
    class_counts: Counter[str] = Counter()
    empty_frames: list[int] = []
    sparse_frames: list[int] = []
    for raw_frame, proposals in raw["frames"].items():
        frame_index = int(raw_frame)
        kept = filter_locked_proposals(proposals, frame_index=frame_index)
        filtered_frames[str(frame_index)] = kept
        if not kept:
            empty_frames.append(frame_index)
        if len(kept) <= 1:
            sparse_frames.append(frame_index)
        for item in kept:
            class_counts[str(item["class"])] += 1
    receipt = {
        "stage": "locked-filter-complete",
        "createdAt": _utc_now(),
        "lockedTaskId": config.locked_task_id,
        "frameCount": len(filtered_frames),
        "proposalCountBefore": int(raw["receipt"]["proposalCount"]),
        "proposalCountAfter": sum(class_counts.values()),
        "emptyFramesAfter": len(empty_frames),
        "emptyFrames": empty_frames,
        "sparseFramesAtMostOneProposal": sparse_frames,
        "classCounts": dict(sorted(class_counts.items())),
        "reviewThresholds": LOCKED_REVIEW_THRESHOLDS,
        "crossClassNmsIou": 0.45,
        "eligibleForTraining": False,
    }
    _write_json(root / "predictions.json", {"receipt": receipt, "frames": filtered_frames})
    _write_json(root / "prediction-filter-receipt.json", receipt)
    return receipt


def audit_locked_task(config: LockedPrelabelConfig) -> dict[str, Any]:
    import cv2
    import numpy as np

    root = config.artifact_root
    prediction_file = _load_json(root / "predictions.json")
    manifest = _load_json(config.package / "annotation-manifest.json")
    frames = manifest["frames"]
    selected = audit_frame_indices(boundary=0, total_frames=len(frames), limit=12)
    colors = {
        "person": (70, 70, 255), "car": (255, 180, 30), "truck": (40, 210, 40),
        "forklift": (210, 70, 210), "reach_stacker": (20, 220, 220),
        "bicycle": (255, 100, 100), "motorcycle": (255, 100, 100), "bus": (50, 160, 255),
    }
    tiles: list[Any] = []
    for frame_index in selected:
        image = cv2.imread(str(config.package / frames[frame_index]["imagePath"]), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"cannot render locked source frame {frame_index}")
        height, width = image.shape[:2]
        for item in prediction_file["frames"].get(str(frame_index), []):
            x1, y1, x2, y2 = item["bbox"]
            left, top, right, bottom = int(x1 * width), int(y1 * height), int(x2 * width), int(y2 * height)
            label = f"{item['class']} {float(item['confidence']):.2f}"
            color = colors.get(str(item["class"]), (255, 255, 255))
            cv2.rectangle(image, (left, top), (right, bottom), color, max(2, width // 1000))
            cv2.putText(image, label, (left, max(18, top - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
        cv2.putText(image, f"LOCKED CVAT frame {frame_index}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2, cv2.LINE_AA)
        tiles.append(cv2.resize(image, (777, 456), interpolation=cv2.INTER_AREA))
    audit_dir = root / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    montage_paths: list[str] = []
    for start in range(0, len(tiles), 6):
        group = tiles[start:start + 6]
        while len(group) < 6:
            group.append(np.zeros_like(tiles[0]))
        montage = np.vstack((np.hstack(group[0:2]), np.hstack(group[2:4]), np.hstack(group[4:6])))
        path = audit_dir / f"locked-proposal-montage-{start // 6 + 1}.jpg"
        if not cv2.imwrite(str(path), montage, [cv2.IMWRITE_JPEG_QUALITY, 92]):
            raise OSError(f"failed to write locked audit montage: {path}")
        montage_paths.append(str(path))
    receipt = {
        "stage": "locked-audit-render-complete",
        "frames": selected,
        "montages": montage_paths,
        "eligibleForTraining": False,
    }
    _write_json(audit_dir / "audit-render-receipt.json", receipt)
    return receipt


def apply_locked_task(config: LockedPrelabelConfig) -> dict[str, Any]:
    root = config.artifact_root
    snapshot = _load_json(root / "snapshot" / "task-10-snapshot.json")
    prediction_file = _load_json(root / "predictions.json")
    manifest = _load_json(config.package / "annotation-manifest.json")
    _, _, checkpoint = _validated_training_evidence(config)
    client = _client(config.base_url)
    train_live = _task_state(client, config.train_task_id)
    locked_live = _task_state(client, config.locked_task_id)
    train_shapes = _ensure_rectangle_contract(train_live["annotations"])
    locked_shapes = _ensure_rectangle_contract(locked_live["annotations"])
    validate_frame_mapping(manifest["frames"], locked_live["meta"].get("frames", []))
    verify_preapply_guards(
        expected_train_hash=str(snapshot["trainTaskShapeHash"]),
        live_train_hash=canonical_shape_hash(train_shapes),
        expected_locked_hash=str(snapshot["lockedTaskShapeHash"]),
        live_locked_hash=canonical_shape_hash(locked_shapes),
        expected_checkpoint_hash=str(snapshot["checkpointSha256"]),
        live_checkpoint_hash=_sha256_file(checkpoint),
    )
    label_ids = {str(item["name"]): int(item["id"]) for item in locked_live["labels"]}
    shapes = build_prediction_shapes(
        prediction_file["frames"], locked_live["meta"].get("frames", []), label_ids,
    )
    expected_hash = canonical_shape_hash(shapes)
    payload = {
        "version": int(locked_live["annotations"].get("version", 0)),
        "tags": [],
        "shapes": shapes,
        "tracks": [],
    }
    _write_json(root / "apply-payload.json", payload)
    client.put(f"/api/tasks/{config.locked_task_id}/annotations/", payload, timeout=300)
    after = client.get(f"/api/tasks/{config.locked_task_id}/annotations", timeout=180)
    after_shapes = _ensure_rectangle_contract(after)
    try:
        if canonical_shape_hash(after_shapes) != expected_hash:
            raise RuntimeError("post-apply locked-task semantic hash verification failed")
        train_after = client.get(f"/api/tasks/{config.train_task_id}/annotations", timeout=180)
        if canonical_shape_hash(_ensure_rectangle_contract(train_after)) != str(snapshot["trainTaskShapeHash"]):
            raise RuntimeError("CVAT task 9 changed during locked-test apply")
    except Exception:
        rollback = _load_json(root / "snapshot" / "rollback-payload.json")
        rollback["version"] = int(after.get("version", 0))
        client.put(f"/api/tasks/{config.locked_task_id}/annotations/", rollback, timeout=300)
        raise
    label_names = {int(item["id"]): str(item["name"]) for item in locked_live["labels"]}
    class_counts = Counter(label_names[int(shape["label_id"])] for shape in after_shapes)
    job_id = int(snapshot["jobs"][0]["id"]) if snapshot.get("jobs") else 0
    receipt = {
        "stage": "locked-apply-complete",
        "createdAt": _utc_now(),
        "trainTaskId": config.train_task_id,
        "trainTaskShapeCount": len(train_shapes),
        "trainTaskShapeHash": str(snapshot["trainTaskShapeHash"]),
        "trainTaskUnchanged": True,
        "lockedTaskId": config.locked_task_id,
        "lockedTaskShapeCountBefore": len(locked_shapes),
        "lockedTaskShapeCountAfter": len(after_shapes),
        "lockedTaskShapeHashAfter": canonical_shape_hash(after_shapes),
        "classCounts": dict(sorted(class_counts.items())),
        "checkpointSha256": _sha256_file(checkpoint),
        "lockedTaskUsedForTraining": False,
        "lockedTaskPrelabeledForHumanReview": True,
        "eligibleForTraining": False,
        "helperActivated": False,
        "resumeUrl": (
            f"{config.base_url.rstrip('/')}/tasks/{config.locked_task_id}/jobs/{job_id}?frame=0"
            if job_id else f"{config.base_url.rstrip('/')}/tasks/{config.locked_task_id}"
        ),
    }
    _write_json(root / "apply-receipt.json", receipt)
    return receipt


def _config(args: argparse.Namespace) -> LockedPrelabelConfig:
    return LockedPrelabelConfig(
        package=args.package.resolve(),
        output=args.output.resolve(),
        base_model=args.base_model.resolve(),
        base_url=args.base_url,
        train_task_id=args.train_task_id,
        locked_task_id=args.locked_task_id,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("snapshot", "predict", "filter", "audit", "apply"))
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-model", type=Path, default=Path("yolo11n.pt"))
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--train-task-id", type=int, default=9)
    parser.add_argument("--locked-task-id", type=int, default=10)
    args = parser.parse_args()
    config = _config(args)
    operations = {
        "snapshot": snapshot_locked_task,
        "predict": predict_locked_task,
        "filter": filter_locked_task,
        "audit": audit_locked_task,
        "apply": apply_locked_task,
    }
    result = operations[args.stage](config)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
