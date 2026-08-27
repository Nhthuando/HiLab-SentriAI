"""Sweep fixed confidence values on validation and export every false negative."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import cv2

from evaluation.evaluate_local_video_model import _filter_predictions, _load_split
from evaluation.metrics import evaluate_detections, iou
from stream.native_video_frames import NativeVideoFrameLoader


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _value(metric: Mapping[str, Any]) -> float | None:
    value = metric.get("value")
    return float(value) if value is not None else None


def false_negative_records(
    frames: list[dict[str, Any]],
    ground_truth: Mapping[str, list[dict[str, Any]]],
    predictions: Mapping[str, list[dict[str, Any]]],
    threshold: float,
    *,
    iou_threshold: float = 0.50,
) -> list[dict[str, Any]]:
    """Return unmatched reach-stacker truths using the production metric's greedy match."""
    missed: list[dict[str, Any]] = []
    for frame in frames:
        frame_id = str(frame["frameId"])
        truths = [item for item in ground_truth.get(frame_id, []) if item.get("class") == "reach_stacker"]
        candidates = sorted(
            (
                item for item in predictions.get(frame_id, [])
                if item.get("class") == "reach_stacker" and float(item.get("confidence", 0.0)) >= threshold
            ),
            key=lambda item: -float(item.get("confidence", 0.0)),
        )
        matched_truth: set[int] = set()
        for prediction in candidates:
            best_index = None
            best_overlap = iou_threshold
            for truth_index, truth in enumerate(truths):
                if truth_index in matched_truth:
                    continue
                overlap = iou(prediction["bbox"], truth["bbox"])
                if overlap >= best_overlap:
                    best_overlap = overlap
                    best_index = truth_index
            if best_index is not None:
                matched_truth.add(best_index)
        all_predictions = [
            item for item in predictions.get(frame_id, []) if item.get("class") == "reach_stacker"
        ]
        for truth_index, truth in enumerate(truths):
            if truth_index in matched_truth:
                continue
            ranked = sorted(
                (
                    (iou(item["bbox"], truth["bbox"]), float(item.get("confidence", 0.0)))
                    for item in all_predictions
                ),
                reverse=True,
            )
            missed.append({
                "falseNegativeId": f"{frame_id}-gt-{truth_index:02d}",
                "frameId": frame_id,
                "sourceId": frame["sourceId"],
                "timestampMs": int(frame["timestampMs"]),
                "groundTruthIndex": truth_index,
                "bbox": truth["bbox"],
                "bestPredictionIoU": round(ranked[0][0], 6) if ranked else None,
                "bestPredictionConfidence": round(ranked[0][1], 6) if ranked else None,
            })
    return missed


