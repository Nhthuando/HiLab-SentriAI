"""Train a temporary annotation helper and safely refresh part of a CVAT task.

The helper produced here is deliberately isolated from SentriAI's active-model
paths.  Its sole purpose is to make the remainder of a CVAT review task easier.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import requests


CANONICAL_CLASSES = (
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "bus",
    "truck",
    "container_truck",
    "forklift",
    "reach_stacker",
    "mobile_crane",
)
FORBIDDEN_HELPER_CLASSES = frozenset({"container_truck"})
DEFAULT_HELPER_THRESHOLDS = {
    "person": 0.20,
    "bicycle": 0.18,
    "car": 0.15,
    "motorcycle": 0.18,
    "bus": 0.25,
    "truck": 0.15,
    "forklift": 0.12,
    "reach_stacker": 0.12,
    "mobile_crane": 0.15,
}
DEFAULT_BASE_ONLY_THRESHOLDS = {
    "bicycle": 0.40,
    "motorcycle": 0.35,
    "bus": 0.50,
}
REVIEW_THRESHOLDS = {
    "person": 0.50,
    "car": 0.30,
    "truck": 0.35,
    "forklift": 0.25,
    "reach_stacker": 0.30,
    "bicycle": 0.40,
    "motorcycle": 0.35,
    "bus": 0.50,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _shape_semantics(shape: Mapping[str, Any]) -> dict[str, Any]:
    """Return only annotation semantics; CVAT-owned IDs are intentionally omitted."""
    return {
        "type": str(shape.get("type", "")),
        "frame": int(shape.get("frame", -1)),
        "label_id": int(shape.get("label_id", -1)),
        "points": [round(float(value), 6) for value in shape.get("points", [])],
        "occluded": bool(shape.get("occluded", False)),
        "outside": bool(shape.get("outside", False)),
        "z_order": int(shape.get("z_order", 0)),
        "rotation": round(float(shape.get("rotation", 0.0)), 6),
        "attributes": shape.get("attributes", []),
        "source": str(shape.get("source", "manual")),
        "group": int(shape.get("group", 0) or 0),
    }


def canonical_shape_hash(shapes: Iterable[Mapping[str, Any]]) -> str:
    canonical = [_shape_semantics(shape) for shape in shapes]
    canonical.sort(key=lambda item: (
        item["frame"], item["label_id"], item["type"], item["points"],
        item["source"], _json_bytes(item["attributes"]),
    ))
    return _sha256_bytes(_json_bytes(canonical))


def _shape_for_put(shape: Mapping[str, Any]) -> dict[str, Any]:
    semantic = _shape_semantics(shape)
    result = {
        "type": semantic["type"],
        "frame": semantic["frame"],
        "label_id": semantic["label_id"],
        "points": semantic["points"],
        "occluded": semantic["occluded"],
        "outside": semantic["outside"],
        "z_order": semantic["z_order"],
        "rotation": semantic["rotation"],
        "attributes": semantic["attributes"],
        "source": semantic["source"],
    }
    if semantic["group"]:
        result["group"] = semantic["group"]
    return result


def shape_to_yolo(shape: Mapping[str, Any], width: int, height: int) -> tuple[float, float, float, float]:
    if shape.get("type") != "rectangle":
        raise ValueError(f"unsupported CVAT shape type: {shape.get('type')!r}")
    points = shape.get("points")
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)) or len(points) != 4:
        raise ValueError("CVAT rectangle must contain four point values")
    if width <= 0 or height <= 0:
        raise ValueError("frame dimensions must be positive")
    x1, y1, x2, y2 = (float(value) for value in points)
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    epsilon = 1e-3
    if (
        right <= left or bottom <= top or left < -epsilon or top < -epsilon
        or right > width + epsilon or bottom > height + epsilon
    ):
        raise ValueError("CVAT rectangle is invalid or outside its frame")
    left, top = max(0.0, left), max(0.0, top)
    right, bottom = min(float(width), right), min(float(height), bottom)
    return (
        (left + right) / (2.0 * width),
        (top + bottom) / (2.0 * height),
        (right - left) / width,
        (bottom - top) / height,
    )


def deterministic_split(frame_indices: Sequence[int], *, val_stride: int = 7) -> tuple[list[int], list[int]]:
    if val_stride < 2:
        raise ValueError("val_stride must be at least two")
    ordered = sorted({int(frame) for frame in frame_indices})
    if len(ordered) < 2:
        raise ValueError("at least two frames are required")
    val = [frame for position, frame in enumerate(ordered) if position % val_stride == val_stride - 1]
    if not val:
        val = [ordered[-1]]
    val_set = set(val)
    train = [frame for frame in ordered if frame not in val_set]
    if not train:
        train = [val.pop(0)]
    return train, val


def _intersection_over_union(first: Sequence[float], second: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = (float(value) for value in first)
    bx1, by1, bx2, by2 = (float(value) for value in second)
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    first_area = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    second_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def class_agnostic_nms(proposals: Sequence[Mapping[str, Any]], *, iou_threshold: float = 0.5) -> list[dict[str, Any]]:
    if not 0.0 <= iou_threshold <= 1.0:
        raise ValueError("iou_threshold must be between zero and one")
    ordered = sorted((dict(item) for item in proposals), key=lambda item: (-float(item["confidence"]), str(item["class"])))
    kept: list[dict[str, Any]] = []
    for candidate in ordered:
        bbox = candidate.get("bbox")
        if not isinstance(bbox, Sequence) or isinstance(bbox, (str, bytes)) or len(bbox) != 4:
            raise ValueError("proposal bbox must contain four values")
        values = [float(value) for value in bbox]
        if not (0.0 <= values[0] < values[2] <= 1.0 and 0.0 <= values[1] < values[3] <= 1.0):
            raise ValueError("proposal bbox must be normalized and non-empty")
        candidate["bbox"] = values
        if any(_intersection_over_union(values, existing["bbox"]) >= iou_threshold for existing in kept):
            continue
        kept.append(candidate)
    return kept


def filter_proposals_for_review(frame: int, proposals: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Prefer fewer trustworthy boxes over making the reviewer delete low-confidence noise."""
    filtered: list[dict[str, Any]] = []
    for raw in proposals:
        item = dict(raw)
        class_name = str(item.get("class"))
        confidence = float(item.get("confidence", 0.0))
        bbox = item.get("bbox")
        if class_name not in REVIEW_THRESHOLDS or confidence < REVIEW_THRESHOLDS[class_name]:
            continue
        if not isinstance(bbox, Sequence) or isinstance(bbox, (str, bytes)) or len(bbox) != 4:
            raise ValueError("proposal bbox must contain four values")
        x1, y1, x2, y2 = (float(value) for value in bbox)
        # Frames 244-511 come from camera 2. Its burned-in timestamp occupies
        # the top-left strip and repeatedly fooled the small helper as people/cars.
        if 244 <= frame < 512 and x1 < 0.35 and y2 <= 0.12:
            continue
        # On the same camera the scene horizon is below 30% height. Thin
        # detections ending above it are cranes/light poles, never people.
        if 244 <= frame < 512 and class_name == "person" and y2 < 0.30:
            continue
        filtered.append(item)
    return class_agnostic_nms(filtered, iou_threshold=0.45)


