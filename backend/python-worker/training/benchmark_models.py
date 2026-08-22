"""Benchmark YOLO checkpoints on one Ultralytics dataset split.

The script reports two things separately:
- validation metrics on the requested split, for class-aligned fine-tuned models
- single-frame prediction latency on images loaded in memory, for runtime speed
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

import cv2
import torch
import yaml
from ultralytics import YOLO


def _metric(value: Any) -> float:
    try:
        return round(float(value), 5)
    except (TypeError, ValueError):
        return 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((percentile / 100.0) * (len(ordered) - 1))))
    return round(ordered[index], 3)


def _read_data_yaml(data_yaml: Path) -> dict[str, Any]:
    with data_yaml.open("r", encoding="utf-8") as source:
        loaded = yaml.safe_load(source) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Invalid dataset yaml: {data_yaml}")
    return loaded


def _split_images_dir(data_yaml: Path, split: str) -> Path:
    config = _read_data_yaml(data_yaml)
    dataset_root = Path(str(config.get("path") or data_yaml.parent)).expanduser()
    split_value = config.get(split)
    if not split_value:
        raise ValueError(f"Dataset yaml has no split named {split!r}")
    if isinstance(split_value, list):
        split_value = split_value[0]
    split_path = Path(str(split_value))
    return (split_path if split_path.is_absolute() else dataset_root / split_path).resolve()


def _load_images(images_dir: Path, limit: int) -> list[Any]:
    paths = sorted(
        path
        for path in images_dir.rglob("*")
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    )
    if limit > 0:
        paths = paths[:limit]
    images = []
    for path in paths:
        image = cv2.imread(str(path))
        if image is not None:
            images.append(image)
    if not images:
        raise ValueError(f"No readable images in {images_dir}")
    return images


def _parse_candidate(raw: str) -> dict[str, Any]:
    parts = raw.split("|")
    if len(parts) not in {2, 3}:
        raise ValueError("--candidate format must be name|path|val, e.g. v8|weights.pt|true")
    name, model_path = parts[0].strip(), parts[1].strip()
    should_validate = True if len(parts) == 2 else parts[2].strip().casefold() not in {"0", "false", "no"}
    if not name or not model_path:
        raise ValueError("--candidate requires a name and path")
    return {"name": name, "path": model_path, "validate": should_validate}


def _validation_metrics(
    name: str,
    model_path: Path,
    data_yaml: Path,
    split: str,
    imgsz: int,
    device: str,
    output_dir: Path,
) -> dict[str, Any]:
    model = YOLO(str(model_path))
    result = model.val(
        data=str(data_yaml),
        split=split,
        imgsz=imgsz,
        batch=1,
        device=device,
        workers=0,
        verbose=False,
        plots=False,
        save_json=False,
        project=str(output_dir / "ultralytics"),
        name=f"{name}-val",
        exist_ok=True,
    )
    box = getattr(result, "box", None)
    speed = getattr(result, "speed", {}) or {}
    metrics = {
        "precision": _metric(getattr(box, "mp", 0.0)),
        "recall": _metric(getattr(box, "mr", 0.0)),
        "map50": _metric(getattr(box, "map50", 0.0)),
        "map50_95": _metric(getattr(box, "map", 0.0)),
        "speed_ms_per_image": {key: _metric(value) for key, value in speed.items()},
    }
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return metrics


def _latency_metrics(
    model_path: Path,
    images: list[Any],
    imgsz: int,
    device: str,
    warmup: int,
    iterations: int,
    half: bool,
) -> dict[str, Any]:
    model = YOLO(str(model_path))
    for index in range(max(0, warmup)):
        model.predict(
            images[index % len(images)],
            imgsz=imgsz,
            device=device,
            half=half,
            verbose=False,
        )
    if torch.cuda.is_available():
        torch.cuda.synchronize()

    latencies: list[float] = []
    total = max(1, iterations)
    for index in range(total):
        image = images[index % len(images)]
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        start = time.perf_counter()
        model.predict(image, imgsz=imgsz, device=device, half=half, verbose=False)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        latencies.append((time.perf_counter() - start) * 1000.0)

    mean_ms = statistics.fmean(latencies)
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return {
        "iterations": total,
        "mean_ms": round(mean_ms, 3),
        "median_ms": round(statistics.median(latencies), 3),
        "p95_ms": _percentile(latencies, 95),
        "fps": round(1000.0 / mean_ms, 2) if mean_ms > 0 else 0.0,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    data_yaml = Path(args.data).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output_dir = output.parent
    images = _load_images(_split_images_dir(data_yaml, args.speed_split), args.image_limit)
    candidates = [_parse_candidate(candidate) for candidate in args.candidate]
    device = args.device
    half = bool(args.half and device != "cpu")

    report: dict[str, Any] = {
        "data": str(data_yaml),
        "validation_split": args.val_split,
        "speed_split": args.speed_split,
        "imgsz": args.imgsz,
        "device": device,
        "half": half,
        "image_count_for_speed": len(images),
        "candidates": [],
    }

    for candidate in candidates:
        model_path = Path(candidate["path"]).resolve()
        item: dict[str, Any] = {
            "name": candidate["name"],
            "path": str(model_path),
            "validate": candidate["validate"],
        }
        if candidate["validate"]:
            item["validation"] = _validation_metrics(
                candidate["name"],
                model_path,
                data_yaml,
                args.val_split,
                args.imgsz,
                device,
                output_dir,
            )
        item["latency"] = _latency_metrics(
            model_path,
            images,
            args.imgsz,
            device,
            args.warmup,
            args.iterations,
            half,
        )
        report["candidates"].append(item)

    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--candidate", action="append", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--val-split", default="test")
    parser.add_argument("--speed-split", default="test")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="0" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--warmup", type=int, default=8)
    parser.add_argument("--iterations", type=int, default=80)
    parser.add_argument("--image-limit", type=int, default=20)
    parser.add_argument("--half", action="store_true")
    report = run(parser.parse_args())
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
