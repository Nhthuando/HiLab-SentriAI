"""Run the production supplemental detector over a reviewed local video.

This measures the actual base+custom+ByteTrack path at a deterministic 10 FPS,
including 2-of-3 custom confirmation and between-inference track retention.
No database, WebSocket, event, or model-registry state is changed.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Iterator, Mapping

os.environ.setdefault("OPENCV_FOR_THREADS_NUM", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import cv2
import torch

PYTHON_WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_WORKER_ROOT))

from detection.tracked_detector import COCO_CLASS_IDS, TrackedYoloDetector
from evaluation.evaluate_local_video_model import _load_split, _number, _sha256, _summarize
from evaluation.metrics import evaluate_detections


@contextlib.contextmanager
def _environment(values: Mapping[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((percentile / 100) * (len(ordered) - 1))))
    return round(ordered[index], 3)


def _source_record(manifest: Mapping[str, Any], source_id: str) -> Mapping[str, Any]:
    for source in manifest.get("sources", []):
        if source.get("sourceId") == source_id:
            return source
    raise ValueError(f"Unknown reviewed sourceId: {source_id}")


def _segments(positive_timestamps_ms: list[int], maximum_label_gap_ms: int) -> list[tuple[int, int]]:
    if not positive_timestamps_ms:
        return []
    ordered = sorted(set(positive_timestamps_ms))
    output: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for timestamp in ordered[1:]:
        if timestamp - previous > maximum_label_gap_ms:
            output.append((start, previous))
            start = timestamp
        previous = timestamp
    output.append((start, previous))
    return output


def temporal_continuity(
    positive_timestamps_ms: list[int],
    detected_timestamps_ms: list[int],
    *,
    maximum_label_gap_ms: int,
) -> dict[str, Any]:
    segments = _segments(positive_timestamps_ms, maximum_label_gap_ms)
    detected = sorted(set(detected_timestamps_ms))
    gaps: list[int] = []
    segment_reports: list[dict[str, Any]] = []
    for start, end in segments:
        inside = [timestamp for timestamp in detected if start <= timestamp <= end]
        if not inside:
            maximum_gap = end - start if end > start else maximum_label_gap_ms
        else:
            candidate_gaps = [inside[0] - start, end - inside[-1]]
            candidate_gaps.extend(second - first for first, second in zip(inside, inside[1:]))
            maximum_gap = max(candidate_gaps, default=0)
        gaps.append(maximum_gap)
        segment_reports.append({
            "startMs": start,
            "endMs": end,
            "detectionFrameCount": len(inside),
            "maxGapMs": maximum_gap,
        })
    return {
        "segments": segment_reports,
        "maxGapSeconds": round(max(gaps, default=0) / 1000, 3),
    }


def runtime_environment(
    *,
    imgsz: int,
    custom_imgsz: int | None,
    initiation: float,
    continuation: float,
    custom_interval: int,
) -> dict[str, str]:
    effective_custom_imgsz = custom_imgsz if custom_imgsz is not None else imgsz
    thresholds_json = json.dumps({
        "custom": {
            "reach_stacker": {"initiation": initiation, "continuation": continuation},
        },
    }, separators=(",", ":"))
    return {
        "AREA_INFERENCE_SIZE": str(imgsz),
        "AREA_CUSTOM_INFERENCE_SIZE": str(effective_custom_imgsz),
        "AREA_INFERENCE_HALF": "true" if torch.cuda.is_available() else "false",
        "AREA_ROI_ENABLED": "false",
        "AREA_CLASS_THRESHOLDS_JSON": thresholds_json,
        "CUSTOM_AUGMENT_INTERVAL": str(custom_interval),
        "CUSTOM_AUGMENT_MATCH_OVERLAP": "0.18",
    }


def run(
    snapshot: Path,
    video_root: Path,
    source_id: str,
    base_model: Path,
    custom_model: Path,
    output: Path,
    *,
    split: str,
    target_fps: float,
    imgsz: int,
    initiation: float,
    continuation: float,
    custom_interval: int,
    warmup_frames: int,
    custom_imgsz: int | None = None,
) -> dict[str, Any]:
    if continuation > initiation:
        raise ValueError("Continuation threshold cannot exceed initiation threshold")
    snapshot = snapshot.resolve()
    manifest, split_frames, ground_truth = _load_split(snapshot, split)
    frames = [frame for frame in split_frames if frame.get("sourceId") == source_id]
    if not frames:
        raise ValueError(f"No reviewed {split} frames for {source_id}")
    source = _source_record(manifest, source_id)
    video = (video_root.resolve() / str(source["sourceFile"])).resolve()
    if not video.is_file():
        raise FileNotFoundError(video)

    ranges = [item for item in source.get("ranges", []) if item.get("split") == split]
    if not ranges:
        raise ValueError(f"Source {source_id} has no locked {split} range")
    start_ms = min(int(item["startMs"]) for item in ranges)
    requested_end_ms = max(int(item["endMs"]) for item in ranges)

    effective_custom_imgsz = custom_imgsz if custom_imgsz is not None else imgsz
    environment = runtime_environment(
        imgsz=imgsz,
        custom_imgsz=custom_imgsz,
        initiation=initiation,
        continuation=continuation,
        custom_interval=custom_interval,
    )
    base_model = base_model.resolve()
    custom_model = custom_model.resolve()
    active_model = {
        "version_key": f"video-eval-{custom_model.stem}",
        "artifact_path": str(custom_model),
        "artifact_sha256": _sha256(custom_model),
        "label_map": {
            "Xe nâng container": "reach_stacker",
            "reach_stacker": "reach_stacker",
        },
        "runtime_mode": "SUPPLEMENTAL",
    }

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Cannot open {video}")
    source_fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if source_fps <= 0 or frame_count <= 0:
        capture.release()
        raise RuntimeError("Video metadata is invalid")
    duration_ms = int(round(frame_count / source_fps * 1000))
    end_ms = min(requested_end_ms, duration_ms)
    start_frame = max(0, int(round(start_ms * source_fps / 1000)))
    end_frame = min(frame_count - 1, int(round(end_ms * source_fps / 1000)))
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    sample_step = source_fps / target_fps
    next_sample = float(start_frame)
    current_frame = start_frame

    sequence: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    measured_started: float | None = None
    processed = 0
    with _environment(environment):
        detector = TrackedYoloDetector(model_path=str(base_model))
        detector.configure_detection_control(
            coco_classes=frozenset(COCO_CLASS_IDS),
            custom_classes=frozenset({"reach_stacker"}),
            active_model=active_model,
        )
        try:
            while current_frame <= end_frame:
                ok = capture.grab()
                if not ok:
                    break
                if current_frame + 0.5 < next_sample:
                    current_frame += 1
                    continue
                ok, frame = capture.retrieve()
                if not ok or frame is None:
                    break
                timestamp_ms = int(round(current_frame / source_fps * 1000))
                frame = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
                if processed == warmup_frames:
                    if torch.cuda.is_available():
                        torch.cuda.synchronize()
                        torch.cuda.reset_peak_memory_stats()
                    measured_started = time.perf_counter()
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                inference_started = time.perf_counter()
                detections = detector.track(frame)
                # Include the dominant production post-processing cost.
                cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                if processed >= warmup_frames:
                    latencies_ms.append((time.perf_counter() - inference_started) * 1000)
                reaches = [
                    {
                        "class": "reach_stacker",
                        "source": "CUSTOM",
                        "confidence": float(item.get("confidence") or 0),
                        "bbox": [float(value) for value in item["normalized_bbox"]],
                        "trackId": item.get("trackId"),
                        "canInitiate": item.get("canInitiate") is True,
                        "canContinue": item.get("canContinue") is True,
                        "customConfirmed": item.get("customConfirmed") is True,
                    }
                    for item in detections
                    if item.get("canonicalClass") == "reach_stacker"
                ]
                sequence.append({"timestampMs": timestamp_ms, "detections": reaches})
                processed += 1
                next_sample += sample_step
                current_frame += 1
        finally:
            capture.release()
            del detector
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    measured_seconds = (
        time.perf_counter() - measured_started
        if measured_started is not None and len(sequence) > warmup_frames
        else 0.0
    )
    if torch.cuda.is_available():
        peak_allocated = int(torch.cuda.max_memory_allocated())
        peak_reserved = int(torch.cuda.max_memory_reserved())
        torch.cuda.empty_cache()
    else:
        peak_allocated = peak_reserved = 0

    reviewed_predictions: dict[str, list[dict[str, Any]]] = {}
    for frame in frames:
        timestamp = int(frame["timestampMs"])
        nearest = min(sequence, key=lambda item: abs(int(item["timestampMs"]) - timestamp))
        reviewed_predictions[str(frame["frameId"])] = list(nearest["detections"])
    source_ground_truth = {str(frame["frameId"]): ground_truth[str(frame["frameId"])] for frame in frames}
    detection_report = evaluate_detections(source_ground_truth, reviewed_predictions)
    summary = _summarize(detection_report, frames, source_ground_truth, reviewed_predictions)

    positive_timestamps = [
        int(frame["timestampMs"])
        for frame in frames
        if any(item["class"] == "reach_stacker" for item in source_ground_truth[str(frame["frameId"])])
    ]
    detected_timestamps = [
        int(item["timestampMs"])
        for item in sequence
        if item["detections"]
    ]
    reviewed_intervals = [int(item.get("intervalMs") or 0) for item in ranges if int(item.get("intervalMs") or 0) > 0]
    continuity = temporal_continuity(
        positive_timestamps,
        detected_timestamps,
        maximum_label_gap_ms=max(reviewed_intervals, default=2000) + 500,
    )
    false_initiation_frames = sum(
        1 for item in sequence if any(detection["canInitiate"] for detection in item["detections"])
    ) if not positive_timestamps else None
    confirmed_reach_frames = sum(1 for item in sequence if item["detections"])
    measured_frames = max(0, len(sequence) - warmup_frames)
    report = {
        "schemaVersion": 1,
        "runtimeMode": "SUPPLEMENTAL",
        "datasetContentHash": manifest["contentHash"],
        "artifactSha256": _sha256(custom_model),
        "sourceId": source_id,
        "sourceFile": video.name,
        "split": split,
        "reviewComplete": True,
        "range": {"startMs": start_ms, "endMs": end_ms},
        "configuration": {
            "targetFps": target_fps,
            "imageSize": imgsz,
            "baseImageSize": imgsz,
            "customImageSize": effective_custom_imgsz,
            "customInterval": custom_interval,
            "initiationThreshold": initiation,
            "continuationThreshold": continuation,
            "customConfirmation": "2 hits in 3 custom-inference opportunities",
        },
        "reviewedFrameMetrics": summary,
        "temporalContinuity": continuity,
        "hardNegative": {
            "confirmedReachFrames": confirmed_reach_frames if not positive_timestamps else None,
            "falseInitiationFrames": false_initiation_frames,
        },
        "performance": {
            "processedFrames": len(sequence),
            "measuredFrames": measured_frames,
            "wallSeconds": round(measured_seconds, 4),
            "endToEndFps": round(measured_frames / measured_seconds, 3) if measured_seconds > 0 else None,
            "latencyMedianMs": round(statistics.median(latencies_ms), 3) if latencies_ms else None,
            "latencyP95Ms": _percentile(latencies_ms, 95),
            "peakCudaAllocatedBytes": peak_allocated,
            "peakCudaReservedBytes": peak_reserved,
        },
    }
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sequence_path = output.with_name(f"{output.stem}-sequence.jsonl")
    with sequence_path.open("w", encoding="utf-8") as destination:
        for item in sequence:
            destination.write(json.dumps(item, ensure_ascii=False) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--video-root", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--custom-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("val", "test"), required=True)
    parser.add_argument("--target-fps", type=float, default=10.0)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument(
        "--custom-imgsz",
        type=int,
        default=None,
        help="Supplemental custom-model image size (defaults to --imgsz).",
    )
    parser.add_argument("--initiation", type=float, required=True)
    parser.add_argument("--continuation", type=float, required=True)
    parser.add_argument("--custom-interval", type=int, default=2)
    parser.add_argument("--warmup-frames", type=int, default=10)
    args = parser.parse_args()
    report = run(
        args.snapshot, args.video_root, args.source_id, args.base_model, args.custom_model,
        args.output, split=args.split, target_fps=args.target_fps, imgsz=args.imgsz,
        custom_imgsz=args.custom_imgsz,
        initiation=args.initiation, continuation=args.continuation,
        custom_interval=args.custom_interval, warmup_frames=args.warmup_frames,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
