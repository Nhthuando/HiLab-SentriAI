"""Prepare and validate a local BAI-KIEM golden-frame candidate set.

Extraction is strictly sequential.  The module never creates annotations and it
never includes an absolute source path in the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence

import cv2
import numpy as np


SCHEMA_VERSION = 1
ANNOTATION_STATUSES = frozenset({"PENDING", "ANNOTATED", "NEGATIVE"})
EVALUATABLE_STATUSES = frozenset({"ANNOTATED", "NEGATIVE"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DHASH_RE = re.compile(r"^[0-9a-f]{16}$")


class GoldenManifestError(ValueError):
    """Raised when a golden manifest violates its portable schema."""


@dataclass(frozen=True)
class ExtractionSummary:
    requested: int
    accepted: int
    exact_duplicates: int
    near_duplicates: int
    decoded_frames: int


def _portable_relative_path(value: object, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise GoldenManifestError(f"{field} must be a non-empty relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
        raise GoldenManifestError(f"{field} must be portable and relative")
    return value


def validate_manifest(manifest: object) -> dict[str, Any]:
    """Validate and return a manifest without touching its referenced files."""
    if not isinstance(manifest, dict):
        raise GoldenManifestError("manifest must be an object")
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise GoldenManifestError(f"schemaVersion must equal {SCHEMA_VERSION}")
    if not isinstance(manifest.get("datasetId"), str) or not manifest["datasetId"]:
        raise GoldenManifestError("datasetId must be a non-empty string")
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise GoldenManifestError("source must be an object")
    if not isinstance(source.get("sourceId"), str) or not source["sourceId"]:
        raise GoldenManifestError("source.sourceId must be a non-empty string")
    source_file = source.get("sourceFile")
    if not isinstance(source_file, str) or not source_file or Path(source_file).name != source_file:
        raise GoldenManifestError("source.sourceFile must contain a basename only")
    duration_ms = source.get("durationMs")
    if not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or duration_ms <= 0:
        raise GoldenManifestError("source.durationMs must be a positive integer")
    extraction = manifest.get("extraction")
    if not isinstance(extraction, dict):
        raise GoldenManifestError("extraction must be an object")
    time_block_seconds = extraction.get("timeBlockSeconds")
    if not isinstance(time_block_seconds, int) or isinstance(time_block_seconds, bool) or time_block_seconds <= 0:
        raise GoldenManifestError("extraction.timeBlockSeconds must be a positive integer")
    frames = manifest.get("frames")
    if not isinstance(frames, list):
        raise GoldenManifestError("frames must be an array")

    frame_ids: set[str] = set()
    image_paths: set[str] = set()
    for index, record in enumerate(frames):
        prefix = f"frames[{index}]"
        if not isinstance(record, dict):
            raise GoldenManifestError(f"{prefix} must be an object")
        expected_keys = {
            "frameId", "sourceId", "timestampMs", "imagePath", "sha256",
            "perceptualHash", "annotationStatus", "labelsPath", "tags", "timeBlock", "split",
        }
        if set(record) != expected_keys:
            raise GoldenManifestError(f"{prefix} has an unexpected field set")
        frame_id = record.get("frameId")
        if not isinstance(frame_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,80}", frame_id):
            raise GoldenManifestError(f"{prefix}.frameId is invalid")
        if frame_id in frame_ids:
            raise GoldenManifestError(f"duplicate frameId: {frame_id}")
        frame_ids.add(frame_id)
        if record.get("sourceId") != source["sourceId"]:
            raise GoldenManifestError(f"{prefix}.sourceId does not match source")
        timestamp_ms = record.get("timestampMs")
        if not isinstance(timestamp_ms, int) or isinstance(timestamp_ms, bool) or timestamp_ms < 0:
            raise GoldenManifestError(f"{prefix}.timestampMs must be a non-negative integer")
        if timestamp_ms >= duration_ms:
            raise GoldenManifestError(f"{prefix}.timestampMs is outside source duration")
        image_path = _portable_relative_path(record.get("imagePath"), f"{prefix}.imagePath")
        if image_path in image_paths:
            raise GoldenManifestError(f"duplicate imagePath: {image_path}")
        image_paths.add(image_path)
        if not isinstance(record.get("sha256"), str) or not SHA256_RE.fullmatch(record["sha256"]):
            raise GoldenManifestError(f"{prefix}.sha256 is invalid")
        if not isinstance(record.get("perceptualHash"), str) or not DHASH_RE.fullmatch(record["perceptualHash"]):
            raise GoldenManifestError(f"{prefix}.perceptualHash is invalid")
        status = record.get("annotationStatus")
        if status not in ANNOTATION_STATUSES:
            raise GoldenManifestError(f"{prefix}.annotationStatus is invalid")
        labels_path = _portable_relative_path(record.get("labelsPath"), f"{prefix}.labelsPath", nullable=True)
        if status == "ANNOTATED" and labels_path is None:
            raise GoldenManifestError(f"{prefix}.labelsPath is required for ANNOTATED")
        if status == "PENDING" and labels_path is not None:
            raise GoldenManifestError(f"{prefix}.labelsPath must be null for PENDING")
        tags = record.get("tags")
        if not isinstance(tags, list) or not tags or any(not isinstance(tag, str) or not tag for tag in tags):
            raise GoldenManifestError(f"{prefix}.tags must be a non-empty string array")
        if len(tags) != len(set(tags)):
            raise GoldenManifestError(f"{prefix}.tags contains duplicates")
        time_block = record.get("timeBlock")
        if not isinstance(time_block, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,100}", time_block):
            raise GoldenManifestError(f"{prefix}.timeBlock is invalid")
        if record.get("split") not in {"calibration", "validation", "test"}:
            raise GoldenManifestError(f"{prefix}.split is invalid")
        expected_block, expected_split = _time_block_assignment(
            timestamp_ms, duration_ms, source["sourceId"], time_block_seconds,
        )
        if record["timeBlock"] != expected_block or record["split"] != expected_split:
            raise GoldenManifestError(f"{prefix} timeBlock/split does not match its timestamp")
    block_splits: dict[str, str] = {}
    for record in frames:
        previous = block_splits.setdefault(record["timeBlock"], record["split"])
        if previous != record["split"]:
            raise GoldenManifestError(f"timeBlock {record['timeBlock']} crosses splits")
    return manifest


def load_manifest(path: Path | str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return validate_manifest(json.load(handle))


def evaluatable_records(manifest: object) -> list[dict[str, Any]]:
    validated = validate_manifest(manifest)
    return [record for record in validated["frames"] if record["annotationStatus"] in EVALUATABLE_STATUSES]


def difference_hash(image: np.ndarray) -> str:
    if image is None or image.size == 0:
        raise ValueError("image must not be empty")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = resized[:, 1:] > resized[:, :-1]
    value = 0
    for bit in bits.reshape(-1):
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def hash_distance(left: str, right: str) -> int:
    if not DHASH_RE.fullmatch(left) or not DHASH_RE.fullmatch(right):
        raise ValueError("dHash values must be 16 lowercase hexadecimal characters")
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _target_timestamps(duration_ms: int, interval_seconds: float, hard_case_timestamps_ms: Iterable[int]) -> list[tuple[int, list[str]]]:
    if duration_ms <= 0:
        raise ValueError("video duration must be positive")
    if not math.isfinite(interval_seconds) or interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive and finite")
    targets: dict[int, set[str]] = {}
    step_ms = max(1, round(interval_seconds * 1000))
    for timestamp_ms in range(0, duration_ms, step_ms):
        targets.setdefault(timestamp_ms, set()).add("interval")
    for raw in hard_case_timestamps_ms:
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0 or raw >= duration_ms:
            raise ValueError(f"hard-case timestamp outside video duration: {raw!r}")
        targets.setdefault(raw, set()).add("hard-case")
    return [(timestamp, sorted(tags)) for timestamp, tags in sorted(targets.items())]


def _time_block_assignment(timestamp_ms: int, duration_ms: int, source_id: str, block_seconds: int) -> tuple[str, str]:
    block_ms = block_seconds * 1000
    block_index = min((duration_ms - 1) // block_ms, timestamp_ms // block_ms)
    block_count = max(1, math.ceil(duration_ms / block_ms))
    calibration_blocks = max(1, round(block_count * 0.20)) if block_count >= 3 else 0
    validation_blocks = max(1, round(block_count * 0.40)) if block_count >= 2 else 0
    if block_index < calibration_blocks:
        split = "calibration"
    elif block_index < calibration_blocks + validation_blocks:
        split = "validation"
    else:
        split = "test"
    return f"{source_id}-tb{block_index:03d}", split


def extract_golden_frames(
    source_path: Path | str,
    output_directory: Path | str,
    *,
    source_id: str,
    dataset_id: str,
    interval_seconds: float = 10.0,
    hard_case_timestamps_ms: Sequence[int] = (),
    dhash_distance_threshold: int = 4,
    jpeg_quality: int = 92,
    time_block_seconds: int = 120,
    dhash_dedupe_window_seconds: float = 2.0,
) -> tuple[dict[str, Any], ExtractionSummary]:
    """Sequentially extract unique candidate frames and write a portable manifest."""
    source = Path(source_path)
    output = Path(output_directory)
    if not source.is_file():
        raise FileNotFoundError(source)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,80}", source_id):
        raise ValueError("source_id must be a portable stable identifier")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,80}", dataset_id):
        raise ValueError("dataset_id must be a portable stable identifier")
    if not 0 <= dhash_distance_threshold <= 64:
        raise ValueError("dhash_distance_threshold must be in [0, 64]")
    if not 1 <= jpeg_quality <= 100:
        raise ValueError("jpeg_quality must be in [1, 100]")
    if time_block_seconds <= 0:
        raise ValueError("time_block_seconds must be positive")
    if not math.isfinite(dhash_dedupe_window_seconds) or dhash_dedupe_window_seconds < 0:
        raise ValueError("dhash_dedupe_window_seconds must be finite and non-negative")

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"cannot open video: {source.name}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not math.isfinite(fps) or fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
        capture.release()
        raise RuntimeError("video metadata is invalid")
    duration_ms = max(1, math.ceil(frame_count * 1000.0 / fps))
    targets = _target_timestamps(duration_ms, interval_seconds, hard_case_timestamps_ms)

    image_directory = output / "images"
    labels_directory = output / "labels"
    image_directory.mkdir(parents=True, exist_ok=True)
    labels_directory.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    seen_sha: set[str] = set()
    seen_dhash: list[tuple[str, int]] = []
    exact_duplicates = 0
    near_duplicates = 0
    decoded_frames = 0
    target_index = 0

    try:
        while target_index < len(targets):
            ok = capture.grab()
            if not ok:
                break
            frame_index = decoded_frames
            decoded_frames += 1
            timestamp_ms = round(frame_index * 1000.0 / fps)
            if timestamp_ms < targets[target_index][0]:
                continue
            ok, frame = capture.retrieve()
            if not ok:
                raise RuntimeError(f"failed to decode frame at {timestamp_ms} ms")
            due_tags: set[str] = set()
            while target_index < len(targets) and targets[target_index][0] <= timestamp_ms:
                due_tags.update(targets[target_index][1])
                target_index += 1
            encoded_ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
            if not encoded_ok:
                raise RuntimeError(f"failed to encode frame at {timestamp_ms} ms")
            payload = encoded.tobytes()
            sha256 = hashlib.sha256(payload).hexdigest()
            if sha256 in seen_sha:
                exact_duplicates += 1
                continue
            perceptual_hash = difference_hash(frame)
            dedupe_window_ms = round(dhash_dedupe_window_seconds * 1000)
            if any(
                timestamp_ms - previous_timestamp <= dedupe_window_ms
                and hash_distance(perceptual_hash, previous_hash) <= dhash_distance_threshold
                for previous_hash, previous_timestamp in seen_dhash
            ):
                near_duplicates += 1
                continue
            frame_id = f"bai-kiem-{timestamp_ms:09d}"
            filename = f"{frame_id}.jpg"
            (image_directory / filename).write_bytes(payload)
            time_block, split = _time_block_assignment(timestamp_ms, duration_ms, source_id, time_block_seconds)
            record = {
                "frameId": frame_id,
                "sourceId": source_id,
                "timestampMs": timestamp_ms,
                "imagePath": f"images/{filename}",
                "sha256": sha256,
                "perceptualHash": perceptual_hash,
                "annotationStatus": "PENDING",
                "labelsPath": None,
                "tags": sorted(due_tags),
                "timeBlock": time_block,
                "split": split,
            }
            records.append(record)
            seen_sha.add(sha256)
            seen_dhash.append((perceptual_hash, timestamp_ms))
    finally:
        capture.release()

    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "datasetId": dataset_id,
        "source": {
            "sourceId": source_id,
            "sourceFile": source.name,
            "durationMs": duration_ms,
            "fps": round(fps, 6),
            "width": width,
            "height": height,
        },
        "extraction": {
            "intervalSeconds": interval_seconds,
            "hardCaseTimestampsMs": list(hard_case_timestamps_ms),
            "dhashDistanceThreshold": dhash_distance_threshold,
            "jpegQuality": jpeg_quality,
            "timeBlockSeconds": time_block_seconds,
            "dhashDedupeWindowSeconds": dhash_dedupe_window_seconds,
            "mode": "SEQUENTIAL",
        },
        "frames": records,
    }
    validate_manifest(manifest)
    manifest_path = output / "golden-manifest.json"
    temporary_path = output / "golden-manifest.json.tmp"
    temporary_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(manifest_path)
    summary = ExtractionSummary(
        requested=len(targets), accepted=len(records), exact_duplicates=exact_duplicates,
        near_duplicates=near_duplicates, decoded_frames=decoded_frames,
    )
    return manifest, summary


def scan_contact_hard_cases(
    source_path: Path | str,
    *,
    sample_interval_seconds: float = 5.0,
    maximum_results: int = 12,
) -> list[dict[str, Any]]:
    """Sequentially select difficult imaging conditions, without semantic claims."""
    if sample_interval_seconds <= 0 or maximum_results <= 0:
        raise ValueError("scan interval and maximum_results must be positive")
    capture = cv2.VideoCapture(str(Path(source_path)))
    if not capture.isOpened():
        capture.release()
        raise RuntimeError("cannot open video for contact scan")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    step = max(1, round(fps * sample_interval_seconds))
    candidates: list[dict[str, Any]] = []
    previous_small: np.ndarray | None = None
    index = 0
    try:
        while True:
            ok = capture.grab()
            if not ok:
                break
            if index % step == 0:
                ok, frame = capture.retrieve()
                if not ok:
                    raise RuntimeError(f"failed to decode contact frame {index}")
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                small = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
                sharpness = float(cv2.Laplacian(small, cv2.CV_64F).var())
                brightness = float(small.mean())
                change = 0.0 if previous_small is None else float(cv2.absdiff(small, previous_small).mean())
                candidates.append({
                    "timestampMs": round(index * 1000.0 / fps),
                    "sharpness": round(sharpness, 4),
                    "brightness": round(brightness, 4),
                    "visualChange": round(change, 4),
                })
                previous_small = small
            index += 1
    finally:
        capture.release()
    if not candidates:
        return []
    ranked: list[tuple[str, list[dict[str, Any]]]] = [
        ("low-sharpness", sorted(candidates, key=lambda item: (item["sharpness"], item["timestampMs"]))),
        ("low-light", sorted(candidates, key=lambda item: (item["brightness"], item["timestampMs"]))),
        ("high-light", sorted(candidates, key=lambda item: (-item["brightness"], item["timestampMs"]))),
        ("visual-change", sorted(candidates, key=lambda item: (-item["visualChange"], item["timestampMs"]))),
    ]
    selected: dict[int, dict[str, Any]] = {}
    cursor = 0
    while len(selected) < min(maximum_results, len(candidates)):
        added = False
        for reason, items in ranked:
            if cursor >= len(items):
                continue
            item = items[cursor]
            timestamp = item["timestampMs"]
            if timestamp not in selected:
                selected[timestamp] = {**item, "selectionReason": reason}
                added = True
                if len(selected) >= maximum_results:
                    break
        cursor += 1
        if not added and cursor >= len(candidates):
            break
    return [selected[timestamp] for timestamp in sorted(selected)]


def _parse_timestamps(value: str) -> list[int]:
    if not value.strip():
        return []
    return [int(item.strip()) for item in value.split(",")]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract = subparsers.add_parser("extract", help="sequentially extract a candidate set")
    extract.add_argument("source", type=Path)
    extract.add_argument("output", type=Path)
    extract.add_argument("--source-id", required=True)
    extract.add_argument("--dataset-id", required=True)
    extract.add_argument("--interval-seconds", type=float, default=10.0)
    extract.add_argument("--hard-case-timestamps-ms", type=_parse_timestamps, default=[])
    extract.add_argument("--dhash-distance-threshold", type=int, default=4)
    extract.add_argument("--jpeg-quality", type=int, default=92)
    extract.add_argument("--time-block-seconds", type=int, default=120)
    extract.add_argument("--dhash-dedupe-window-seconds", type=float, default=2.0)
    validate = subparsers.add_parser("validate", help="validate a manifest")
    validate.add_argument("manifest", type=Path)
    scan = subparsers.add_parser("scan", help="find non-semantic hard imaging conditions")
    scan.add_argument("source", type=Path)
    scan.add_argument("--sample-interval-seconds", type=float, default=5.0)
    scan.add_argument("--maximum-results", type=int, default=12)
    args = parser.parse_args(argv)
    if args.command == "validate":
        manifest = load_manifest(args.manifest)
        print(json.dumps({"valid": True, "frames": len(manifest["frames"]), "evaluatable": len(evaluatable_records(manifest))}))
        return 0
    if args.command == "scan":
        print(json.dumps(scan_contact_hard_cases(args.source, sample_interval_seconds=args.sample_interval_seconds, maximum_results=args.maximum_results), indent=2))
        return 0
    manifest, summary = extract_golden_frames(
        args.source, args.output, source_id=args.source_id, dataset_id=args.dataset_id,
        interval_seconds=args.interval_seconds, hard_case_timestamps_ms=args.hard_case_timestamps_ms,
        dhash_distance_threshold=args.dhash_distance_threshold, jpeg_quality=args.jpeg_quality,
        time_block_seconds=args.time_block_seconds,
        dhash_dedupe_window_seconds=args.dhash_dedupe_window_seconds,
    )
    print(json.dumps({"manifest": str(args.output / "golden-manifest.json"), "frames": len(manifest["frames"]), **summary.__dict__}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
