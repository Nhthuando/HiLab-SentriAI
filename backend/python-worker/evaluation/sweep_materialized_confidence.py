"""Sweep confidence on a materialized one-class YOLO validation split."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
import yaml
from ultralytics import YOLO

from evaluation.metrics import iou


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _split_paths(data_yaml: Path, split: str) -> tuple[list[Path], Path]:
    config = yaml.safe_load(data_yaml.read_text(encoding="utf-8")) or {}
    root = Path(str(config.get("path") or data_yaml.parent))
    if not root.is_absolute():
        root = (data_yaml.parent / root).resolve()
    image_root = Path(str(config[split]))
    if not image_root.is_absolute():
        image_root = (root / image_root).resolve()
    images = sorted(path for path in image_root.rglob("*") if path.suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"})
    if not images:
        raise ValueError(f"split {split!r} contains no images")
    return images, root


def _truths(image: Path) -> list[list[float]]:
    label_path = image.parent.parent.parent / "labels" / image.parent.name / f"{image.stem}.txt"
    if not label_path.is_file():
        raise FileNotFoundError(f"validation label is missing: {label_path}")
    output: list[list[float]] = []
    for raw_line in label_path.read_text(encoding="utf-8").splitlines():
        fields = raw_line.split()
        if not fields:
            continue
        if len(fields) != 5 or int(fields[0]) != 0:
            raise ValueError(f"one-class validation label is invalid: {label_path}")
        center_x, center_y, width, height = (float(value) for value in fields[1:])
        output.append([
            center_x - width / 2, center_y - height / 2,
            center_x + width / 2, center_y + height / 2,
        ])
    return output


def evaluate_threshold(
    ground_truth: Mapping[str, Sequence[Sequence[float]]],
    predictions: Mapping[str, Sequence[Mapping[str, Any]]],
    confidence: float,
    *,
    iou_threshold: float = 0.50,
) -> dict[str, Any]:
    tp = fp = fn = 0
    for frame_id in sorted(set(ground_truth) | set(predictions)):
        truths = list(ground_truth.get(frame_id, ()))
        candidates = sorted(
            [item for item in predictions.get(frame_id, ()) if float(item["confidence"]) >= confidence],
            key=lambda item: -float(item["confidence"]),
        )
        matched: set[int] = set()
        for prediction in candidates:
            best_index = None
            best_overlap = iou_threshold
            for truth_index, truth in enumerate(truths):
                if truth_index in matched:
                    continue
                overlap = iou(prediction["bbox"], truth)
                if overlap >= best_overlap:
                    best_overlap = overlap
                    best_index = truth_index
            if best_index is None:
                fp += 1
            else:
                matched.add(best_index)
                tp += 1
        fn += len(truths) - len(matched)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "confidence": confidence,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "tp": tp, "fp": fp, "fn": fn,
    }


def run(
    data_yaml: Path,
    model_path: Path,
    output: Path,
    *,
    thresholds: Sequence[float],
    split: str = "val",
    image_size: int = 768,
    batch: int = 8,
    device: str = "0",
) -> dict[str, Any]:
    data_yaml = data_yaml.resolve()
    model_path = model_path.resolve()
    images, _root = _split_paths(data_yaml, split)
    ground_truth = {str(path): _truths(path) for path in images}
    predictions: dict[str, list[dict[str, Any]]] = {}
    model = YOLO(str(model_path))
    started = time.perf_counter()
    chunk_size = max(batch, batch * 4)
    for offset in range(0, len(images), chunk_size):
        chunk = images[offset:offset + chunk_size]
        kwargs: dict[str, Any] = {
            "source": [str(path) for path in chunk],
            "batch": batch,
            "imgsz": image_size,
            "conf": 0.001,
            "iou": 0.70,
            "max_det": 300,
            "device": device,
            "verbose": False,
        }
        if str(device).casefold() != "cpu":
            kwargs["quantize"] = 16
        results = model.predict(**kwargs)
        for path, result in zip(chunk, results, strict=True):
            height, width = result.orig_shape
            boxes = getattr(result, "boxes", None)
            predictions[str(path)] = [] if boxes is None else [
                {
                    "bbox": [xyxy[0] / width, xyxy[1] / height, xyxy[2] / width, xyxy[3] / height],
                    "confidence": float(confidence),
                }
                for xyxy, confidence in zip(boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist(), strict=True)
            ]
    wall_seconds = time.perf_counter() - started
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    rows = [evaluate_threshold(ground_truth, predictions, float(value)) for value in thresholds]
    eligible = [row for row in rows if row["recall"] >= 0.75]
    best = max(eligible or rows, key=lambda row: (row["f1"], row["precision"], row["recall"]))
    report = {
        "schemaVersion": 1,
        "split": split,
        "lockedTestUsed": False,
        "dataYaml": str(data_yaml),
        "modelPath": str(model_path),
        "artifactSha256": _sha256(model_path),
        "frameCount": len(images),
        "groundTruthCount": sum(len(items) for items in ground_truth.values()),
        "imageSize": image_size,
        "performance": {
            "wallSeconds": round(wall_seconds, 6),
            "wallFps": round(len(images) / wall_seconds, 3),
        },
        "thresholds": rows,
        "recommended": {**best, "policy": "maximum F1 subject to recall >= 0.75"},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--thresholds", type=float, nargs="+", required=True)
    parser.add_argument("--split", default="val")
    parser.add_argument("--imgsz", type=int, default=768)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()
    print(json.dumps(run(
        args.data, args.model, args.output, thresholds=args.thresholds,
        split=args.split, image_size=args.imgsz, batch=args.batch, device=args.device,
    ), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
