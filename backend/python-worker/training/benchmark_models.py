"""Benchmark YOLO checkpoints on one Ultralytics dataset split.

The script reports two things separately:
- validation metrics on the requested split, for class-aligned fine-tuned models
- single-frame prediction latency on images loaded in memory, for runtime speed
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2
import torch
import yaml
from ultralytics import YOLO

PYTHON_WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_WORKER_ROOT))


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
            quantize=16 if half else None,
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
        model.predict(image, imgsz=imgsz, device=device, quantize=16 if half else None, verbose=False)
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


@contextlib.contextmanager
def _temporary_environment(values: dict[str, str]):
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


def _first_local_asset(root: Path, filenames: list[str]) -> Path | None:
    for filename in filenames:
        for candidate in (root / filename, root / "models" / filename):
            if candidate.is_file():
                return candidate.resolve()
    return None


def discover_area_assets(model_root: Path) -> dict[str, Path | None]:
    """Resolve local assets without ever handing a missing model name to Ultralytics."""
    return {
        "yolo11n_pytorch": _first_local_asset(model_root, ["yolo11n.pt"]),
        "yolo11s_pytorch": _first_local_asset(model_root, ["yolo11s.pt"]),
        "yolo11n_tensorrt": _first_local_asset(model_root, ["yolo11n.engine"]),
        "yolo11s_tensorrt": _first_local_asset(model_root, ["yolo11s.engine"]),
    }


class _BenchmarkReader:
    def __init__(self, video: Path, resolution: tuple[int, int]) -> None:
        self.capture = cv2.VideoCapture(str(video))
        if not self.capture.isOpened():
            self.capture.release()
            raise RuntimeError(f"cannot open benchmark source: {video.name}")
        self.resolution = resolution
        self.source_fps = float(self.capture.get(cv2.CAP_PROP_FPS))
        self.did_loop = False
        self.read_count = 0

    def read_frame(self) -> tuple[bool, Any]:
        self.read_count += 1
        ok, frame = self.capture.read()
        if not ok or frame is None:
            return False, None
        return True, cv2.resize(frame, self.resolution, interpolation=cv2.INTER_AREA)

    def release(self) -> None:
        self.capture.release()


class _TimedDetector:
    def __init__(self, detector: Any) -> None:
        self.detector = detector
        self.last_track_latency_ms = 0.0

    def track(self, frame: Any) -> Any:
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        started = time.perf_counter()
        result = self.detector.track(frame)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        self.last_track_latency_ms = (time.perf_counter() - started) * 1000.0
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self.detector, name)


class _NoWritePersistence:
    """Records persistence calls while making external writes impossible."""
    def __init__(self) -> None:
        self.create_calls = 0
        self.close_calls = 0
        self.clip_update_calls = 0

    async def create(self, **payload: Any) -> dict[str, Any]:
        self.create_calls += 1
        return dict(payload)

    async def close(self, **payload: Any) -> dict[str, Any]:
        self.close_calls += 1
        return dict(payload)

    async def update_clip(self, violation_id: str, filename: str) -> dict[str, str]:
        self.clip_update_calls += 1
        return {"violationId": violation_id, "filename": filename}


class _NoWriteEmitter:
    """Consumes the real feed payload and verifies JSON/base64 serialization."""
    def __init__(self) -> None:
        self.feed_calls = 0
        self.area_event_calls = 0
        self.alert_calls = 0
        self.serialized_feed_bytes = 0
        self.decoded_jpeg_bytes = 0

    async def emit_frame(self, **payload: Any) -> bool:
        encoded = str(payload["image_base64"])
        prefix = "data:image/jpeg;base64,"
        if not encoded.startswith(prefix):
            raise RuntimeError("Area feed did not contain a JPEG data URL")
        decoded = base64.b64decode(encoded[len(prefix):], validate=True)
        if not decoded:
            raise RuntimeError("Area feed contained an empty JPEG")
        self.feed_calls += 1
        self.decoded_jpeg_bytes += len(decoded)
        self.serialized_feed_bytes += len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
        return True

    async def emit_area_event(self, _payload: Any) -> bool:
        self.area_event_calls += 1
        return True

    async def emit_alert(self, _payload: Any) -> bool:
        self.alert_calls += 1
        return True

    async def close(self) -> None:
        return None


class _StaticZoneSync:
    def __init__(self, snapshot: Any) -> None:
        self.snapshot = snapshot

    def get_snapshot(self) -> Any:
        return self.snapshot


def _area_cell(
    video: Path,
    base_model_path: Path,
    *,
    imgsz: int,
    roi_enabled: bool,
    measured_frames: int,
    warmup_frames: int,
    half: bool,
    runtime_mode: str = "SUPPLEMENTAL",
    unified_artifact: Path | None = None,
    unified_label_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    from detection.area_pipeline import AreaPipeline
    from detection.tracked_detector import COCO_CLASS_IDS, TrackedYoloDetector
    from zone.zone_checker import ViolationTransition, ZoneChecker
    from zone.zone_sync import ZoneSnapshot

    roi_config = json.dumps([{
        "name": "bai-kiem-full-frame", "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        "detectors": ["base"],
    }])
    is_unified = runtime_mode == "UNIFIED"
    environment = {
        "AREA_INFERENCE_SIZE": str(imgsz),
        "AREA_INFERENCE_HALF": "true" if half else "false",
        "AREA_ROI_ENABLED": "true" if roi_enabled and not is_unified else "false",
        "AREA_ROI_CONFIG_JSON": roi_config if roi_enabled and not is_unified else "[]",
        "AREA_ROI_INTERVAL": "3",
        "AREA_ROI_TILE_SIZE": "640",
        "AREA_ROI_TILE_OVERLAP": "0.20",
        "AREA_ROI_MAX_TILES": "8",
    }
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    reader = _BenchmarkReader(video, (1280, 720))
    processed_frames = 0
    detector_latencies: list[float] = []
    roi_latencies: list[float] = []
    persistence_sink = _NoWritePersistence()
    emitter_sink = _NoWriteEmitter()
    zone_checker = ZoneChecker(camera_id="BAI-KIEM-BENCHMARK", grace_frames=3, missing_grace_seconds=12.0)
    if is_unified:
        if unified_artifact is None or unified_label_map is None:
            raise ValueError("UNIFIED benchmark requires an artifact and label map")
        runtime_classes = frozenset(unified_label_map.values())
        active_model: dict[str, object] | None = {
            "version_key": f"benchmark-{unified_artifact.stem}",
            "artifact_path": str(unified_artifact.resolve()),
            "artifact_sha256": hashlib.sha256(unified_artifact.read_bytes()).hexdigest(),
            "label_map": dict(unified_label_map),
            "runtime_mode": "UNIFIED",
        }
        coco_classes = frozenset()
        custom_classes = runtime_classes
    else:
        runtime_classes = frozenset(COCO_CLASS_IDS)
        active_model = None
        coco_classes = runtime_classes
        custom_classes = frozenset()
    class_to_labels = {canonical: [canonical] for canonical in runtime_classes}
    zones = [{
        "id": "benchmark-zone", "name": "Benchmark full frame",
        "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        "ruleType": "PROHIBIT_SPECIFIED", "targetLabels": sorted(runtime_classes),
    }]
    snapshot = ZoneSnapshot(
        zones=tuple(zones), class_to_labels=class_to_labels,
        coco_classes=coco_classes, custom_classes=custom_classes, active_model=active_model,
    )
    started: float | None = None
    ended: float | None = None
    last_result: dict[str, Any] | None = None
    event_loop = asyncio.new_event_loop()
    try:
        with _temporary_environment(environment):
            detector = _TimedDetector(TrackedYoloDetector(model_path=str(base_model_path)))
            pipeline = AreaPipeline(
                camera_id="BAI-KIEM-BENCHMARK", target_fps=max(reader.source_fps, 1.0),
                resolution=(1280, 720), detector=detector, zone_sync=_StaticZoneSync(snapshot),
                zone_checker=zone_checker, reader=reader, emitter=emitter_sink,
                persistence=persistence_sink, record_violation_clips=False,
            )
            total = warmup_frames + measured_frames
            while processed_frames < total:
                if processed_frames == warmup_frames:
                    if torch.cuda.is_available():
                        torch.cuda.synchronize()
                        torch.cuda.reset_peak_memory_stats()
                    # Start before the first measured read/decode/resize.
                    started = time.perf_counter()
                result = pipeline.process_single_frame()
                if not result.get("success"):
                    break
                if is_unified and detector.detector._runtime_mode != "UNIFIED":
                    raise RuntimeError("UNIFIED artifact did not enter the one-pass runtime")
                last_result = result
                event_loop.run_until_complete(pipeline.publish_result(result))
                if processed_frames >= warmup_frames:
                    detector_latencies.append(detector.last_track_latency_ms)
                    roi_latencies.append(float(detector.last_roi_latency_ms))
                processed_frames += 1
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            ended = time.perf_counter()
            if last_result is None:
                raise RuntimeError("benchmark produced no successful Area feed output")
            # Exercise STARTED/ENDED persistence and event emission outside the
            # timed interval. Natural detections are intentionally not altered.
            entered_at = datetime(2026, 8, 22, tzinfo=timezone.utc)
            started_probe = ViolationTransition(
                action="STARTED", violation_id="benchmark-no-write-probe", camera_id="BAI-KIEM-BENCHMARK",
                track_id=-1, zone_id="benchmark-zone", zone_name="Benchmark full frame",
                object_label="benchmark_probe", status="OPEN", entered_at=entered_at,
            )
            ended_probe = ViolationTransition(
                action="ENDED", violation_id="benchmark-no-write-probe", camera_id="BAI-KIEM-BENCHMARK",
                track_id=-1, zone_id="benchmark-zone", zone_name="Benchmark full frame",
                object_label="benchmark_probe", status="CLOSED", entered_at=entered_at,
                exited_at=entered_at + timedelta(seconds=1), duration_seconds=1,
            )
            event_loop.run_until_complete(pipeline.publish_result({
                **last_result, "transitions": [started_probe, ended_probe],
            }))
            del pipeline
            del detector
    finally:
        reader.release()
        event_loop.close()
    actual_measured = max(0, processed_frames - warmup_frames)
    if started is None or actual_measured == 0:
        raise RuntimeError("benchmark source ended before measured frames")
    assert ended is not None
    wall_seconds = ended - started
    allocated = int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else 0
    reserved = int(torch.cuda.max_memory_reserved()) if torch.cuda.is_available() else 0
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return {
        "status": "MEASURED",
        "runtimeMode": runtime_mode,
        "decodedFrames": reader.read_count,
        "processedFrames": actual_measured,
        "warmupFrames": min(warmup_frames, processed_frames),
        "wallSeconds": round(wall_seconds, 6),
        "endToEndFps": round(actual_measured / wall_seconds, 3),
        "detectorLatencyMs": {
            "median": round(statistics.median(detector_latencies), 3),
            "p95": _percentile(detector_latencies, 95),
        },
        "roiLatencyMs": {
            "median": round(statistics.median(roi_latencies), 3),
            "p95": _percentile(roi_latencies, 95),
        },
        "peakCudaAllocatedBytes": allocated,
        "peakCudaReservedBytes": reserved,
        "outputSink": {
            "feedCalls": emitter_sink.feed_calls,
            "areaEventCalls": emitter_sink.area_event_calls,
            "alertCalls": emitter_sink.alert_calls,
            "serializedFeedBytes": emitter_sink.serialized_feed_bytes,
            "decodedJpegBytes": emitter_sink.decoded_jpeg_bytes,
        },
        "persistenceSink": {
            "type": "injected-in-memory-call-recorder",
            "createCalls": persistence_sink.create_calls,
            "closeCalls": persistence_sink.close_calls,
            "clipUpdateCalls": persistence_sink.clip_update_calls,
            "externalClientConfigured": False,
        },
        "eventPathProbe": {
            "timed": False,
            "executed": True,
            "reason": "deterministically exercises production STARTED/ENDED output without altering detections",
        },
        "resizedInput": [1280, 720],
    }


def run_area_matrix(args: argparse.Namespace) -> dict[str, Any]:
    video = Path(args.area_video).resolve()
    if not video.is_file():
        raise FileNotFoundError(video)
    model_root = Path(args.model_root).resolve()
    assets = discover_area_assets(model_root)
    cells: list[dict[str, Any]] = []
    for model_name in ("yolo11n", "yolo11s"):
        for runtime in ("pytorch_fp16", "tensorrt_fp16"):
            asset = assets[f"{model_name}_{'pytorch' if runtime == 'pytorch_fp16' else 'tensorrt'}"]
            for imgsz in args.matrix_imgsz:
                for roi_enabled in (False, True):
                    cell: dict[str, Any] = {
                        "model": model_name, "runtime": runtime, "imgsz": imgsz,
                        "roiEnabled": roi_enabled, "asset": asset.name if asset else None,
                    }
                    if asset is None:
                        cell.update({
                            "status": "BLOCKED_MISSING_LOCAL_ASSET",
                            "reason": f"No local {model_name} {'engine' if runtime == 'tensorrt_fp16' else 'checkpoint'} was found; automatic download/export is disabled.",
                        })
                    else:
                        cell.update(_area_cell(
                            video, asset, imgsz=imgsz, roi_enabled=roi_enabled,
                            measured_frames=args.matrix_frames, warmup_frames=args.matrix_warmup,
                            half=runtime == "pytorch_fp16",
                        ))
                    cells.append(cell)
    unified_label_map: dict[str, str] | None = None
    unified_label_map_setting = getattr(args, "unified_label_map", None)
    if unified_label_map_setting:
        raw_label_map = json.loads(Path(unified_label_map_setting).read_text(encoding="utf-8"))
        if not isinstance(raw_label_map, dict) or not raw_label_map or not all(
            isinstance(label, str) and label and isinstance(canonical, str) and canonical
            for label, canonical in raw_label_map.items()
        ):
            raise ValueError("--unified-label-map must contain a non-empty string-to-string JSON object")
        unified_label_map = dict(raw_label_map)
    data_root = (PYTHON_WORKER_ROOT.parent / "data").resolve()
    base_asset = assets["yolo11n_pytorch"]
    for runtime, setting in (
        ("pytorch_fp16", getattr(args, "unified_checkpoint", None)),
        ("tensorrt_fp16", getattr(args, "unified_engine", None)),
    ):
        artifact = Path(setting).resolve() if setting else None
        for imgsz in args.matrix_imgsz:
            cell = {
                "model": "unified-yolo11n",
                "runtime": runtime,
                "imgsz": imgsz,
                "roiEnabled": False,
                "asset": artifact.name if artifact else None,
            }
            if artifact is None or not artifact.is_file():
                cell.update({
                    "status": "BLOCKED_MISSING_LOCAL_ASSET",
                    "reason": f"No local unified {'engine' if runtime == 'tensorrt_fp16' else 'checkpoint'} was provided.",
                })
            elif unified_label_map is None:
                cell.update({
                    "status": "BLOCKED_MISSING_LABEL_MAP",
                    "reason": "--unified-label-map is required for exact canonical routing.",
                })
            elif base_asset is None:
                cell.update({
                    "status": "BLOCKED_MISSING_LOCAL_ASSET",
                    "reason": "The local yolo11n.pt rollback checkpoint was not found.",
                })
            elif data_root not in artifact.parents:
                cell.update({
                    "status": "BLOCKED_UNSAFE_ARTIFACT_PATH",
                    "reason": "Unified artifacts must remain below backend/data for production checksum validation.",
                })
            else:
                cell.update(_area_cell(
                    video,
                    base_asset,
                    imgsz=imgsz,
                    roi_enabled=False,
                    measured_frames=args.matrix_frames,
                    warmup_frames=args.matrix_warmup,
                    half=runtime == "pytorch_fp16",
                    runtime_mode="UNIFIED",
                    unified_artifact=artifact,
                    unified_label_map=unified_label_map,
                ))
            cells.append(cell)
    report = {
        "schemaVersion": 1,
        "sourceFile": video.name,
        "hardware": {
            "platform": platform.platform(),
            "cudaAvailable": torch.cuda.is_available(),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "torch": torch.__version__,
        },
        "targetEndToEndFps": 8.0,
        "cells": cells,
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


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
    parser.add_argument("--data")
    parser.add_argument("--candidate", action="append")
    parser.add_argument("--output", required=True)
    parser.add_argument("--val-split", default="test")
    parser.add_argument("--speed-split", default="test")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="0" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--warmup", type=int, default=8)
    parser.add_argument("--iterations", type=int, default=80)
    parser.add_argument("--image-limit", type=int, default=20)
    parser.add_argument("--half", action="store_true")
    parser.add_argument("--area-video")
    parser.add_argument("--model-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--matrix-imgsz", action="append", type=int, default=[])
    parser.add_argument("--matrix-frames", type=int, default=40)
    parser.add_argument("--matrix-warmup", type=int, default=5)
    parser.add_argument("--unified-checkpoint")
    parser.add_argument("--unified-engine")
    parser.add_argument("--unified-label-map")
    args = parser.parse_args()
    if args.area_video:
        args.matrix_imgsz = args.matrix_imgsz or [640, 896, 960]
        report = run_area_matrix(args)
    else:
        if not args.data or not args.candidate:
            parser.error("--data and at least one --candidate are required unless --area-video is used")
        report = run(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
