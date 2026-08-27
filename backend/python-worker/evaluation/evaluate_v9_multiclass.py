"""Calibrate and evaluate the final BAI-KIEM V9 multi-class detector."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2
import torch
from ultralytics import YOLO

from evaluation.metrics import evaluate_detections, iou
from training.v9_final_dataset import V9_CLASSES


DEFAULT_THRESHOLDS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_truth(label_path: Path, class_names: Sequence[str]) -> list[dict[str, Any]]:
    truths: list[dict[str, Any]] = []
    for line_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 5:
            raise ValueError(f"invalid YOLO row at {label_path}:{line_number}")
        class_id = int(fields[0])
        class_name = str(class_names[class_id])
        if class_name not in V9_CLASSES:
            raise ValueError(f"locked/reviewed dataset contains unsupported class {class_name!r}")
        center_x, center_y, width, height = (float(value) for value in fields[1:])
        truths.append({
            "class": class_name,
            "bbox": [
                max(0.0, center_x - width / 2),
                max(0.0, center_y - height / 2),
                min(1.0, center_x + width / 2),
                min(1.0, center_y + height / 2),
            ],
        })
    return truths


def _load_reviewed(source: Path, split: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = source.resolve()
    final_manifest = source / "dataset-manifest.json"
    annotation_manifest = source / "annotation-manifest.json"
    if final_manifest.is_file():
        manifest = json.loads(final_manifest.read_text(encoding="utf-8"))
        if manifest.get("datasetKind") != "BAIKIEM_V9_FINAL_TRAIN_VAL" or split != "val":
            raise ValueError("final training dataset permits validation evaluation only")
        classes = [str(value) for value in manifest["classes"]]
        raw_frames = [frame for frame in manifest["framesMetadata"] if frame.get("split") == split]
        locked = False
        dataset_hash = str(manifest["contentHash"])
    elif annotation_manifest.is_file():
        manifest = json.loads(annotation_manifest.read_text(encoding="utf-8"))
        receipt = json.loads((source / "cvat-review-receipt.json").read_text(encoding="utf-8"))
        if receipt.get("reviewStatus") != "REVIEWED" or int(receipt.get("frameCount", -1)) != len(manifest.get("frames", [])):
            raise ValueError("CVAT annotation package is not frozen and completely reviewed")
        locked = bool(manifest.get("lockedBlind"))
        if split != "test" or not locked:
            raise ValueError("annotation package evaluation is reserved for the locked test")
        classes = [str(value) for value in manifest["classes"]]
        raw_frames = list(manifest["frames"])
        dataset_hash = hashlib.sha256(
            json.dumps({"receipt": receipt, "frames": raw_frames}, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    else:
        raise FileNotFoundError("no supported reviewed manifest was found")
    if not raw_frames:
        raise ValueError(f"reviewed source has no {split} frames")
    frames: list[dict[str, Any]] = []
    for raw in raw_frames:
        image = source / str(raw["imagePath"])
        label = source / str(raw["labelsPath"])
        if not image.is_file() or not label.is_file():
            raise FileNotFoundError("reviewed image or label is missing")
        frames.append({
            "frameId": str(raw.get("frameId") or image.stem),
            "sourceId": str(raw.get("sourceId") or "unknown"),
            "timestampMs": int(raw.get("timestampMs") or 0),
            "image": image,
            "truth": _read_truth(label, classes),
        })
    return frames, {"locked": locked, "datasetHash": dataset_hash, "source": str(source)}


def _predict(
    model_path: Path,
    frames: list[dict[str, Any]],
    *,
    image_size: int,
    batch: int,
    device: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    model = YOLO(str(model_path))
    names = {int(key): str(value) for key, value in dict(model.names).items()}
    if tuple(names[index] for index in range(len(names))) != V9_CLASSES:
        raise ValueError("checkpoint class order differs from the V9 contract")
    if torch.cuda.is_available() and device != "cpu":
        torch.cuda.synchronize()
    started = time.perf_counter()
    inference_ms: list[float] = []
    predictions: dict[str, list[dict[str, Any]]] = {}
    chunk_size = max(batch, batch * 4)
    for offset in range(0, len(frames), chunk_size):
        chunk = frames[offset:offset + chunk_size]
        results = model.predict(
            source=[str(frame["image"]) for frame in chunk],
            imgsz=image_size,
            batch=batch,
            conf=0.01,
            iou=0.70,
            agnostic_nms=False,
            max_det=300,
            device=device,
            quantize=16 if device != "cpu" else None,
            verbose=False,
        )
        for frame, result in zip(chunk, results, strict=True):
            height, width = result.orig_shape
            boxes = getattr(result, "boxes", None)
            detections: list[dict[str, Any]] = []
            if boxes is not None:
                for xyxy, confidence, class_id in zip(
                    boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist(), boxes.cls.cpu().tolist(), strict=True,
                ):
                    x1, y1, x2, y2 = xyxy
                    detections.append({
                        "class": names[int(class_id)],
                        "source": "CUSTOM",
                        "confidence": float(confidence),
                        "bbox": [x1 / width, y1 / height, x2 / width, y2 / height],
                    })
            predictions[frame["frameId"]] = detections
            inference_ms.append(float((getattr(result, "speed", {}) or {}).get("inference", 0.0)))
    if torch.cuda.is_available() and device != "cpu":
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return predictions, {
        "frameCount": len(frames),
        "wallSeconds": round(elapsed, 4),
        "wallFps": round(len(frames) / elapsed, 3),
        "meanModelInferenceMs": round(statistics.fmean(inference_ms), 4),
    }


def _filter(
    predictions: Mapping[str, list[dict[str, Any]]],
    thresholds: float | Mapping[str, float],
) -> dict[str, list[dict[str, Any]]]:
    return {
        frame_id: [
            item for item in items
            if float(item["confidence"]) >= (
                float(thresholds) if isinstance(thresholds, (int, float)) else float(thresholds[item["class"]])
            )
        ]
        for frame_id, items in predictions.items()
    }


def _number(value: Mapping[str, Any]) -> float | None:
    raw = value.get("value")
    return float(raw) if isinstance(raw, (int, float)) else None


def _summary(report: Mapping[str, Any]) -> dict[str, Any]:
    per_class = report["perClass"]
    class_rows = {}
    for name in V9_CLASSES:
        row = per_class[name]
        class_rows[name] = {
            "precision": _number(row["precision"]),
            "recall": _number(row["recall"]),
            "f1": _number(row["f1"]),
            "ap50": _number(row["ap50"]),
            "tp": int(row["tp"]), "fp": int(row["fp"]), "fn": int(row["fn"]),
        }
    return {
        "micro": {
            "precision": _number(report["precision"]),
            "recall": _number(report["recall"]),
            "f1": _number(report["f1"]),
            **report["counts"],
        },
        "macro": {
            metric: round(statistics.fmean(float(class_rows[name][metric] or 0.0) for name in V9_CLASSES), 6)
            for metric in ("precision", "recall", "f1", "ap50")
        },
        "perClass": class_rows,
        "truckReachStackerConfusion": report["truckReachStackerConfusion"],
    }


def _map50_95(
    ground_truth: Mapping[str, list[dict[str, Any]]],
    predictions: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    rows = []
    for threshold in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95):
        report = evaluate_detections(
            ground_truth, predictions, iou_threshold=threshold,
            include_threshold_calibration=False,
        )
        per_class = {
            name: _number(report["perClass"][name]["ap50"])
            for name in V9_CLASSES
        }
        rows.append({
            "iou": threshold,
            "macroAp": round(statistics.fmean(float(per_class[name] or 0.0) for name in V9_CLASSES), 6),
            "perClass": per_class,
        })
    return {
        "macroMap50To95": round(statistics.fmean(row["macroAp"] for row in rows), 6),
        "perClassMap50To95": {
            name: round(statistics.fmean(float(row["perClass"][name] or 0.0) for row in rows), 6)
            for name in V9_CLASSES
        },
        "iouRows": rows,
    }


def _choose_thresholds(sweep: list[dict[str, Any]]) -> dict[str, float]:
    selected: dict[str, float] = {}
    for name in V9_CLASSES:
        rows = [(row["confidence"], row["metrics"]["perClass"][name]) for row in sweep]
        passing = [item for item in rows if (item[1]["recall"] or 0.0) >= 0.85 and (item[1]["precision"] or 0.0) >= 0.85]
        pool = passing or rows
        best = max(pool, key=lambda item: (item[1]["f1"] or 0.0, item[1]["precision"] or 0.0, item[1]["recall"] or 0.0))
        selected[name] = float(best[0])
    return selected


def _false_negatives(
    frames: list[dict[str, Any]],
    predictions: Mapping[str, list[dict[str, Any]]],
    thresholds: Mapping[str, float],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for frame in frames:
        frame_predictions = _filter({frame["frameId"]: predictions.get(frame["frameId"], [])}, thresholds)[frame["frameId"]]
        matched: set[int] = set()
        for prediction in sorted(frame_predictions, key=lambda item: -float(item["confidence"])):
            best_index = None
            best_overlap = 0.50
            for truth_index, truth in enumerate(frame["truth"]):
                if truth_index in matched or truth["class"] != prediction["class"]:
                    continue
                overlap = iou(prediction["bbox"], truth["bbox"])
                if overlap >= best_overlap:
                    best_index, best_overlap = truth_index, overlap
            if best_index is not None:
                matched.add(best_index)
        for truth_index, truth in enumerate(frame["truth"]):
            if truth_index in matched:
                continue
            overlaps = sorted(
                ({"class": item["class"], "confidence": item["confidence"], "iou": iou(item["bbox"], truth["bbox"])} for item in predictions.get(frame["frameId"], [])),
                key=lambda item: (item["iou"], item["confidence"]), reverse=True,
            )
            output.append({
                "frameId": frame["frameId"], "sourceId": frame["sourceId"],
                "timestampMs": frame["timestampMs"], "imagePath": str(frame["image"]),
                "class": truth["class"], "bbox": truth["bbox"],
                "bestPrediction": overlaps[0] if overlaps else None,
            })
    return output


def _render_false_negative_frames(
    frames: list[dict[str, Any]], false_negatives: list[dict[str, Any]], output: Path,
) -> int:
    by_frame: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in false_negatives:
        by_frame[item["frameId"]].append(item)
    frame_map = {frame["frameId"]: frame for frame in frames}
    image_dir = output / "false-negatives" / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    for frame_id, items in by_frame.items():
        frame = frame_map[frame_id]
        image = cv2.imread(str(frame["image"]))
        if image is None:
            raise RuntimeError(f"cannot render false negative frame: {frame['image']}")
        height, width = image.shape[:2]
        for item in items:
            x1, y1, x2, y2 = item["bbox"]
            first = (int(x1 * width), int(y1 * height))
            second = (int(x2 * width), int(y2 * height))
            cv2.rectangle(image, first, second, (0, 0, 255), 4)
            cv2.putText(image, f"FN {item['class']}", (first[0], max(25, first[1] - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.imwrite(str(image_dir / f"{frame_id}.jpg"), image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return len(by_frame)


def run(
    source: Path,
    model_path: Path,
    output: Path,
    *,
    split: str,
    image_size: int,
    batch: int,
    device: str,
    threshold_report: Path | None = None,
) -> dict[str, Any]:
    source = source.resolve()
    model_path = model_path.resolve()
    output = output.resolve()
    frames, provenance = _load_reviewed(source, split)
    if provenance["locked"] and threshold_report is None:
        raise ValueError("locked test requires thresholds frozen on validation")
    ground_truth = {frame["frameId"]: frame["truth"] for frame in frames}
    predictions, performance = _predict(model_path, frames, image_size=image_size, batch=batch, device=device)
    raw_predictions_path = output / f"{split}-raw-predictions.jsonl"
    raw_predictions_path.parent.mkdir(parents=True, exist_ok=True)
    with raw_predictions_path.open("w", encoding="utf-8") as handle:
        for frame in frames:
            handle.write(json.dumps({
                "frameId": frame["frameId"], "sourceId": frame["sourceId"],
                "timestampMs": frame["timestampMs"], "detections": predictions[frame["frameId"]],
            }, ensure_ascii=False) + "\n")

    if threshold_report is None:
        sweep = []
        for confidence in DEFAULT_THRESHOLDS:
            metrics = _summary(evaluate_detections(
                ground_truth, _filter(predictions, confidence),
                include_threshold_calibration=False,
            ))
            sweep.append({"confidence": confidence, "metrics": metrics})
        selected_thresholds = _choose_thresholds(sweep)
        threshold_source = "validation-calibration"
    else:
        frozen = json.loads(threshold_report.resolve().read_text(encoding="utf-8"))
        if frozen.get("artifactSha256") != _sha256(model_path) or int(frozen.get("imageSize", 0)) != image_size:
            raise ValueError("frozen thresholds do not match the checkpoint/image size")
        selected_thresholds = {name: float(frozen["perClass"][name]) for name in V9_CLASSES}
        sweep = []
        threshold_source = str(threshold_report.resolve())

    selected_predictions = _filter(predictions, selected_thresholds)
    selected_report = evaluate_detections(
        ground_truth, selected_predictions, include_threshold_calibration=False,
    )
    false_negatives = _false_negatives(frames, predictions, selected_thresholds)
    output.mkdir(parents=True, exist_ok=True)
    false_negative_path = output / "false-negatives" / "all.json"
    _atomic_json(false_negative_path, {"count": len(false_negatives), "items": false_negatives})
    rendered_frames = _render_false_negative_frames(frames, false_negatives, output)
    class_ground_truth = Counter(item["class"] for items in ground_truth.values() for item in items)
    report = {
        "schemaVersion": 1,
        "runtimeMode": "UNIFIED",
        "split": split,
        "lockedTestUsed": bool(provenance["locked"]),
        "reviewComplete": True,
        "datasetContentHash": provenance["datasetHash"],
        "sourcePath": provenance["source"],
        "sourceIds": sorted({frame["sourceId"] for frame in frames}),
        "artifactPath": str(model_path),
        "artifactSha256": _sha256(model_path),
        "imageSize": image_size,
        "frameCount": len(frames),
        "groundTruth": dict(class_ground_truth),
        "performance": performance,
        "thresholdSource": threshold_source,
        "perClassThresholds": selected_thresholds,
        "globalConfidenceSweep": sweep,
        "selectedMetrics": _summary(selected_report),
        "averagePrecision": _map50_95(ground_truth, predictions),
        "falseNegatives": {"count": len(false_negatives), "frameCount": rendered_frames, "path": str(false_negative_path)},
    }
    _atomic_json(output / f"{split}-evaluation.json", report)
    if not provenance["locked"]:
        _atomic_json(output / "frozen-thresholds.json", {
            "schemaVersion": 1,
            "artifactSha256": report["artifactSha256"],
            "datasetContentHash": report["datasetContentHash"],
            "imageSize": image_size,
            "perClass": selected_thresholds,
            "selectionPolicy": "maximum per-class F1, prefer precision>=0.85 and recall>=0.85",
            "lockedTestUsed": False,
        })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("val", "test"), required=True)
    parser.add_argument("--imgsz", type=int, default=768)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--device", default="0" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--threshold-report", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(
        args.source, args.model, args.output, split=args.split, image_size=args.imgsz,
        batch=args.batch, device=args.device, threshold_report=args.threshold_report,
    ), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
