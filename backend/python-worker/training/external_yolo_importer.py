"""Import a local Roboflow/YOLO archive into an immutable training snapshot.

The user-supplied archive is treated as untrusted input.  This module never
trains in place from it: it validates paths and annotations, then writes a
content-addressed snapshot under ``backend/data/training/datasets``.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

EVENT_PREFIX = "SENTRIAI_EXTERNAL_DATASET "
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
DEFAULT_LABEL_MAP = {
    "stacker": {"label": "Xe nâng", "baseClass": "reach stacker"},
}


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"Unsafe archive entry: {name}")
    return path.as_posix()


def _read_entries(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    entries: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = _safe_name(info.filename)
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError(f"Archive links are not allowed: {name}")
        if name in entries:
            # Roboflow exports can contain an identical root data.yaml twice.
            # Accept only a byte-for-byte duplicate; ambiguous archive entries
            # with different contents remain unsafe.
            if archive.read(entries[name]) != archive.read(info):
                raise ValueError(f"Conflicting duplicate archive entry: {name}")
            continue
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Archive exceeds the 512 MiB uncompressed safety limit")
        entries[name] = info
    return entries


def _names(dataset_config: dict[str, Any]) -> dict[int, str]:
    raw_names = dataset_config.get("names")
    if isinstance(raw_names, list):
        names = {index: str(value).strip() for index, value in enumerate(raw_names)}
    elif isinstance(raw_names, dict):
        names = {int(index): str(value).strip() for index, value in raw_names.items()}
    else:
        raise ValueError("data.yaml must define class names")
    if not names or any(not value for value in names.values()):
        raise ValueError("data.yaml contains an empty class name")
    return names


def _number(value: str, context: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value in {context}") from exc


def _bbox(values: list[str], context: str) -> tuple[int, dict[str, float]]:
    if len(values) < 5:
        raise ValueError(f"Annotation has too few values in {context}")
    class_value = _number(values[0], context)
    if class_value < 0 or class_value != int(class_value):
        raise ValueError(f"Annotation class is invalid in {context}")
    class_id = int(class_value)
    coordinates = [_number(value, context) for value in values[1:]]
    if len(coordinates) == 4:
        center_x, center_y, width, height = coordinates
        x, y = center_x - width / 2, center_y - height / 2
    elif len(coordinates) >= 6 and len(coordinates) % 2 == 0:
        # The supplied Roboflow archive is YOLOv8 segmentation.  Preserve its
        # object-detection semantics by deriving the tight normalized bbox.
        xs, ys = coordinates[0::2], coordinates[1::2]
        x, y = min(xs), min(ys)
        width, height = max(xs) - x, max(ys) - y
    else:
        raise ValueError(f"Annotation is neither YOLO bbox nor polygon in {context}")
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < width <= 1 and 0 < height <= 1 and x + width <= 1 and y + height <= 1):
        raise ValueError(f"Annotation bbox is outside the normalized image in {context}")
    return class_id, {"x": round(x, 8), "y": round(y, 8), "w": round(width, 8), "h": round(height, 8)}


def _image_entries(entries: dict[str, zipfile.ZipInfo]) -> list[str]:
    images: list[str] = []
    for name in entries:
        parts = PurePosixPath(name).parts
        if len(parts) != 3 or parts[0] not in {"train", "valid", "test"} or parts[1] != "images":
            continue
        if PurePosixPath(name).suffix.casefold() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        images.append(name)
    if not images:
        raise ValueError("Archive contains no supported image files")
    return sorted(images)


def _label_path(image_path: str) -> str:
    image = PurePosixPath(image_path)
    return PurePosixPath(image.parts[0], "labels", f"{image.stem}.txt").as_posix()


def _write_atomic(path: Path, text: str) -> None:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False)
    try:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        Path(handle.name).replace(path)
    finally:
        if not handle.closed:
            handle.close()
        Path(handle.name).unlink(missing_ok=True)


def import_external_yolo_archive(archive_path: Path, output_root: Path) -> dict[str, Any]:
    """Validate one local YOLOv8 archive and return its immutable manifest data."""
    source = archive_path.resolve()
    if not source.is_file() or source.suffix.casefold() != ".zip":
        raise ValueError("External dataset must be an existing .zip archive")

    with zipfile.ZipFile(source) as archive:
        entries = _read_entries(archive)
        config_info = entries.get("data.yaml")
        if not config_info:
            raise ValueError("Archive must contain data.yaml at its root")
        try:
            config = yaml.safe_load(archive.read(config_info)) or {}
        except yaml.YAMLError as exc:
            raise ValueError("data.yaml is invalid") from exc
        if not isinstance(config, dict):
            raise ValueError("data.yaml must contain an object")
        names = _names(config)
        samples: list[dict[str, Any]] = []
        media_by_hash: dict[str, bytes] = {}

        for image_path in _image_entries(entries):
            label_path = _label_path(image_path)
            if label_path not in entries:
                raise ValueError(f"Image is missing annotation file: {image_path}")
            image_content = archive.read(entries[image_path])
            source_hash = _sha256_bytes(image_content)
            media_by_hash[source_hash] = image_content
            label_content = archive.read(entries[label_path]).decode("utf-8-sig")
            split = {"train": "train", "valid": "val", "test": "test"}[PurePosixPath(image_path).parts[0]]
            extension = PurePosixPath(image_path).suffix.casefold()
            for index, raw_line in enumerate(label_content.splitlines()):
                line = raw_line.strip()
                if not line:
                    continue
                class_id, box = _bbox(line.split(), f"{label_path}:{index + 1}")
                source_label = names.get(class_id)
                mapped = DEFAULT_LABEL_MAP.get(source_label.casefold() if source_label else "")
                if not mapped:
                    raise ValueError(f"Class '{source_label}' is not permitted for external bootstrap training")
                samples.append({
                    "sampleId": f"external-{source_hash[:20]}-{index}",
                    "label": mapped["label"],
                    "baseClass": mapped["baseClass"],
                    "sourceId": f"external:{source_hash}",
                    "mediaKind": "IMAGE",
                    "frameTimestampMs": None,
                    "bbox": box,
                    "mediaPath": f"media/{source_hash}{extension}",
                    "mediaSha256": source_hash,
                    "split": split,
                })

    if not samples:
        raise ValueError("Archive has no object annotations")
    snapshot = {"schemaVersion": 2, "samples": sorted(samples, key=lambda item: item["sampleId"])}
    content_hash = _sha256_bytes(_canonical_json(snapshot).encode("utf-8"))
    directory = output_root.resolve() / content_hash
    media_dir = directory / "media"
    directory.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(exist_ok=True)
    for source_hash, content in media_by_hash.items():
        matching = next(item for item in samples if item["mediaSha256"] == source_hash)
        target = directory / matching["mediaPath"]
        if target.is_file() and _sha256_bytes(target.read_bytes()) != source_hash:
            raise ValueError(f"Immutable media collision for {target.name}")
        if not target.exists():
            target.write_bytes(content)
    manifest = directory / "manifest.json"
    if manifest.is_file():
        existing = json.loads(manifest.read_text(encoding="utf-8"))
        if existing.get("contentHash") != content_hash:
            raise ValueError("Immutable dataset directory has conflicting manifest")
    else:
        _write_atomic(manifest, json.dumps({**snapshot, "contentHash": content_hash, "origin": {
            "kind": "external_yolo_archive", "archiveName": source.name, "sourceLabelMap": DEFAULT_LABEL_MAP,
        }}, ensure_ascii=False, indent=2))
    return {
        "contentHash": content_hash,
        "directory": str(directory),
        "manifestPath": str(manifest),
        "sampleCount": len(samples),
        "sourceCount": len(media_by_hash),
        "splits": {split: sum(1 for sample in samples if sample["split"] == split) for split in ("train", "val", "test")},
        "labels": sorted({sample["label"] for sample in samples}),
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: external_yolo_importer.py <archive-path> <datasets-root>")
    result = import_external_yolo_archive(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"{EVENT_PREFIX}{json.dumps(result, ensure_ascii=False)}", flush=True)
