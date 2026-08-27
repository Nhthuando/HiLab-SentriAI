"""Build a CVAT review package around validation false-negative anchors.

The output contains proposals only. It never reads the locked test split and
cannot be passed to training until every frame is reviewed and finalized.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

import cv2
from ultralytics import YOLO

from evaluation.golden_dataset import difference_hash, hash_distance
from evaluation.metrics import iou
from stream.native_video_frames import NativeVideoFrameLoader
from training.local_video_dataset import (
    CLASS_NAMES,
    CLASS_TO_ID,
    REACH_STACKER_LABEL,
    create_cvat_archive,
    write_dataset_index_files,
)


def select_temporally_diverse(
    candidates: list[dict[str, Any]],
    *,
    minimum: int = 60,
    maximum: int = 80,
    minimum_hash_distance: int = 2,
) -> list[dict[str, Any]]:
    """Reduce adjacent near-duplicates while retaining a bounded review load."""
    ordered = sorted(candidates, key=lambda item: int(item["timestampMs"]))
    if minimum <= 0 or maximum < minimum:
        raise ValueError("invalid selection bounds")
    selected: list[dict[str, Any]] = []
    selected_hashes: set[str] = set()
    for item in ordered:
        image_hash = str(item["sha256"])
        if image_hash in selected_hashes:
            continue
        if (
            not item.get("isAnchor")
            and selected
            and hash_distance(str(selected[-1]["perceptualHash"]), str(item["perceptualHash"])) < minimum_hash_distance
        ):
            continue
        selected.append(item)
        selected_hashes.add(image_hash)

    if len(selected) < min(minimum, len(ordered)):
        selected_ids = {id(item) for item in selected}
        remaining = [item for item in ordered if id(item) not in selected_ids and str(item["sha256"]) not in selected_hashes]
        needed = min(minimum, len(ordered)) - len(selected)
        if needed > 0 and remaining:
            indexes = {
                min(len(remaining) - 1, math.floor(index * len(remaining) / needed))
                for index in range(needed)
            }
            for index in sorted(indexes):
                item = remaining[index]
                if str(item["sha256"]) not in selected_hashes:
                    selected.append(item)
                    selected_hashes.add(str(item["sha256"]))
    if len(selected) > maximum:
        anchors = [item for item in selected if item.get("isAnchor")]
        other = [item for item in selected if not item.get("isAnchor")]
        slots = max(0, maximum - len(anchors))
        indexes = {
            min(len(other) - 1, math.floor(index * len(other) / slots))
            for index in range(slots)
        } if slots and other else set()
        selected = [*anchors, *(other[index] for index in sorted(indexes))]
    return sorted(selected, key=lambda item: int(item["timestampMs"]))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _square_window(
    bbox: list[float], width: int, height: int, size: int,
) -> tuple[int, int, int, int]:
    center_x = (bbox[0] + bbox[2]) * width / 2
    center_y = (bbox[1] + bbox[3]) * height / 2
    size = min(size, width, height)
    left = max(0, min(width - size, int(round(center_x - size / 2))))
    top = max(0, min(height - size, int(round(center_y - size / 2))))
    return left, top, left + size, top + size


def _project_bbox(
    bbox: list[float], width: int, height: int, window: tuple[int, int, int, int],
) -> list[float]:
    left, top, right, bottom = window
    return [
        max(0.0, min(1.0, (bbox[0] * width - left) / (right - left))),
        max(0.0, min(1.0, (bbox[1] * height - top) / (bottom - top))),
        max(0.0, min(1.0, (bbox[2] * width - left) / (right - left))),
        max(0.0, min(1.0, (bbox[3] * height - top) / (bottom - top))),
    ]


def _center_distance(left: list[float], right: list[float]) -> float:
    left_center = ((left[0] + left[2]) / 2, (left[1] + left[3]) / 2)
    right_center = ((right[0] + right[2]) / 2, (right[1] + right[3]) / 2)
    return math.hypot(left_center[0] - right_center[0], left_center[1] - right_center[1])


def _associate_track(
    items: list[dict[str, Any]],
    candidates: Mapping[str, list[dict[str, Any]]],
    anchor_timestamp_ms: int,
) -> None:
    ordered = sorted(items, key=lambda item: int(item["timestampMs"]))
    anchor_index = min(range(len(ordered)), key=lambda index: abs(int(ordered[index]["timestampMs"]) - anchor_timestamp_ms))

    def choose(item: dict[str, Any], prior: list[float]) -> tuple[list[float], str, float | None]:
        options = candidates.get(str(item["frameId"]), [])
        ranked = sorted(
            options,
            key=lambda candidate: (
                iou(candidate["bbox"], prior) - 0.15 * _center_distance(candidate["bbox"], prior)
                + 0.02 * float(candidate["confidence"])
            ),
            reverse=True,
        )
        if ranked and (iou(ranked[0]["bbox"], prior) >= 0.05 or _center_distance(ranked[0]["bbox"], prior) <= 0.20):
            return list(ranked[0]["bbox"]), "model_assisted_track", float(ranked[0]["confidence"])
        return list(prior), "propagated_for_review", None

    anchor = ordered[anchor_index]
    anchor_box, source, confidence = choose(anchor, list(anchor["referenceBbox"]))
    anchor["proposalBbox"], anchor["proposalSource"], anchor["proposalConfidence"] = anchor_box, source, confidence
    prior = anchor_box
    for item in ordered[anchor_index + 1:]:
        prior, source, confidence = choose(item, prior)
        item["proposalBbox"], item["proposalSource"], item["proposalConfidence"] = prior, source, confidence
    prior = anchor_box
    for item in reversed(ordered[:anchor_index]):
        prior, source, confidence = choose(item, prior)
        item["proposalBbox"], item["proposalSource"], item["proposalConfidence"] = prior, source, confidence


def build_review_package(
    reviewed_snapshot: Path,
    false_negative_manifest: Path,
    video_root: Path,
    ffmpeg_path: Path,
    model_path: Path,
    output_directory: Path,
    *,
    dataset_id: str = "BAI-KIEM-MISSED-REACH-NATIVE-V1",
    radius_ms: int = 10_000,
    interval_ms: int = 250,
    crop_size: int = 896,
    device: str = "0",
    batch: int = 8,
) -> dict[str, Any]:
    source_snapshot = reviewed_snapshot.resolve()
    manifest = json.loads((source_snapshot / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 3 or manifest.get("reviewStatus") != "REVIEWED":
        raise ValueError("false-negative expansion requires a finalized reviewed snapshot")
    false_negatives = [
        json.loads(line)
        for line in false_negative_manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not false_negatives:
        raise ValueError("false-negative manifest is empty")
    if any(str(item.get("sourceId") or "").endswith("independent-test") for item in false_negatives):
        raise ValueError("locked test sources are forbidden")
    output = output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"review package already exists: {output}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=str(output.parent)))
    for split in ("train", "val", "test"):
        (temporary / "images" / split).mkdir(parents=True)
        (temporary / "labels" / split).mkdir(parents=True)

    loader = NativeVideoFrameLoader(manifest, video_root, ffmpeg_path=ffmpeg_path, cache_frames=False)
    raw_by_track: dict[str, list[dict[str, Any]]] = defaultdict(list)
    try:
        for track_index, missed in enumerate(false_negatives):
            track_id = f"missed-track-{track_index + 1:02d}"
            anchor_timestamp = int(missed["timestampMs"])
            split = "val" if track_index == len(false_negatives) - 1 else "train"
            for timestamp_ms in range(anchor_timestamp - radius_ms, anchor_timestamp + radius_ms + 1, interval_ms):
                frame_request = {
                    "frameId": f"{track_id}-{timestamp_ms:010d}",
                    "sourceId": missed["sourceId"],
                    "timestampMs": timestamp_ms,
                }
                image = loader(frame_request)
                height, width = image.shape[:2]
                window = _square_window(list(missed["bbox"]), width, height, crop_size)
                left, top, right, bottom = window
                crop = image[top:bottom, left:right]
                ok, encoded = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                if not ok:
                    raise RuntimeError(f"cannot encode {track_id}@{timestamp_ms}")
                payload = encoded.tobytes()
                raw_by_track[track_id].append({
                    "frameId": f"{track_id}-{timestamp_ms:010d}",
                    "trackId": track_id,
                    "parentSourceId": missed["sourceId"],
                    "timestampMs": timestamp_ms,
                    "anchorTimestampMs": anchor_timestamp,
                    "split": split,
                    "isAnchor": timestamp_ms == anchor_timestamp,
                    "payload": payload,
                    "sha256": _sha256_bytes(payload),
                    "perceptualHash": difference_hash(crop),
                    "referenceBbox": _project_bbox(list(missed["bbox"]), width, height, window),
                    "originalResolution": [width, height],
                    "nativeCropWindow": list(window),
                })
    finally:
        loader.close()

    selected: list[dict[str, Any]] = []
    for track_id, items in sorted(raw_by_track.items()):
        selected.extend(select_temporally_diverse(items))
    if not 300 <= len(selected) <= 500:
        raise RuntimeError(f"deduplicated review package must contain 300-500 samples, got {len(selected)}")

    for item in selected:
        split = str(item["split"])
        image_path = temporary / "images" / split / f"{item['frameId']}.jpg"
        image_path.write_bytes(item["payload"])
        item["imagePath"] = image_path.relative_to(temporary).as_posix()

    model = YOLO(str(model_path.resolve()))
    proposal_candidates: dict[str, list[dict[str, Any]]] = {}
    for offset in range(0, len(selected), max(batch, batch * 4)):
        chunk = selected[offset:offset + max(batch, batch * 4)]
        results = model.predict(
            source=[str(temporary / item["imagePath"]) for item in chunk],
            stream=True, batch=batch, imgsz=768, conf=0.001, iou=0.70,
            max_det=50, device=device, quantize=16 if str(device).casefold() != "cpu" else None,
            verbose=False,
        )
        for item, result in zip(chunk, results, strict=True):
            boxes = getattr(result, "boxes", None)
            height, width = result.orig_shape
            detections: list[dict[str, Any]] = []
            if boxes is not None:
                for xyxy, confidence in zip(boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist(), strict=True):
                    detections.append({
                        "bbox": [xyxy[0] / width, xyxy[1] / height, xyxy[2] / width, xyxy[3] / height],
                        "confidence": float(confidence),
                    })
            proposal_candidates[str(item["frameId"])] = detections
    del model

    selected_by_track: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in selected:
        selected_by_track[str(item["trackId"])].append(item)
    for items in selected_by_track.values():
        _associate_track(items, proposal_candidates, int(items[0]["anchorTimestampMs"]))

    proposal_sources: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    for item in sorted(selected, key=lambda value: str(value["frameId"])):
        bbox = list(item["proposalBbox"])
        center_x, center_y = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        box_width, box_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        split = str(item["split"])
        label_path = temporary / "labels" / split / f"{item['frameId']}.txt"
        label_path.write_text(
            f"{CLASS_TO_ID['reach_stacker']} {center_x:.8f} {center_y:.8f} {box_width:.8f} {box_height:.8f}\n",
            encoding="utf-8",
        )
        proposal_sources[str(item["proposalSource"])] += 1
        record = {
            "frameId": item["frameId"],
            "sourceId": item["trackId"],
            "parentSourceId": item["parentSourceId"],
            "duplicateGroup": item["trackId"],
            "role": "positive",
            "timestampMs": item["timestampMs"],
            "requestedTimestampMs": item["timestampMs"],
            "split": split,
            "imagePath": item["imagePath"],
            "labelsPath": label_path.relative_to(temporary).as_posix(),
            "sha256": item["sha256"],
            "perceptualHash": item["perceptualHash"],
            "proposalCount": 1,
            "proposalSource": item["proposalSource"],
            "proposalConfidence": item["proposalConfidence"],
            "anchorTimestampMs": item["anchorTimestampMs"],
            "originalResolution": item["originalResolution"],
            "nativeCropWindow": item["nativeCropWindow"],
            "reviewStatus": "PENDING_REVIEW",
        }
        records.append(record)
        samples.append({
            "sampleId": item["frameId"],
            "label": REACH_STACKER_LABEL,
            "baseClass": "reach_stacker",
            "sourceId": item["trackId"],
            "parentSourceId": item["parentSourceId"],
            "mediaKind": "IMAGE",
            "frameTimestampMs": item["timestampMs"],
            "bbox": {"x": bbox[0], "y": bbox[1], "w": box_width, "h": box_height},
            "mediaPath": item["imagePath"],
            "mediaSha256": item["sha256"],
            "split": split,
        })

    sources = []
    source_file = next(
        str(source["sourceFile"])
        for source in manifest.get("sources", [])
        if str(source.get("sourceId")) == str(false_negatives[0]["sourceId"])
    )
    for track_id, items in sorted(selected_by_track.items()):
        timestamps = [int(item["timestampMs"]) for item in items]
        sources.append({
            "sourceId": track_id,
            "parentSourceId": items[0]["parentSourceId"],
            "sourceFile": source_file,
            "duplicateGroup": track_id,
            "role": "positive",
            "fps": 20.0,
            "width": 2592,
            "height": 1520,
            "acceptedFrames": len(items),
            "ranges": [{
                "startMs": min(timestamps), "endMs": max(timestamps),
                "split": items[0]["split"], "intervalMs": interval_ms,
            }],
        })
    annotation_manifest = {
        "schemaVersion": 1,
        "datasetId": dataset_id,
        "classes": list(CLASS_NAMES),
        "reviewStatus": "PENDING_REVIEW",
        "proposalWarning": "False-negative expansion proposals are not ground truth. Review every box; locked test was not used.",
        "lockedTestUsed": False,
        "sourceArtifactSha256": _sha256_file(model_path.resolve()),
        "sources": sources,
        "frames": records,
    }
    (temporary / "annotation-manifest.json").write_text(
        json.dumps(annotation_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    audit_manifest = {
        "schemaVersion": 2,
        "profile": "REACH_STACKER_AUXILIARY_V1_PENDING_REVIEW",
        "requiredClasses": [{"label": REACH_STACKER_LABEL, "baseClass": "reach_stacker"}],
        "samples": samples,
        "negativeMedia": [],
        "origin": {
            "kind": "validation_false_negative_native_expansion",
            "reviewStatus": "PENDING_REVIEW",
            "inputContentHash": manifest["contentHash"],
            "lockedTestUsed": False,
            "sourceArtifactSha256": _sha256_file(model_path.resolve()),
            "rawCandidateCount": sum(len(items) for items in raw_by_track.values()),
            "selectedCount": len(records),
            "minimumHashDistance": 2,
        },
    }
    audit_manifest["contentHash"] = hashlib.sha256(
        json.dumps(audit_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    (temporary / "manifest.json").write_text(
        json.dumps(audit_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    with (temporary / "review.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "frameId", "sourceId", "timestampMs", "split", "role", "imagePath",
            "labelsPath", "proposalCount", "reviewStatus", "reviewerNotes",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key, "") for key in fields})
    write_dataset_index_files(temporary, records, CLASS_NAMES)
    summary = {
        "datasetId": dataset_id,
        "frameCount": len(records),
        "reachStackerProposalCount": len(records),
        "rawCandidateCount": sum(len(items) for items in raw_by_track.values()),
        "nearDuplicateCandidatesRemoved": sum(len(items) for items in raw_by_track.values()) - len(records),
        "splitCounts": dict(sorted(Counter(str(item["split"]) for item in records).items())),
        "proposalSources": dict(sorted(proposal_sources.items())),
        "originalResolution": [2592, 1520],
        "cropSize": crop_size,
        "lockedTestUsed": False,
        "reviewStatus": "PENDING_REVIEW",
    }
    (temporary / "build-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary.replace(output)
    archive = create_cvat_archive(output, output.with_name(f"{output.name}-cvat.zip"))
    return {**summary, "directory": str(output), "cvatArchive": str(archive)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-snapshot", type=Path, required=True)
    parser.add_argument("--false-negatives", type=Path, required=True)
    parser.add_argument("--video-root", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()
    print(json.dumps(build_review_package(
        args.reviewed_snapshot, args.false_negatives, args.video_root, args.ffmpeg,
        args.model, args.output, device=args.device,
    ), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
