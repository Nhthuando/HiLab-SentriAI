"""Inventory local videos and build native-resolution BAI-KIEM V9 CVAT packages.

Only train/validation sources receive model proposals. Locked-test frames are
selected from temporal/visual diversity alone and are never sent to a model.
Absolute source paths are confined to the git-ignored local plan.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import cv2
import imageio_ffmpeg
import numpy as np

from training.local_video_dataset import create_cvat_archive, write_dataset_index_files
from training.v9_profile import EXPECTED_V9_CLASSES, V9Profile, load_v9_profile


SCHEMA_VERSION = 4
VIDEO_SUFFIXES = {".asf", ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".wmv"}
SPLITS = ("train", "val", "test")
COCO_TO_V9 = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

# This preparation job shares a 4 GB laptop GPU and a user workstation. Keep
# OpenCV from opening a CPU thread pool for every decoded frame.
cv2.setNumThreads(1)


class V9DatasetError(ValueError):
    """Raised when source isolation or portable package integrity is unsafe."""


@dataclass(frozen=True)
class SourceVideo:
    source_id: str
    file_name: str
    duration_ms: int
    fps: float
    width: int
    height: int
    codec: str
    signature: str
    duplicate_group: str
    modified_utc: str
    visual_signature: str = ""


@dataclass(frozen=True)
class CandidateFrame:
    frame_id: str
    source_id: str
    timestamp_ms: int
    candidate_path: str
    perceptual_hash: str
    brightness: float
    sharpness: float
    change_score: float
    predictions: tuple[dict[str, Any], ...] = ()
    disagreement_count: int = 0
    low_confidence_count: int = 0
    small_object_count: int = 0
    selection_score: float = 0.0


def _portable_id(name: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "-" for char in name)
    normalized = "-".join(filter(None, normalized.split("-")))
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"{normalized[:48] or 'video'}-{digest}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fast_signature(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha256(str(size).encode("ascii"))
    offsets = sorted({0, max(0, size // 2 - 524_288), max(0, size - 1_048_576)})
    with path.open("rb") as handle:
        for offset in offsets:
            handle.seek(offset)
            digest.update(handle.read(1_048_576))
    return digest.hexdigest()


def _difference_hash(image: np.ndarray) -> str:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = resized[:, 1:] > resized[:, :-1]
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def _hash_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _probe_visual_signature(path: Path, duration_ms: int) -> str:
    hashes: list[str] = []
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    for fraction in (0.05, 0.50, 0.95):
        seconds = duration_ms * fraction / 1000.0
        completed = subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{seconds:.3f}",
                "-i", str(path), "-frames:v", "1", "-vf", "scale=320:-2",
                "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
            ],
            capture_output=True, check=False, timeout=45,
        )
        frame = cv2.imdecode(np.frombuffer(completed.stdout, dtype=np.uint8), cv2.IMREAD_COLOR) if completed.stdout else None
        hashes.append(_difference_hash(frame) if completed.returncode == 0 and frame is not None else "0" * 16)
    return "".join(hashes)


def _visual_distance(left: str, right: str) -> int:
    if len(left) != 48 or len(right) != 48:
        return 192
    return sum(_hash_distance(left[index:index + 16], right[index:index + 16]) for index in range(0, 48, 16))


def inventory_videos(video_root: Path | str) -> list[SourceVideo]:
    root = Path(video_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Video root does not exist: {root}")
    paths = sorted(
        (path for path in root.iterdir() if path.is_file() and path.suffix.casefold() in VIDEO_SUFFIXES),
        key=lambda path: path.name.casefold(),
    )
    if not paths:
        raise V9DatasetError("No supported videos found")
    sources: list[SourceVideo] = []
    for index, path in enumerate(paths, start=1):
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise V9DatasetError(f"Cannot open video: {path.name}")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc = int(capture.get(cv2.CAP_PROP_FOURCC))
        capture.release()
        if not math.isfinite(fps) or fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
            raise V9DatasetError(f"Invalid video metadata: {path.name}")
        duration_ms = int(round(frame_count / fps * 1000))
        codec = "".join(chr((fourcc >> (8 * offset)) & 0xFF) for offset in range(4)).strip("\x00 ") or "unknown"
        signature = _fast_signature(path)
        visual_signature = _probe_visual_signature(path, duration_ms)
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
        sources.append(SourceVideo(
            source_id=_portable_id(path.stem), file_name=path.name, duration_ms=duration_ms,
            fps=round(fps, 6), width=width, height=height, codec=codec,
            signature=signature, duplicate_group=signature[:16], modified_utc=modified,
            visual_signature=visual_signature,
        ))
        print(json.dumps({"event": "inventory_progress", "processed": index, "total": len(paths), "file": path.name}), flush=True)

    groups: list[list[int]] = []
    for index, source in enumerate(sources):
        matched: list[int] | None = None
        for group in groups:
            reference = sources[group[0]]
            duration_delta = abs(source.duration_ms - reference.duration_ms)
            duration_tolerance = max(2_000, int(reference.duration_ms * 0.005))
            if source.signature == reference.signature or (
                duration_delta <= duration_tolerance
                and _visual_distance(source.visual_signature, reference.visual_signature) <= 12
            ):
                matched = group
                break
        if matched is None:
            groups.append([index])
        else:
            matched.append(index)
    for group in groups:
        group_id = f"group-{hashlib.sha256('|'.join(sorted(sources[i].signature for i in group)).encode()).hexdigest()[:12]}"
        for index in group:
            sources[index] = replace(sources[index], duplicate_group=group_id)
    return sources


def assign_source_splits(
    inventory: Sequence[SourceVideo],
    explicit: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    if not inventory:
        raise V9DatasetError("Inventory is empty")
    explicit = dict(explicit or {})
    unknown_files = set(explicit).difference(item.file_name for item in inventory)
    if unknown_files:
        raise V9DatasetError(f"Explicit split references unknown file: {sorted(unknown_files)[0]}")
    grouped: dict[str, list[SourceVideo]] = defaultdict(list)
    for item in inventory:
        grouped[item.duplicate_group].append(item)
    group_splits: dict[str, str] = {}
    for group_id, members in grouped.items():
        requested = {explicit[item.file_name] for item in members if item.file_name in explicit}
        if any(split not in SPLITS for split in requested):
            raise V9DatasetError(f"Invalid split for duplicate group {group_id}")
        if len(requested) > 1:
            raise V9DatasetError(f"Duplicate group {group_id} crosses explicit splits")
        if requested:
            group_splits[group_id] = requested.pop()

    remaining = [group_id for group_id in sorted(grouped) if group_id not in group_splits]
    durations = {group_id: max(item.duration_ms for item in members) for group_id, members in grouped.items()}
    totals = Counter({split: sum(durations[group] for group, value in group_splits.items() if value == split) for split in SPLITS})
    total_duration = sum(durations.values())
    targets = {"train": total_duration * 0.70, "val": total_duration * 0.15, "test": total_duration * 0.15}
    for group_id in sorted(remaining, key=lambda item: (-durations[item], item)):
        split = max(SPLITS, key=lambda name: (targets[name] - totals[name], name == "train", name))
        group_splits[group_id] = split
        totals[split] += durations[group_id]
    if len(grouped) >= 3:
        absent = [split for split in SPLITS if split not in group_splits.values()]
        for split in absent:
            donor_groups = [group for group, value in group_splits.items() if value == "train" and len([v for v in group_splits.values() if v == "train"]) > 1]
            if not donor_groups:
                raise V9DatasetError("Cannot allocate at least one isolated group per split")
            chosen = min(donor_groups, key=lambda group: durations[group])
            group_splits[chosen] = split

    result: list[dict[str, Any]] = []
    for item in inventory:
        split = group_splits[item.duplicate_group]
        result.append({
            "sourceId": item.source_id, "fileName": item.file_name,
            "durationMs": item.duration_ms, "fps": item.fps, "width": item.width,
            "height": item.height, "codec": item.codec, "signature": item.signature,
            "visualSignature": item.visual_signature, "duplicateGroup": item.duplicate_group,
            "modifiedUtc": item.modified_utc, "split": split,
            "mineForTraining": split in {"train", "val"},
        })
    leakage = {group for group in grouped if len({item["split"] for item in result if item["duplicateGroup"] == group}) > 1}
    if leakage:
        raise V9DatasetError(f"Source split leakage: {sorted(leakage)[0]}")
    return result


def write_inventory_outputs(
    video_root: Path, sources: Sequence[SourceVideo], plan_sources: Sequence[Mapping[str, Any]],
    local_plan_path: Path, report_root: Path, profile_path: Path,
) -> dict[str, Any]:
    local_plan_path.parent.mkdir(parents=True, exist_ok=True)
    local_plan = {
        "schemaVersion": 1, "profile": "BAIKIEM_V9_UNIFIED", "videoRoot": str(video_root.resolve()),
        "profilePath": str(profile_path.resolve()), "sources": list(plan_sources),
    }
    local_plan_path.write_text(json.dumps(local_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    split_counts = Counter(str(item["split"]) for item in plan_sources)
    split_duration = Counter()
    for item in plan_sources:
        split_duration[str(item["split"])] += int(item["durationMs"])
    portable = {
        "schemaVersion": 1, "profile": "BAIKIEM_V9_UNIFIED", "sourceCount": len(sources),
        "durationHours": round(sum(item.duration_ms for item in sources) / 3_600_000, 4),
        "splitSourceCounts": dict(sorted(split_counts.items())),
        "splitDurationHours": {key: round(value / 3_600_000, 4) for key, value in sorted(split_duration.items())},
        "duplicateGroupCount": len({item.duplicate_group for item in sources}),
        "sourceGroupLeakage": 0,
        "sources": list(plan_sources),
        "readinessWarning": "Class presence is unknown before human review; all ten classes remain INSUFFICIENT_SOURCE_COVERAGE until CVAT audit proves five independent sources.",
    }
    report_root.mkdir(parents=True, exist_ok=True)
    json_path = report_root / "baikiem-v9-video-inventory.json"
    md_path = report_root / "baikiem-v9-video-inventory.md"
    json_path.write_text(json.dumps(portable, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# BAI-KIEM V9 video inventory", "", f"- Sources: {portable['sourceCount']}",
        f"- Duration: {portable['durationHours']} hours", f"- Duplicate groups: {portable['duplicateGroupCount']}",
        "- Source-group leakage: 0", "", "| File | Split | Duration (h) | Resolution | FPS | Codec |", "|---|---:|---:|---:|---:|---|",
    ]
    for item in plan_sources:
        lines.append(f"| {item['fileName']} | {item['split']} | {int(item['durationMs']) / 3_600_000:.3f} | {item['width']}x{item['height']} | {float(item['fps']):.3f} | {item['codec']} |")
    lines.extend(["", f"> {portable['readinessWarning']}", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return portable


def _frame_metrics(path: Path, previous_small: np.ndarray | None) -> tuple[str, float, float, float, np.ndarray]:
    # Decode directly at 1/8 scale for scene metrics. The native JPEG remains
    # untouched for CVAT/model inference, while peak RAM and CPU load stay low.
    image = cv2.imread(str(path), cv2.IMREAD_REDUCED_COLOR_8)
    if image is None:
        raise V9DatasetError(f"Cannot decode extracted frame: {path}")
    small = cv2.resize(image, (320, 188), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    change = float(np.mean(cv2.absdiff(gray, previous_small))) if previous_small is not None else 255.0
    return _difference_hash(gray), brightness, sharpness, change, gray


def _extract_sampled_frames(source_path: Path, output: Path, interval_seconds: float) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    pattern = output / "%06d.jpg"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    base = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    common = [
        "-i", str(source_path), "-vf", f"fps=1/{interval_seconds:g}",
        "-q:v", "3", "-threads", "2", str(pattern),
    ]
    attempts = [base + ["-hwaccel", "cuda"] + common, base + common]
    error = ""
    for attempt_index, command in enumerate(attempts):
        for old in output.glob("*.jpg"):
            old.unlink()
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        paths = sorted(output.glob("*.jpg"))
        if completed.returncode == 0 and paths:
            return paths
        error = completed.stderr[-2000:]
        if attempt_index == 0:
            print(json.dumps({"event": "nvdec_fallback", "file": source_path.name}), flush=True)
    raise RuntimeError(f"ffmpeg extraction failed for {source_path.name}: {error}")


def _candidate_score(frame: CandidateFrame) -> float:
    prediction_score = sum(min(1.0, float(item["confidence"])) for item in frame.predictions)
    quality = min(1.5, frame.sharpness / 100.0) + min(1.0, frame.change_score / 20.0)
    return round(
        quality + prediction_score + frame.disagreement_count * 5.0
        + frame.low_confidence_count * 2.5 + frame.small_object_count * 1.5,
        6,
    )


def select_diverse_frames(
    candidates: Sequence[CandidateFrame], *, target: int, max_hamming: int,
    minimum_gap_ms: int = 3_000, negative_fraction: float = 0.20,
) -> list[CandidateFrame]:
    if target <= 0:
        raise ValueError("target must be positive")
    positives = [replace(item, selection_score=_candidate_score(item)) for item in candidates if item.predictions]
    negatives = [replace(item, selection_score=_candidate_score(item)) for item in candidates if not item.predictions]
    positives.sort(key=lambda item: (-item.selection_score, item.timestamp_ms, item.frame_id))
    negatives.sort(key=lambda item: (-item.change_score, -item.sharpness, item.timestamp_ms, item.frame_id))
    desired_negative = min(len(negatives), int(round(target * negative_fraction)))
    pools = [(negatives, desired_negative), (positives, target - desired_negative)]
    selected: list[CandidateFrame] = []
    selected_ids: set[str] = set()

    def add(item: CandidateFrame, *, relax_hash: bool = False, relax_gap: bool = False) -> bool:
        if item.frame_id in selected_ids:
            return False
        same_source = [prior for prior in selected if prior.source_id == item.source_id]
        if not relax_gap and any(abs(prior.timestamp_ms - item.timestamp_ms) < minimum_gap_ms for prior in same_source):
            return False
        if not relax_hash and any(_hash_distance(prior.perceptual_hash, item.perceptual_hash) <= max_hamming for prior in same_source):
            return False
        selected.append(item)
        selected_ids.add(item.frame_id)
        return True

    for pool, quota in pools:
        added = 0
        for item in pool:
            if add(item):
                added += 1
            if added >= quota:
                break
    combined = sorted([*positives, *negatives], key=lambda item: (-item.selection_score, item.timestamp_ms, item.frame_id))
    for relax_hash, relax_gap in ((False, False), (True, False), (True, True)):
        for item in combined:
            if len(selected) >= min(target, len(candidates)):
                break
            add(item, relax_hash=relax_hash, relax_gap=relax_gap)
        if len(selected) >= min(target, len(candidates)):
            break
    return sorted(selected[:target], key=lambda item: (item.source_id, item.timestamp_ms))


def _predict_candidates(
    candidates: Sequence[CandidateFrame], root: Path, model_path: Path, *, kind: str,
    profile: V9Profile, device: str, checkpoint_path: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    from ultralytics import YOLO
    import torch

    torch.set_num_threads(2)
    candidate_hash = hashlib.sha256("\n".join(item.frame_id for item in candidates).encode("utf-8")).hexdigest()
    model_hash = _sha256_file(model_path)
    predictions: dict[str, list[dict[str, Any]]] = {}
    if checkpoint_path is not None and checkpoint_path.is_file():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("candidateHash") == candidate_hash and checkpoint.get("modelHash") == model_hash:
            stored = checkpoint.get("predictions")
            if isinstance(stored, dict):
                predictions = {
                    str(frame_id): list(items) for frame_id, items in stored.items()
                    if isinstance(items, list)
                }
                print(json.dumps({
                    "event": "inference_resume", "model": kind,
                    "completed": len(predictions), "total": len(candidates),
                }), flush=True)
    model = YOLO(str(model_path))
    missing = [item for item in candidates if item.frame_id not in predictions]
    safe_batch = max(1, min(2, profile.selection.batch))
    options = {
        "stream": False, "verbose": False, "save": False,
        "conf": profile.selection.proposal_confidence, "iou": 0.70,
        "imgsz": profile.selection.image_size, "batch": safe_batch,
        "device": device,
    }
    for start in range(0, len(missing), safe_batch):
        chunk = missing[start:start + safe_batch]
        paths = [str(root / item.candidate_path) for item in chunk]
        try:
            results = model.predict(source=paths, **options, quantize=16 if device != "cpu" else False)
        except (TypeError, ValueError, SyntaxError):
            results = model.predict(source=paths, **options)
        for frame, result in zip(chunk, results, strict=True):
            frame_predictions: list[dict[str, Any]] = []
            height, width = result.orig_shape
            if result.boxes is not None:
                for box in result.boxes:
                    raw_class = int(box.cls.item())
                    class_name = COCO_TO_V9.get(raw_class) if kind == "base" else "reach_stacker"
                    if class_name is None:
                        continue
                    x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
                    confidence = float(box.conf.item())
                    frame_predictions.append({
                        "class": class_name, "confidence": confidence, "source": kind,
                        "bbox": [x1 / width, y1 / height, x2 / width, y2 / height],
                    })
            predictions[frame.frame_id] = frame_predictions
        processed = len(predictions)
        if checkpoint_path is not None and (processed % 10 == 0 or processed == len(candidates)):
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = checkpoint_path.with_name(f".{checkpoint_path.name}.{os.getpid()}.tmp")
            temporary.write_text(json.dumps({
                "candidateHash": candidate_hash, "modelHash": model_hash,
                "kind": kind, "predictions": predictions,
            }, ensure_ascii=False), encoding="utf-8")
            for retry in range(10):
                try:
                    temporary.replace(checkpoint_path)
                    break
                except PermissionError:
                    if retry == 9:
                        raise
                    time.sleep(0.25)
        if processed % 20 < safe_batch or processed == len(candidates):
            print(json.dumps({
                "event": "inference_progress", "model": kind,
                "processed": processed, "total": len(candidates), "batch": safe_batch,
            }), flush=True)
        time.sleep(0.02)
    result = {item.frame_id: predictions.get(item.frame_id, []) for item in candidates}
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return result


def _iou(left: Sequence[float], right: Sequence[float]) -> float:
    x1, y1 = max(left[0], right[0]), max(left[1], right[1])
    x2, y2 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1]) + max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1]) - intersection
    return intersection / union if union > 0 else 0.0


def _enrich_candidates(
    candidates: Sequence[CandidateFrame], base: Mapping[str, list[dict[str, Any]]],
    custom: Mapping[str, list[dict[str, Any]]], profile: V9Profile,
) -> list[CandidateFrame]:
    enriched: list[CandidateFrame] = []
    for item in candidates:
        predictions = tuple([*base[item.frame_id], *custom[item.frame_id]])
        disagreement = 0
        for left_index, left in enumerate(predictions):
            for right in predictions[left_index + 1:]:
                if left["class"] != right["class"] and _iou(left["bbox"], right["bbox"]) >= 0.35:
                    disagreement += 1
        low = sum(float(value["confidence"]) < profile.selection.high_confidence for value in predictions)
        small = sum((value["bbox"][2] - value["bbox"][0]) * (value["bbox"][3] - value["bbox"][1]) < 0.01 for value in predictions)
        enriched.append(replace(item, predictions=predictions, disagreement_count=disagreement, low_confidence_count=low, small_object_count=small))
    return enriched


def _write_yolo(path: Path, predictions: Sequence[Mapping[str, Any]]) -> None:
    class_to_id = {name: index for index, name in enumerate(EXPECTED_V9_CLASSES)}
    rows: list[str] = []
    for item in predictions:
        x1, y1, x2, y2 = (float(value) for value in item["bbox"])
        x1, y1, x2, y2 = max(0.0, x1), max(0.0, y1), min(1.0, x2), min(1.0, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        rows.append(f"{class_to_id[str(item['class'])]} {(x1+x2)/2:.8f} {(y1+y2)/2:.8f} {x2-x1:.8f} {y2-y1:.8f}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")


def _allocate_targets(sources: Sequence[Mapping[str, Any]], target: int) -> dict[str, int]:
    total = sum(int(item["durationMs"]) for item in sources)
    raw = {str(item["sourceId"]): target * int(item["durationMs"]) / total for item in sources}
    allocated = {source_id: int(math.floor(value)) for source_id, value in raw.items()}
    for source_id in sorted(raw, key=lambda key: (-(raw[key] - allocated[key]), key))[:target - sum(allocated.values())]:
        allocated[source_id] += 1
    return allocated


def _package(
    root: Path, selected: Sequence[CandidateFrame], sources: Sequence[Mapping[str, Any]],
    output: Path, dataset_id: str, *, locked: bool,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=str(output.parent)))
    source_lookup = {str(item["sourceId"]): item for item in sources}
    frames: list[dict[str, Any]] = []
    proposal_details: dict[str, list[dict[str, Any]]] = {}
    class_counts = Counter()
    try:
        for item in selected:
            source = source_lookup[item.source_id]
            split = str(source["split"])
            image_relative = f"images/{split}/{item.frame_id}.jpg"
            label_relative = f"labels/{split}/{item.frame_id}.txt"
            destination = temporary / image_relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / item.candidate_path, destination)
            predictions = () if locked else item.predictions
            _write_yolo(temporary / label_relative, predictions)
            class_counts.update(str(prediction["class"]) for prediction in predictions)
            proposal_details[item.frame_id] = [dict(prediction) for prediction in predictions]
            frames.append({
                "frameId": item.frame_id, "sourceId": item.source_id,
                "duplicateGroup": source["duplicateGroup"], "timestampMs": item.timestamp_ms,
                "split": split, "imagePath": image_relative, "labelsPath": label_relative,
                "sha256": _sha256_file(destination), "perceptualHash": item.perceptual_hash,
                "originalResolution": [int(source["width"]), int(source["height"])],
                "brightness": round(item.brightness, 3), "sharpness": round(item.sharpness, 3),
                "changeScore": round(item.change_score, 3), "proposalCount": len(predictions),
                "disagreementCount": 0 if locked else item.disagreement_count,
                "reviewStatus": "PENDING_REVIEW",
            })
        source_counts = Counter(item.source_id for item in selected)
        portable_sources = [{**dict(source), "selectedFrames": source_counts[str(source["sourceId"])]} for source in sources]
        manifest = {
            "schemaVersion": SCHEMA_VERSION, "datasetId": dataset_id,
            "profile": "BAIKIEM_V9_UNIFIED", "reviewStatus": "PENDING_REVIEW",
            "lockedBlind": locked, "trainingAllowed": False,
            "classes": list(EXPECTED_V9_CLASSES), "sources": portable_sources, "frames": frames,
            "proposalSources": [] if locked else ["yolo11n-coco", "baikiem-reach-v8"],
            "proposalWarning": "Review every frame and label every visible object from all ten classes. Proposals are not ground truth.",
        }
        (temporary / "annotation-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (temporary / "proposal-details.json").write_text(json.dumps(proposal_details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with (temporary / "review.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            fields = ["frameId", "sourceId", "timestampMs", "split", "imagePath", "labelsPath", "proposalCount", "reviewStatus", "reviewerNotes"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for frame in frames:
                writer.writerow({key: frame.get(key, "") for key in fields})
        write_dataset_index_files(temporary, frames, EXPECTED_V9_CLASSES)
        summary = {
            "datasetId": dataset_id, "frameCount": len(frames), "lockedBlind": locked,
            "splitCounts": dict(sorted(Counter(str(frame["split"]) for frame in frames).items())),
            "sourceCounts": dict(sorted(source_counts.items())), "proposalClassCounts": dict(sorted(class_counts.items())),
            "reviewStatus": "PENDING_REVIEW", "trainingStarted": False,
        }
        (temporary / "build-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return summary


def audit_review_package(package: Path | str) -> dict[str, Any]:
    root = Path(package).resolve()
    manifest = json.loads((root / "annotation-manifest.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    absolute_leaks = 0
    non_empty_locked = 0
    hashes: set[str] = set()
    near_duplicates = 0
    seen_by_source: dict[str, list[tuple[str, int]]] = defaultdict(list)
    if tuple(manifest.get("classes", ())) != EXPECTED_V9_CLASSES:
        errors.append("class contract mismatch")
    locked = manifest.get("lockedBlind") is True
    for source in manifest.get("sources", []):
        if any(Path(str(value)).is_absolute() for key, value in source.items() if "path" in str(key).casefold()):
            absolute_leaks += 1
    for frame in manifest.get("frames", []):
        for field in ("imagePath", "labelsPath"):
            value = str(frame.get(field, ""))
            pure = PurePosixPath(value)
            if not value or pure.is_absolute() or ".." in pure.parts or ":" in value or "\\" in value:
                absolute_leaks += 1
        image = root / str(frame["imagePath"])
        label = root / str(frame["labelsPath"])
        if not image.is_file() or not label.is_file():
            errors.append(f"missing media for {frame.get('frameId')}")
            continue
        sha = _sha256_file(image)
        if sha in hashes:
            errors.append(f"exact duplicate image {frame.get('frameId')}")
        hashes.add(sha)
        frame_hash = str(frame.get("perceptualHash", ""))
        timestamp_ms = int(frame.get("timestampMs", 0))
        prior_hashes = seen_by_source[str(frame.get("sourceId"))]
        if any(
            0 < timestamp_ms - prior_timestamp < 12_000
            and len(frame_hash) == len(prior_hash) == 16
            and _hash_distance(frame_hash, prior_hash) <= 4
            for prior_hash, prior_timestamp in prior_hashes
        ):
            near_duplicates += 1
        prior_hashes.append((frame_hash, timestamp_ms))
        rows = label.read_text(encoding="utf-8").splitlines()
        if locked and rows:
            non_empty_locked += 1
        for row in rows:
            fields = row.split()
            if len(fields) != 5:
                errors.append(f"invalid label row {frame.get('frameId')}")
                continue
            try:
                class_id = int(fields[0]); values = [float(value) for value in fields[1:]]
            except ValueError:
                errors.append(f"invalid label value {frame.get('frameId')}")
                continue
            if not 0 <= class_id < len(EXPECTED_V9_CLASSES) or any(not 0.0 <= value <= 1.0 for value in values) or values[2] <= 0 or values[3] <= 0:
                errors.append(f"out-of-range label {frame.get('frameId')}")
    if absolute_leaks:
        errors.append("absolute/private path leak")
    if non_empty_locked:
        errors.append("locked package contains proposals")
    duplicate_groups: dict[str, set[str]] = defaultdict(set)
    for source in manifest.get("sources", []):
        duplicate_groups[str(source.get("duplicateGroup"))].add(str(source.get("split")))
    leakage = sum(len(splits) > 1 for splits in duplicate_groups.values())
    if leakage:
        errors.append("duplicate group split leakage")
    return {
        "package": root.name, "frameCount": len(manifest.get("frames", [])),
        "absolutePathLeaks": absolute_leaks, "exactDuplicates": sum(error.startswith("exact duplicate") for error in errors),
        "nearDuplicatePairsWithinSource": near_duplicates, "duplicateGroupLeakage": leakage,
        "nonEmptyLockedLabels": non_empty_locked, "errors": errors,
    }


def build_v9_review_packages(
    local_plan_path: Path, profile_path: Path, base_model: Path, custom_model: Path,
    train_val_output: Path, locked_output: Path, *, device: str = "0",
) -> dict[str, Any]:
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("MKL_NUM_THREADS", "2")
    try:
        import psutil
    except ImportError:
        pass
    else:
        try:
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except (AttributeError, OSError, psutil.Error):
            pass
    profile = load_v9_profile(profile_path)
    plan = json.loads(local_plan_path.read_text(encoding="utf-8"))
    root = Path(plan["videoRoot"]).resolve()
    sources = plan.get("sources")
    if not isinstance(sources, list) or not sources:
        raise V9DatasetError("Local source plan is empty")
    split_by_group: dict[str, set[str]] = defaultdict(set)
    for source in sources:
        split_by_group[str(source["duplicateGroup"])].add(str(source["split"]))
    if any(len(splits) > 1 for splits in split_by_group.values()):
        raise V9DatasetError("Local plan has duplicate-group split leakage")
    if any(source["split"] == "test" and source.get("mineForTraining") is not False for source in sources):
        raise V9DatasetError("Locked source is marked mineable")
    train_val_sources = [source for source in sources if source["split"] in {"train", "val"}]
    locked_sources = [source for source in sources if source["split"] == "test"]
    if not train_val_sources or not locked_sources:
        raise V9DatasetError("Both train/validation and locked sources are required")
    cache_root = train_val_output.parent / ".baikiem-v9-native-candidates"
    cache_root.mkdir(parents=True, exist_ok=True)
    candidates_by_source: dict[str, list[CandidateFrame]] = {}
    all_frames_by_source: dict[str, list[CandidateFrame]] = {}
    build_completed = False
    try:
        for source_index, source in enumerate(sources, start=1):
            source_id = str(source["sourceId"])
            source_path = root / str(source["fileName"])
            source_cache = cache_root / source_id
            cached_paths = sorted(source_cache.glob("*.jpg")) if source_cache.is_dir() else []
            minimum_complete_count = max(
                1,
                int(int(source["durationMs"]) / 1000.0 / profile.selection.sample_interval_seconds) - 1,
            )
            if len(cached_paths) >= minimum_complete_count:
                paths = cached_paths
                print(json.dumps({
                    "event": "extract_resume", "source": source["fileName"],
                    "index": source_index, "total": len(sources), "cachedFrames": len(paths),
                }), flush=True)
            else:
                if source_cache.exists():
                    shutil.rmtree(source_cache)
                print(json.dumps({"event": "extract_start", "source": source["fileName"], "index": source_index, "total": len(sources)}), flush=True)
                paths = _extract_sampled_frames(source_path, source_cache, profile.selection.sample_interval_seconds)
            metrics_path = source_cache / ".frame-metrics.json"
            accepted: list[CandidateFrame] = []
            all_frames: list[CandidateFrame] = []
            if metrics_path.is_file():
                metrics_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
                if metrics_payload.get("frameCount") == len(paths):
                    all_frames = [CandidateFrame(**item) for item in metrics_payload.get("allFrames", [])]
                    accepted = [CandidateFrame(**item) for item in metrics_payload.get("acceptedFrames", [])]
                    print(json.dumps({
                        "event": "metrics_resume", "source": source["fileName"],
                        "sampled": len(all_frames), "qualityDiverse": len(accepted),
                    }), flush=True)
            if not all_frames:
                previous: np.ndarray | None = None
                last_accepted_hash: str | None = None
                last_accepted_ms = -10**12
                for frame_index, path in enumerate(paths):
                    timestamp_ms = int(round(frame_index * profile.selection.sample_interval_seconds * 1000))
                    dhash, brightness, sharpness, change, previous = _frame_metrics(path, previous)
                    candidate = CandidateFrame(
                        frame_id=f"{source_id}-{timestamp_ms:010d}", source_id=source_id,
                        timestamp_ms=timestamp_ms, candidate_path=path.relative_to(cache_root).as_posix(),
                        perceptual_hash=dhash, brightness=brightness, sharpness=sharpness, change_score=change,
                    )
                    all_frames.append(candidate)
                    quality_ok = 15.0 <= brightness <= 245.0 and sharpness >= 12.0
                    diverse = last_accepted_hash is None or _hash_distance(last_accepted_hash, dhash) > profile.selection.near_duplicate_hamming
                    anchor = timestamp_ms - last_accepted_ms >= int(profile.selection.stationary_anchor_seconds * 1000)
                    if quality_ok and (diverse or anchor):
                        accepted.append(candidate)
                        last_accepted_hash, last_accepted_ms = dhash, timestamp_ms
                metrics_path.write_text(json.dumps({
                    "frameCount": len(paths),
                    "allFrames": [asdict(item) for item in all_frames],
                    "acceptedFrames": [asdict(item) for item in accepted],
                }, ensure_ascii=False), encoding="utf-8")
            required = _allocate_targets(sources, profile.selection.train_val_target_frames + profile.selection.locked_target_frames).get(source_id, 0)
            if len(accepted) < required:
                accepted = all_frames
            all_frames_by_source[source_id] = all_frames
            candidates_by_source[source_id] = accepted
            print(json.dumps({"event": "extract_done", "source": source["fileName"], "sampled": len(paths), "qualityDiverse": len(accepted)}), flush=True)

        train_allocations = _allocate_targets(train_val_sources, profile.selection.train_val_target_frames)
        pool_allocations = _allocate_targets(train_val_sources, profile.selection.maximum_candidate_frames)
        train_candidates: list[CandidateFrame] = []
        for source in train_val_sources:
            source_id = str(source["sourceId"])
            pool_target = min(
                len(candidates_by_source[source_id]),
                max(train_allocations[source_id], pool_allocations[source_id]),
            )
            train_candidates.extend(select_diverse_frames(
                candidates_by_source[source_id], target=pool_target,
                max_hamming=profile.selection.near_duplicate_hamming,
                minimum_gap_ms=int(profile.selection.sample_interval_seconds * 1000),
                negative_fraction=1.0,
            ))
        print(json.dumps({"event": "prelabel_start", "candidateCount": len(train_candidates)}), flush=True)
        checkpoint_root = cache_root / ".checkpoints"
        base_predictions = _predict_candidates(
            train_candidates, cache_root, base_model.resolve(), kind="base", profile=profile,
            device=device, checkpoint_path=checkpoint_root / "base-proposals.json",
        )
        custom_predictions = _predict_candidates(
            train_candidates, cache_root, custom_model.resolve(), kind="custom", profile=profile,
            device=device, checkpoint_path=checkpoint_root / "custom-proposals.json",
        )
        enriched = _enrich_candidates(train_candidates, base_predictions, custom_predictions, profile)
        enriched_by_source: dict[str, list[CandidateFrame]] = defaultdict(list)
        for item in enriched:
            enriched_by_source[item.source_id].append(item)

        train_selected: list[CandidateFrame] = []
        for source in train_val_sources:
            source_id = str(source["sourceId"])
            source_candidates = list(enriched_by_source[source_id])
            if len(source_candidates) < train_allocations[source_id]:
                existing_ids = {item.frame_id for item in source_candidates}
                source_candidates.extend(
                    item for item in all_frames_by_source[source_id]
                    if item.frame_id not in existing_ids
                )
            selected = select_diverse_frames(
                source_candidates, target=train_allocations[source_id],
                max_hamming=profile.selection.near_duplicate_hamming,
                minimum_gap_ms=int(profile.selection.sample_interval_seconds * 1000),
                negative_fraction=profile.selection.negative_fraction,
            )
            if len(selected) != train_allocations[source_id]:
                raise V9DatasetError(f"Source {source_id} supplied {len(selected)}/{train_allocations[source_id]} train/val frames")
            train_selected.extend(selected)

        locked_allocations = _allocate_targets(locked_sources, profile.selection.locked_target_frames)
        locked_selected: list[CandidateFrame] = []
        for source in locked_sources:
            source_id = str(source["sourceId"])
            selected = select_diverse_frames(
                candidates_by_source[source_id], target=locked_allocations[source_id],
                max_hamming=profile.selection.near_duplicate_hamming,
                minimum_gap_ms=int(profile.selection.sample_interval_seconds * 1000), negative_fraction=1.0,
            )
            if len(selected) != locked_allocations[source_id]:
                raise V9DatasetError(f"Source {source_id} supplied {len(selected)}/{locked_allocations[source_id]} locked frames")
            locked_selected.extend(selected)

        train_summary = _package(cache_root, train_selected, train_val_sources, train_val_output, "BAI-KIEM-V9-TRAIN-VAL-REVIEW", locked=False)
        locked_summary = _package(cache_root, locked_selected, locked_sources, locked_output, "BAI-KIEM-V9-LOCKED-BLIND", locked=True)
        train_archive = create_cvat_archive(train_val_output, train_val_output.with_name(f"{train_val_output.name}-cvat.zip"))
        locked_archive = create_cvat_archive(locked_output, locked_output.with_name(f"{locked_output.name}-cvat.zip"))
        audits = [audit_review_package(train_val_output), audit_review_package(locked_output)]
        if any(audit["errors"] for audit in audits):
            raise V9DatasetError(f"Package audit failed: {audits}")
        result = {
            "trainVal": {**train_summary, "directory": str(train_val_output), "cvatArchive": str(train_archive)},
            "locked": {**locked_summary, "directory": str(locked_output), "cvatArchive": str(locked_archive)},
            "audits": audits, "trainingStarted": False,
        }
        report_root = train_val_output.parents[1] / "reports"
        report_root.mkdir(parents=True, exist_ok=True)
        (report_root / "baikiem-v9-review-package-build.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        build_completed = True
        return result
    finally:
        # A failed/interrupted build must keep native frames and proposal
        # checkpoints so a low-resource workstation can resume safely.
        if build_completed:
            shutil.rmtree(cache_root, ignore_errors=True)


def _parse_split_values(values: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise V9DatasetError(f"Split override must be FILE=SPLIT: {value}")
        file_name, split = value.split("=", 1)
        if split not in SPLITS:
            raise V9DatasetError(f"Unknown split: {split}")
        result[file_name] = split
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory_parser = subparsers.add_parser("inventory")
    inventory_parser.add_argument("--video-root", type=Path, required=True)
    inventory_parser.add_argument("--profile", type=Path, required=True)
    inventory_parser.add_argument("--local-plan", type=Path, required=True)
    inventory_parser.add_argument("--report-root", type=Path, required=True)
    inventory_parser.add_argument("--split", action="append", default=[], metavar="FILE=SPLIT")
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--local-plan", type=Path, required=True)
    build_parser.add_argument("--profile", type=Path, required=True)
    build_parser.add_argument("--base-model", type=Path, required=True)
    build_parser.add_argument("--custom-model", type=Path, required=True)
    build_parser.add_argument("--train-val-output", type=Path, required=True)
    build_parser.add_argument("--locked-output", type=Path, required=True)
    build_parser.add_argument("--device", default="0")
    args = parser.parse_args()
    if args.command == "inventory":
        load_v9_profile(args.profile)
        sources = inventory_videos(args.video_root)
        plan = assign_source_splits(sources, _parse_split_values(args.split))
        result = write_inventory_outputs(args.video_root, sources, plan, args.local_plan, args.report_root, args.profile)
    else:
        result = build_v9_review_packages(
            args.local_plan, args.profile, args.base_model, args.custom_model,
            args.train_val_output, args.locked_output, device=args.device,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