def _write_false_negative_images(
    output: Path,
    manifest: Mapping[str, Any],
    frames: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    video_root: Path,
    ffmpeg_path: Path,
) -> None:
    frame_map = {str(frame["frameId"]): frame for frame in frames}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["frameId"]), []).append(record)
    frames_dir = output / "false-negatives" / "frames"
    crops_dir = output / "false-negatives" / "crops"
    frames_dir.mkdir(parents=True, exist_ok=True)
    crops_dir.mkdir(parents=True, exist_ok=True)
    loader = NativeVideoFrameLoader(manifest, video_root, ffmpeg_path=ffmpeg_path, cache_frames=False)
    try:
        for frame_id, items in sorted(grouped.items()):
            image = loader(frame_map[frame_id])
            height, width = image.shape[:2]
            annotated = image.copy()
            for item in items:
                x1, y1, x2, y2 = item["bbox"]
                left, top = int(round(x1 * width)), int(round(y1 * height))
                right, bottom = int(round(x2 * width)), int(round(y2 * height))
                cv2.rectangle(annotated, (left, top), (right, bottom), (0, 0, 255), 5)
                cv2.putText(
                    annotated, "FALSE NEGATIVE", (left, max(35, top - 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 3, cv2.LINE_AA,
                )
                box_width, box_height = max(1, right - left), max(1, bottom - top)
                pad_x, pad_y = max(32, box_width // 4), max(32, box_height // 4)
                crop = image[
                    max(0, top - pad_y):min(height, bottom + pad_y),
                    max(0, left - pad_x):min(width, right + pad_x),
                ]
                cv2.imwrite(str(crops_dir / f"{item['falseNegativeId']}.jpg"), crop)
            cv2.imwrite(str(frames_dir / f"{frame_id}.jpg"), annotated)
    finally:
        loader.close()


def run(
    snapshot: Path,
    evaluation_report: Path,
    model_path: Path,
    output: Path,
    *,
    thresholds: list[float],
    video_root: Path,
    ffmpeg_path: Path,
) -> dict[str, Any]:
    if not thresholds or any(not 0 < value < 1 for value in thresholds):
        raise ValueError("confidence thresholds must be in (0,1)")
    evaluation = json.loads(evaluation_report.read_text(encoding="utf-8"))
    if evaluation.get("split") != "val":
        raise ValueError("confidence sweep permits validation only; locked test is forbidden")
    manifest, frames, ground_truth = _load_split(snapshot.resolve(), "val")
    model_hash = _sha256(model_path.resolve())
    if evaluation.get("datasetContentHash") != manifest.get("contentHash"):
        raise ValueError("evaluation report does not match the validation snapshot")
    if str(evaluation.get("artifactSha256") or "").casefold() != model_hash:
        raise ValueError("evaluation report does not match the requested best.pt")
    entries = evaluation.get("evaluations") or []
    if len(entries) != 1:
        raise ValueError("confidence sweep requires one fixed inference configuration")
    prediction_path = evaluation_report.parent / str(entries[0]["predictions"])
    predictions: dict[str, list[dict[str, Any]]] = {}
    for line in prediction_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        predictions[str(record["frameId"])] = list(record.get("detections") or [])

    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    missed_by_id: dict[str, dict[str, Any]] = {}
    for threshold in thresholds:
        filtered = _filter_predictions(predictions, threshold)
        metrics = evaluate_detections(ground_truth, filtered)
        reach = metrics["perClass"]["reach_stacker"]
        missed = false_negative_records(frames, ground_truth, predictions, threshold)
        for item in missed:
            merged = missed_by_id.setdefault(item["falseNegativeId"], {**item, "missedAtThresholds": []})
            merged["missedAtThresholds"].append(threshold)
        rows.append({
            "confidence": threshold,
            "precision": _value(reach["precision"]),
            "recall": _value(reach["recall"]),
            "f1": _value(reach["f1"]),
            "tp": reach["tp"],
            "fp": reach["fp"],
            "fn": reach["fn"],
        })

    false_negatives = sorted(missed_by_id.values(), key=lambda item: item["falseNegativeId"])
    for item in false_negatives:
        item["missedAtThresholds"] = sorted(item["missedAtThresholds"])
    _write_false_negative_images(
        output, manifest, frames, false_negatives,
        video_root=video_root, ffmpeg_path=ffmpeg_path,
    )
    with (output / "false-negatives.jsonl").open("w", encoding="utf-8") as destination:
        for item in false_negatives:
            destination.write(json.dumps(item, ensure_ascii=False) + "\n")
    report = {
        "schemaVersion": 1,
        "split": "val",
        "lockedTestUsed": False,
        "datasetContentHash": manifest["contentHash"],
        "artifactSha256": model_hash,
        "modelPath": str(model_path.resolve()),
        "inferenceConfiguration": {
            "imageSize": entries[0].get("imageSize"),
            "tileConfiguration": entries[0].get("tileConfiguration"),
        },
        "thresholds": rows,
        "falseNegativeObjectCountAcrossSweep": len(false_negatives),
        "falseNegativeManifest": "false-negatives.jsonl",
        "falseNegativeFramesDirectory": "false-negatives/frames",
        "falseNegativeCropsDirectory": "false-negatives/crops",
    }
    destination = output / "confidence-sweep.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--evaluation-report", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--thresholds", type=float, nargs="+", required=True)
    parser.add_argument("--video-root", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(
        args.snapshot, args.evaluation_report, args.model, args.output,
        thresholds=args.thresholds, video_root=args.video_root, ffmpeg_path=args.ffmpeg,
    ), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