def merge_preserving_prefix(
    existing_shapes: Sequence[Mapping[str, Any]],
    prediction_shapes: Sequence[Mapping[str, Any]],
    *,
    boundary: int,
    preserve_manual_suffix: bool = False,
) -> list[dict[str, Any]]:
    if boundary <= 0:
        raise ValueError("boundary must be positive")
    if any(int(shape.get("frame", -1)) < boundary for shape in prediction_shapes):
        raise ValueError("predictions must not target the reviewed prefix")
    prefix = [shape for shape in existing_shapes if int(shape.get("frame", -1)) < boundary]
    protected = [
        shape for shape in existing_shapes
        if preserve_manual_suffix
        and int(shape.get("frame", -1)) >= boundary
        and str(shape.get("source", "manual")) == "manual"
    ]
    protected_by_frame: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for shape in protected:
        protected_by_frame[int(shape["frame"])].append(shape)
    accepted_predictions: list[Mapping[str, Any]] = []
    for prediction in prediction_shapes:
        same_frame = protected_by_frame.get(int(prediction["frame"]), [])
        if any(
            _intersection_over_union(prediction.get("points", []), manual.get("points", [])) >= 0.30
            for manual in same_frame
        ):
            continue
        accepted_predictions.append(prediction)
    result = [_shape_for_put(shape) for shape in (*prefix, *protected, *accepted_predictions)]
    result.sort(key=lambda item: (int(item["frame"]), int(item["label_id"]), item["points"]))
    return result


