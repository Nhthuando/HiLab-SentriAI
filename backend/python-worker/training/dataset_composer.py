"""Compose immutable reach-stacker snapshots without mutating their sources."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

TARGET_LABEL = "Xe nâng container"
TARGET_BASE_CLASS = "reach_stacker"
ALLOWED_LABELS = frozenset({"xe nâng", "xe nâng container"})
ALLOWED_SPLITS = frozenset({"train", "val", "test"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_class(label: object, base_class: object) -> tuple[str, str]:
    normalized_label = str(label or "").strip().casefold()
    normalized_base = re.sub(r"[\s-]+", "_", str(base_class or "").strip().casefold())
    if normalized_label not in ALLOWED_LABELS or normalized_base != TARGET_BASE_CLASS:
        raise ValueError(f"Snapshot contains a non-reach-stacker class: {label!r} / {base_class!r}")
    return TARGET_LABEL, TARGET_BASE_CLASS


def _safe_media(manifest_path: Path, relative_path: object) -> Path:
    root = manifest_path.parent.resolve()
    media = (root / str(relative_path or "")).resolve()
    if media == root or root not in media.parents:
        raise ValueError("Snapshot contains an unsafe media path")
    if not media.is_file():
        raise FileNotFoundError(f"Snapshot media is missing: {media}")
    return media


def _atomic_copy(source: Path, target: Path) -> None:
    if target.is_file():
        if _sha256(target) == target.stem:
            return
        raise ValueError(f"Immutable media collision for {target.name}")
    handle = tempfile.NamedTemporaryFile("wb", dir=target.parent, delete=False)
    temporary = Path(handle.name)
    try:
        with source.open("rb") as reader, handle:
            shutil.copyfileobj(reader, handle, length=1024 * 1024)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def compose_snapshots(
    manifests: Iterable[Path],
    output_root: Path,
    *,
    excluded_parent_sources: Mapping[str, Iterable[str]] | None = None,
    excluded_media_hashes: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, object]:
    """Create one canonical, content-addressed reach-stacker snapshot."""
    manifest_paths = [Path(path).resolve() for path in manifests]
    if len(manifest_paths) < 2:
        raise ValueError("At least two snapshots are required for composition")

    samples: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []
    media_sources: dict[str, Path] = {}
    media_extensions: dict[str, str] = {}
    source_splits: dict[str, str] = {}
    media_splits: dict[str, str] = {}
    positive_keys: set[str] = set()
    negative_hashes: set[str] = set()
    input_ids: list[str] = []
    normalized_exclusions = {
        str(input_id): frozenset(str(source_id) for source_id in source_ids)
        for input_id, source_ids in (excluded_parent_sources or {}).items()
    }
    normalized_media_exclusions = {
        str(input_id): frozenset(str(media_hash).casefold() for media_hash in media_hashes)
        for input_id, media_hashes in (excluded_media_hashes or {}).items()
    }

    for manifest_path in manifest_paths:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schemaVersion") != 2:
            raise ValueError("Unsupported training manifest version")
        input_id = str(manifest.get("contentHash") or manifest_path.parent.name)
        input_ids.append(input_id)
        excluded_sources = normalized_exclusions.get(input_id, frozenset())
        excluded_hashes = normalized_media_exclusions.get(input_id, frozenset())
        raw_samples = manifest.get("samples")
        if not isinstance(raw_samples, list):
            raise ValueError("Training manifest samples must be an array")

        for raw in raw_samples:
            if not isinstance(raw, dict):
                raise ValueError("Training samples must be objects")
            parent_source_id = str(raw.get("parentSourceId") or raw.get("sourceId") or "").strip()
            if parent_source_id in excluded_sources:
                continue
            if str(raw.get("mediaSha256") or "").casefold() in excluded_hashes:
                continue
            label, base_class = _canonical_class(raw.get("label"), raw.get("baseClass"))
            split = str(raw.get("split") or "")
            source_id = str(raw.get("sourceId") or "").strip()
            if split not in ALLOWED_SPLITS or not source_id:
                raise ValueError("Training sample has invalid split or sourceId")
            previous = source_splits.setdefault(source_id, split)
            if previous != split:
                raise ValueError("One sourceId appears in multiple splits")
            media_hash = str(raw.get("mediaSha256") or "").casefold()
            if not re.fullmatch(r"[0-9a-f]{64}", media_hash):
                raise ValueError("Training sample has invalid mediaSha256")
            previous_media_split = media_splits.setdefault(media_hash, split)
            if previous_media_split != split:
                raise ValueError("One media hash appears in multiple splits")
            media = _safe_media(manifest_path, raw.get("mediaPath"))
            if _sha256(media) != media_hash:
                raise ValueError(f"Training media checksum mismatch: {media.name}")
            media_sources.setdefault(media_hash, media)
            media_extensions.setdefault(media_hash, media.suffix.casefold() or ".jpg")
            box = raw.get("bbox")
            if not isinstance(box, dict) or any(key not in box for key in ("x", "y", "w", "h")):
                raise ValueError("Training sample has invalid bbox")
            bbox = {key: float(box[key]) for key in ("x", "y", "w", "h")}
            dedupe_key = _canonical_json({"media": media_hash, "bbox": bbox, "split": split})
            if dedupe_key in positive_keys:
                continue
            positive_keys.add(dedupe_key)
            sample_id = f"composed-{hashlib.sha256(dedupe_key.encode('utf-8')).hexdigest()[:24]}"
            samples.append({
                **raw,
                "sampleId": sample_id,
                "label": label,
                "baseClass": base_class,
                "mediaPath": f"media/{media_hash}{media_extensions[media_hash]}",
                "mediaSha256": media_hash,
                "bbox": bbox,
            })

        raw_negatives = manifest.get("negativeMedia", [])
        if not isinstance(raw_negatives, list):
            raise ValueError("negativeMedia must be an array")
        for raw in raw_negatives:
            if not isinstance(raw, dict):
                raise ValueError("negativeMedia entries must be objects")
            parent_source_id = str(raw.get("parentSourceId") or raw.get("sourceId") or "").strip()
            if parent_source_id in excluded_sources:
                continue
            if str(raw.get("mediaSha256") or "").casefold() in excluded_hashes:
                continue
            split = str(raw.get("split") or "")
            source_id = str(raw.get("sourceId") or "").strip()
            if split not in ALLOWED_SPLITS or not source_id:
                raise ValueError("Hard-negative media has invalid split or sourceId")
            previous = source_splits.setdefault(source_id, split)
            if previous != split:
                raise ValueError("One sourceId appears in multiple splits")
            media_hash = str(raw.get("mediaSha256") or "").casefold()
            if not re.fullmatch(r"[0-9a-f]{64}", media_hash):
                raise ValueError("Hard-negative media has invalid mediaSha256")
            previous_media_split = media_splits.setdefault(media_hash, split)
            if previous_media_split != split:
                raise ValueError("One media hash appears in multiple splits")
            media = _safe_media(manifest_path, raw.get("mediaPath"))
            if _sha256(media) != media_hash:
                raise ValueError(f"Hard-negative media checksum mismatch: {media.name}")
            media_sources.setdefault(media_hash, media)
            media_extensions.setdefault(media_hash, media.suffix.casefold() or ".jpg")
            if media_hash in negative_hashes:
                continue
            negative_hashes.add(media_hash)
            negatives.append({
                **raw,
                "negativeId": f"composed-negative-{media_hash[:24]}",
                "mediaPath": f"media/{media_hash}{media_extensions[media_hash]}",
                "mediaSha256": media_hash,
            })

    positive_hashes = {str(sample["mediaSha256"]) for sample in samples}
    negatives = [item for item in negatives if str(item["mediaSha256"]) not in positive_hashes]
    origin: dict[str, object] = {"kind": "composed_snapshots", "inputs": input_ids}
    used_exclusions = {
        input_id: sorted(normalized_exclusions[input_id])
        for input_id in input_ids
        if normalized_exclusions.get(input_id)
    }
    if used_exclusions:
        origin["excludedParentSourceIds"] = used_exclusions
    used_media_exclusions = {
        input_id: sorted(normalized_media_exclusions[input_id])
        for input_id in input_ids
        if normalized_media_exclusions.get(input_id)
    }
    if used_media_exclusions:
        origin["excludedMediaSha256"] = used_media_exclusions
    snapshot = {
        "schemaVersion": 2,
        "profile": "REACH_STACKER_AUXILIARY_V1",
        "requiredClasses": [{"label": TARGET_LABEL, "baseClass": TARGET_BASE_CLASS}],
        "samples": sorted(samples, key=lambda item: str(item["sampleId"])),
        "negativeMedia": sorted(negatives, key=lambda item: str(item["negativeId"])),
        "origin": origin,
    }
    content_hash = hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()
    directory = output_root.resolve() / content_hash
    media_dir = directory / "media"
    directory.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(exist_ok=True)
    referenced_hashes = positive_hashes | {str(item["mediaSha256"]) for item in negatives}
    for media_hash in sorted(referenced_hashes):
        _atomic_copy(media_sources[media_hash], media_dir / f"{media_hash}{media_extensions[media_hash]}")
    manifest_path = directory / "manifest.json"
    manifest_data = {**snapshot, "contentHash": content_hash}
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("contentHash") != content_hash:
            raise ValueError("Immutable composed dataset directory conflicts with its manifest")
    else:
        temporary = manifest_path.with_name(f"manifest.{os.getpid()}.part")
        temporary.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(manifest_path)

    positive_images = {str(sample["mediaSha256"]) for sample in samples}
    split_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"boxes": 0, "positiveImages": 0, "negativeImages": 0})
    for sample in samples:
        split_counts[str(sample["split"])]["boxes"] += 1
    for split in ALLOWED_SPLITS:
        split_counts[split]["positiveImages"] = len({
            str(sample["mediaSha256"]) for sample in samples if sample["split"] == split
        })
        split_counts[split]["negativeImages"] = sum(item["split"] == split for item in negatives)
    return {
        "contentHash": content_hash,
        "directory": str(directory),
        "manifestPath": str(manifest_path),
        "positiveBoxCount": len(samples),
        "positiveImageCount": len(positive_images),
        "negativeImageCount": len(negatives),
        "sourceCount": len(source_splits),
        "splits": dict(split_counts),
    }


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit("usage: dataset_composer.py <output-root> <manifest-a> <manifest-b> [manifest-c ...]")
    result = compose_snapshots([Path(value) for value in sys.argv[2:]], Path(sys.argv[1]))
    print(json.dumps(result, ensure_ascii=False), flush=True)
