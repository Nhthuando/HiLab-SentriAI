"""Train the final five-class BAI-KIEM V9 YOLO11n candidate safely."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("OPENCV_FOR_THREADS_NUM", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import cv2
import torch
from ultralytics import YOLO

from training.v9_final_dataset import V9_CLASSES


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _validate_dataset(dataset: Path) -> dict[str, Any]:
    manifest_path = dataset / "dataset-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("datasetKind") != "BAIKIEM_V9_FINAL_TRAIN_VAL":
        raise ValueError("dataset is not the frozen BAI-KIEM V9 train/validation snapshot")
    if tuple(manifest.get("classes", ())) != V9_CLASSES:
        raise ValueError("dataset class order differs from the V9 five-class contract")
    if int(manifest.get("frames", {}).get("train", 0)) <= 0 or int(manifest.get("frames", {}).get("val", 0)) <= 0:
        raise ValueError("dataset has no train or validation frames")
    if int(manifest.get("trainValidationImageHashOverlap", -1)) != 0:
        raise ValueError("train/validation image leakage was detected")
    for split in ("train", "val"):
        if any(int(manifest.get("boxes", {}).get(split, {}).get(name, 0)) <= 0 for name in V9_CLASSES):
            raise ValueError(f"{split} split does not cover all V9 classes")
    return manifest


def train_v9(
    dataset: Path,
    base_model: Path,
    output_root: Path,
    *,
    name: str,
    epochs: int,
    batch: int,
    workers: int,
    resume: bool = False,
) -> dict[str, Any]:
    dataset = dataset.resolve()
    base_model = base_model.resolve()
    output_root = output_root.resolve()
    manifest = _validate_dataset(dataset)
    if not base_model.is_file():
        raise FileNotFoundError(f"YOLO11n initialization checkpoint is missing: {base_model}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for final V9 training")

    cv2.setNumThreads(1)
    try:
        cv2.ocl.setUseOpenCL(False)
    except cv2.error:
        pass
    torch.set_num_threads(1)
    torch.cuda.empty_cache()

    run_dir = output_root / "runs" / name
    last_checkpoint = run_dir / "weights" / "last.pt"
    best_checkpoint = run_dir / "weights" / "best.pt"
    if resume:
        if not last_checkpoint.is_file():
            raise FileNotFoundError(f"resume checkpoint is missing: {last_checkpoint}")
        model_source = last_checkpoint
    else:
        if run_dir.exists():
            raise FileExistsError(f"fresh V9 run directory already exists: {run_dir}")
        model_source = base_model

    configuration = {
        "epochs": epochs,
        "imgsz": 896,
        "batch": batch,
        "workers": workers,
        "device": 0,
        "amp": True,
        "cache": False,
        "patience": 20,
        "optimizer": "AdamW",
        "lr0": 0.001,
        "lrf": 0.01,
        "warmup_epochs": 1.0,
        "translate": 0.08,
        "scale": 0.35,
        "fliplr": 0.5,
        "hsv_h": 0.01,
        "hsv_s": 0.35,
        "hsv_v": 0.25,
        "mosaic": 0.25,
        "mixup": 0.0,
        "close_mosaic": 15,
        "seed": 42,
        "deterministic": True,
        "save_period": 10,
        "plots": True,
        "verbose": True,
    }
    started = time.time()
    start_receipt = {
        "schemaVersion": 1,
        "status": "RUNNING",
        "runName": name,
        "initialization": "resume-last" if resume else "official-yolo11n-pretrained",
        "initializationPath": str(model_source),
        "baseModelSha256": _sha256(base_model),
        "datasetPath": str(dataset),
        "datasetContentHash": manifest["contentHash"],
        "classes": list(V9_CLASSES),
        "lockedTestUsed": False,
        "configuration": configuration,
        "gpu": torch.cuda.get_device_name(0),
        "startedUnix": started,
    }
    _atomic_json(output_root / "reports" / f"{name}-training.json", start_receipt)
    print("SENTRIAI_V9 " + json.dumps(start_receipt, ensure_ascii=False), flush=True)

    model = YOLO(str(model_source))
    train_args = dict(configuration)
    if resume:
        # Ultralytics explicitly permits batch/workers/cache overrides on a
        # resumable checkpoint while restoring optimizer and scheduler state.
        results = model.train(
            resume=True, batch=batch, workers=workers, cache=False, device=0,
            patience=20, save_period=10, plots=True,
        )
    else:
        results = model.train(
            data=str(dataset / "data.yaml"),
            project=str(output_root / "runs"),
            name=name,
            exist_ok=False,
            pretrained=True,
            **train_args,
        )
    if not best_checkpoint.is_file():
        raise FileNotFoundError("Ultralytics completed without a best.pt checkpoint")
    artifact_dir = output_root / "models" / name
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact = artifact_dir / "best.pt"
    shutil.copy2(best_checkpoint, artifact)
    (artifact_dir / "labels.json").write_text(
        json.dumps({name: name for name in V9_CLASSES}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result_dict = {
        key: float(value)
        for key, value in getattr(results, "results_dict", {}).items()
        if isinstance(value, (int, float)) or hasattr(value, "item")
    }
    receipt = {
        **start_receipt,
        "status": "COMPLETED",
        "elapsedSeconds": round(time.time() - started, 3),
        "bestCheckpoint": str(artifact),
        "bestCheckpointSha256": _sha256(artifact),
        "trainingResult": result_dict,
        "lockedTestUsed": False,
    }
    _atomic_json(output_root / "reports" / f"{name}-training.json", receipt)
    _atomic_json(artifact_dir / "training-receipt.json", receipt)
    print("SENTRIAI_V9 " + json.dumps(receipt, ensure_ascii=False), flush=True)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--name", default="baikiem-v9-unified-candidate")
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    train_v9(
        args.dataset, args.base_model, args.output_root,
        name=args.name, epochs=args.epochs, batch=args.batch, workers=args.workers,
        resume=args.resume,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
