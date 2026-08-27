"""Materialize immutable Node dataset snapshots into Ultralytics YOLO datasets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import cv2


def manifest_class_definitions(manifest: dict[str, Any]) -> list[dict[str, str]]:
    """Return the ordered label/base-class contract frozen into a snapshot.

    Profile exports carry ``requiredClasses`` so training/evaluation cannot
    silently fall back to an obsolete hard-coded class list. Older generic
    snapshots remain supported by deriving the same contract from samples.
    """
    raw_required = manifest.get("requiredClasses")
    raw_definitions = raw_required if isinstance(raw_required, list) and raw_required else manifest.get("samples", [])
    if not isinstance(raw_definitions, list) or not raw_definitions:
        raise ValueError("Training manifest must define at least one class")

    definitions: dict[str, str] = {}
    order: list[str] = []
    for item in raw_definitions:
        if not isinstance(item, dict):
            raise ValueError("Training class definitions must be objects")
        label = str(item.get("label") or "").strip()
        base_class = str(item.get("baseClass") or "").strip()
        if not label or not base_class:
            raise ValueError("Training class definitions require label and baseClass")
        existing = definitions.get(label)
        if existing is not None and existing != base_class:
            raise ValueError(f"Training label {label!r} maps to conflicting base classes")
        if existing is None:
            definitions[label] = base_class
            order.append(label)

    if not (isinstance(raw_required, list) and raw_required):
        order.sort()

    for sample in manifest.get("samples", []):
        if not isinstance(sample, dict):
            raise ValueError("Training samples must be objects")
        label = str(sample.get("label") or "").strip()
        base_class = str(sample.get("baseClass") or "").strip()
        if label not in definitions:
            raise ValueError(f"Training sample class {label!r} is not in requiredClasses")
        if definitions[label] != base_class:
            raise ValueError(f"Training sample {label!r} does not match its required baseClass")

    return [{"label": label, "baseClass": definitions[label]} for label in order]


def _frame(media: Path, kind: str, timestamp_ms: int | None):
    if kind == "IMAGE":
        return cv2.imread(str(media))
    capture = cv2.VideoCapture(str(media))
    capture.set(cv2.CAP_PROP_POS_MSEC, timestamp_ms or 0)
    ok, frame = capture.read()
    capture.release()
    return frame if ok else None


def _safe_snapshot_media(manifest_path: Path, relative_media_path: str) -> Path:
    snapshot_root = manifest_path.parent.resolve()
    media = (snapshot_root / relative_media_path).resolve()
    if media == snapshot_root or snapshot_root not in media.parents:
        raise ValueError("Manifest contains an unsafe media path")
    return media


def materialize(manifest_path: Path, output_root: Path) -> Path:
    """Write images/labels/data.yaml without reaching back to mutable user uploads.

    One imported image can have several YOLO boxes. Group annotations first so
    its generated label file preserves every object rather than overwriting
    earlier boxes for the same source image/frame.
    """
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 2:
        raise ValueError("Unsupported training manifest version")
    root = output_root / manifest_path.parent.name
    classes = [item["label"] for item in manifest_class_definitions(manifest)]
    class_index = {name: index for index, name in enumerate(classes)}
    allowed_splits = {"train", "val", "test"}
    media_splits: dict[tuple[str, str, int | None], str] = {}
    source_splits: dict[str, str] = {}
    grouped: dict[tuple[str, str, int | None, str], list[dict[str, Any]]] = {}

    for item in manifest["samples"]:
        split = str(item.get("split") or "")
        if split not in allowed_splits:
            raise ValueError(f"Unsupported training split: {split}")
        source_key = (str(item["mediaPath"]), str(item["mediaKind"]), item.get("frameTimestampMs"))
        previous_split = media_splits.setdefault(source_key, split)
        if previous_split != split:
            raise ValueError("One source image/frame cannot appear in multiple training splits")
        source_id = str(item.get("sourceId") or "").strip()
        if not source_id:
            raise ValueError("Training sample requires sourceId")
        previous_source_split = source_splits.setdefault(source_id, split)
        if previous_source_split != split:
            raise ValueError("One sourceId cannot appear in multiple training splits")
        grouped.setdefault((*source_key, split), []).append(item)

    negatives = manifest.get("negativeMedia", [])
    if not isinstance(negatives, list):
        raise ValueError("negativeMedia must be an array")
    negative_groups: list[tuple[str, str, int | None, str, dict[str, Any]]] = []
    negative_ids: set[str] = set()
    positive_media = {key[:3] for key in grouped}
    for item in negatives:
        if not isinstance(item, dict):
            raise ValueError("negativeMedia entries must be objects")
        split = str(item.get("split") or "")
        if split not in allowed_splits:
            raise ValueError(f"Unsupported training split: {split}")
        source_key = (str(item.get("mediaPath") or ""), str(item.get("mediaKind") or ""), item.get("frameTimestampMs"))
        if not source_key[0] or not source_key[1]:
            raise ValueError("Hard-negative media requires mediaPath and mediaKind")
        if source_key in positive_media:
            raise ValueError("One media/frame cannot be both positive and hard negative")
        previous_split = media_splits.setdefault(source_key, split)
        if previous_split != split:
            raise ValueError("One source image/frame cannot appear in multiple training splits")
        source_id = str(item.get("sourceId") or "").strip()
        if not source_id:
            raise ValueError("Hard-negative media requires sourceId")
        previous_source_split = source_splits.setdefault(source_id, split)
        if previous_source_split != split:
            raise ValueError("One sourceId cannot appear in multiple training splits")
        negative_id = str(item.get("negativeId") or "").strip()
        if not negative_id:
            raise ValueError("Hard-negative media requires negativeId")
        if negative_id in negative_ids:
            raise ValueError(f"Duplicate hard-negative item id: {negative_id}")
        negative_ids.add(negative_id)
        negative_groups.append((*source_key, split, item))

    present_splits = {key[3] for key in grouped} | {item[3] for item in negative_groups}
    for split in present_splits:
        (root / "images" / split).mkdir(parents=True, exist_ok=True)
        (root / "labels" / split).mkdir(parents=True, exist_ok=True)

    failures: list[dict[str, str]] = []
    for (relative_media_path, media_kind, timestamp_ms, split), items in grouped.items():
        media = _safe_snapshot_media(manifest_path, relative_media_path)
        frame = _frame(media, media_kind, timestamp_ms)
        if frame is None:
            failures.extend({"sampleId": item["sampleId"], "reason": "Cannot read media/frame"} for item in items)
            continue
        ordered_items = sorted(items, key=lambda item: str(item["sampleId"]))
        stem = str(ordered_items[0]["sampleId"])
        if len(ordered_items) > 1:
            source_ids = "|".join(str(item["sampleId"]) for item in ordered_items)
            stem = f"source-{hashlib.sha256(source_ids.encode('utf-8')).hexdigest()[:20]}"
        cv2.imwrite(str(root / "images" / split / f"{stem}.jpg"), frame)
        lines: list[str] = []
        for item in ordered_items:
            box = item["bbox"]
            x, y, w, h = (float(box[key]) for key in ("x", "y", "w", "h"))
            lines.append(f"{class_index[item['label']]} {x + w / 2:.6f} {y + h / 2:.6f} {w:.6f} {h:.6f}\n")
        (root / "labels" / split / f"{stem}.txt").write_text("".join(lines), encoding="utf-8")

    for relative_media_path, media_kind, timestamp_ms, split, item in negative_groups:
        media = _safe_snapshot_media(manifest_path, relative_media_path)
        frame = _frame(media, media_kind, timestamp_ms)
        if frame is None:
            failures.append({"sampleId": str(item["negativeId"]), "reason": "Cannot read hard-negative media/frame"})
            continue
        stem = str(item["negativeId"])
        image_path = root / "images" / split / f"{stem}.jpg"
        label_path = root / "labels" / split / f"{stem}.txt"
        # The input snapshot is immutable, so overwriting the deterministic
        # generated pair makes interrupted/retried jobs safely idempotent.
        cv2.imwrite(str(image_path), frame)
        label_path.write_text("", encoding="utf-8")

    test_path = "test: images/test\n" if "test" in present_splits else ""
    (root / "data.yaml").write_text(
        f"path: {root.resolve().as_posix()}\ntrain: images/train\nval: images/val\n" + test_path + "names:\n" + "\n".join(f"  {index}: {name}" for name, index in class_index.items()) + "\n",
        encoding="utf-8",
    )
    (root / "export-report.json").write_text(json.dumps({"failures": failures}, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        raise ValueError(f"Dataset export has {len(failures)} unreadable media/frame sample(s)")
    return root
