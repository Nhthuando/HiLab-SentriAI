"""GPU-safe custom-model training. The base monitor model is never modified."""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Ultralytics imports OpenCV below.  Keep its native worker pool intentionally
# small: this worker is designed to train on laptops that may have a 4 GB GPU
# and several foreground applications open at the same time.
os.environ.setdefault("OPENCV_FOR_THREADS_NUM", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import cv2
import torch
from ultralytics import YOLO

from .dataset_exporter import manifest_class_definitions, materialize
from .local_video_dataset import CLASS_NAMES as LOCAL_VIDEO_CLASS_NAMES

EVENT_PREFIX = "SENTRIAI_EVENT "


def _emit(event: str, **payload: Any) -> None:
    print(f"{EVENT_PREFIX}{json.dumps({'event': event, **payload}, ensure_ascii=False)}", flush=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_runner_report(output: Path, job_id: str, report: dict[str, Any]) -> None:
    """Persist a terminal result when the parent Node process restarts."""
    reports = output / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    destination = reports / f"{job_id}.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)


def _worker_health() -> dict[str, Any] | None:
    worker_url = os.getenv("PYTHON_WORKER_HTTP_URL", "http://127.0.0.1:8001").rstrip("/")
    try:
        with urllib.request.urlopen(f"{worker_url}/health", timeout=2.0) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None


def _monitor_camera_active() -> bool:
    health = _worker_health()
    return any(bool(camera.get("active")) for camera in (health or {}).get("cameras", {}).values())


def _metric(value: Any) -> float:
    try:
        return round(float(value), 5)
    except (TypeError, ValueError):
        return 0.0


def _metric_values(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value) if isinstance(value, (list, tuple)) else []


def _evaluation(metrics: Any, labels: list[str], runtime_mode: str = "SUPPLEMENTAL") -> dict[str, Any]:
    box = getattr(metrics, "box", None)
    per_class_values = list(getattr(box, "maps", []) or [])
    per_class_precision = _metric_values(getattr(box, "p", None))
    per_class_recall = _metric_values(getattr(box, "r", None))
    per_class = {
        label: {
            "map": _metric(per_class_values[index]) if index < len(per_class_values) else None,
            "precision": _metric(per_class_precision[index]) if index < len(per_class_precision) else None,
            "recall": _metric(per_class_recall[index]) if index < len(per_class_recall) else None,
        }
        for index, label in enumerate(labels)
    }
    base_regression = (
        {"passed": True, "mode": "base_yolo_unchanged"}
        if runtime_mode == "SUPPLEMENTAL"
        else {"passed": False, "mode": "pending_locked_video_gate"}
    )
    return {
        "map50": _metric(getattr(box, "map50", 0.0)),
        "map": _metric(getattr(box, "map", 0.0)),
        "precision": _metric(getattr(box, "mp", 0.0)),
        "recall": _metric(getattr(box, "mr", 0.0)),
        "perClass": per_class,
        "runtimeMode": runtime_mode,
        "baseRegression": base_regression,
    }


def _finite_metric(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _quality_gate(
    metrics: dict[str, Any],
    required_classes: list[str] | None = None,
    runtime_mode: str = "SUPPLEMENTAL",
) -> tuple[bool, list[str]]:
    minimum_map50 = float(os.getenv("TRAINING_MIN_MAP50", "0.65"))
    minimum_precision = float(os.getenv("TRAINING_MIN_PRECISION", "0.65"))
    minimum_recall = float(os.getenv("TRAINING_MIN_RECALL", "0.55"))
    failures: list[str] = []
    for field, threshold, label in (
        ("map50", minimum_map50, "mAP50"),
        ("precision", minimum_precision, "precision"),
        ("recall", minimum_recall, "recall"),
    ):
        value = _finite_metric(metrics.get(field))
        if value is None:
            failures.append(f"{label} is undefined")
        elif value < threshold:
            failures.append(f"{label} below required threshold")
    if required_classes:
        minimum_class_map = float(os.getenv("TRAINING_YARD_MIN_CLASS_MAP", "0.55"))
        for label in required_classes:
            class_map = _finite_metric(metrics.get("perClass", {}).get(label, {}).get("map"))
            if class_map is None:
                failures.append(f"{label} mAP is undefined")
            elif class_map < minimum_class_map:
                failures.append(f"{label} mAP below required threshold")
    if runtime_mode == "UNIFIED":
        reach_metrics = metrics.get("perClass", {}).get("reach_stacker", {})
        for field in ("precision", "recall"):
            value = _finite_metric(reach_metrics.get(field))
            if value is None:
                failures.append(f"reach_stacker {field} is undefined")
            elif value < 0.90:
                failures.append(f"reach_stacker {field} below 0.90")
    return not failures, failures


def _is_system_memory_error(error: BaseException) -> bool:
    """Recognise recoverable host-RAM pressure without masking other failures."""
    message = str(error).lower()
    return "insufficient memory" in message or "outofmemoryerror" in message or "std::bad_alloc" in message


def _configure_low_memory_training() -> None:
    """Use one native thread and release allocator caches before a resumed run."""
    cv2.setNumThreads(1)
    try:
        cv2.ocl.setUseOpenCL(False)
    except cv2.error:
        pass
    torch.set_num_threads(1)
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _training_dataset_contract(manifest_path: Path, output: Path) -> dict[str, Any]:
    """Resolve legacy supplemental and reviewed local-video manifests safely."""
    snapshot = json.loads(manifest_path.read_text(encoding="utf-8"))
    if snapshot.get("datasetKind") == "LOCAL_VIDEO_REVIEWED":
        if snapshot.get("schemaVersion") != 3 or snapshot.get("reviewStatus") != "REVIEWED":
            raise ValueError("Local-video training requires a finalized REVIEWED schema-v3 snapshot")
        classes = snapshot.get("classes")
        if classes != list(LOCAL_VIDEO_CLASS_NAMES):
            raise ValueError("Local-video class order does not match the unified BAI-KIEM profile")
        frames = snapshot.get("frames")
        if not isinstance(frames, list) or not frames:
            raise ValueError("Reviewed local-video snapshot has no frames")
        counts = {split: 0 for split in ("train", "val", "test")}
        source_splits: dict[str, set[str]] = {}
        validation_classes: set[str] = set()
        for index, frame in enumerate(frames):
            if not isinstance(frame, dict):
                raise ValueError(f"frames[{index}] is invalid")
            split = frame.get("split")
            source_id = frame.get("sourceId")
            if split not in counts or not isinstance(source_id, str) or not source_id:
                raise ValueError(f"frames[{index}] has invalid split/sourceId")
            counts[split] += 1
            source_splits.setdefault(source_id, set()).add(split)
            for field in ("imagePath", "labelsPath"):
                relative = frame.get(field)
                if not isinstance(relative, str) or not (manifest_path.parent / relative).is_file():
                    raise ValueError(f"frames[{index}] is missing {field}")
            if split == "val":
                label_path = manifest_path.parent / str(frame["labelsPath"])
                for line in label_path.read_text(encoding="utf-8").splitlines():
                    fields = line.split()
                    if fields:
                        class_id = int(fields[0])
                        if not 0 <= class_id < len(classes):
                            raise ValueError(f"frames[{index}] has an invalid class ID")
                        validation_classes.add(classes[class_id])
        if counts["train"] == 0 or counts["val"] == 0 or counts["test"] == 0:
            raise ValueError("Unified dataset requires non-empty train, val, and locked test splits")
        content_hash = snapshot.get("contentHash")
        if not isinstance(content_hash, str) or len(content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in content_hash.casefold()
        ):
            raise ValueError("Reviewed local-video snapshot has no valid content hash")
        data_yaml = manifest_path.parent / "data.yaml"
        if not data_yaml.is_file():
            raise ValueError("Reviewed local-video snapshot has no data.yaml")
        return {
            "snapshot": snapshot,
            "dataset": manifest_path.parent,
            "labels": list(classes),
            "labelMap": {name: name for name in classes},
            "counts": counts,
            "profile": "BAIKIEM_LOCAL_UNIFIED_YOLO11N",
            "runtimeMode": "UNIFIED",
            "datasetContentHash": content_hash.casefold(),
            "sourceSplits": {source: sorted(splits) for source, splits in sorted(source_splits.items())},
            "validationClasses": sorted(validation_classes),
        }

    # Keep generated YOLO files separate from immutable source snapshots.
    dataset = materialize(manifest_path, output / "materialized-datasets")
    profile = snapshot.get("profile")
    class_definitions = manifest_class_definitions(snapshot)
    labels = [item["label"] for item in class_definitions]
    samples = snapshot.get("samples")
    if not isinstance(samples, list):
        raise ValueError("Training manifest has no samples")
    counts = {
        split: sum(1 for sample in samples if sample.get("split") == split)
        for split in ("train", "val", "test")
    }
    return {
        "snapshot": snapshot,
        "dataset": dataset,
        "labels": labels,
        "labelMap": {item["label"]: item["baseClass"] for item in class_definitions},
        "counts": counts,
        "profile": profile,
        "runtimeMode": "SUPPLEMENTAL",
        "datasetContentHash": snapshot.get("contentHash"),
        "sourceSplits": {},
        "validationClasses": labels if isinstance(profile, str) and profile else [],
    }


def run_training(manifest_path: str, base_model: str, output_root: str, job_id: str, total_epochs: int = 60) -> dict[str, Any]:
    """Train one custom augmentation candidate and return a safe, JSON-ready report."""
    output = Path(output_root).resolve()
    # A 4 GB mobile GPU cannot reliably train and serve the Area feed together.
    # Waiting releases the training process entirely, so the live camera keeps priority.
    if _monitor_camera_active():
        report = {"outcome": "paused", "reason": "CAMERA_ACTIVE"}
        _write_runner_report(output, job_id, report)
        _emit("paused", reason="CAMERA_ACTIVE")
        return report

    manifest = Path(manifest_path).resolve()
    contract = _training_dataset_contract(manifest, output)
    dataset = Path(contract["dataset"])
    profile = contract["profile"]
    labels = list(contract["labels"])
    label_map = dict(contract["labelMap"])
    runtime_mode = str(contract["runtimeMode"])
    counts = contract["counts"]
    train_count, val_count, test_count = counts["train"], counts["val"], counts["test"]
    if train_count == 0 or val_count == 0:
        raise ValueError("Dataset must contain source-separated train and validation samples")

    _configure_low_memory_training()
    run_directory = output / "runs" / job_id
    resume_checkpoint = run_directory / "weights" / "last.pt"
    should_resume = resume_checkpoint.is_file()
    model = YOLO(str(resume_checkpoint if should_resume else base_model))
    epochs = max(1, int(total_epochs))
    _emit("running", epoch=0, totalEpochs=epochs, resumed=should_resume)
    paused_for_camera = False

    def on_epoch_end(trainer: Any) -> None:
        nonlocal paused_for_camera
        epoch = int(getattr(trainer, "epoch", 0)) + 1
        _emit("progress", epoch=min(epoch, epochs), totalEpochs=epochs)
        # A health request per batch can stall a small-GPU training run when
        # the monitor worker is intentionally offline.  Check at the epoch
        # boundary instead: camera work still wins, while CUDA batches run
        # without network polling in their hot path.
        if not paused_for_camera and _monitor_camera_active():
            paused_for_camera = True
            trainer.stop = True
            _emit("paused", reason="CAMERA_ACTIVE")

    model.add_callback("on_fit_epoch_end", on_epoch_end)
    # Conservative batch/workers preserve enough VRAM for the loaded monitor model
    # when the camera is re-opened after a queued run.
    train_options: dict[str, Any] = {
        "data": str(dataset / "data.yaml"),
        "epochs": epochs,
        "imgsz": int(os.getenv("TRAINING_IMAGE_SIZE", "896" if runtime_mode == "UNIFIED" else "640")),
        "batch": int(os.getenv("TRAINING_BATCH", "1")),
        "workers": 0,
        "device": 0,
        "amp": True,
        "patience": int(os.getenv("TRAINING_PATIENCE", "15")),
        # Disk cache avoids retaining decoded images in process memory between
        # batches, which is safer than RAM cache on operator workstations.
        "cache": "disk",
        "project": str(output / "runs"),
        "name": job_id,
        "exist_ok": True,
        "verbose": False,
        # Realistic yard-camera augmentation shared by supplemental and
        # unified candidates. Avoid rotations/perspective that cannot occur
        # on a fixed CCTV camera and keep mosaic modest for small/far targets.
        "degrees": 0.0,
        "translate": 0.08,
        "scale": 0.35,
        "shear": 0.0,
        "perspective": 0.0,
        "flipud": 0.0,
        "fliplr": 0.5,
        "hsv_h": 0.01,
        "hsv_s": 0.35,
        "hsv_v": 0.25,
        "mosaic": 0.25,
        "mixup": 0.0,
        "close_mosaic": 10,
        "optimizer": os.getenv("TRAINING_OPTIMIZER", "AdamW"),
        "lr0": float(os.getenv("TRAINING_LR0", "0.001")),
        "lrf": float(os.getenv("TRAINING_LRF", "0.01")),
        "warmup_epochs": float(os.getenv("TRAINING_WARMUP_EPOCHS", "1.0")),
    }
    if should_resume:
        train_options["resume"] = str(resume_checkpoint)
    try:
        result = model.train(**train_options)
    except Exception as error:
        if _is_system_memory_error(error):
            report = {"outcome": "paused", "reason": "LOW_SYSTEM_MEMORY"}
            _write_runner_report(output, job_id, report)
            _emit("paused", reason="LOW_SYSTEM_MEMORY")
            return report
        raise
    if paused_for_camera:
        report = {"outcome": "paused", "reason": "CAMERA_ACTIVE"}
        _write_runner_report(output, job_id, report)
        return report
    save_dir = Path(getattr(result, "save_dir", getattr(getattr(model, "trainer", None), "save_dir", output / "runs" / job_id)))
    best = save_dir / "weights" / "best.pt"
    if not best.is_file():
        raise RuntimeError("Training completed without a best checkpoint")

    _emit("evaluating", epoch=epochs, totalEpochs=epochs)
    # The locked test split is consumed only by the later video-level
    # acceptance gate. Candidate selection must never tune against it.
    evaluation_split = "val"
    validation = model.val(data=str(dataset / "data.yaml"), split=evaluation_split, device=0, workers=0, verbose=False)
    metrics = _evaluation(validation, labels, runtime_mode)
    metrics["evaluationSplit"] = evaluation_split
    required_classes = list(contract["validationClasses"])
    accepted, failures = _quality_gate(metrics, required_classes, runtime_mode)
    metrics["validationGate"] = {"passed": accepted, "failures": list(failures)}
    metrics["qualityGate"] = {"passed": accepted, "failures": failures}
    metrics["trainingProfile"] = profile
    metrics["datasetContentHash"] = contract["datasetContentHash"]
    metrics["sourceSplits"] = contract["sourceSplits"]
    metrics["trainingArguments"] = {
        key: train_options[key]
        for key in (
            "epochs", "imgsz", "batch", "workers", "amp", "patience", "degrees",
            "translate", "scale", "shear", "perspective", "flipud", "fliplr",
            "hsv_h", "hsv_s", "hsv_v", "mosaic", "mixup", "close_mosaic",
            "optimizer", "lr0", "lrf", "warmup_epochs",
        )
        if key in train_options
    }
    if runtime_mode == "UNIFIED":
        # Validation metrics alone are intentionally insufficient for a model
        # that replaces base COCO. A later locked-video/FPS finalizer may
        # promote this artifact, but the training runner itself never can.
        accepted = False
        failures = [*failures, "locked video accuracy/continuity/FPS gate is pending"]
        metrics["qualityGate"] = {"passed": False, "failures": failures}
        metrics["activationGate"] = {"passed": False, "reason": "PENDING_LOCKED_VIDEO_GATE"}

    artifact_dir = output / "models" / job_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact = artifact_dir / "best.pt"
    shutil.copy2(best, artifact)
    (artifact_dir / "labels.json").write_text(json.dumps(label_map, ensure_ascii=False, indent=2), encoding="utf-8")
    (artifact_dir / "evaluation.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    relative_artifact = artifact.relative_to(output.parents[0]).as_posix()
    report = {
        "outcome": "completed",
        "artifactPath": relative_artifact,
        "artifactSha256": _sha256(artifact),
        "metrics": metrics,
        "labelMap": label_map,
        "accepted": accepted,
    }
    _write_runner_report(output, job_id, report)
    _emit("completed", **report)
    return report


if __name__ == "__main__":
    if len(sys.argv) != 6:
        raise SystemExit("usage: runner.py <manifest> <base-model> <output-root> <job-id> <epochs>")
    final = run_training(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]))
    _emit("result", **final)