def annotation_helper_train_options(
    project: str | Path,
    *,
    epochs: int,
    device: int | str,
    boundary: int = 210,
    fine_tune: bool = False,
) -> dict[str, Any]:
    if epochs < 1:
        raise ValueError("epochs must be positive")
    if boundary < 2:
        raise ValueError("boundary must be at least two")
    return {
        "project": str(project),
        "name": f"baikiem-v9-annotation-assist-{boundary}",
        "exist_ok": True,
        "epochs": epochs,
        "patience": min(10, max(5, epochs // 4)),
        "imgsz": 896,
        "batch": 1,
        "workers": 0,
        "cache": False,
        "amp": True,
        "device": device,
        "seed": 42,
        "deterministic": True,
        "pretrained": True,
        "optimizer": "AdamW",
        "lr0": 0.0005 if fine_tune else 0.001,
        "lrf": 0.01,
        "warmup_epochs": 1.0 if fine_tune else 2.0,
        "degrees": 2.0,
        "translate": 0.05,
        "scale": 0.20,
        "shear": 0.0,
        "perspective": 0.0002,
        "flipud": 0.0,
        "fliplr": 0.5,
        "hsv_h": 0.01,
        "hsv_s": 0.35,
        "hsv_v": 0.25,
        "mosaic": 0.5,
        "mixup": 0.0,
        "close_mosaic": 5,
        "plots": False,
        "save": True,
        "save_period": 5,
        "verbose": True,
    }


@dataclass(frozen=True)
class AssistConfig:
    package: Path
    output: Path
    base_model: Path
    base_url: str = "http://localhost:8080"
    task_id: int = 9
    locked_task_id: int = 10
    boundary: int = 210
    epochs: int = 40


class CvatClient:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        response = self.session.post(
            f"{self.base_url}/api/auth/login",
            json={"username": username, "password": password},
            timeout=30,
        )
        self._raise(response)
        self.session.headers.update({"Authorization": f"Token {response.json()['key']}"})

    @staticmethod
    def _raise(response: requests.Response) -> None:
        if not response.ok:
            raise RuntimeError(f"CVAT HTTP {response.status_code}: {response.text[:1000]}")

    def get(self, path: str, *, params: Mapping[str, Any] | None = None, timeout: float = 120) -> Any:
        response = self.session.get(f"{self.base_url}{path}", params=params, timeout=timeout)
        self._raise(response)
        return response.json()

    def put(self, path: str, payload: Mapping[str, Any], *, timeout: float = 180) -> Any:
        response = self.session.put(f"{self.base_url}{path}", json=payload, timeout=timeout)
        self._raise(response)
        return response.json() if response.content else None


def _client(base_url: str) -> CvatClient:
    username = os.environ.get("CVAT_USERNAME", "")
    password = os.environ.get("CVAT_PASSWORD", "")
    if not username or not password:
        raise RuntimeError("CVAT_USERNAME and CVAT_PASSWORD are required")
    return CvatClient(base_url, username, password)


def _task_state(client: CvatClient, task_id: int) -> dict[str, Any]:
    return {
        "task": client.get(f"/api/tasks/{task_id}"),
        "jobs": client.get("/api/jobs", params={"task_id": task_id, "page_size": 100}).get("results", []),
        "meta": client.get(f"/api/tasks/{task_id}/data/meta", timeout=60),
        "labels": client.get("/api/labels", params={"task_id": task_id, "page_size": 100}).get("results", []),
        "annotations": client.get(f"/api/tasks/{task_id}/annotations", timeout=180),
    }


def _assert_locked_empty(annotations: Mapping[str, Any], locked_task_id: int) -> None:
    counts = {kind: len(annotations.get(kind, []) or []) for kind in ("tags", "shapes", "tracks")}
    if any(counts.values()):
        raise ValueError(f"locked task {locked_task_id} is not empty: {counts}")


def _ensure_rectangle_contract(annotations: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if annotations.get("tags") or annotations.get("tracks"):
        raise ValueError("annotation-assist supports rectangle shapes only; task has tags or tracks")
    shapes = annotations.get("shapes", [])
    if not isinstance(shapes, list):
        raise ValueError("CVAT annotations contain an invalid shapes list")
    for shape in shapes:
        if not isinstance(shape, Mapping) or shape.get("type") != "rectangle":
            raise ValueError("annotation-assist supports rectangle shapes only")
    return shapes


def _ensure_class_coverage_in_val(
    train: list[int], val: list[int], labels_by_frame: Mapping[int, set[str]], classes: Sequence[str],
) -> tuple[list[int], list[int]]:
    train_set, val_set = set(train), set(val)
    for class_name in classes:
        class_frames = sorted(frame for frame, labels in labels_by_frame.items() if class_name in labels)
        if class_frames and not any(frame in val_set for frame in class_frames):
            candidate = next((frame for frame in class_frames if frame in train_set), None)
            if candidate is not None and len(train_set) > 1:
                train_set.remove(candidate)
                val_set.add(candidate)
        if len(class_frames) > 1 and not any(frame in train_set for frame in class_frames):
            candidate = next((frame for frame in reversed(class_frames) if frame in val_set), None)
            if candidate is not None and len(val_set) > 1:
                val_set.remove(candidate)
                train_set.add(candidate)
    return sorted(train_set), sorted(val_set)


def _hardlink_or_copy(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
        return "hardlink"
    except OSError:
        shutil.copy2(source, destination)
        return "copy"


def snapshot_and_export(config: AssistConfig) -> dict[str, Any]:
    package = config.package.resolve()
    output = config.output.resolve()
    if not (package / "annotation-manifest.json").is_file():
        raise FileNotFoundError(f"annotation package is missing: {package}")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"annotation-assist output is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    client = _client(config.base_url)
    state = _task_state(client, config.task_id)
    locked_annotations = client.get(f"/api/tasks/{config.locked_task_id}/annotations", timeout=180)
    _assert_locked_empty(locked_annotations, config.locked_task_id)

    original_manifest = json.loads((package / "annotation-manifest.json").read_text(encoding="utf-8"))
    original_frames = original_manifest.get("frames")
    original_classes = original_manifest.get("classes")
    if original_classes != list(CANONICAL_CLASSES) or not isinstance(original_frames, list):
        raise ValueError("source package does not match the canonical V9 contract")
    meta_frames = state["meta"].get("frames", [])
    if len(meta_frames) != len(original_frames) or len(meta_frames) < config.boundary:
        raise ValueError("CVAT/source package frame count differs from the annotation-assist boundary")
    for index, (meta, frame) in enumerate(zip(meta_frames, original_frames, strict=True)):
        if str(meta.get("name")) != str(frame.get("imagePath")):
            raise ValueError(f"CVAT/source frame mapping differs at frame {index}")

    label_names = {int(item["id"]): str(item["name"]) for item in state["labels"]}
    if set(label_names.values()) != set(CANONICAL_CLASSES):
        raise ValueError("CVAT task labels differ from the canonical V9 contract")
    shapes = _ensure_rectangle_contract(state["annotations"])
    prefix_shapes = [shape for shape in shapes if int(shape["frame"]) < config.boundary]
    protected_suffix_shapes = [
        shape for shape in shapes
        if int(shape["frame"]) >= config.boundary and str(shape.get("source", "manual")) == "manual"
    ]
    class_counts: Counter[str] = Counter()
    labels_by_frame: dict[int, set[str]] = defaultdict(set)
    shapes_by_frame: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for shape in prefix_shapes:
        frame_index = int(shape["frame"])
        label_name = label_names.get(int(shape["label_id"]))
        if label_name not in CANONICAL_CLASSES:
            raise ValueError(f"reviewed prefix uses unknown label ID {shape['label_id']}")
        if label_name in FORBIDDEN_HELPER_CLASSES:
            raise ValueError("reviewed prefix still contains container_truck; map it to truck before helper training")
        meta = meta_frames[frame_index]
        shape_to_yolo(shape, int(meta["width"]), int(meta["height"]))
        class_counts[label_name] += 1
        labels_by_frame[frame_index].add(label_name)
        shapes_by_frame[frame_index].append(shape)
    helper_classes = [name for name in CANONICAL_CLASSES if class_counts.get(name, 0) and name not in FORBIDDEN_HELPER_CLASSES]
    if not helper_classes:
        raise ValueError("reviewed prefix contains no trainable rectangles")

    train, val = deterministic_split(list(range(config.boundary)), val_stride=7)
    train, val = _ensure_class_coverage_in_val(train, val, labels_by_frame, helper_classes)
    split_by_frame = {frame: "train" for frame in train}
    split_by_frame.update({frame: "val" for frame in val})
    dataset_root = output / "dataset"
    materialized_frames: list[dict[str, Any]] = []
    link_modes: Counter[str] = Counter()
    content_digest = hashlib.sha256()
    for frame_index in range(config.boundary):
        source_frame = original_frames[frame_index]
        source_image = package / str(source_frame["imagePath"])
        if not source_image.is_file():
            raise FileNotFoundError(f"source image is missing: {source_image}")
        split = split_by_frame[frame_index]
        filename = f"{frame_index:04d}-{source_image.name}"
        image_relative = Path("images") / split / filename
        label_relative = Path("labels") / split / f"{Path(filename).stem}.txt"
        link_modes[_hardlink_or_copy(source_image, dataset_root / image_relative)] += 1
        rows: list[str] = []
        for shape in sorted(shapes_by_frame.get(frame_index, []), key=lambda item: (int(item["label_id"]), item["points"])):
            label_name = label_names[int(shape["label_id"])]
            center_x, center_y, width, height = shape_to_yolo(
                shape, int(meta_frames[frame_index]["width"]), int(meta_frames[frame_index]["height"]),
            )
            rows.append(
                f"{helper_classes.index(label_name)} {center_x:.8f} {center_y:.8f} {width:.8f} {height:.8f}\n"
            )
        label_path = dataset_root / label_relative
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_text = "".join(rows)
        label_path.write_text(label_text, encoding="utf-8")
        image_hash = str(source_frame.get("sha256") or _sha256_file(source_image))
        content_digest.update(f"{frame_index}:{image_hash}:{label_text}".encode("utf-8"))
        materialized_frames.append({
            "taskFrame": frame_index,
            "frameId": source_frame["frameId"],
            "sourceImagePath": str(source_frame["imagePath"]),
            "imagePath": image_relative.as_posix(),
            "labelsPath": label_relative.as_posix(),
            "split": split,
            "boxCount": len(rows),
            "width": int(meta_frames[frame_index]["width"]),
            "height": int(meta_frames[frame_index]["height"]),
            "sourceSha256": image_hash,
        })
    names_yaml = "\n".join(f"  {index}: {name}" for index, name in enumerate(helper_classes))
    (dataset_root / "data.yaml").write_text(
        f"path: {dataset_root.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n{names_yaml}\n",
        encoding="utf-8",
    )

    snapshot = {
        "schemaVersion": 1,
        "createdAt": _utc_now(),
        "purpose": "BAI-KIEM V9 temporary annotation helper",
        "taskId": config.task_id,
        "lockedTaskId": config.locked_task_id,
        "boundary": config.boundary,
        "task": state["task"],
        "jobs": state["jobs"],
        "labels": state["labels"],
        "meta": state["meta"],
        "annotations": state["annotations"],
        "lockedAnnotationsAtSnapshot": locked_annotations,
        "prefixShapeHash": canonical_shape_hash(prefix_shapes),
        "protectedSuffixShapeHash": canonical_shape_hash(protected_suffix_shapes),
        "fullShapeHash": canonical_shape_hash(shapes),
        "prefixShapeCount": len(prefix_shapes),
        "protectedSuffixShapeCount": len(protected_suffix_shapes),
        "fullShapeCount": len(shapes),
        "prefixClassCounts": dict(sorted(class_counts.items())),
    }
    _write_json(output / "snapshot" / "task-9-snapshot.json", snapshot)
    _write_json(output / "snapshot" / "rollback-payload.json", {
        "version": state["annotations"].get("version", 0),
        "tags": state["annotations"].get("tags", []),
        "shapes": [_shape_for_put(shape) for shape in shapes],
        "tracks": state["annotations"].get("tracks", []),
    })
    dataset_manifest = {
        "schemaVersion": 1,
        "createdAt": _utc_now(),
        "purpose": "ANNOTATION_ASSIST_ONLY_NOT_FOR_ACTIVATION",
        "sourceTaskId": config.task_id,
        "lockedTaskUsed": False,
        "boundary": config.boundary,
        "classes": helper_classes,
        "classCounts": dict(sorted(class_counts.items())),
        "counts": {"train": len(train), "val": len(val), "total": config.boundary},
        "linkModes": dict(link_modes),
        "contentHash": content_digest.hexdigest(),
        "frames": materialized_frames,
    }
    _write_json(dataset_root / "annotation-assist-manifest.json", dataset_manifest)
    receipt = {
        "stage": "snapshot-export-complete",
        "output": str(output),
        "taskId": config.task_id,
        "boundary": config.boundary,
        "frameCount": config.boundary,
        "shapeCount": len(prefix_shapes),
        "classCounts": dict(sorted(class_counts.items())),
        "helperClasses": helper_classes,
        "trainFrames": len(train),
        "valFrames": len(val),
        "prefixShapeHash": snapshot["prefixShapeHash"],
        "protectedSuffixShapeHash": snapshot["protectedSuffixShapeHash"],
        "protectedSuffixShapeCount": snapshot["protectedSuffixShapeCount"],
        "fullShapeHash": snapshot["fullShapeHash"],
        "lockedTaskEmpty": True,
    }
    _write_json(output / "snapshot-export-receipt.json", receipt)
    return receipt


def _configure_low_resource_process() -> None:
    os.environ.setdefault("OPENCV_FOR_THREADS_NUM", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
        except (AttributeError, OSError):
            pass


def _metric_dict(result: Any) -> dict[str, Any]:
    values = getattr(result, "results_dict", None)
    if isinstance(values, Mapping):
        return {str(key): float(value) for key, value in values.items() if isinstance(value, (int, float))}
    return {}


def train_helper(config: AssistConfig) -> dict[str, Any]:
    output = config.output.resolve()
    dataset_manifest_path = output / "dataset" / "annotation-assist-manifest.json"
    if not dataset_manifest_path.is_file():
        raise FileNotFoundError("snapshot/export stage must complete before training")
    base_model = config.base_model.resolve()
    if not base_model.is_file():
        raise FileNotFoundError(f"annotation-helper initialization checkpoint is missing: {base_model}")
    official_pretrained = base_model.name.casefold() == "yolo11n.pt"
    prior_helper = (
        base_model.name.casefold() == "annotation-helper-best.pt"
        and (base_model.parent.parent / "training-receipt.json").is_file()
    )
    if not official_pretrained and not prior_helper:
        raise ValueError("annotation helper must initialize from yolo11n.pt or a prior isolated annotation helper")
    _configure_low_resource_process()
    import cv2
    import torch
    from ultralytics import YOLO

    cv2.setNumThreads(1)
    torch.set_num_threads(1)
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    device: int | str = 0 if torch.cuda.is_available() else "cpu"
    options = annotation_helper_train_options(
        output / "runs", epochs=config.epochs, device=device,
        boundary=config.boundary, fine_tune=prior_helper,
    )
    started = time.monotonic()
    model = YOLO(str(base_model))
    data_path = (output / "dataset" / "data.yaml").resolve()
    baseline = model.val(
        data=str(data_path), imgsz=896, batch=1, workers=0, device=device,
        plots=False, verbose=False, project=str(output / "baseline"),
        name=f"before-finetune-{config.boundary}", exist_ok=True,
    )
    baseline_metrics = _metric_dict(baseline)
    result = model.train(data=str(data_path), **options)
    save_dir = Path(str(getattr(result, "save_dir", output / "runs" / options["name"])))
    source_best = save_dir / "weights" / "best.pt"
    if not source_best.is_file():
        raise FileNotFoundError(f"Ultralytics did not produce best.pt: {source_best}")
    checkpoint = output / "checkpoint" / "annotation-helper-best.pt"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_best, checkpoint)
    dataset_manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
    trained_metrics = _metric_dict(result)
    receipt = {
        "stage": "training-complete",
        "purpose": "ANNOTATION_ASSIST_ONLY_NOT_FOR_ACTIVATION",
        "createdAt": _utc_now(),
        "baseModel": str(base_model),
        "baseModelSha256": _sha256_file(base_model),
        "initialization": "prior-annotation-helper" if prior_helper else "official-yolo11n-pretrained",
        "checkpoint": str(checkpoint),
        "checkpointSha256": _sha256_file(checkpoint),
        "datasetContentHash": dataset_manifest["contentHash"],
        "classes": dataset_manifest["classes"],
        "classCounts": dataset_manifest["classCounts"],
        "trainingOptions": options,
        "baselineMetrics": baseline_metrics,
        "metrics": trained_metrics,
        "metricDelta": {
            key: round(trained_metrics.get(key, 0.0) - baseline_metrics.get(key, 0.0), 6)
            for key in sorted(set(baseline_metrics).intersection(trained_metrics))
            if key.startswith("metrics/") or key == "fitness"
        },
        "elapsedSeconds": round(time.monotonic() - started, 2),
        "activated": False,
        "lockedTaskUsed": False,
    }
    _write_json(output / "training-receipt.json", receipt)
    return receipt


def _prediction_threshold(class_name: str) -> float:
    return DEFAULT_HELPER_THRESHOLDS.get(class_name, 0.20)


def predict_remaining(config: AssistConfig) -> dict[str, Any]:
    output = config.output.resolve()
    snapshot = json.loads((output / "snapshot" / "task-9-snapshot.json").read_text(encoding="utf-8"))
    dataset_manifest = json.loads((output / "dataset" / "annotation-assist-manifest.json").read_text(encoding="utf-8"))
    checkpoint = output / "checkpoint" / "annotation-helper-best.pt"
    if not checkpoint.is_file():
        raise FileNotFoundError("helper checkpoint is missing")
    original_manifest = json.loads((config.package / "annotation-manifest.json").read_text(encoding="utf-8"))
    proposal_details_path = config.package / "proposal-details.json"
    proposal_details = json.loads(proposal_details_path.read_text(encoding="utf-8")) if proposal_details_path.is_file() else {}
    helper_classes = [str(name) for name in dataset_manifest["classes"]]
    absent_base_classes = set(DEFAULT_BASE_ONLY_THRESHOLDS).difference(helper_classes)
    _configure_low_resource_process()
    import cv2
    import torch
    from ultralytics import YOLO

    cv2.setNumThreads(1)
    torch.set_num_threads(1)
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    device: int | str = 0 if torch.cuda.is_available() else "cpu"
    model = YOLO(str(checkpoint))
    predictions: dict[str, list[dict[str, Any]]] = {}
    class_counts: Counter[str] = Counter()
    started = time.monotonic()
    frames = original_manifest.get("frames", [])
    if len(frames) != len(snapshot["meta"].get("frames", [])):
        raise ValueError("snapshot/source frame count changed before prediction")
    remaining = frames[config.boundary:]
    for position, frame in enumerate(remaining, start=1):
        task_frame = config.boundary + position - 1
        source_image = config.package / str(frame["imagePath"])
        result = model.predict(
            source=str(source_image), imgsz=896, conf=0.08, iou=0.45,
            agnostic_nms=True, max_det=100, device=device, verbose=False,
        )[0]
        candidates: list[dict[str, Any]] = []
        boxes = getattr(result, "boxes", None)
        if boxes is not None:
            class_ids = boxes.cls.detach().cpu().tolist()
            confidences = boxes.conf.detach().cpu().tolist()
            normalized_boxes = boxes.xyxyn.detach().cpu().tolist()
            for class_id, confidence, bbox in zip(class_ids, confidences, normalized_boxes, strict=True):
                class_index = int(class_id)
                if not 0 <= class_index < len(helper_classes):
                    raise ValueError("helper prediction class ID is outside its class map")
                class_name = helper_classes[class_index]
                confidence = float(confidence)
                if class_name in FORBIDDEN_HELPER_CLASSES or confidence < _prediction_threshold(class_name):
                    continue
                values = [max(0.0, min(1.0, float(value))) for value in bbox]
                if values[2] <= values[0] or values[3] <= values[1]:
                    continue
                candidates.append({"class": class_name, "confidence": confidence, "bbox": values, "source": "helper"})
        for item in proposal_details.get(str(frame["frameId"]), []):
            class_name = str(item.get("class"))
            confidence = float(item.get("confidence", 0.0))
            if class_name not in absent_base_classes or confidence < DEFAULT_BASE_ONLY_THRESHOLDS[class_name]:
                continue
            bbox = item.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            values = [max(0.0, min(1.0, float(value))) for value in bbox]
            if values[2] <= values[0] or values[3] <= values[1]:
                continue
            candidates.append({"class": class_name, "confidence": confidence, "bbox": values, "source": "base-fallback"})
        kept = class_agnostic_nms(candidates, iou_threshold=0.45)
        for item in kept:
            class_counts[item["class"]] += 1
        predictions[str(task_frame)] = kept
        if position == 1 or position % 25 == 0 or position == len(remaining):
            print(f"annotation-assist predict {position}/{len(remaining)}", flush=True)
    receipt = {
        "stage": "prediction-complete",
        "createdAt": _utc_now(),
        "taskId": config.task_id,
        "boundary": config.boundary,
        "frameCount": len(remaining),
        "proposalCount": sum(class_counts.values()),
        "classCounts": dict(sorted(class_counts.items())),
        "helperThresholds": {name: _prediction_threshold(name) for name in helper_classes},
        "baseFallbackThresholds": {
            name: DEFAULT_BASE_ONLY_THRESHOLDS[name] for name in sorted(absent_base_classes)
        },
        "crossClassNmsIou": 0.45,
        "checkpointSha256": _sha256_file(checkpoint),
        "elapsedSeconds": round(time.monotonic() - started, 2),
        "lockedTaskUsed": False,
    }
    _write_json(output / "predictions.json", {"receipt": receipt, "frames": predictions})
    _write_json(output / "prediction-receipt.json", receipt)
    return receipt


def audit_frame_indices(*, boundary: int, total_frames: int, limit: int = 12) -> list[int]:
    if boundary < 0 or total_frames <= boundary or limit < 1:
        raise ValueError("audit range must contain at least one remaining frame")
    count = min(limit, total_frames - boundary)
    if count == 1:
        return [boundary]
    last = total_frames - 1
    return sorted({round(boundary + index * (last - boundary) / (count - 1)) for index in range(count)})


def render_audit_montages(config: AssistConfig) -> dict[str, Any]:
    """Render a small cross-source sample for a human sanity check before CVAT mutation."""
    import cv2
    import numpy as np

    output = config.output.resolve()
    prediction_file = json.loads((output / "predictions.json").read_text(encoding="utf-8"))
    source_manifest = json.loads((config.package / "annotation-manifest.json").read_text(encoding="utf-8"))
    frames = source_manifest["frames"]
    selected = audit_frame_indices(boundary=config.boundary, total_frames=len(frames), limit=12)
    colors = {
        "person": (70, 70, 255), "car": (255, 180, 30), "truck": (40, 210, 40),
        "forklift": (210, 70, 210), "reach_stacker": (20, 220, 220),
        "bicycle": (255, 100, 100), "motorcycle": (255, 100, 100), "bus": (50, 160, 255),
    }
    tiles: list[Any] = []
    for frame_index in selected:
        image = cv2.imread(str(config.package / frames[frame_index]["imagePath"]), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"cannot render source frame {frame_index}")
        height, width = image.shape[:2]
        for item in prediction_file["frames"].get(str(frame_index), []):
            x1, y1, x2, y2 = item["bbox"]
            left, top, right, bottom = int(x1 * width), int(y1 * height), int(x2 * width), int(y2 * height)
            label = f"{item['class']} {float(item['confidence']):.2f}"
            color = colors.get(str(item["class"]), (255, 255, 255))
            cv2.rectangle(image, (left, top), (right, bottom), color, max(2, width // 1000))
            cv2.putText(image, label, (left, max(18, top - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
        cv2.putText(image, f"CVAT frame {frame_index}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2, cv2.LINE_AA)
        tiles.append(cv2.resize(image, (777, 456), interpolation=cv2.INTER_AREA))
    audit_dir = output / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    montage_paths: list[str] = []
    for start in range(0, len(tiles), 6):
        group = tiles[start:start + 6]
        while len(group) < 6:
            group.append(np.zeros_like(tiles[0]))
        montage = np.vstack((np.hstack(group[0:2]), np.hstack(group[2:4]), np.hstack(group[4:6])))
        path = audit_dir / f"proposal-montage-{start // 6 + 1}.jpg"
        if not cv2.imwrite(str(path), montage, [cv2.IMWRITE_JPEG_QUALITY, 92]):
            raise OSError(f"failed to write audit montage: {path}")
        montage_paths.append(str(path))
    receipt = {"stage": "audit-render-complete", "frames": selected, "montages": montage_paths}
    _write_json(audit_dir / "audit-render-receipt.json", receipt)
    return receipt


def filter_predictions(config: AssistConfig) -> dict[str, Any]:
    output = config.output.resolve()
    prediction_path = output / "predictions.json"
    raw_path = output / "predictions-low-threshold.json"
    if not raw_path.exists():
        shutil.copy2(prediction_path, raw_path)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    filtered_frames: dict[str, list[dict[str, Any]]] = {}
    class_counts: Counter[str] = Counter()
    empty_frames = 0
    for raw_frame, proposals in payload["frames"].items():
        frame = int(raw_frame)
        kept = filter_proposals_for_review(frame, proposals)
        filtered_frames[str(frame)] = kept
        if not kept:
            empty_frames += 1
        for item in kept:
            class_counts[str(item["class"])] += 1
    receipt = {
        "stage": "prediction-filter-complete",
        "createdAt": _utc_now(),
        "taskId": config.task_id,
        "boundary": config.boundary,
        "frameCount": len(filtered_frames),
        "proposalCountBefore": int(payload["receipt"]["proposalCount"]),
        "proposalCountAfter": sum(class_counts.values()),
        "emptyFramesAfter": empty_frames,
        "classCounts": dict(sorted(class_counts.items())),
        "reviewThresholds": REVIEW_THRESHOLDS,
        "camera2OverlayExclusion": {
            "frames": [244, 511],
            "timestamp": "x1 < 0.35 and y2 <= 0.12",
            "personAboveHorizon": "y2 < 0.30",
        },
    }
    _write_json(prediction_path, {"receipt": receipt, "frames": filtered_frames})
    _write_json(output / "prediction-filter-receipt.json", receipt)
    return receipt


def _prediction_shapes(
    predictions: Mapping[str, Sequence[Mapping[str, Any]]],
    meta_frames: Sequence[Mapping[str, Any]],
    label_ids: Mapping[str, int],
    boundary: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw_frame, items in predictions.items():
        frame = int(raw_frame)
        if frame < boundary or frame >= len(meta_frames):
            raise ValueError(f"prediction targets forbidden frame {frame}")
        width, height = int(meta_frames[frame]["width"]), int(meta_frames[frame]["height"])
        for item in items:
            class_name = str(item["class"])
            if class_name not in label_ids or class_name in FORBIDDEN_HELPER_CLASSES:
                raise ValueError(f"prediction uses unsupported class {class_name!r}")
            x1, y1, x2, y2 = (float(value) for value in item["bbox"])
            result.append({
                "type": "rectangle",
                "frame": frame,
                "label_id": int(label_ids[class_name]),
                "points": [x1 * width, y1 * height, x2 * width, y2 * height],
                "occluded": False,
                "outside": False,
                "z_order": 0,
                "rotation": 0.0,
                "attributes": [],
                "source": "auto",
            })
    return result


def apply_guarded(config: AssistConfig) -> dict[str, Any]:
    output = config.output.resolve()
    snapshot = json.loads((output / "snapshot" / "task-9-snapshot.json").read_text(encoding="utf-8"))
    prediction_file = json.loads((output / "predictions.json").read_text(encoding="utf-8"))
    client = _client(config.base_url)
    live = _task_state(client, config.task_id)
    locked_before = client.get(f"/api/tasks/{config.locked_task_id}/annotations", timeout=180)
    _assert_locked_empty(locked_before, config.locked_task_id)
    live_shapes = _ensure_rectangle_contract(live["annotations"])
    live_prefix = [shape for shape in live_shapes if int(shape["frame"]) < config.boundary]
    live_protected_suffix = [
        shape for shape in live_shapes
        if int(shape["frame"]) >= config.boundary and str(shape.get("source", "manual")) == "manual"
    ]
    if canonical_shape_hash(live_prefix) != snapshot["prefixShapeHash"]:
        raise RuntimeError("reviewed prefix changed after snapshot; refusing to overwrite CVAT")
    if canonical_shape_hash(live_shapes) != snapshot["fullShapeHash"]:
        raise RuntimeError("task annotations changed after snapshot; refusing to overwrite CVAT")
    if canonical_shape_hash(live_protected_suffix) != snapshot.get("protectedSuffixShapeHash"):
        raise RuntimeError("protected manual suffix changed after snapshot; refusing to overwrite CVAT")
    live_label_ids = {str(item["name"]): int(item["id"]) for item in live["labels"]}
    prediction_shapes = _prediction_shapes(
        prediction_file["frames"], live["meta"].get("frames", []), live_label_ids, config.boundary,
    )
    merged = merge_preserving_prefix(
        live_shapes, prediction_shapes, boundary=config.boundary, preserve_manual_suffix=True,
    )
    expected_prefix_hash = canonical_shape_hash(shape for shape in merged if int(shape["frame"]) < config.boundary)
    expected_protected_hash = canonical_shape_hash(
        shape for shape in merged
        if int(shape["frame"]) >= config.boundary and str(shape.get("source")) == "manual"
    )
    expected_full_hash = canonical_shape_hash(merged)
    payload = {
        "version": live["annotations"].get("version", 0),
        "tags": [],
        "shapes": merged,
        "tracks": [],
    }
    _write_json(output / "apply-payload.json", payload)
    client.put(f"/api/tasks/{config.task_id}/annotations/", payload, timeout=300)
    after = client.get(f"/api/tasks/{config.task_id}/annotations", timeout=180)
    after_shapes = _ensure_rectangle_contract(after)
    after_prefix = [shape for shape in after_shapes if int(shape["frame"]) < config.boundary]
    after_protected_suffix = [
        shape for shape in after_shapes
        if int(shape["frame"]) >= config.boundary and str(shape.get("source", "manual")) == "manual"
    ]
    try:
        if canonical_shape_hash(after_prefix) != expected_prefix_hash or expected_prefix_hash != snapshot["prefixShapeHash"]:
            raise RuntimeError("post-apply reviewed-prefix verification failed")
        if canonical_shape_hash(after_shapes) != expected_full_hash:
            raise RuntimeError("post-apply full-task verification failed")
        if (
            canonical_shape_hash(after_protected_suffix) != expected_protected_hash
            or expected_protected_hash != snapshot.get("protectedSuffixShapeHash")
        ):
            raise RuntimeError("post-apply protected-manual-suffix verification failed")
        locked_after = client.get(f"/api/tasks/{config.locked_task_id}/annotations", timeout=180)
        _assert_locked_empty(locked_after, config.locked_task_id)
    except Exception:
        rollback = json.loads((output / "snapshot" / "rollback-payload.json").read_text(encoding="utf-8"))
        rollback["version"] = after.get("version", 0)
        client.put(f"/api/tasks/{config.task_id}/annotations/", rollback, timeout=300)
        raise
    label_names = {int(item["id"]): str(item["name"]) for item in live["labels"]}
    remaining_counts = Counter(
        label_names[int(shape["label_id"])] for shape in after_shapes if int(shape["frame"]) >= config.boundary
    )
    receipt = {
        "stage": "apply-complete",
        "createdAt": _utc_now(),
        "taskId": config.task_id,
        "boundary": config.boundary,
        "reviewedPrefixShapeCount": len(after_prefix),
        "reviewedPrefixShapeHashBefore": snapshot["prefixShapeHash"],
        "reviewedPrefixShapeHashAfter": canonical_shape_hash(after_prefix),
        "reviewedPrefixUnchanged": True,
        "protectedSuffixShapeCount": len(after_protected_suffix),
        "protectedSuffixShapeHashBefore": snapshot.get("protectedSuffixShapeHash"),
        "protectedSuffixShapeHashAfter": canonical_shape_hash(after_protected_suffix),
        "protectedSuffixUnchanged": True,
        "remainingProposalCount": sum(remaining_counts.values()),
        "remainingClassCounts": dict(sorted(remaining_counts.items())),
        "fullShapeCountBefore": snapshot["fullShapeCount"],
        "fullShapeCountAfter": len(after_shapes),
        "lockedTaskId": config.locked_task_id,
        "lockedTaskEmpty": True,
        "helperActivated": False,
        "resumeUrl": f"{config.base_url.rstrip('/')}/tasks/{config.task_id}/jobs/8?frame={config.boundary}",
    }
    _write_json(output / "apply-receipt.json", receipt)
    return receipt


def restore_snapshot(config: AssistConfig) -> dict[str, Any]:
    output = config.output.resolve()
    snapshot = json.loads((output / "snapshot" / "task-9-snapshot.json").read_text(encoding="utf-8"))
    rollback = json.loads((output / "snapshot" / "rollback-payload.json").read_text(encoding="utf-8"))
    client = _client(config.base_url)
    live = client.get(f"/api/tasks/{config.task_id}/annotations", timeout=180)
    rollback["version"] = live.get("version", 0)
    client.put(f"/api/tasks/{config.task_id}/annotations/", rollback, timeout=300)
    restored = client.get(f"/api/tasks/{config.task_id}/annotations", timeout=180)
    restored_shapes = _ensure_rectangle_contract(restored)
    if canonical_shape_hash(restored_shapes) != snapshot["fullShapeHash"]:
        raise RuntimeError("snapshot restore verification failed")
    receipt = {"stage": "restore-complete", "taskId": config.task_id, "shapeCount": len(restored_shapes)}
    _write_json(output / "restore-receipt.json", receipt)
    return receipt


def _config(args: argparse.Namespace) -> AssistConfig:
    return AssistConfig(
        package=args.package.resolve(), output=args.output.resolve(), base_model=args.base_model.resolve(),
        base_url=args.base_url, task_id=args.task_id, locked_task_id=args.locked_task_id,
        boundary=args.boundary, epochs=args.epochs,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("snapshot", "train", "predict", "filter", "audit", "apply", "restore"))
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-model", type=Path, default=Path("yolo11n.pt"))
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--task-id", type=int, default=9)
    parser.add_argument("--locked-task-id", type=int, default=10)
    parser.add_argument("--boundary", type=int, default=210)
    parser.add_argument("--epochs", type=int, default=40)
    args = parser.parse_args()
    config = _config(args)
    operations = {
        "snapshot": snapshot_and_export,
        "train": train_helper,
        "predict": predict_remaining,
        "filter": filter_predictions,
        "audit": render_audit_montages,
        "apply": apply_guarded,
        "restore": restore_snapshot,
    }
    result = operations[args.stage](config)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
