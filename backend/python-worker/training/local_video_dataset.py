"""Build a private, review-required YOLO annotation package from local videos.

The generated boxes are proposals only. Every frame remains PENDING_REVIEW and
must be checked by a human before this module will be allowed to finalize it in
a later training step. Absolute source paths are accepted only as CLI inputs and
are never written into the portable output manifest.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

import cv2
import numpy as np
import yaml

from evaluation.golden_dataset import difference_hash, hash_distance


SCHEMA_VERSION = 1
CLASS_NAMES = (
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "truck",
    "reach_stacker",
    "forklift",
)
CLASS_TO_ID = {name: index for index, name in enumerate(CLASS_NAMES)}
REACH_STACKER_LABEL = "Xe nâng container"
SPLITS = frozenset({"train", "val", "test"})
ROLES = frozenset({"positive", "hard_negative", "cross_camera_negative"})
PORTABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,100}$")


class LocalVideoPlanError(ValueError):
    """Raised when the local source plan can leak or corrupt an evaluation."""


@dataclass(frozen=True)
class Proposal:
    class_name: str
    confidence: float
    xyxy: tuple[float, float, float, float]
    source: str


Predictor = Callable[[np.ndarray, str, int], list[Proposal]]


def write_dataset_index_files(output_directory: Path | str, records: Sequence[Mapping[str, object]], classes: Sequence[str]) -> None:
    """Write the portable split lists required by CVAT and Ultralytics."""
    output = Path(output_directory)
    for split in sorted(SPLITS):
        split_paths = [str(record["imagePath"]) for record in records if record.get("split") == split]
        (output / f"{split}.txt").write_text("\n".join(split_paths) + ("\n" if split_paths else ""), encoding="utf-8")
    yaml_lines = [
        "path: .",
        "train: train.txt",
        "val: val.txt",
        "test: test.txt",
        "names:",
        *[f"  {index}: {name}" for index, name in enumerate(classes)],
        "",
    ]
    (output / "data.yaml").write_text("\n".join(yaml_lines), encoding="utf-8")


def refresh_package_indexes(output_directory: Path | str) -> None:
    """Regenerate only portable list/YAML files for an existing package."""
    output = Path(output_directory)
    manifest = json.loads((output / "annotation-manifest.json").read_text(encoding="utf-8"))
    frames = manifest.get("frames")
    classes = manifest.get("classes")
    if not isinstance(frames, list) or not isinstance(classes, list):
        raise LocalVideoPlanError("annotation manifest has no frames/classes")
    write_dataset_index_files(output, frames, classes)


def create_cvat_archive(output_directory: Path | str, archive_path: Path | str) -> Path:
    """Create a cross-platform CVAT archive with POSIX member names.

    Passing a Windows ``Path`` directly as ``arcname`` stores backslashes in
    ZIP members. Linux CVAT then extracts each value as a literal filename and
    Datumaro reports that all 943 images are missing. Build the member list
    from the manifest and serialize every path explicitly as POSIX instead.
    """
    output = Path(output_directory).resolve()
    destination = Path(archive_path).resolve()
    manifest_path = output / "annotation-manifest.json"
    if not manifest_path.is_file():
        raise LocalVideoPlanError("annotation-manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise LocalVideoPlanError("annotation manifest has no frames")

    relative_members: list[PurePosixPath] = [
        PurePosixPath("data.yaml"),
        *(PurePosixPath(f"{split}.txt") for split in sorted(SPLITS)),
    ]
    for index, raw_frame in enumerate(frames):
        frame = _object(raw_frame, f"frames[{index}]")
        for field in ("imagePath", "labelsPath"):
            value = frame.get(field)
            if not isinstance(value, str) or "\\" in value or PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts:
                raise LocalVideoPlanError(f"frame {index} has unsafe {field}")
            relative_members.append(PurePosixPath(value))

    missing = [str(relative) for relative in relative_members if not (output / Path(*relative.parts)).is_file()]
    if missing:
        raise LocalVideoPlanError(f"CVAT archive member is missing: {missing[0]}")
    if len(relative_members) != len(set(relative_members)):
        raise LocalVideoPlanError("CVAT archive contains duplicate member paths")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            for relative in sorted(relative_members, key=str):
                archive.write(output / Path(*relative.parts), arcname=relative.as_posix())
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None or any("\\" in name for name in archive.namelist()):
                raise LocalVideoPlanError("CVAT archive integrity/path validation failed")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def stage_cvat_reviewed_package(
    original_package: Path | str,
    cvat_export_zip: Path | str,
    reviewed_directory: Path | str,
    *,
    reviewer_confirmation: bool,
) -> Path:
    """Overlay a completed CVAT export onto a clean locked package.

    CVAT can omit label files for reviewed negative images. An image present in
    the export with no matching label is therefore staged as an explicit empty
    label. Images themselves always come from the original hash-locked package.
    """
    if reviewer_confirmation is not True:
        raise LocalVideoPlanError("explicit confirmation that every CVAT frame was reviewed is required")
    original = Path(original_package).resolve()
    export_zip = Path(cvat_export_zip).resolve()
    target = Path(reviewed_directory).resolve()
    if not export_zip.is_file():
        raise LocalVideoPlanError("CVAT export ZIP is missing")
    if target.exists():
        raise FileExistsError(f"reviewed staging directory already exists: {target}")
    manifest_path = original / "annotation-manifest.json"
    if not manifest_path.is_file():
        raise LocalVideoPlanError("annotation-manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != SCHEMA_VERSION or tuple(manifest.get("classes", ())) != CLASS_NAMES:
        raise LocalVideoPlanError("annotation manifest schema/classes do not match this training profile")
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise LocalVideoPlanError("annotation manifest has no frames")
    expected_images = {str(_object(frame, "frame")["imagePath"]) for frame in frames}
    expected_labels = {str(_object(frame, "frame")["labelsPath"]) for frame in frames}

    def logical_export_path(name: str) -> str:
        # A task created from an image archive can retain the original
        # ``images/<split>/...`` path while the Ultralytics exporter also
        # places every task item under its own ``train`` split.  Normalize
        # only that exact, redundant wrapper; the exact-set checks below
        # still reject missing, extra, or ambiguously mapped files.
        if name.startswith("images/train/images/"):
            return name.removeprefix("images/train/")
        if name.startswith("labels/train/images/"):
            return "labels/" + name.removeprefix("labels/train/images/")
        return name

    with zipfile.ZipFile(export_zip) as archive:
        members: dict[str, zipfile.ZipInfo] = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename
            pure = PurePosixPath(name)
            if "\\" in name or pure.is_absolute() or ".." in pure.parts or ":" in name:
                raise LocalVideoPlanError(f"unsafe CVAT export member: {name}")
            normalized = logical_export_path(pure.as_posix())
            if normalized in members:
                raise LocalVideoPlanError(f"duplicate CVAT export member: {normalized}")
            members[normalized] = info
        exported_images = {name for name in members if name.startswith("images/")}
        exported_labels = {name for name in members if name.startswith("labels/")}
        if exported_images != expected_images:
            missing = sorted(expected_images - exported_images)
            extra = sorted(exported_images - expected_images)
            raise LocalVideoPlanError(
                f"CVAT export image set differs from locked package; missing={missing[:1]} extra={extra[:1]}"
            )
        if not exported_labels <= expected_labels:
            raise LocalVideoPlanError(f"CVAT export contains an unknown label file: {sorted(exported_labels - expected_labels)[0]}")
        data_info = members.get("data.yaml")
        if data_info is None:
            raise LocalVideoPlanError("CVAT export has no data.yaml")
        data_config = yaml.safe_load(archive.read(data_info).decode("utf-8")) or {}
        raw_names = data_config.get("names") if isinstance(data_config, Mapping) else None
        if isinstance(raw_names, Mapping):
            exported_classes = [raw_names.get(index, raw_names.get(str(index))) for index in range(len(CLASS_NAMES))]
        elif isinstance(raw_names, list):
            exported_classes = list(raw_names)
        else:
            exported_classes = []
        if exported_classes != list(CLASS_NAMES):
            raise LocalVideoPlanError("CVAT export class order does not match the locked package")

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=str(target.parent)))
        try:
            shutil.copytree(
                original,
                temporary,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("*.zip"),
            )
            for relative in sorted(expected_labels):
                destination = temporary / Path(*PurePosixPath(relative).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                info = members.get(relative)
                destination.write_bytes(archive.read(info) if info is not None else b"")

            review_csv = temporary / "review.csv"
            with review_csv.open("r", newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            if not rows:
                raise LocalVideoPlanError("review.csv has no rows")
            for row in rows:
                row["reviewStatus"] = "REVIEWED"
            with review_csv.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            refresh_package_indexes(temporary)
            temporary.replace(target)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    return target


def _object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LocalVideoPlanError(f"{field} must be an object")
    return value


def _portable_basename(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LocalVideoPlanError(f"{field} must be a non-empty file name")
    candidate = value.strip()
    if Path(candidate).name != candidate or PurePosixPath(candidate).is_absolute() or ":" in candidate:
        raise LocalVideoPlanError(f"{field} must contain a basename only")
    return candidate


def _positive_int(value: object, field: str, *, allow_zero: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < (0 if allow_zero else 1):
        qualifier = "non-negative" if allow_zero else "positive"
        raise LocalVideoPlanError(f"{field} must be a {qualifier} integer")
    return value


def validate_video_plan(plan: object) -> dict[str, Any]:
    """Validate a source/split plan without touching the filesystem."""
    root = _object(plan, "plan")
    if root.get("schemaVersion") != SCHEMA_VERSION:
        raise LocalVideoPlanError(f"schemaVersion must equal {SCHEMA_VERSION}")
    dataset_id = root.get("datasetId")
    if not isinstance(dataset_id, str) or PORTABLE_ID.fullmatch(dataset_id) is None:
        raise LocalVideoPlanError("datasetId must be a portable identifier")
    if tuple(root.get("classes", ())) != CLASS_NAMES:
        raise LocalVideoPlanError(f"classes must equal {list(CLASS_NAMES)!r} in this exact order")
    sources = root.get("sources")
    if not isinstance(sources, list) or not sources:
        raise LocalVideoPlanError("sources must be a non-empty array")

    source_ids: set[str] = set()
    file_names: set[str] = set()
    duplicate_splits: dict[str, set[str]] = {}
    normalized_sources: list[dict[str, Any]] = []
    for source_index, raw_source in enumerate(sources):
        prefix = f"sources[{source_index}]"
        source = _object(raw_source, prefix)
        source_id = source.get("sourceId")
        if not isinstance(source_id, str) or PORTABLE_ID.fullmatch(source_id) is None:
            raise LocalVideoPlanError(f"{prefix}.sourceId must be a portable identifier")
        if source_id in source_ids:
            raise LocalVideoPlanError(f"duplicate sourceId: {source_id}")
        source_ids.add(source_id)
        file_name = _portable_basename(source.get("fileName"), f"{prefix}.fileName")
        if file_name.casefold() in file_names:
            raise LocalVideoPlanError(f"duplicate fileName: {file_name}")
        file_names.add(file_name.casefold())
        duplicate_group = source.get("duplicateGroup")
        if not isinstance(duplicate_group, str) or PORTABLE_ID.fullmatch(duplicate_group) is None:
            raise LocalVideoPlanError(f"{prefix}.duplicateGroup must be a portable identifier")
        role = source.get("role")
        if role not in ROLES:
            raise LocalVideoPlanError(f"{prefix}.role must be one of {sorted(ROLES)}")
        raw_ranges = source.get("ranges")
        if not isinstance(raw_ranges, list) or not raw_ranges:
            raise LocalVideoPlanError(f"{prefix}.ranges must be a non-empty array")
        normalized_ranges: list[dict[str, Any]] = []
        prior_end = -1
        source_splits: set[str] = set()
        for range_index, raw_range in enumerate(raw_ranges):
            range_prefix = f"{prefix}.ranges[{range_index}]"
            range_value = _object(raw_range, range_prefix)
            start_ms = _positive_int(range_value.get("startMs"), f"{range_prefix}.startMs", allow_zero=True)
            end_ms = _positive_int(range_value.get("endMs"), f"{range_prefix}.endMs")
            interval_ms = _positive_int(range_value.get("intervalMs"), f"{range_prefix}.intervalMs")
            split = range_value.get("split")
            if split not in SPLITS:
                raise LocalVideoPlanError(f"{range_prefix}.split must be one of {sorted(SPLITS)}")
            if end_ms <= start_ms:
                raise LocalVideoPlanError(f"{range_prefix}.endMs must be greater than startMs")
            if start_ms < prior_end:
                raise LocalVideoPlanError(f"{prefix}.ranges must be ordered and non-overlapping")
            prior_end = end_ms
            source_splits.add(split)
            normalized_ranges.append({
                "startMs": start_ms,
                "endMs": end_ms,
                "split": split,
                "intervalMs": interval_ms,
            })
        if "test" in source_splits and len(source_splits) != 1:
            raise LocalVideoPlanError(f"{prefix} cannot mix test with train/val ranges")
        duplicate_splits.setdefault(duplicate_group, set()).update(source_splits)
        normalized_sources.append({
            "sourceId": source_id,
            "fileName": file_name,
            "duplicateGroup": duplicate_group,
            "role": role,
            "ranges": normalized_ranges,
        })
    for duplicate_group, splits in duplicate_splits.items():
        if "test" in splits and len(splits) != 1:
            raise LocalVideoPlanError(
                f"duplicateGroup {duplicate_group} crosses locked test and train/val splits",
            )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "datasetId": dataset_id,
        "classes": list(CLASS_NAMES),
        "sources": normalized_sources,
    }


def load_video_plan(path: Path | str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return validate_video_plan(json.load(handle))


def _iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if intersection <= 0:
        return 0.0
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def merge_proposals(
    base_proposals: Iterable[Proposal],
    custom_proposals: Iterable[Proposal],
    *,
    overlap_threshold: float = 0.35,
) -> list[Proposal]:
    """Merge proposals without creating a semantic truck/reach alias.

    A dedicated reach proposal can suppress an overlapping generic truck box
    only in this annotation-assistance output. It never changes a runtime
    detection and every result still requires review.
    """
    if not math.isfinite(overlap_threshold) or not 0 <= overlap_threshold <= 1:
        raise ValueError("overlap_threshold must be in [0, 1]")
    custom = [item for item in custom_proposals if item.class_name in CLASS_TO_ID]
    merged = [
        item for item in base_proposals
        if item.class_name in CLASS_TO_ID
        and not (
            item.class_name == "truck"
            and any(candidate.class_name == "reach_stacker" and _iou(item.xyxy, candidate.xyxy) >= overlap_threshold for candidate in custom)
        )
    ]
    merged.extend(custom)
    return sorted(merged, key=lambda item: (CLASS_TO_ID[item.class_name], item.xyxy, -item.confidence))


def _target_frames(source: Mapping[str, Any], fps: float, frame_count: int) -> dict[int, tuple[int, str]]:
    duration_ms = math.ceil(frame_count * 1000.0 / fps)
    targets: dict[int, tuple[int, str]] = {}
    for value in source["ranges"]:
        end_ms = min(value["endMs"], duration_ms)
        for requested_ms in range(value["startMs"], end_ms, value["intervalMs"]):
            frame_index = min(frame_count - 1, max(0, round(requested_ms * fps / 1000.0)))
            targets[frame_index] = (requested_ms, value["split"])
    return targets


def _normalized_yolo_line(proposal: Proposal, width: int, height: int) -> str | None:
    x1, y1, x2, y2 = proposal.xyxy
    x1 = min(float(width), max(0.0, x1))
    x2 = min(float(width), max(0.0, x2))
    y1 = min(float(height), max(0.0, y1))
    y2 = min(float(height), max(0.0, y2))
    if x2 <= x1 or y2 <= y1 or proposal.class_name not in CLASS_TO_ID:
        return None
    center_x = ((x1 + x2) / 2.0) / width
    center_y = ((y1 + y2) / 2.0) / height
    box_width = (x2 - x1) / width
    box_height = (y2 - y1) / height
    return f"{CLASS_TO_ID[proposal.class_name]} {center_x:.6f} {center_y:.6f} {box_width:.6f} {box_height:.6f}"


class UltralyticsProposalPredictor:
    """Generate deliberately permissive proposals for later human review."""

    _BASE_NAMES = frozenset({"person", "bicycle", "car", "motorcycle", "truck"})

    def __init__(
        self,
        base_model_path: Path | str,
        reach_model_path: Path | str,
        *,
        device: str = "0",
        imgsz: int = 768,
        base_confidence: float = 0.25,
        reach_confidence: float = 0.25,
    ) -> None:
        from ultralytics import YOLO

        self._base = YOLO(str(base_model_path))
        self._reach = YOLO(str(reach_model_path))
        self._device = device
        self._imgsz = imgsz
        self._base_confidence = base_confidence
        self._reach_confidence = reach_confidence

    @staticmethod
    def _items(result: Any, names: Mapping[int, str], source: str, *, force_class: str | None = None) -> list[Proposal]:
        boxes = getattr(result, "boxes", None)
        if boxes is None or boxes.xyxy is None:
            return []
        proposals: list[Proposal] = []
        for index in range(len(boxes)):
            raw_name = names.get(int(boxes.cls[index].item()), "")
            class_name = force_class or str(raw_name).strip().lower().replace(" ", "_")
            if class_name not in CLASS_TO_ID:
                continue
            xyxy = tuple(float(value) for value in boxes.xyxy[index].tolist())
            proposals.append(Proposal(class_name, float(boxes.conf[index].item()), xyxy, source))
        return proposals

    def __call__(self, frame: np.ndarray, _source_id: str, _timestamp_ms: int) -> list[Proposal]:
        precision = 16 if self._device.lower() != "cpu" else None
        base_result = self._base.predict(
            frame,
            imgsz=self._imgsz,
            conf=self._base_confidence,
            classes=[0, 1, 2, 3, 7],
            device=self._device,
            quantize=precision,
            verbose=False,
        )[0]
        reach_result = self._reach.predict(
            frame,
            imgsz=self._imgsz,
            conf=self._reach_confidence,
            device=self._device,
            quantize=precision,
            verbose=False,
        )[0]
        base = [item for item in self._items(base_result, self._base.names, "COCO") if item.class_name in self._BASE_NAMES]
        reach = self._items(reach_result, self._reach.names, "CUSTOM", force_class="reach_stacker")
        return merge_proposals(base, reach)


def build_annotation_package(
    plan_path: Path | str,
    video_root: Path | str,
    output_directory: Path | str,
    *,
    predictor: Predictor,
    output_width: int = 1280,
    output_height: int = 720,
    jpeg_quality: int = 92,
    dhash_distance_threshold: int = 2,
    dhash_window_ms: int = 1500,
) -> dict[str, object]:
    """Extract frames and write pending YOLO proposals plus a portable manifest."""
    plan = load_video_plan(plan_path)
    root = Path(video_root)
    output = Path(output_directory)
    if not root.is_dir():
        raise FileNotFoundError(root)
    if output_width <= 0 or output_height <= 0:
        raise ValueError("output dimensions must be positive")
    if not 1 <= jpeg_quality <= 100:
        raise ValueError("jpeg_quality must be in [1, 100]")
    if not 0 <= dhash_distance_threshold <= 64 or dhash_window_ms < 0:
        raise ValueError("invalid dHash dedupe settings")
    for split in sorted(SPLITS):
        (output / "images" / split).mkdir(parents=True, exist_ok=True)
        (output / "labels" / split).mkdir(parents=True, exist_ok=True)

    records: list[dict[str, object]] = []
    source_records: list[dict[str, object]] = []
    split_counts = {split: 0 for split in SPLITS}
    proposal_counts = {class_name: 0 for class_name in CLASS_NAMES}
    exact_hashes: set[str] = set()
    for source in plan["sources"]:
        source_path = root / source["fileName"]
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        capture = cv2.VideoCapture(str(source_path))
        if not capture.isOpened():
            capture.release()
            raise RuntimeError(f"cannot open video: {source['fileName']}")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not math.isfinite(fps) or fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
            capture.release()
            raise RuntimeError(f"invalid video metadata: {source['fileName']}")
        targets = _target_frames(source, fps, frame_count)
        recent_hashes: list[tuple[int, str]] = []
        accepted = 0
        frame_index = 0
        try:
            while targets and frame_index < frame_count:
                ok = capture.grab()
                if not ok:
                    break
                target = targets.pop(frame_index, None)
                if target is None:
                    frame_index += 1
                    continue
                ok, frame = capture.retrieve()
                if not ok:
                    raise RuntimeError(f"failed to decode {source['fileName']} frame {frame_index}")
                requested_ms, split = target
                actual_ms = round(frame_index * 1000.0 / fps)
                resized = cv2.resize(frame, (output_width, output_height), interpolation=cv2.INTER_AREA)
                perceptual_hash = difference_hash(resized)
                recent_hashes = [(timestamp, digest) for timestamp, digest in recent_hashes if actual_ms - timestamp <= dhash_window_ms]
                if any(hash_distance(perceptual_hash, digest) <= dhash_distance_threshold for _timestamp, digest in recent_hashes):
                    frame_index += 1
                    continue
                encoded_ok, encoded = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
                if not encoded_ok:
                    raise RuntimeError(f"failed to encode {source['fileName']} frame {frame_index}")
                payload = encoded.tobytes()
                sha256 = hashlib.sha256(payload).hexdigest()
                if sha256 in exact_hashes:
                    frame_index += 1
                    continue
                proposals = predictor(resized, source["sourceId"], actual_ms)
                label_lines = [line for item in proposals if (line := _normalized_yolo_line(item, output_width, output_height)) is not None]
                frame_id = f"{source['sourceId'].lower()}-{actual_ms:09d}"
                image_relative = f"images/{split}/{frame_id}.jpg"
                label_relative = f"labels/{split}/{frame_id}.txt"
                (output / image_relative).write_bytes(payload)
                (output / label_relative).write_text("\n".join(label_lines) + ("\n" if label_lines else ""), encoding="utf-8")
                for proposal in proposals:
                    if proposal.class_name in proposal_counts:
                        proposal_counts[proposal.class_name] += 1
                records.append({
                    "frameId": frame_id,
                    "sourceId": source["sourceId"],
                    "duplicateGroup": source["duplicateGroup"],
                    "role": source["role"],
                    "timestampMs": actual_ms,
                    "requestedTimestampMs": requested_ms,
                    "split": split,
                    "imagePath": image_relative,
                    "labelsPath": label_relative,
                    "sha256": sha256,
                    "perceptualHash": perceptual_hash,
                    "proposalCount": len(label_lines),
                    "reviewStatus": "PENDING_REVIEW",
                })
                recent_hashes.append((actual_ms, perceptual_hash))
                exact_hashes.add(sha256)
                split_counts[split] += 1
                accepted += 1
                frame_index += 1
        finally:
            capture.release()
        source_records.append({
            "sourceId": source["sourceId"],
            "sourceFile": source["fileName"],
            "duplicateGroup": source["duplicateGroup"],
            "role": source["role"],
            "fps": round(fps, 6),
            "frameCount": frame_count,
            "width": width,
            "height": height,
            "acceptedFrames": accepted,
            "ranges": source["ranges"],
        })

    records.sort(key=lambda item: (str(item["sourceId"]), int(item["timestampMs"])))
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "datasetId": plan["datasetId"],
        "classes": list(CLASS_NAMES),
        "reviewStatus": "PENDING_REVIEW",
        "proposalWarning": "Model-assisted proposals are not ground truth. Review every box and every empty frame.",
        "sources": source_records,
        "frames": records,
    }
    (output / "annotation-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (output / "review.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "frameId", "sourceId", "timestampMs", "split", "role", "imagePath",
            "labelsPath", "proposalCount", "reviewStatus", "reviewerNotes",
        ])
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key, "") for key in writer.fieldnames})
    write_dataset_index_files(output, records, CLASS_NAMES)
    summary: dict[str, object] = {
        "datasetId": plan["datasetId"],
        "frameCount": len(records),
        "splitCounts": {key: split_counts[key] for key in sorted(split_counts)},
        "proposalCounts": proposal_counts,
        "sourceCount": len(source_records),
        "reviewStatus": "PENDING_REVIEW",
    }
    (output / "build-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_reviewed_label_file(path: Path, frame_id: str) -> tuple[int, dict[str, int]]:
    if not path.is_file():
        raise LocalVideoPlanError(f"missing reviewed label file for {frame_id}")
    counts = {name: 0 for name in CLASS_NAMES}
    box_count = 0
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split()
        try:
            if len(fields) != 5:
                raise ValueError("expected five YOLO fields")
            class_id = int(fields[0])
            if not 0 <= class_id < len(CLASS_NAMES):
                raise ValueError(f"unknown class id {class_id}")
            center_x, center_y, width, height = (float(value) for value in fields[1:])
            if not all(math.isfinite(value) for value in (center_x, center_y, width, height)):
                raise ValueError("box coordinates must be finite")
            if width <= 0 or height <= 0:
                raise ValueError("box dimensions must be positive")
            left, top = center_x - width / 2.0, center_y - height / 2.0
            right, bottom = center_x + width / 2.0, center_y + height / 2.0
            if left < -1e-6 or top < -1e-6 or right > 1.000001 or bottom > 1.000001:
                raise ValueError("box falls outside normalized image bounds")
        except ValueError as error:
            raise LocalVideoPlanError(f"{path.name}:{line_number}: {error}") from error
        counts[CLASS_NAMES[class_id]] += 1
        box_count += 1
    return box_count, counts


def _reviewed_frame_ids(review_csv: Path) -> set[str]:
    if not review_csv.is_file():
        raise LocalVideoPlanError("review.csv is missing")
    with review_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    reviewed: set[str] = set()
    seen: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        frame_id = (row.get("frameId") or "").strip()
        if not frame_id or frame_id in seen:
            raise LocalVideoPlanError(f"review.csv row {row_number} has a missing or duplicate frameId")
        seen.add(frame_id)
        status = (row.get("reviewStatus") or "").strip().upper()
        if status == "REVIEWED":
            reviewed.add(frame_id)
        elif status != "PENDING_REVIEW":
            raise LocalVideoPlanError(f"review.csv row {row_number} has invalid reviewStatus {status!r}")
    return reviewed


def finalize_reviewed_package(
    original_package: Path | str,
    reviewed_yolo_directory: Path | str,
    snapshots_directory: Path | str,
) -> Path:
    """Freeze a fully reviewed package into a content-addressed snapshot.

    The reviewed directory may be a CVAT Ultralytics export extracted over a
    copy of the original package. Images must remain byte-identical; only YOLO
    label files and review statuses may change.
    """
    original = Path(original_package).resolve()
    reviewed = Path(reviewed_yolo_directory).resolve()
    snapshots = Path(snapshots_directory).resolve()
    manifest_path = original / "annotation-manifest.json"
    if not manifest_path.is_file():
        raise LocalVideoPlanError("annotation-manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != SCHEMA_VERSION or tuple(manifest.get("classes", ())) != CLASS_NAMES:
        raise LocalVideoPlanError("annotation manifest schema/classes do not match this training profile")
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise LocalVideoPlanError("annotation manifest has no frames")
    reviewed_ids = _reviewed_frame_ids(reviewed / "review.csv")
    expected_ids = {str(frame.get("frameId") or "") for frame in frames if isinstance(frame, Mapping)}
    pending = sorted(expected_ids - reviewed_ids)
    unknown = sorted(reviewed_ids - expected_ids)
    if unknown:
        raise LocalVideoPlanError(f"review.csv contains unknown frame IDs: {unknown[:3]}")
    if pending:
        raise LocalVideoPlanError(f"{len(pending)} frames remain PENDING_REVIEW; first: {pending[0]}")

    split_hashes: dict[str, set[str]] = {split: set() for split in SPLITS}
    per_class = {name: 0 for name in CLASS_NAMES}
    negative_frames = 0
    normalized_frames: list[dict[str, object]] = []
    content_parts: list[str] = []
    for index, raw_frame in enumerate(frames):
        frame = _object(raw_frame, f"frames[{index}]")
        frame_id = str(frame.get("frameId") or "")
        split = frame.get("split")
        if split not in SPLITS:
            raise LocalVideoPlanError(f"frame {frame_id} has invalid split")
        image_relative = frame.get("imagePath")
        label_relative = frame.get("labelsPath")
        for value, field in ((image_relative, "imagePath"), (label_relative, "labelsPath")):
            if not isinstance(value, str) or PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts or "\\" in value or ":" in value:
                raise LocalVideoPlanError(f"frame {frame_id} has unsafe {field}")
        image_path = reviewed / str(image_relative)
        label_path = reviewed / str(label_relative)
        if not image_path.is_file():
            raise LocalVideoPlanError(f"missing reviewed image for {frame_id}")
        image_hash = _sha256_file(image_path)
        if image_hash != frame.get("sha256"):
            raise LocalVideoPlanError(f"image hash changed for {frame_id}")
        if any(image_hash in hashes for other_split, hashes in split_hashes.items() if other_split != split):
            raise LocalVideoPlanError(f"image hash leaks across splits for {frame_id}")
        split_hashes[str(split)].add(image_hash)
        box_count, counts = _validate_reviewed_label_file(label_path, frame_id)
        if box_count == 0:
            negative_frames += 1
        for class_name, count in counts.items():
            per_class[class_name] += count
        label_hash = _sha256_file(label_path)
        content_parts.append(f"{frame_id}\0{split}\0{image_hash}\0{label_hash}")
        normalized_frames.append({
            **dict(frame),
            "reviewStatus": "REVIEWED",
            "proposalCount": None,
            "boxCount": box_count,
            "labelsSha256": label_hash,
        })
    content_hash = hashlib.sha256("\n".join(sorted(content_parts)).encode("utf-8")).hexdigest()
    safe_dataset_id = re.sub(r"[^a-z0-9-]+", "-", str(manifest["datasetId"]).lower()).strip("-")
    target = snapshots / f"{safe_dataset_id}-{content_hash[:12]}"
    if target.exists():
        existing_manifest = target / "manifest.json"
        if existing_manifest.is_file() and json.loads(existing_manifest.read_text(encoding="utf-8")).get("contentHash") == content_hash:
            return target
        raise FileExistsError(f"snapshot target already exists with different content: {target}")
    snapshots.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=str(snapshots)))
    try:
        shutil.copy2(reviewed / "data.yaml", temporary / "data.yaml")
        shutil.copy2(reviewed / "review.csv", temporary / "review.csv")
        for split in sorted(SPLITS):
            shutil.copy2(reviewed / f"{split}.txt", temporary / f"{split}.txt")
        for frame in normalized_frames:
            for key in ("imagePath", "labelsPath"):
                relative = str(frame[key])
                destination = temporary / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(reviewed / relative, destination)
        final_manifest = {
            "schemaVersion": 3,
            "datasetKind": "LOCAL_VIDEO_REVIEWED",
            "datasetId": manifest["datasetId"],
            "contentHash": content_hash,
            "reviewStatus": "REVIEWED",
            "classes": list(CLASS_NAMES),
            "sources": manifest.get("sources", []),
            "frames": normalized_frames,
            "summary": {
                "frameCount": len(normalized_frames),
                "negativeFrameCount": negative_frames,
                "perClass": per_class,
            },
        }
        (temporary / "manifest.json").write_text(
            json.dumps(final_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target


def repartition_reviewed_snapshot(
    reviewed_snapshot: Path | str,
    output_root: Path | str,
    *,
    dataset_id: str,
    source_policies: Mapping[str, Mapping[str, object]],
) -> Path:
    """Create a new immutable active-learning split from reviewed annotations.

    This operation never changes labels or images. It is intended for a failed
    locked-test iteration where an earlier time block is promoted to training
    and a later, still-untouched time block becomes the next locked test.
    Every changed source must provide complete, non-overlapping time ranges.
    """
    source = Path(reviewed_snapshot).resolve()
    manifest_path = source / "manifest.json"
    if not manifest_path.is_file():
        raise LocalVideoPlanError("reviewed snapshot manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("schemaVersion") != 3
        or manifest.get("datasetKind") != "LOCAL_VIDEO_REVIEWED"
        or manifest.get("reviewStatus") != "REVIEWED"
        or manifest.get("classes") != list(CLASS_NAMES)
    ):
        raise LocalVideoPlanError("repartition requires an exact REVIEWED schema-v3 snapshot")
    if PORTABLE_ID.fullmatch(dataset_id) is None:
        raise LocalVideoPlanError("repartition dataset_id is invalid")
    known_sources = {str(item.get("sourceId") or "") for item in manifest.get("sources", [])}
    unknown_sources = set(source_policies).difference(known_sources)
    if unknown_sources:
        raise LocalVideoPlanError(f"repartition contains unknown sourceId: {sorted(unknown_sources)[0]}")

    normalized_policies: dict[str, dict[str, object]] = {}
    for source_id, raw_policy in source_policies.items():
        raw_ranges = raw_policy.get("ranges")
        if not isinstance(raw_ranges, list) or not raw_ranges:
            raise LocalVideoPlanError(f"repartition policy for {source_id} requires ranges")
        ranges: list[dict[str, object]] = []
        for index, raw_range in enumerate(raw_ranges):
            if not isinstance(raw_range, Mapping):
                raise LocalVideoPlanError(f"repartition range {source_id}[{index}] is invalid")
            try:
                start_ms = int(raw_range["startMs"])
                end_ms = int(raw_range["endMs"])
                interval_ms = int(raw_range["intervalMs"])
            except (KeyError, TypeError, ValueError) as error:
                raise LocalVideoPlanError(f"repartition range {source_id}[{index}] is invalid") from error
            split = str(raw_range.get("split") or "")
            if start_ms < 0 or end_ms <= start_ms or interval_ms <= 0 or split not in SPLITS:
                raise LocalVideoPlanError(f"repartition range {source_id}[{index}] is invalid")
            ranges.append({
                "startMs": start_ms,
                "endMs": end_ms,
                "split": split,
                "intervalMs": interval_ms,
            })
        ordered = sorted(ranges, key=lambda item: int(item["startMs"]))
        if any(int(second["startMs"]) < int(first["endMs"]) for first, second in zip(ordered, ordered[1:])):
            raise LocalVideoPlanError(f"repartition ranges overlap for {source_id}")
        role = str(raw_policy.get("role") or "")
        if role and role not in ROLES:
            raise LocalVideoPlanError(f"repartition role is invalid for {source_id}")
        normalized_policies[source_id] = {"ranges": ordered, "role": role or None}

    normalized_frames: list[dict[str, object]] = []
    content_parts: list[str] = []
    split_hashes: dict[str, set[str]] = {split: set() for split in SPLITS}
    paths_by_frame: dict[str, tuple[str, str, str]] = {}
    split_counts = {split: 0 for split in SPLITS}
    for index, raw_frame in enumerate(manifest.get("frames", [])):
        frame = _object(raw_frame, f"frames[{index}]")
        frame_id = str(frame.get("frameId") or "")
        source_id = str(frame.get("sourceId") or "")
        split = str(frame.get("split") or "")
        role = str(frame.get("role") or "")
        policy = normalized_policies.get(source_id)
        if policy is not None:
            timestamp_ms = int(frame.get("requestedTimestampMs", frame.get("timestampMs", 0)) or 0)
            matching = [
                item for item in policy["ranges"]  # type: ignore[index]
                if int(item["startMs"]) <= timestamp_ms < int(item["endMs"])
            ]
            if len(matching) != 1:
                raise LocalVideoPlanError(f"repartition ranges do not cover frame {frame_id}")
            split = str(matching[0]["split"])
            role_override = policy.get("role")
            if isinstance(role_override, str) and role_override:
                role = role_override
        if split not in SPLITS:
            raise LocalVideoPlanError(f"frame {frame_id} has invalid repartition split")

        original_image = source / str(frame.get("imagePath") or "")
        original_label = source / str(frame.get("labelsPath") or "")
        if not original_image.is_file() or not original_label.is_file():
            raise LocalVideoPlanError(f"repartition source files are missing for {frame_id}")
        image_hash = _sha256_file(original_image)
        label_hash = _sha256_file(original_label)
        if image_hash != frame.get("sha256") or label_hash != frame.get("labelsSha256"):
            raise LocalVideoPlanError(f"repartition checksum mismatch for {frame_id}")
        if any(image_hash in hashes for other_split, hashes in split_hashes.items() if other_split != split):
            raise LocalVideoPlanError(f"repartition creates exact image leakage for {frame_id}")
        split_hashes[split].add(image_hash)
        image_relative = f"images/{split}/{original_image.name}"
        label_relative = f"labels/{split}/{original_label.name}"
        normalized_frames.append({
            **dict(frame),
            "split": split,
            "role": role,
            "imagePath": image_relative,
            "labelsPath": label_relative,
        })
        paths_by_frame[frame_id] = (split, image_relative, label_relative)
        split_counts[split] += 1
        content_parts.append(f"{frame_id}\0{split}\0{image_hash}\0{label_hash}")

    content_hash = hashlib.sha256("\n".join(sorted(content_parts)).encode("utf-8")).hexdigest()
    safe_dataset_id = re.sub(r"[^a-z0-9-]+", "-", dataset_id.lower()).strip("-")
    target = Path(output_root).resolve() / f"{safe_dataset_id}-{content_hash[:12]}"
    if target.exists():
        existing = target / "manifest.json"
        if existing.is_file() and json.loads(existing.read_text(encoding="utf-8")).get("contentHash") == content_hash:
            return target
        raise FileExistsError(f"repartition target already exists with different content: {target}")

    source_records: list[dict[str, object]] = []
    for raw_source_record in manifest.get("sources", []):
        source_record = dict(_object(raw_source_record, "sources[]"))
        source_id = str(source_record.get("sourceId") or "")
        policy = normalized_policies.get(source_id)
        if policy is not None:
            source_record["ranges"] = policy["ranges"]
            if policy.get("role"):
                source_record["role"] = policy["role"]
        source_record["acceptedFrames"] = sum(1 for frame in normalized_frames if frame["sourceId"] == source_id)
        source_records.append(source_record)

    output_root_path = Path(output_root).resolve()
    output_root_path.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=str(output_root_path)))
    try:
        for frame in normalized_frames:
            frame_id = str(frame["frameId"])
            original_frame = next(item for item in manifest["frames"] if item["frameId"] == frame_id)
            for original_key, new_key in (("imagePath", "imagePath"), ("labelsPath", "labelsPath")):
                destination = temporary / str(frame[new_key])
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / str(original_frame[original_key]), destination)

        review_rows: list[dict[str, str]] = []
        with (source / "review.csv").open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            for row in reader:
                split, image_relative, label_relative = paths_by_frame[str(row["frameId"])]
                row.update({"split": split, "imagePath": image_relative, "labelsPath": label_relative})
                review_rows.append(row)
        with (temporary / "review.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(review_rows)
        write_dataset_index_files(temporary, normalized_frames, CLASS_NAMES)
        final_manifest = {
            **manifest,
            "datasetId": dataset_id,
            "contentHash": content_hash,
            "parentContentHash": manifest.get("contentHash"),
            "sources": source_records,
            "frames": normalized_frames,
            "summary": {**dict(manifest.get("summary") or {}), "splitCounts": split_counts},
        }
        (temporary / "manifest.json").write_text(
            json.dumps(final_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target


def export_reach_stacker_supplemental_snapshot(
    reviewed_snapshot: Path | str,
    output_root: Path | str,
) -> Path:
    """Project a reviewed multi-class snapshot into a one-class custom dataset.

    The pretrained COCO detector remains responsible for people and common
    vehicles.  Every reviewed frame without a reach stacker becomes an
    explicit hard negative, including frames containing trucks, forklifts,
    containers, and empty yard backgrounds.  This avoids rebuilding the COCO
    head and preserves the fast base/custom rollback architecture.
    """
    source = Path(reviewed_snapshot).resolve()
    manifest_path = source / "manifest.json"
    if not manifest_path.is_file():
        raise LocalVideoPlanError("reviewed snapshot manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("schemaVersion") != 3
        or manifest.get("datasetKind") != "LOCAL_VIDEO_REVIEWED"
        or manifest.get("reviewStatus") != "REVIEWED"
        or manifest.get("classes") != list(CLASS_NAMES)
    ):
        raise LocalVideoPlanError("supplemental export requires an exact REVIEWED local-video snapshot")
    input_hash = manifest.get("contentHash")
    if not isinstance(input_hash, str) or re.fullmatch(r"[0-9a-f]{64}", input_hash) is None:
        raise LocalVideoPlanError("reviewed snapshot content hash is invalid")
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise LocalVideoPlanError("reviewed snapshot has no frames")

    samples: list[dict[str, object]] = []
    negatives: list[dict[str, object]] = []
    media_sources: dict[str, Path] = {}
    media_extensions: dict[str, str] = {}
    reach_class_id = CLASS_TO_ID["reach_stacker"]
    for index, raw_frame in enumerate(frames):
        frame = _object(raw_frame, f"frames[{index}]")
        frame_id = str(frame.get("frameId") or "")
        source_id = str(frame.get("sourceId") or "")
        split = str(frame.get("split") or "")
        if not frame_id or not source_id or split not in SPLITS:
            raise LocalVideoPlanError(f"frames[{index}] has invalid identity/provenance")
        image_relative = str(frame.get("imagePath") or "")
        label_relative = str(frame.get("labelsPath") or "")
        image_path = source / image_relative
        label_path = source / label_relative
        if not image_path.is_file() or not label_path.is_file():
            raise LocalVideoPlanError(f"reviewed media/label is missing for {frame_id}")
        media_hash = str(frame.get("sha256") or "").casefold()
        if re.fullmatch(r"[0-9a-f]{64}", media_hash) is None or _sha256_file(image_path) != media_hash:
            raise LocalVideoPlanError(f"reviewed media checksum mismatch for {frame_id}")
        media_sources.setdefault(media_hash, image_path)
        media_extensions.setdefault(media_hash, image_path.suffix.casefold() or ".jpg")
        media_path = f"media/{media_hash}{media_extensions[media_hash]}"
        # A physical video may intentionally contribute disjoint train/val time
        # blocks.  Keep the parent source explicit while giving each locked
        # block a distinct source identity for schema-v2 split validation.
        block_source_id = f"local:{source_id}:{split}"
        reach_boxes: list[dict[str, float]] = []
        reason_classes: set[str] = set()
        for line_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
            fields = line.split()
            if not fields:
                continue
            if len(fields) != 5:
                raise LocalVideoPlanError(f"invalid YOLO row for {frame_id}:{line_number}")
            try:
                class_id = int(fields[0])
                center_x, center_y, width, height = (float(value) for value in fields[1:])
            except ValueError as error:
                raise LocalVideoPlanError(f"invalid YOLO value for {frame_id}:{line_number}") from error
            if not 0 <= class_id < len(CLASS_NAMES) or not all(
                math.isfinite(value) for value in (center_x, center_y, width, height)
            ):
                raise LocalVideoPlanError(f"invalid YOLO class/value for {frame_id}:{line_number}")
            left, top = center_x - width / 2, center_y - height / 2
            epsilon = 1e-6
            if (
                width <= 0
                or height <= 0
                or left < -epsilon
                or top < -epsilon
                or left + width > 1 + epsilon
                or top + height > 1 + epsilon
            ):
                raise LocalVideoPlanError(f"YOLO box is outside the image for {frame_id}:{line_number}")
            if class_id == reach_class_id:
                reach_boxes.append({
                    "x": round(max(0.0, left), 8),
                    "y": round(max(0.0, top), 8),
                    "w": round(min(width, 1.0), 8),
                    "h": round(min(height, 1.0), 8),
                })
            else:
                reason_classes.add(CLASS_NAMES[class_id])
        timestamp_ms = int(frame.get("timestampMs") or 0)
        if reach_boxes:
            for box_index, bbox in enumerate(reach_boxes):
                samples.append({
                    "sampleId": f"local-{frame_id}-{box_index}",
                    "label": REACH_STACKER_LABEL,
                    "baseClass": "reach_stacker",
                    "sourceId": block_source_id,
                    "parentSourceId": source_id,
                    "mediaKind": "IMAGE",
                    "frameTimestampMs": timestamp_ms,
                    "bbox": bbox,
                    "mediaPath": media_path,
                    "mediaSha256": media_hash,
                    "split": split,
                })
        else:
            negatives.append({
                "negativeId": f"local-negative-{frame_id}",
                "sourceId": block_source_id,
                "parentSourceId": source_id,
                "mediaKind": "IMAGE",
                "frameTimestampMs": timestamp_ms,
                "mediaPath": media_path,
                "mediaSha256": media_hash,
                "split": split,
                "reasonClasses": sorted(reason_classes) or ["empty_yard"],
            })

    snapshot = {
        "schemaVersion": 2,
        "profile": "REACH_STACKER_AUXILIARY_V1",
        "requiredClasses": [{"label": REACH_STACKER_LABEL, "baseClass": "reach_stacker"}],
        "samples": sorted(samples, key=lambda item: str(item["sampleId"])),
        "negativeMedia": sorted(negatives, key=lambda item: str(item["negativeId"])),
        "origin": {
            "kind": "reviewed_local_video_projection",
            "inputContentHash": input_hash,
            "policy": "reach_stacker_positive_all_other_reviewed_frames_negative",
        },
    }
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    destination = Path(output_root).resolve() / content_hash
    if destination.exists():
        existing = destination / "manifest.json"
        if existing.is_file() and json.loads(existing.read_text(encoding="utf-8")).get("contentHash") == content_hash:
            return destination
        raise FileExistsError(f"supplemental snapshot target conflicts: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{content_hash[:12]}-", dir=str(destination.parent)))
    try:
        media_directory = temporary / "media"
        media_directory.mkdir()
        referenced_hashes = {
            str(item["mediaSha256"])
            for item in [*samples, *negatives]
        }
        for media_hash in sorted(referenced_hashes):
            shutil.copy2(
                media_sources[media_hash],
                media_directory / f"{media_hash}{media_extensions[media_hash]}",
            )
        (temporary / "manifest.json").write_text(
            json.dumps({**snapshot, "contentHash": content_hash}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--video-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--base-model", required=True, type=Path)
    parser.add_argument("--reach-model", required=True, type=Path)
    parser.add_argument("--device", default="0")
    parser.add_argument("--imgsz", type=int, default=768)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args(argv)
    predictor = UltralyticsProposalPredictor(
        args.base_model,
        args.reach_model,
        device=args.device,
        imgsz=args.imgsz,
    )
    summary = build_annotation_package(
        args.plan,
        args.video_root,
        args.output,
        predictor=predictor,
        output_width=args.width,
        output_height=args.height,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
