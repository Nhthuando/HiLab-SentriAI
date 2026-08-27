"""Bounded, opt-in ROI tile scheduling for Area detection.

The module is intentionally detector-agnostic.  Callers provide a callback for
the registry-enabled base and/or custom detector, and receive candidates in
full-frame coordinates.  No tracker, model, or persistence state is owned here.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence

import numpy as np


DEFAULT_ROI_INTERVAL = 3
DEFAULT_ROI_TILE_SIZE = 640
DEFAULT_ROI_TILE_OVERLAP = 0.20
DEFAULT_ROI_MAX_TILES = 8
DEFAULT_DEDUPE_IOU = 0.50
ALLOWED_DETECTORS = frozenset({"base", "custom"})
GENERIC_COCO_VEHICLES = frozenset({"car", "bus", "truck"})


class RoiConfigurationError(ValueError):
    """Raised when ROI inference configuration could broaden inference unsafely."""


def _finite_number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RoiConfigurationError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise RoiConfigurationError(f"{field} must be a finite number")
    return number


@dataclass(frozen=True, slots=True)
class RoiSpec:
    name: str
    polygon: Sequence[tuple[float, float]]
    detectors: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise RoiConfigurationError("ROI name must be a non-empty string")
        if isinstance(self.polygon, (str, bytes)) or len(self.polygon) < 3:
            raise RoiConfigurationError(f"ROI {self.name!r} polygon requires at least three points")

        normalized_points: list[tuple[float, float]] = []
        for index, point in enumerate(self.polygon):
            if isinstance(point, (str, bytes)) or not isinstance(point, Sequence) or len(point) != 2:
                raise RoiConfigurationError(f"ROI {self.name!r} point {index} must be [x, y]")
            x = _finite_number(point[0], field=f"ROI {self.name!r} point {index}.x")
            y = _finite_number(point[1], field=f"ROI {self.name!r} point {index}.y")
            if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
                raise RoiConfigurationError(f"ROI {self.name!r} points must stay inside [0,1]")
            normalized_points.append((x, y))

        signed_area = sum(
            normalized_points[index][0] * normalized_points[(index + 1) % len(normalized_points)][1]
            - normalized_points[(index + 1) % len(normalized_points)][0] * normalized_points[index][1]
            for index in range(len(normalized_points))
        )
        if abs(signed_area) <= 1e-12:
            raise RoiConfigurationError(f"ROI {self.name!r} polygon must have non-zero area")

        if not isinstance(self.detectors, (set, frozenset, list, tuple)):
            raise RoiConfigurationError(f"ROI {self.name!r} detectors must be a list")
        normalized_detectors = frozenset(
            detector.strip().casefold() if isinstance(detector, str) else ""
            for detector in self.detectors
        )
        if not normalized_detectors or not normalized_detectors.issubset(ALLOWED_DETECTORS):
            raise RoiConfigurationError(
                f"ROI {self.name!r} detectors must contain only base and/or custom"
            )
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "polygon", tuple(normalized_points))
        object.__setattr__(self, "detectors", normalized_detectors)


@dataclass(frozen=True, slots=True)
class TileWindow:
    roi_name: str
    x1: int
    y1: int
    x2: int
    y2: int

    def __post_init__(self) -> None:
        if not isinstance(self.roi_name, str) or not self.roi_name:
            raise RoiConfigurationError("tile roi_name must be non-empty")
        coordinates = (self.x1, self.y1, self.x2, self.y2)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in coordinates):
            raise RoiConfigurationError("tile coordinates must be integers")
        if self.x1 < 0 or self.y1 < 0 or self.x2 <= self.x1 or self.y2 <= self.y1:
            raise RoiConfigurationError("tile coordinates must describe a positive clipped rectangle")


def _validate_tile_settings(tile_size: int, overlap: float, max_tiles: int) -> tuple[int, float, int]:
    if isinstance(tile_size, bool) or not isinstance(tile_size, int) or tile_size <= 0:
        raise RoiConfigurationError("AREA_ROI_TILE_SIZE must be a positive integer")
    overlap_value = _finite_number(overlap, field="AREA_ROI_TILE_OVERLAP")
    if not 0.0 <= overlap_value < 0.5:
        raise RoiConfigurationError("AREA_ROI_TILE_OVERLAP must be in [0,0.5)")
    if isinstance(max_tiles, bool) or not isinstance(max_tiles, int) or max_tiles <= 0:
        raise RoiConfigurationError("AREA_ROI_MAX_TILES must be a positive integer")
    return tile_size, overlap_value, max_tiles


def _axis_positions(start: int, end: int, frame_extent: int, tile_extent: int, step: int) -> list[int]:
    window = min(frame_extent, tile_extent)
    first = max(0, min(start, frame_extent - window))
    last = max(0, min(end - window, frame_extent - window))
    if last <= first:
        return [first]
    positions = list(range(first, last + 1, step))
    if positions[-1] != last:
        positions.append(last)
    return positions


def build_tiles(
    frame_width: int,
    frame_height: int,
    rois: Sequence[RoiSpec],
    *,
    tile_size: int = DEFAULT_ROI_TILE_SIZE,
    overlap: float = DEFAULT_ROI_TILE_OVERLAP,
    max_tiles: int = DEFAULT_ROI_MAX_TILES,
    detector: str | None = None,
) -> list[TileWindow]:
    """Build deterministic, frame-clipped windows over ROI bounding rectangles."""

    if (
        isinstance(frame_width, bool)
        or not isinstance(frame_width, int)
        or frame_width <= 0
        or isinstance(frame_height, bool)
        or not isinstance(frame_height, int)
        or frame_height <= 0
    ):
        raise ValueError("frame dimensions must be positive integers")
    tile_size, overlap, max_tiles = _validate_tile_settings(tile_size, overlap, max_tiles)
    if detector is not None and detector not in ALLOWED_DETECTORS:
        raise RoiConfigurationError("detector must be base or custom")
    step = max(1, int(round(tile_size * (1.0 - overlap))))

    windows: list[TileWindow] = []
    seen: set[tuple[str, int, int, int, int]] = set()
    for roi in rois:
        if not isinstance(roi, RoiSpec):
            raise RoiConfigurationError("rois must contain RoiSpec values")
        if detector is not None and detector not in roi.detectors:
            continue
        xs = [point[0] for point in roi.polygon]
        ys = [point[1] for point in roi.polygon]
        start_x = max(0, min(frame_width - 1, int(math.floor(min(xs) * frame_width))))
        start_y = max(0, min(frame_height - 1, int(math.floor(min(ys) * frame_height))))
        end_x = max(start_x + 1, min(frame_width, int(math.ceil(max(xs) * frame_width))))
        end_y = max(start_y + 1, min(frame_height, int(math.ceil(max(ys) * frame_height))))
        x_positions = _axis_positions(start_x, end_x, frame_width, tile_size, step)
        y_positions = _axis_positions(start_y, end_y, frame_height, tile_size, step)
        for y1 in y_positions:
            for x1 in x_positions:
                window = TileWindow(
                    roi.name,
                    x1,
                    y1,
                    min(frame_width, x1 + tile_size),
                    min(frame_height, y1 + tile_size),
                )
                key = (window.roi_name, window.x1, window.y1, window.x2, window.y2)
                if key in seen:
                    continue
                seen.add(key)
                windows.append(window)
                if len(windows) >= max_tiles:
                    return windows
    return windows


def remap_detection(
    detection: Mapping[str, object],
    tile: TileWindow,
    *,
    frame_width: int,
    frame_height: int,
) -> dict[str, object]:
    """Return a detection copied from tile-local to clipped full-frame coordinates."""

    bbox = detection.get("bbox")
    if isinstance(bbox, (str, bytes)) or not isinstance(bbox, Sequence) or len(bbox) < 4:
        raise ValueError("ROI detection bbox must contain four coordinates")
    try:
        local = [float(value) for value in bbox[:4]]
    except (TypeError, ValueError) as error:
        raise ValueError("ROI detection bbox coordinates must be numeric") from error
    if not all(math.isfinite(value) for value in local):
        raise ValueError("ROI detection bbox coordinates must be finite")

    tile_width = tile.x2 - tile.x1
    tile_height = tile.y2 - tile.y1
    x1 = max(0, min(frame_width - 1, int(round(max(0.0, min(float(tile_width), local[0]))) + tile.x1)))
    y1 = max(0, min(frame_height - 1, int(round(max(0.0, min(float(tile_height), local[1]))) + tile.y1)))
    x2 = max(1, min(frame_width, int(round(max(0.0, min(float(tile_width), local[2]))) + tile.x1)))
    y2 = max(1, min(frame_height, int(round(max(0.0, min(float(tile_height), local[3]))) + tile.y1)))
    if x2 <= x1 or y2 <= y1:
        raise ValueError("ROI detection bbox is empty after clipping")

    output = dict(detection)
    output["bbox"] = [x1, y1, x2, y2]
    output["normalized_bbox"] = [
        round(x1 / frame_width, 4),
        round(y1 / frame_height, 4),
        round(x2 / frame_width, 4),
        round(y2 / frame_height, 4),
    ]
    output["roiName"] = tile.roi_name
    output["roiTile"] = [tile.x1, tile.y1, tile.x2, tile.y2]
    return output


def _bbox(detection: Mapping[str, object]) -> list[float] | None:
    value = detection.get("bbox")
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) < 4:
        return None
    try:
        box = [float(item) for item in value[:4]]
    except (TypeError, ValueError):
        return None
    return box if all(math.isfinite(item) for item in box) and box[2] > box[0] and box[3] > box[1] else None


def _iou(first: Sequence[float], second: Sequence[float]) -> float:
    intersection = max(0.0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0.0, min(first[3], second[3]) - max(first[1], second[1])
    )
    if intersection <= 0.0:
        return 0.0
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / max(1e-9, first_area + second_area - intersection)


def _candidate_priority(detection: Mapping[str, object]) -> tuple[int, int, float]:
    return (
        1 if detection.get("customConfirmed") is True else 0,
        1 if detection.get("trackId") is not None else 0,
        float(detection.get("confidence") or 0.0),
    )


def class_aware_deduplicate(
    detections: Iterable[Mapping[str, object]],
    *,
    iou_threshold: float = DEFAULT_DEDUPE_IOU,
) -> list[dict[str, object]]:
    """Deduplicate exact classes and apply only confirmed Task-6 supersession.

    Different semantic classes remain independent.  The sole cross-class rule
    mirrors the detector policy: a confirmed custom distinction may replace an
    overlapping generic COCO vehicle.
    """

    threshold = _finite_number(iou_threshold, field="dedupe IoU")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("dedupe IoU must be in [0,1]")
    ordered = sorted((dict(item) for item in detections), key=_candidate_priority, reverse=True)
    kept: list[dict[str, object]] = []
    for candidate in ordered:
        candidate_box = _bbox(candidate)
        canonical = str(candidate.get("canonicalClass") or candidate.get("class") or "")
        if candidate_box is None or not canonical:
            continue
        discard = False
        replace_indices: list[int] = []
        for index, existing in enumerate(kept):
            existing_box = _bbox(existing)
            if existing_box is None or _iou(candidate_box, existing_box) < threshold:
                continue
            existing_class = str(existing.get("canonicalClass") or existing.get("class") or "")
            if canonical == existing_class:
                discard = True
                break
            candidate_supersedes = (
                candidate.get("customConfirmed") is True
                and canonical not in GENERIC_COCO_VEHICLES
                and existing_class in GENERIC_COCO_VEHICLES
            )
            existing_supersedes = (
                existing.get("customConfirmed") is True
                and existing_class not in GENERIC_COCO_VEHICLES
                and canonical in GENERIC_COCO_VEHICLES
            )
            if candidate_supersedes:
                replace_indices.append(index)
            elif existing_supersedes:
                discard = True
                break
        if discard:
            continue
        for index in reversed(replace_indices):
            kept.pop(index)
        kept.append(candidate)
    return kept


def _point_in_polygon(x: float, y: float, polygon: Sequence[tuple[float, float]]) -> bool:
    """Boundary-inclusive ray casting without adding a geometry dependency."""

    inside = False
    previous_x, previous_y = polygon[-1]
    for current_x, current_y in polygon:
        cross = (current_x - previous_x) * (y - previous_y) - (current_y - previous_y) * (x - previous_x)
        if abs(cross) <= 1e-9 and min(previous_x, current_x) - 1e-9 <= x <= max(previous_x, current_x) + 1e-9 and min(previous_y, current_y) - 1e-9 <= y <= max(previous_y, current_y) + 1e-9:
            return True
        if (current_y > y) != (previous_y > y):
            intersection_x = (previous_x - current_x) * (y - current_y) / (previous_y - current_y) + current_x
            if x < intersection_x:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside


DetectorCallback = Callable[[np.ndarray], Iterable[Mapping[str, object]]]


@dataclass(slots=True)
class RoiScheduler:
    enabled: bool = False
    rois: Sequence[RoiSpec] = ()
    interval: int = DEFAULT_ROI_INTERVAL
    tile_size: int = DEFAULT_ROI_TILE_SIZE
    overlap: float = DEFAULT_ROI_TILE_OVERLAP
    max_tiles: int = DEFAULT_ROI_MAX_TILES
    dedupe_iou: float = DEFAULT_DEDUPE_IOU
    _inference_count: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise RoiConfigurationError("AREA_ROI_ENABLED must be a boolean")
        if isinstance(self.interval, bool) or not isinstance(self.interval, int) or self.interval <= 0:
            raise RoiConfigurationError("AREA_ROI_INTERVAL must be a positive integer")
        self.tile_size, self.overlap, self.max_tiles = _validate_tile_settings(
            self.tile_size, self.overlap, self.max_tiles
        )
        if any(not isinstance(roi, RoiSpec) for roi in self.rois):
            raise RoiConfigurationError("rois must contain RoiSpec values")
        self.rois = tuple(self.rois)
        names = [roi.name.casefold() for roi in self.rois]
        if len(names) != len(set(names)):
            raise RoiConfigurationError("ROI names must be unique ignoring case")
        threshold = _finite_number(self.dedupe_iou, field="dedupe IoU")
        if not 0.0 <= threshold <= 1.0:
            raise RoiConfigurationError("dedupe IoU must be in [0,1]")
        self.dedupe_iou = threshold
        self._inference_count = 0

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> "RoiScheduler":
        values = os.environ if environment is None else environment
        enabled = _parse_bool(values.get("AREA_ROI_ENABLED"), default=False)
        raw_config = values.get("AREA_ROI_CONFIG_JSON", "[]")
        try:
            decoded = json.loads(raw_config or "[]")
        except json.JSONDecodeError as error:
            raise RoiConfigurationError("AREA_ROI_CONFIG_JSON must be valid JSON") from error
        if not isinstance(decoded, list):
            raise RoiConfigurationError("AREA_ROI_CONFIG_JSON must decode to a list")
        rois: list[RoiSpec] = []
        for index, item in enumerate(decoded):
            if not isinstance(item, dict) or set(item) != {"name", "polygon", "detectors"}:
                raise RoiConfigurationError(
                    f"AREA_ROI_CONFIG_JSON[{index}] must contain exactly name, polygon, and detectors"
                )
            rois.append(RoiSpec(item["name"], item["polygon"], item["detectors"]))
        return cls(
            enabled=enabled,
            rois=tuple(rois),
            interval=_parse_positive_int(values.get("AREA_ROI_INTERVAL"), "AREA_ROI_INTERVAL", DEFAULT_ROI_INTERVAL),
            tile_size=_parse_positive_int(values.get("AREA_ROI_TILE_SIZE"), "AREA_ROI_TILE_SIZE", DEFAULT_ROI_TILE_SIZE),
            overlap=_parse_float(values.get("AREA_ROI_TILE_OVERLAP"), "AREA_ROI_TILE_OVERLAP", DEFAULT_ROI_TILE_OVERLAP),
            max_tiles=_parse_positive_int(values.get("AREA_ROI_MAX_TILES"), "AREA_ROI_MAX_TILES", DEFAULT_ROI_MAX_TILES),
        )

    def should_run(self, frame_index: int) -> bool:
        if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
            raise ValueError("frame_index must be a non-negative integer")
        return self.enabled and bool(self.rois) and frame_index > 0 and frame_index % self.interval == 0

    @property
    def inference_index(self) -> int:
        """Monotonic count of ROI inference opportunities that actually ran."""

        return self._inference_count

    def infer(
        self,
        frame: np.ndarray,
        *,
        frame_index: int,
        callbacks: Mapping[str, DetectorCallback],
    ) -> list[dict[str, object]]:
        """Run scoped tile callbacks and return full-frame candidates."""

        if not self.should_run(frame_index):
            return []
        if not isinstance(frame, np.ndarray) or frame.ndim < 2 or frame.shape[0] <= 0 or frame.shape[1] <= 0:
            raise ValueError("frame must be a non-empty numpy image")
        unsupported = set(callbacks).difference(ALLOWED_DETECTORS)
        if unsupported:
            raise ValueError("callbacks may contain only base and custom")

        self._inference_count += 1
        height, width = frame.shape[:2]
        roi_by_name = {roi.name: roi for roi in self.rois}
        candidates: list[dict[str, object]] = []
        # The cap applies globally, not once per detector. A shared tile executes
        # each requested engine while counting as one bounded spatial window.
        tiles = build_tiles(
            width,
            height,
            self.rois,
            tile_size=self.tile_size,
            overlap=self.overlap,
            max_tiles=self.max_tiles,
        )
        for tile in tiles:
            roi = roi_by_name[tile.roi_name]
            crop = frame[tile.y1:tile.y2, tile.x1:tile.x2]
            for detector in sorted(roi.detectors):
                callback = callbacks.get(detector)
                if callback is None:
                    continue
                for detection in callback(crop):
                    try:
                        remapped = remap_detection(
                            detection,
                            tile,
                            frame_width=width,
                            frame_height=height,
                        )
                    except ValueError:
                        continue
                    bbox = remapped["normalized_bbox"]
                    center_x = (float(bbox[0]) + float(bbox[2])) / 2.0
                    center_y = (float(bbox[1]) + float(bbox[3])) / 2.0
                    if not _point_in_polygon(center_x, center_y, roi.polygon):
                        continue
                    remapped["roiDetector"] = detector
                    remapped["roiInferenceIndex"] = self._inference_count
                    candidates.append(remapped)
        return class_aware_deduplicate(candidates, iou_threshold=self.dedupe_iou)


def _parse_bool(raw: object, *, default: bool) -> bool:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    if not isinstance(raw, str):
        raise RoiConfigurationError("AREA_ROI_ENABLED must be true or false")
    normalized = raw.strip().casefold()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise RoiConfigurationError("AREA_ROI_ENABLED must be true or false")


def _parse_positive_int(raw: object, name: str, default: int) -> int:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    if not isinstance(raw, str):
        raise RoiConfigurationError(f"{name} must be a positive integer")
    try:
        value = int(raw)
    except ValueError as error:
        raise RoiConfigurationError(f"{name} must be a positive integer") from error
    if value <= 0:
        raise RoiConfigurationError(f"{name} must be a positive integer")
    return value


def _parse_float(raw: object, name: str, default: float) -> float:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    if not isinstance(raw, str):
        raise RoiConfigurationError(f"{name} must be a number")
    try:
        return float(raw)
    except ValueError as error:
        raise RoiConfigurationError(f"{name} must be a number") from error
