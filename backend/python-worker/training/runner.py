"""GPU-safe custom-model training. The base monitor model is never modified."""
from __future__ import annotations

import hashlib
import json
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

from .dataset_exporter import materialize

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


def _evaluation(metrics: Any, labels: list[str]) -> dict[str, Any]:
    box = getattr(metrics, "box", None)
    per_class_values = list(getattr(box, "maps", []) or [])
    per_class = {
        label: {"map": _metric(per_class_values[index]) if index < len(per_class_values) else 0.0}
        for index, label in enumerate(labels)
    }
    return {
        "map50": _metric(getattr(box, "map50", 0.0)),
        "map": _metric(getattr(box, "map", 0.0)),
        "precision": _metric(getattr(box, "mp", 0.0)),
        "recall": _metric(getattr(box, "mr", 0.0)),
        "perClass": per_class,
        # The candidate is an augment-only detector. Base COCO detections remain
        # in the live pipeline and are never filtered by this training process.
        "baseRegression": {"passed": True, "mode": "base_yolo_unchanged"},
    }


def _quality_gate(metrics: dict[str, Any], profile: str | None = None) -> tuple[bool, list[str]]:
    minimum_map50 = float(os.getenv("TRAINING_MIN_MAP50", "0.65"))
    minimum_precision = float(os.getenv("TRAINING_MIN_PRECISION", "0.65"))
    minimum_recall = float(os.getenv("TRAINING_MIN_RECALL", "0.55"))
    failures: list[str] = []
    if metrics["map50"] < minimum_map50:
        failures.append("mAP50 below required threshold")
    if metrics["precision"] < minimum_precision:
        failures.append("precision below required threshold")
    if metrics["recall"] < minimum_recall:
        failures.append("recall below required threshold")
    if profile == "YARD_VEHICLE_V1":
        minimum_class_map = float(os.getenv("TRAINING_YARD_MIN_CLASS_MAP", "0.55"))
        for label in ("Container", "Xe tải", "Xe nâng"):
            if _metric(metrics.get("perClass", {}).get(label, {}).get("map")) < minimum_class_map:
                failures.append(f"{label} mAP below required threshold")
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
    dataset = materialize(manifest, output / "datasets")
    snapshot = json.loads(manifest.read_text(encoding="utf-8"))
    profile = snapshot.get("profile")
    labels = sorted({str(sample["label"]) for sample in snapshot["samples"]})
    label_map = {str(sample["label"]): str(sample["baseClass"]) for sample in snapshot["samples"]}
    train_count = sum(1 for sample in snapshot["samples"] if sample["split"] == "train")
    val_count = sum(1 for sample in snapshot["samples"] if sample["split"] == "val")
    test_count = sum(1 for sample in snapshot["samples"] if sample["split"] == "test")
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
        "imgsz": int(os.getenv("TRAINING_IMAGE_SIZE", "640")),
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
    evaluation_split = "test" if test_count else "val"
    validation = model.val(data=str(dataset / "data.yaml"), split=evaluation_split, device=0, workers=0, verbose=False)
    metrics = _evaluation(validation, labels)
    metrics["evaluationSplit"] = evaluation_split
    accepted, failures = _quality_gate(metrics, profile if isinstance(profile, str) else None)
    metrics["qualityGate"] = {"passed": accepted, "failures": failures}
    metrics["trainingProfile"] = profile

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
