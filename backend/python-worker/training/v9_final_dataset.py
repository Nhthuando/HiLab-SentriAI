"""Build the immutable, five-class BAI-KIEM V9 train/validation dataset."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


V9_CLASSES = ("person", "car", "truck", "forklift", "reach_stacker")
VALID_SPLITS = frozenset({"train", "val"})
BLOCK_MS = 120_000


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _all_reviewed(package: Path, frame_count: int) -> None:
    receipt_path = package / "cvat-review-receipt.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("reviewStatus") == "REVIEWED" and int(receipt.get("frameCount", -1)) == frame_count:
            return
    with (package / "review.csv").open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != frame_count or any(row.get("reviewStatus") != "REVIEWED" for row in rows):
        raise ValueError(f"package has not been completely reviewed: {package}")


def _read_labels(path: Path, class_names: list[str]) -> tuple[str, Counter[str], int]:
    rows: set[tuple[int, float, float, float, float]] = set()
    counts: Counter[str] = Counter()
    duplicates = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        fields = line.split()
        if len(fields) != 5:
            raise ValueError(f"invalid YOLO row at {path}:{line_number}")
        source_id = int(fields[0])
        if not 0 <= source_id < len(class_names):
            raise ValueError(f"invalid class ID at {path}:{line_number}")
        class_name = class_names[source_id]
        if class_name not in V9_CLASSES:
            # Unrepresented canonical classes have no reviewed boxes in the
            # accepted sources. Refuse non-empty unsupported labels instead of
            # silently turning them into background.
            raise ValueError(f"unsupported non-empty class {class_name!r} at {path}:{line_number}")
        values = tuple(float(value) for value in fields[1:])
        if any(not 0.0 <= value <= 1.0 for value in values) or values[2] <= 0.0 or values[3] <= 0.0:
            raise ValueError(f"invalid normalized box at {path}:{line_number}")
        row = (V9_CLASSES.index(class_name), *values)
        rounded = (row[0], *(round(value, 8) for value in row[1:]))
        if rounded in rows:
            duplicates += 1
            continue
        rows.add(rounded)
        counts[class_name] += 1
    ordered = sorted(rows)
    text = "".join(
        f"{class_id} {x:.8f} {y:.8f} {w:.8f} {h:.8f}\n"
        for class_id, x, y, w, h in ordered
    )
    return text, counts, duplicates


def _load_frames(package: Path, *, include_old_test: bool) -> list[dict[str, Any]]:
    manifest = json.loads((package / "annotation-manifest.json").read_text(encoding="utf-8"))
    frames = manifest.get("frames")
    classes = manifest.get("classes")
    if not isinstance(frames, list) or not frames or not isinstance(classes, list):
        raise ValueError(f"invalid annotation manifest: {package}")
    _all_reviewed(package, len(frames))
    loaded: list[dict[str, Any]] = []
    for frame in frames:
        old_split = str(frame.get("split"))
        if old_split == "test" and not include_old_test:
            continue
        image = package / str(frame["imagePath"])
        label = package / str(frame["labelsPath"])
        if not image.is_file() or not label.is_file():
            raise FileNotFoundError(f"reviewed frame media is missing in {package}")
        image_hash = str(frame.get("sha256") or _sha256(image)).casefold()
        if _sha256(image) != image_hash:
            raise ValueError(f"image hash mismatch: {image}")
        label_text, class_counts, row_duplicates = _read_labels(label, [str(name) for name in classes])
        loaded.append({
            "package": package.name,
            "frameId": str(frame.get("frameId") or image.stem),
            "sourceId": str(frame.get("sourceId") or package.name),
            "timestampMs": int(frame.get("timestampMs") or 0),
            "image": image,
            "imageSha256": image_hash,
            "perceptualHash": str(frame.get("perceptualHash") or ""),
            "labelText": label_text,
            "classCounts": dict(class_counts),
            "rowDuplicates": row_duplicates,
            "originalSplit": old_split,
        })
    return loaded


def _split_for(frame: dict[str, Any], salt: int) -> str:
    time_block = int(frame["timestampMs"]) // BLOCK_MS
    token = f"{salt}|{frame['sourceId']}|{time_block}".encode("utf-8")
    return "val" if int(hashlib.sha256(token).hexdigest()[:8], 16) % 100 < 15 else "train"


def _select_salt(frames: list[dict[str, Any]]) -> tuple[int, dict[str, str]]:
    total_counts = Counter()
    for frame in frames:
        total_counts.update(frame["classCounts"])
    best: tuple[float, int, dict[str, str]] | None = None
    for salt in range(512):
        splits = {frame["imageSha256"]: _split_for(frame, salt) for frame in frames}
        split_frames = Counter(splits.values())
        split_counts = {name: Counter() for name in VALID_SPLITS}
        for frame in frames:
            split_counts[splits[frame["imageSha256"]]].update(frame["classCounts"])
        if split_frames["train"] == 0 or split_frames["val"] == 0:
            continue
        if any(split_counts[split][name] == 0 for split in VALID_SPLITS for name in V9_CLASSES):
            continue
        val_fraction = split_frames["val"] / len(frames)
        class_error = sum(
            abs(split_counts["val"][name] / max(1, total_counts[name]) - 0.15)
            for name in V9_CLASSES
        )
        score = abs(val_fraction - 0.15) * 3.0 + class_error
        candidate = (score, salt, splits)
        if best is None or candidate[0] < best[0]:
            best = candidate
    if best is None:
        raise ValueError("could not create a class-covered temporal train/validation split")
    return best[1], best[2]


def _link_or_copy(source: Path, destination: Path) -> str:
    try:
        os.link(source, destination)
        return "hardlink"
    except OSError:
        shutil.copy2(source, destination)
        return "copy"


def build_v9_dataset(packages: Iterable[Path], output_directory: Path) -> dict[str, Any]:
    package_paths = [Path(package).resolve() for package in packages]
    if not package_paths:
        raise ValueError("at least one reviewed package is required")
    output = output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"immutable dataset already exists: {output}")

    # Earlier arguments have higher authority. The freshly frozen CVAT export
    # is passed first so it wins over an exact image duplicate from V8 data.
    unique: dict[str, dict[str, Any]] = {}
    exact_duplicates = 0
    conflicting_duplicates = 0
    excluded_old_test = 0
    input_stats: list[dict[str, Any]] = []
    for package in package_paths:
        manifest = json.loads((package / "annotation-manifest.json").read_text(encoding="utf-8"))
        all_frames = manifest.get("frames", [])
        excluded_old_test += sum(str(frame.get("split")) == "test" for frame in all_frames)
        frames = _load_frames(package, include_old_test=False)
        input_stats.append({"package": package.name, "eligibleFrames": len(frames)})
        for frame in frames:
            prior = unique.get(frame["imageSha256"])
            if prior is not None:
                exact_duplicates += 1
                conflicting_duplicates += prior["labelText"] != frame["labelText"]
                continue
            unique[frame["imageSha256"]] = frame
    frames = sorted(unique.values(), key=lambda item: (item["sourceId"], item["timestampMs"], item["imageSha256"]))
    salt, splits = _select_salt(frames)

    snapshot_rows = []
    for frame in frames:
        snapshot_rows.append({
            "imageSha256": frame["imageSha256"],
            "labelSha256": hashlib.sha256(frame["labelText"].encode("utf-8")).hexdigest(),
            "sourceId": frame["sourceId"],
            "timestampMs": frame["timestampMs"],
            "split": splits[frame["imageSha256"]],
        })
    content_hash = hashlib.sha256(_canonical_json({"classes": V9_CLASSES, "frames": snapshot_rows}).encode("utf-8")).hexdigest()

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=str(output.parent)))
    try:
        for split in VALID_SPLITS:
            (temporary / "images" / split).mkdir(parents=True)
            (temporary / "labels" / split).mkdir(parents=True)
        class_counts = {split: Counter() for split in VALID_SPLITS}
        frame_counts = Counter()
        empty_counts = Counter()
        source_counts: dict[str, Counter[str]] = defaultdict(Counter)
        transfer_modes = Counter()
        manifest_frames = []
        split_lists: dict[str, list[str]] = defaultdict(list)
        for frame in frames:
            split = splits[frame["imageSha256"]]
            stem = frame["imageSha256"][:32]
            image_rel = Path("images") / split / f"{stem}{frame['image'].suffix.casefold()}"
            label_rel = Path("labels") / split / f"{stem}.txt"
            transfer_modes[_link_or_copy(frame["image"], temporary / image_rel)] += 1
            (temporary / label_rel).write_text(frame["labelText"], encoding="utf-8")
            frame_counts[split] += 1
            source_counts[frame["sourceId"]][split] += 1
            if not frame["labelText"]:
                empty_counts[split] += 1
            class_counts[split].update(frame["classCounts"])
            # Ultralytics resolves entries inside a list file against the
            # process working directory on Windows, not reliably against the
            # data.yaml root. Persist the future final absolute path.
            split_lists[split].append((output / image_rel).as_posix())
            manifest_frames.append({
                "frameId": frame["frameId"],
                "sourcePackage": frame["package"],
                "sourceId": frame["sourceId"],
                "timestampMs": frame["timestampMs"],
                "split": split,
                "imagePath": image_rel.as_posix(),
                "labelsPath": label_rel.as_posix(),
                "imageSha256": frame["imageSha256"],
                "perceptualHash": frame["perceptualHash"],
            })
        for split in VALID_SPLITS:
            (temporary / f"{split}.txt").write_text("".join(f"{item}\n" for item in split_lists[split]), encoding="utf-8")
        yaml_names = "\n".join(f"  {index}: {name}" for index, name in enumerate(V9_CLASSES))
        (temporary / "data.yaml").write_text(
            f"path: {output.as_posix()}\ntrain: train.txt\nval: val.txt\nnames:\n{yaml_names}\n",
            encoding="utf-8",
        )
        audit = {
            "schemaVersion": 1,
            "datasetKind": "BAIKIEM_V9_FINAL_TRAIN_VAL",
            "contentHash": content_hash,
            "classes": list(V9_CLASSES),
            "splitMethod": {"kind": "source-time-block-hash", "blockMs": BLOCK_MS, "validationTarget": 0.15, "salt": salt},
            "inputs": input_stats,
            "frames": dict(frame_counts),
            "emptyFrames": dict(empty_counts),
            "boxes": {split: dict(class_counts[split]) for split in sorted(VALID_SPLITS)},
            "sources": {source: dict(counts) for source, counts in sorted(source_counts.items())},
            "excludedOldLockedTestFrames": excluded_old_test,
            "exactDuplicateImagesRemoved": exact_duplicates,
            "conflictingDuplicateAnnotations": conflicting_duplicates,
            "duplicateLabelRowsRemoved": sum(int(frame["rowDuplicates"]) for frame in frames),
            "mediaTransfer": dict(transfer_modes),
            "trainValidationImageHashOverlap": 0,
        }
        manifest = {**audit, "framesMetadata": manifest_frames}
        (temporary / "dataset-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (temporary / "dataset-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {**audit, "directory": str(output)}


def repair_v9_dataset_lists(dataset: Path) -> dict[str, int]:
    """Repair list-file paths in an otherwise immutable generated snapshot."""
    dataset = dataset.resolve()
    manifest = json.loads((dataset / "dataset-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("datasetKind") != "BAIKIEM_V9_FINAL_TRAIN_VAL":
        raise ValueError("not a generated BAI-KIEM V9 dataset")
    by_split: dict[str, list[str]] = defaultdict(list)
    for frame in manifest.get("framesMetadata", []):
        split = str(frame.get("split"))
        if split not in VALID_SPLITS:
            raise ValueError("generated manifest contains an invalid split")
        image = dataset / str(frame["imagePath"])
        label = dataset / str(frame["labelsPath"])
        if not image.is_file() or not label.is_file():
            raise FileNotFoundError("generated dataset media is missing")
        by_split[split].append(image.as_posix())
    for split in VALID_SPLITS:
        (dataset / f"{split}.txt").write_text(
            "".join(f"{path}\n" for path in by_split[split]), encoding="utf-8",
        )
    return {split: len(by_split[split]) for split in sorted(VALID_SPLITS)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("packages", type=Path, nargs="+")
    args = parser.parse_args()
    print(json.dumps(build_v9_dataset(args.packages, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
