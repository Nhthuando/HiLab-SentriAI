"""Build an immutable reach-stacker tile snapshot from reviewed CCTV frames.

The locked test split is deliberately forbidden. Tiles are derived only from
train/validation frames and retain their original split and source provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Iterable

import cv2

from detection.roi_inference import RoiSpec, build_tiles
from stream.native_video_frames import NativeVideoFrameLoader
from training.local_video_dataset import CLASS_NAMES, CLASS_TO_ID, REACH_STACKER_LABEL


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export_tiled_reach_snapshot(
    reviewed_snapshot: Path,
    output_root: Path,
    *,
    splits: Iterable[str] = ("train", "val"),
    roi: tuple[float, float, float, float] = (0.0, 0.10, 1.0, 0.85),
    crop_size: int = 480,
    overlap: float = 0.10,
    max_tiles: int = 8,
    video_root: Path | None = None,
    ffmpeg_path: Path | None = None,
) -> dict[str, object]:
    source = reviewed_snapshot.resolve()
    output = output_root.resolve()
    manifest_path = source / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("reviewed snapshot manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("schemaVersion") != 3
        or manifest.get("datasetKind") != "LOCAL_VIDEO_REVIEWED"
        or manifest.get("reviewStatus") != "REVIEWED"
        or manifest.get("classes") != list(CLASS_NAMES)
    ):
        raise ValueError("tile export requires an exact reviewed local-video snapshot")
    input_hash = str(manifest.get("contentHash") or "")
    selected_splits = frozenset(str(split) for split in splits)
    if not selected_splits or not selected_splits <= {"train", "val"}:
        raise ValueError("tile export permits only train and val splits")
    left, top, right, bottom = roi
    roi_spec = RoiSpec(
        "training-yard-roi",
        ((left, top), (right, top), (right, bottom), (left, bottom)),
        frozenset({"custom"}),
    )
    if crop_size <= 0 or max_tiles <= 0:
        raise ValueError("crop size and max tiles must be positive")

    output.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".reach-tiles-", dir=str(output)))
    media_dir = temporary / "media"
    media_dir.mkdir()
    samples: list[dict[str, object]] = []
    negatives: list[dict[str, object]] = []
    media_splits: dict[str, str] = {}
    crop_count = 0
    skipped_partial_crops = 0
    reach_class_id = CLASS_TO_ID["reach_stacker"]
    native_loader = (
        NativeVideoFrameLoader(
            manifest, video_root, ffmpeg_path=ffmpeg_path, cache_frames=False,
        )
        if video_root is not None else None
    )
    try:
        for raw_frame in manifest.get("frames", []):
            if not isinstance(raw_frame, dict) or raw_frame.get("split") not in selected_splits:
                continue
            frame_id = str(raw_frame.get("frameId") or "")
            source_id = str(raw_frame.get("sourceId") or "")
            split = str(raw_frame["split"])
            image_path = source / str(raw_frame.get("imagePath") or "")
            label_path = source / str(raw_frame.get("labelsPath") or "")
            image = native_loader(raw_frame) if native_loader is not None else cv2.imread(str(image_path))
            if image is None or not label_path.is_file():
                raise RuntimeError(f"reviewed image/label is unreadable for {frame_id}")
            height, width = image.shape[:2]
            reach_boxes: list[tuple[float, float, float, float]] = []
            for line_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
                fields = line.split()
                if not fields:
                    continue
                if len(fields) != 5:
                    raise ValueError(f"invalid YOLO row for {frame_id}:{line_number}")
                class_id = int(fields[0])
                if class_id != reach_class_id:
                    continue
                center_x, center_y, box_width, box_height = (float(value) for value in fields[1:])
                reach_boxes.append((
                    (center_x - box_width / 2) * width,
                    (center_y - box_height / 2) * height,
                    (center_x + box_width / 2) * width,
                    (center_y + box_height / 2) * height,
                ))

            windows = build_tiles(
                width, height, (roi_spec,), tile_size=crop_size,
                overlap=overlap, max_tiles=max_tiles, detector="custom",
            )
            for tile_index, tile in enumerate(windows):
                selected: list[dict[str, float]] = []
                intersects_unselected = False
                for box in reach_boxes:
                    box_width = max(0.0, box[2] - box[0])
                    box_height = max(0.0, box[3] - box[1])
                    intersection_width = max(0.0, min(box[2], tile.x2) - max(box[0], tile.x1))
                    intersection_height = max(0.0, min(box[3], tile.y2) - max(box[1], tile.y1))
                    intersection = intersection_width * intersection_height
                    if intersection <= 0:
                        continue
                    center_x = (box[0] + box[2]) / 2
                    center_y = (box[1] + box[3]) / 2
                    coverage = intersection / max(1e-9, box_width * box_height)
                    if tile.x1 <= center_x <= tile.x2 and tile.y1 <= center_y <= tile.y2 and coverage >= 0.50:
                        clipped_left = max(box[0], tile.x1) - tile.x1
                        clipped_top = max(box[1], tile.y1) - tile.y1
                        clipped_right = min(box[2], tile.x2) - tile.x1
                        clipped_bottom = min(box[3], tile.y2) - tile.y1
                        selected.append({
                            "x": round(clipped_left / (tile.x2 - tile.x1), 8),
                            "y": round(clipped_top / (tile.y2 - tile.y1), 8),
                            "w": round((clipped_right - clipped_left) / (tile.x2 - tile.x1), 8),
                            "h": round((clipped_bottom - clipped_top) / (tile.y2 - tile.y1), 8),
                        })
                    else:
                        intersects_unselected = True
                if not selected and intersects_unselected:
                    skipped_partial_crops += 1
                    continue

                crop = image[tile.y1:tile.y2, tile.x1:tile.x2]
                encoded_ok, encoded = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                if not encoded_ok:
                    raise RuntimeError(f"cannot encode crop for {frame_id}:{tile_index}")
                payload = encoded.tobytes()
                media_hash = _sha256(payload)
                previous_split = media_splits.setdefault(media_hash, split)
                if previous_split != split:
                    raise ValueError("one generated crop appears in multiple splits")
                media_path = f"media/{media_hash}.jpg"
                destination = media_dir / f"{media_hash}.jpg"
                if not destination.is_file():
                    destination.write_bytes(payload)
                crop_id = f"{frame_id}-tile-{tile_index:02d}"
                block_source_id = f"tile:{source_id}:{split}"
                if selected:
                    for box_index, bbox in enumerate(selected):
                        samples.append({
                            "sampleId": f"tile-{crop_id}-{box_index}",
                            "label": REACH_STACKER_LABEL,
                            "baseClass": "reach_stacker",
                            "sourceId": block_source_id,
                            "parentSourceId": source_id,
                            "mediaKind": "IMAGE",
                            "frameTimestampMs": int(raw_frame.get("timestampMs") or 0),
                            "bbox": bbox,
                            "mediaPath": media_path,
                            "mediaSha256": media_hash,
                            "split": split,
                        })
                else:
                    negatives.append({
                        "negativeId": f"tile-negative-{crop_id}",
                        "sourceId": block_source_id,
                        "parentSourceId": source_id,
                        "mediaKind": "IMAGE",
                        "frameTimestampMs": int(raw_frame.get("timestampMs") or 0),
                        "mediaPath": media_path,
                        "mediaSha256": media_hash,
                        "split": split,
                        "reasonClasses": ["tiled_yard_background"],
                    })
                crop_count += 1

        snapshot = {
            "schemaVersion": 2,
            "profile": "REACH_STACKER_AUXILIARY_V1",
            "requiredClasses": [{"label": REACH_STACKER_LABEL, "baseClass": "reach_stacker"}],
            "samples": sorted(samples, key=lambda item: str(item["sampleId"])),
            "negativeMedia": sorted(negatives, key=lambda item: str(item["negativeId"])),
            "origin": {
                "kind": "reviewed_local_video_tiles",
                "inputContentHash": input_hash,
                "splits": sorted(selected_splits),
                "roi": list(roi),
                "cropSize": crop_size,
                "overlap": overlap,
                "maxTiles": max_tiles,
                "skippedPartialCrops": skipped_partial_crops,
                "nativeSourceFrames": native_loader is not None,
                "nativeFrameDecoder": "ffmpeg-fast-seek" if ffmpeg_path is not None else "opencv",
            },
        }
        content_hash = hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()
        target = output / content_hash
        final_manifest = {**snapshot, "contentHash": content_hash}
        (temporary / "manifest.json").write_text(
            json.dumps(final_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        if target.exists():
            existing = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            if existing.get("contentHash") != content_hash:
                raise FileExistsError(f"immutable tile snapshot conflict: {target}")
            shutil.rmtree(temporary)
        else:
            temporary.replace(target)
        result = {
            "contentHash": content_hash,
            "directory": str(target),
            "manifestPath": str(target / "manifest.json"),
            "cropCount": crop_count,
            "positiveBoxCount": len(samples),
            "negativeImageCount": len(negatives),
            "skippedPartialCrops": skipped_partial_crops,
        }
        if native_loader is not None:
            native_loader.close()
        return result
    except Exception:
        if native_loader is not None:
            native_loader.close()
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reviewed_snapshot", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("--crop-size", type=int, default=480)
    parser.add_argument("--overlap", type=float, default=0.10)
    parser.add_argument("--max-tiles", type=int, default=8)
    parser.add_argument("--roi", type=float, nargs=4, default=(0.0, 0.10, 1.0, 0.85))
    parser.add_argument("--video-root", type=Path)
    parser.add_argument("--ffmpeg", type=Path)
    args = parser.parse_args()
    if args.ffmpeg is not None and args.video_root is None:
        parser.error("--ffmpeg requires --video-root")
    result = export_tiled_reach_snapshot(
        args.reviewed_snapshot, args.output_root,
        roi=tuple(args.roi), crop_size=args.crop_size,
        overlap=args.overlap, max_tiles=args.max_tiles,
        video_root=args.video_root, ffmpeg_path=args.ffmpeg,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
