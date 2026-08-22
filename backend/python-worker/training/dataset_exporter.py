"""Materialize immutable Node dataset snapshots into Ultralytics YOLO datasets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import cv2


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
    classes = sorted({item["label"] for item in manifest["samples"]})
    class_index = {name: index for index, name in enumerate(classes)}
    allowed_splits = {"train", "val", "test"}
    source_splits: dict[tuple[str, str, int | None], str] = {}
    grouped: dict[tuple[str, str, int | None, str], list[dict[str, Any]]] = {}

    for item in manifest["samples"]:
        split = str(item.get("split") or "")
        if split not in allowed_splits:
            raise ValueError(f"Unsupported training split: {split}")
        source_key = (str(item["mediaPath"]), str(item["mediaKind"]), item.get("frameTimestampMs"))
        previous_split = source_splits.setdefault(source_key, split)
        if previous_split != split:
            raise ValueError("One source image/frame cannot appear in multiple training splits")
        grouped.setdefault((*source_key, split), []).append(item)

    for split in {key[3] for key in grouped}:
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

    test_path = "test: images/test\n" if any(item["split"] == "test" for item in manifest["samples"]) else ""
    (root / "data.yaml").write_text(
        f"path: {root.resolve().as_posix()}\ntrain: images/train\nval: images/val\n" + test_path + "names:\n" + "\n".join(f"  {index}: {name}" for name, index in class_index.items()) + "\n",
        encoding="utf-8",
    )
    (root / "export-report.json").write_text(json.dumps({"failures": failures}, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        raise ValueError(f"Dataset export has {len(failures)} unreadable media/frame sample(s)")
    return root
