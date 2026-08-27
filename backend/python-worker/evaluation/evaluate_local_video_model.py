"""Evaluate a supplemental reach-stacker model on the reviewed local-video snapshot.

Validation mode performs confidence calibration without consulting the locked
test split.  Test mode requires the already-selected image size and threshold,
so the test set cannot silently become another tuning set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

os.environ.setdefault("OPENCV_FOR_THREADS_NUM", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import cv2
import torch
from ultralytics import YOLO

PYTHON_WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_WORKER_ROOT))

from evaluation.metrics import evaluate_detections
from detection.roi_inference import RoiSpec, build_tiles
from stream.native_video_frames import NativeVideoFrameLoader


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(metric: Mapping[str, Any]) -> float | None:
    value = metric.get("value")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def choose_threshold(
    points: Iterable[Mapping[str, Any]],
    *,
    minimum_precision: float = 0.90,
) -> dict[str, Any]:
    """Choose without test-set peeking: highest recall at target precision.

    If no point reaches the precision target, use the maximum-F1 point and
    clearly mark the target as missed instead of fabricating an acceptance.
    """
    normalized: list[dict[str, Any]] = []
    for point in points:
        precision = _number(point.get("precision", {}))
        recall = _number(point.get("recall", {}))
        if precision is None or recall is None:
            continue
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        normalized.append({
            "threshold": float(point["threshold"]),
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "tp": int(point.get("tp", 0)),
            "fp": int(point.get("fp", 0)),
            "fn": int(point.get("fn", 0)),
        })
    if not normalized:
        raise ValueError("No finite precision/recall calibration points")
    eligible = [point for point in normalized if point["precision"] >= minimum_precision]
    if eligible:
        selected = max(eligible, key=lambda point: (point["recall"], point["f1"], -point["threshold"]))
        reason = "maximum recall among thresholds meeting the precision target"
    else:
        selected = max(normalized, key=lambda point: (point["f1"], point["recall"], point["precision"]))
        reason = "no threshold met the precision target; maximum F1 fallback"
    return {
        **selected,
        "minimumPrecision": minimum_precision,
        "metPrecisionTarget": bool(eligible),
        "selectionReason": reason,
    }


def _load_split(snapshot: Path, split: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("schemaVersion") != 3
        or manifest.get("datasetKind") != "LOCAL_VIDEO_REVIEWED"
        or manifest.get("reviewStatus") != "REVIEWED"
    ):
        raise ValueError("Evaluation requires an exact finalized schema-v3 reviewed snapshot")
    classes = manifest.get("classes")
    if not isinstance(classes, list) or "reach_stacker" not in classes or "truck" not in classes:
        raise ValueError("Reviewed snapshot class contract is invalid")
    selected = [frame for frame in manifest.get("frames", []) if frame.get("split") == split]
    if not selected:
        raise ValueError(f"Reviewed snapshot has no {split!r} frames")

    ground_truth: dict[str, list[dict[str, Any]]] = {}
    for frame in selected:
        frame_id = str(frame["frameId"])
        labels: list[dict[str, Any]] = []
        label_path = snapshot / str(frame["labelsPath"])
        for raw_line in label_path.read_text(encoding="utf-8").splitlines():
            fields = raw_line.split()
            if not fields:
                continue
            class_id = int(fields[0])
            center_x, center_y, width, height = (float(value) for value in fields[1:])
            labels.append({
                "class": str(classes[class_id]),
                "bbox": [
                    max(0.0, center_x - width / 2),
                    max(0.0, center_y - height / 2),
                    min(1.0, center_x + width / 2),
                    min(1.0, center_y + height / 2),
                ],
            })
        ground_truth[frame_id] = labels
    return manifest, selected, ground_truth


def _predict(
    model: YOLO,
    snapshot: Path,
    frames: list[dict[str, Any]],
    *,
    imgsz: int,
    device: str,
    batch: int,
    confidence: float,
    source_loader: Callable[[Mapping[str, Any]], Any] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    started = time.perf_counter()
    predictions: dict[str, list[dict[str, Any]]] = {}
    inference_ms: list[float] = []
    # Ultralytics materializes a list source as PIL/numpy images before it
    # starts streaming results. Hundreds of 2.5K CCTV frames can therefore
    # exhaust system RAM even with a small GPU batch. Bound the source list;
    # this changes only memory usage, not ordering, model inputs, or metrics.
    chunk_size = max(batch, batch * 4)
    for offset in range(0, len(frames), chunk_size):
        chunk_frames = frames[offset:offset + chunk_size]
        chunk_sources = [
            source_loader(frame) if source_loader is not None
            else str(snapshot / str(frame["imagePath"]))
            for frame in chunk_frames
        ]
        results = model.predict(
            source=chunk_sources,
            stream=True,
            batch=batch,
            imgsz=imgsz,
            conf=confidence,
            iou=0.70,
            max_det=50,
            device=device,
            quantize=16 if str(device).casefold() != "cpu" else None,
            verbose=False,
        )
        for frame, result in zip(chunk_frames, results, strict=True):
            frame_predictions: list[dict[str, Any]] = []
            height, width = result.orig_shape
            boxes = getattr(result, "boxes", None)
            if boxes is not None:
                for xyxy, confidence_tensor in zip(boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist(), strict=True):
                    x1, y1, x2, y2 = xyxy
                    frame_predictions.append({
                        "class": "reach_stacker",
                        "source": "CUSTOM",
                        "confidence": float(confidence_tensor),
                        "bbox": [
                            max(0.0, min(1.0, x1 / width)),
                            max(0.0, min(1.0, y1 / height)),
                            max(0.0, min(1.0, x2 / width)),
                            max(0.0, min(1.0, y2 / height)),
                        ],
                    })
            predictions[str(frame["frameId"])] = frame_predictions
            speed = getattr(result, "speed", {}) or {}
            inference_ms.append(float(speed.get("inference", 0.0)))
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    return predictions, {
        "frameCount": len(frames),
        "wallSeconds": round(elapsed, 4),
        "wallFps": round(len(frames) / elapsed, 3) if elapsed > 0 else None,
        "meanModelInferenceMs": round(statistics.fmean(inference_ms), 4) if inference_ms else None,
    }


def _iou(first: list[float], second: list[float]) -> float:
    intersection = max(0.0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0.0, min(first[3], second[3]) - max(first[1], second[1])
    )
    if intersection <= 0.0:
        return 0.0
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / max(1e-9, first_area + second_area - intersection)


def _deduplicate_predictions(
    detections: Iterable[Mapping[str, Any]], *, iou_threshold: float = 0.50,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for detection in sorted(detections, key=lambda item: float(item.get("confidence") or 0), reverse=True):
        candidate = dict(detection)
        bbox = candidate.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        if any(_iou(bbox, existing["bbox"]) >= iou_threshold for existing in kept):
            continue
        kept.append(candidate)
    return kept


def _predict_tiles(
    model: YOLO,
    snapshot: Path,
    frames: list[dict[str, Any]],
    *,
    imgsz: int,
    device: str,
    batch: int,
    confidence: float,
    tile_size: int,
    tile_overlap: float,
    tile_max: int,
    tile_roi: tuple[float, float, float, float],
    source_loader: Callable[[Mapping[str, Any]], Any] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    started = time.perf_counter()
    predictions: dict[str, list[dict[str, Any]]] = {}
    inference_ms: list[float] = []
    tile_count = 0
    left, top, right, bottom = tile_roi
    roi = RoiSpec(
        "validation-yard-roi",
        ((left, top), (right, top), (right, bottom), (left, bottom)),
        frozenset({"custom"}),
    )
    for frame in frames:
        image_path = snapshot / str(frame["imagePath"])
        image = source_loader(frame) if source_loader is not None else cv2.imread(str(image_path))
        if image is None:
            raise RuntimeError(f"Cannot read validation image: {image_path}")
        height, width = image.shape[:2]
        windows = build_tiles(
            width, height, (roi,), tile_size=tile_size,
            overlap=tile_overlap, max_tiles=tile_max, detector="custom",
        )
        crops = [image[tile.y1:tile.y2, tile.x1:tile.x2] for tile in windows]
        results = model.predict(
            source=crops,
            stream=True,
            batch=batch,
            imgsz=imgsz,
            conf=confidence,
            iou=0.70,
            max_det=50,
            device=device,
            quantize=16 if str(device).casefold() != "cpu" else None,
            verbose=False,
        )
        detections: list[dict[str, Any]] = []
        for tile, result in zip(windows, results, strict=True):
            boxes = getattr(result, "boxes", None)
            if boxes is not None:
                for xyxy, confidence_tensor in zip(boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist(), strict=True):
                    x1, y1, x2, y2 = xyxy
                    detections.append({
                        "class": "reach_stacker",
                        "source": "CUSTOM",
                        "confidence": float(confidence_tensor),
                        "bbox": [
                            max(0.0, min(1.0, (tile.x1 + x1) / width)),
                            max(0.0, min(1.0, (tile.y1 + y1) / height)),
                            max(0.0, min(1.0, (tile.x1 + x2) / width)),
                            max(0.0, min(1.0, (tile.y1 + y2) / height)),
                        ],
                    })
            speed = getattr(result, "speed", {}) or {}
            inference_ms.append(float(speed.get("inference", 0.0)))
        predictions[str(frame["frameId"])] = detections
        tile_count += len(windows)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    return predictions, {
        "frameCount": len(frames),
        "tileCount": tile_count,
        "wallSeconds": round(elapsed, 4),
        "wallFps": round(len(frames) / elapsed, 3) if elapsed > 0 else None,
        "meanTileInferenceMs": round(statistics.fmean(inference_ms), 4) if inference_ms else None,
    }


def _filter_predictions(
    predictions: Mapping[str, list[dict[str, Any]]], threshold: float,
) -> dict[str, list[dict[str, Any]]]:
    return {
        frame_id: [item for item in items if float(item["confidence"]) >= threshold]
        for frame_id, items in predictions.items()
    }


def _summarize(
    report: Mapping[str, Any],
    frames: list[dict[str, Any]],
    ground_truth: Mapping[str, list[dict[str, Any]]],
    predictions: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    reach = report.get("perClass", {}).get("reach_stacker", {})
    hard_negative_ids = {
        str(frame["frameId"])
        for frame in frames
        if not any(item["class"] == "reach_stacker" for item in ground_truth[str(frame["frameId"])])
    }
    hard_negative_predictions = sum(len(predictions.get(frame_id, [])) for frame_id in hard_negative_ids)
    return {
        "reachStacker": {
            "precision": _number(reach.get("precision", {})),
            "recall": _number(reach.get("recall", {})),
            "f1": _number(reach.get("f1", {})),
            "ap50": _number(reach.get("ap50", {})),
            "tp": reach.get("tp"),
            "fp": reach.get("fp"),
            "fn": reach.get("fn"),
        },
        "truckAsReachStacker": report.get("truckReachStackerConfusion", {}).get("truckAsReachStacker"),
        "truckAsReachStackerRate": _number(
            report.get("truckReachStackerConfusion", {}).get("truckAsReachStackerRate", {})
        ),
        "hardNegativeFrames": len(hard_negative_ids),
        "hardNegativePredictions": hard_negative_predictions,
    }


def run(
    snapshot: Path,
    model_path: Path,
    output: Path,
    *,
    split: str,
    image_sizes: list[int],
    device: str,
    batch: int,
    fixed_threshold: float | None,
    tile_roi: tuple[float, float, float, float] | None = None,
    tile_size: int = 640,
    tile_imgsz: int | None = None,
    tile_overlap: float = 0.10,
    tile_max: int = 8,
    video_root: Path | None = None,
    ffmpeg_path: Path | None = None,
) -> dict[str, Any]:
    if split == "test" and fixed_threshold is None:
        raise ValueError("Locked test evaluation requires --fixed-threshold selected on validation")
    if split != "val" and fixed_threshold is None:
        raise ValueError("Threshold calibration is allowed only on validation")
    if fixed_threshold is not None and len(image_sizes) != 1:
        raise ValueError("A fixed-threshold evaluation requires exactly one image size")

    snapshot = snapshot.resolve()
    model_path = model_path.resolve()
    manifest, frames, ground_truth = _load_split(snapshot, split)
    output.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(model_path))
    native_loader = (
        NativeVideoFrameLoader(manifest, video_root, ffmpeg_path=ffmpeg_path)
        if video_root is not None else None
    )
    evaluations: list[dict[str, Any]] = []
    for imgsz in image_sizes:
        inference_threshold = fixed_threshold if fixed_threshold is not None else 0.001
        raw_predictions, performance = _predict(
            model, snapshot, frames, imgsz=imgsz, device=device, batch=batch,
            confidence=inference_threshold, source_loader=native_loader,
        )
        if tile_roi is not None:
            effective_tile_imgsz = tile_imgsz if tile_imgsz is not None else tile_size
            tiled_predictions, tile_performance = _predict_tiles(
                model, snapshot, frames,
                imgsz=effective_tile_imgsz,
                device=device,
                batch=batch,
                confidence=inference_threshold,
                tile_size=tile_size,
                tile_overlap=tile_overlap,
                tile_max=tile_max,
                tile_roi=tile_roi,
                source_loader=native_loader,
            )
            raw_predictions = {
                str(frame["frameId"]): _deduplicate_predictions([
                    *raw_predictions[str(frame["frameId"])],
                    *tiled_predictions[str(frame["frameId"])],
                ])
                for frame in frames
            }
            combined_seconds = float(performance["wallSeconds"]) + float(tile_performance["wallSeconds"])
            performance = {
                **performance,
                "wallSeconds": round(combined_seconds, 4),
                "wallFps": round(len(frames) / combined_seconds, 3) if combined_seconds > 0 else None,
                "fullFrameWallSeconds": performance["wallSeconds"],
                "tile": tile_performance,
            }
        prediction_path = output / f"{split}-{imgsz}-predictions.jsonl"
        with prediction_path.open("w", encoding="utf-8") as destination:
            for frame in frames:
                frame_id = str(frame["frameId"])
                destination.write(json.dumps({
                    "frameId": frame_id,
                    "sourceId": frame["sourceId"],
                    "timestampMs": frame["timestampMs"],
                    "detections": raw_predictions[frame_id],
                }, ensure_ascii=False) + "\n")

        if fixed_threshold is None:
            raw_report = evaluate_detections(ground_truth, raw_predictions)
            groups = raw_report["thresholdCalibration"]["groups"]
            reach_group = next(
                group for group in groups
                if group["class"] == "reach_stacker" and group["source"] == "custom"
            )
            selection = choose_threshold(reach_group["prPoints"])
            threshold = float(selection["threshold"])
        else:
            threshold = fixed_threshold
            selection = {
                "threshold": threshold,
                "selectionReason": "fixed on validation before locked-test evaluation",
                "metPrecisionTarget": None,
                "minimumPrecision": 0.90,
            }
        filtered = _filter_predictions(raw_predictions, threshold)
        filtered_report = evaluate_detections(ground_truth, filtered)
        summary = _summarize(filtered_report, frames, ground_truth, filtered)
        summary["meetsImageTargets"] = bool(
            (summary["reachStacker"]["precision"] or 0) >= 0.90
            and (summary["reachStacker"]["recall"] or 0) >= 0.85
            and (summary["truckAsReachStackerRate"] or 0) < 0.05
        )
        evaluations.append({
            "imageSize": imgsz,
            "tileConfiguration": ({
                "roi": list(tile_roi),
                "cropSize": tile_size,
                "imageSize": tile_imgsz if tile_imgsz is not None else tile_size,
                "overlap": tile_overlap,
                "maxTiles": tile_max,
            } if tile_roi is not None else None),
            "thresholdSelection": selection,
            "summary": summary,
            "performance": performance,
            "predictions": prediction_path.name,
        })
    if native_loader is not None:
        native_loader.close()
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    report = {
        "schemaVersion": 1,
        "runtimeMode": "SUPPLEMENTAL",
        "split": split,
        "datasetContentHash": manifest["contentHash"],
        "artifactSha256": _sha256(model_path),
        "modelPath": str(model_path),
        "reviewComplete": True,
        "nativeVideoFrames": video_root is not None,
        "nativeFrameDecoder": "ffmpeg-fast-seek" if ffmpeg_path is not None else "opencv",
        "frameCount": len(frames),
        "sourceIds": sorted({str(frame["sourceId"]) for frame in frames}),
        "evaluations": evaluations,
    }
    report_path = output / f"{split}-evaluation.json"
    temporary = report_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("val", "test"), default="val")
    parser.add_argument("--imgsz", type=int, nargs="+", default=[640, 768, 896])
    parser.add_argument("--device", default="0" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--fixed-threshold", type=float)
    parser.add_argument(
        "--tile-roi", type=float, nargs=4, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"),
        help="Optional normalized rectangular ROI evaluated with bounded custom-model tiles.",
    )
    parser.add_argument("--tile-size", type=int, default=640)
    parser.add_argument("--tile-imgsz", type=int)
    parser.add_argument("--tile-overlap", type=float, default=0.10)
    parser.add_argument("--tile-max", type=int, default=8)
    parser.add_argument(
        "--video-root", type=Path,
        help="Decode reviewed timestamps from original videos instead of resized snapshot images.",
    )
    parser.add_argument(
        "--ffmpeg", type=Path,
        help="Optional FFmpeg executable for fast, exact ASF seeks (requires --video-root).",
    )
    args = parser.parse_args()
    if args.ffmpeg is not None and args.video_root is None:
        parser.error("--ffmpeg requires --video-root")
    report = run(
        args.snapshot, args.model, args.output, split=args.split,
        image_sizes=args.imgsz, device=args.device, batch=args.batch,
        fixed_threshold=args.fixed_threshold,
        tile_roi=tuple(args.tile_roi) if args.tile_roi is not None else None,
        tile_size=args.tile_size, tile_imgsz=args.tile_imgsz,
        tile_overlap=args.tile_overlap, tile_max=args.tile_max,
        video_root=args.video_root,
        ffmpeg_path=args.ffmpeg,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
