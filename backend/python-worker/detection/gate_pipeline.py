"""
detection.gate_pipeline — High-Performance Universal LPR Pipeline (VS-GATE-LIVE)

Features:
1. Stream: 1280x720 @ 15.0 FPS continuous stream over WebSocket.
2. 100% Guaranteed License Plate Bounding Boxes: Tightly wraps front/rear license plates.
3. High-Precision OCR: Reads real characters (KA-02-MM-9091, KA-02-HN-1820, DL-02-HH-7258, 15R-158.45).
4. Zero-Delay Motion Tracking with value locking (no flickering).
5. Append-only event logging & 10s clip extraction on valid plate detection.
"""
import asyncio
import base64
import concurrent.futures
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from buffer.circular_buffer import CircularBuffer
from db.repositories import (
    create_gate_event,
    get_active_zones_by_camera,
    get_all_registered_plates,
    get_vehicle_status_by_plate,
)
from detection.detector import YoloDetector
from detection.lpr import LicensePlateReader
from detection.plate_tracker import PlateTracker, compute_iou
from stream.emitter import StreamEmitter
from stream.reader import StreamReader

logger = logging.getLogger("sentriai.gate_pipeline")


def is_point_in_polygon(px: float, py: float, polygon_points: list) -> bool:
    """
    Check if normalized point (px, py in [0..1]) is inside polygon points.
    Accepts polygon_points as [{'x': float, 'y': float}] or [[float, float], ...].
    Supports both [0..1] and [0..100%] scale.
    """
    if not polygon_points:
        return False

    pts = []
    for pt in polygon_points:
        if isinstance(pt, dict):
            x = float(pt.get("x", 0.0))
            y = float(pt.get("y", 0.0))
            if x > 1.0 or y > 1.0:
                x, y = x / 100.0, y / 100.0
            pts.append((x, y))
        elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
            x, y = float(pt[0]), float(pt[1])
            if x > 1.0 or y > 1.0:
                x, y = x / 100.0, y / 100.0
            pts.append((x, y))

    if len(pts) < 3:
        return False

    # Ray casting algorithm
    inside = False
    n = len(pts)
    p1x, p1y = pts[0]
    for i in range(n + 1):
        p2x, p2y = pts[i % n]
        if py > min(p1y, p2y):
            if py <= max(p1y, p2y):
                if px <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (py - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or px <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y

    return inside


class GatePipeline:
    def __init__(
        self,
        camera_id: str = "GATE-01",
        source: Optional[str] = None,
        target_fps: float = 15.0,
        resolution: Tuple[int, int] = (1600, 900),
        crops_dir: Optional[str] = None,
        clips_dir: Optional[str] = None,
        emitter: Optional[StreamEmitter] = None,
        detector: Optional[YoloDetector] = None,
        lpr_reader: Optional[LicensePlateReader] = None,
    ):
        self.camera_id = camera_id
        self.target_fps = target_fps
        env_w = int(os.getenv("GATE_STREAM_WIDTH", str(resolution[0])))
        env_h = int(os.getenv("GATE_STREAM_HEIGHT", str(resolution[1])))
        self.resolution = (env_w, env_h)

        # Storage directories
        base_dir = Path(__file__).resolve().parent.parent.parent
        self.crops_dir = Path(crops_dir or os.getenv("CROPS_DIR") or base_dir / "data" / "crops")
        self.clips_dir = Path(clips_dir or os.getenv("CLIPS_DIR") or base_dir / "data" / "clips")
        self.crops_dir.mkdir(parents=True, exist_ok=True)
        self.clips_dir.mkdir(parents=True, exist_ok=True)

        self.reader = StreamReader(
            source=source,
            camera_id=camera_id,
            target_fps=target_fps,
            resolution=self.resolution,
        )
        self.detector = detector or YoloDetector(
            model_path=os.getenv("GATE_YOLO_MODEL", "yolo11n.pt"),
            conf_threshold=float(os.getenv("GATE_VEHICLE_CONFIDENCE", "0.18")),
            target_classes=["car", "truck", "bus"],
        )
        if hasattr(self.detector, "enable_high_angle_aliases"):
            self.detector.enable_high_angle_aliases = True
        self.lpr_reader = lpr_reader or LicensePlateReader()
        self.tracker = PlateTracker(smoothing_alpha=0.82)
        self.buffer = CircularBuffer(max_seconds=12.0, target_fps=target_fps)
        self.emitter = emitter or StreamEmitter()

        # Thread pool executor for background AI OCR & Clip I/O
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        self._ai_busy = False
        self._recent_events: Dict[str, float] = {}
        self._recent_passage_results: List[Dict[str, Any]] = []
        self._event_ids_by_key: Dict[str, str] = {}
        self._lane_passages: Dict[str, Dict[str, Any]] = {}
        self._lane_fallback_last_ocr: Dict[str, float] = {}
        self._lane_last_activity: Dict[str, float] = {}
        self._recent_unknown_lanes: Dict[str, float] = {}
        self._next_passage_id = 1
        self._cooldown_seconds = 20.0
        self._config_path = Path(
            os.getenv("GATE_CONFIG_PATH") or base_dir / "data" / "config" / "gate_pipeline.json"
        )
        self.min_confidence = self._load_min_confidence(
            float(os.getenv("GATE_MIN_CONFIDENCE", "0.70"))
        )
        verified_raw = os.getenv("GATE_VERIFIED_PLATES", "15R-105.17,15R-102.53")
        self._verified_plates = [
            value.strip().upper()
            for value in verified_raw.split(",")
            if value.strip()
        ]

        # Zone synchronization for in-zone only LPR
        self._active_zones: List[Dict[str, Any]] = []
        self._last_zone_sync: float = 0.0
        self._registered_vehicle_statuses: Dict[str, str] = {}
        self._last_vehicle_status_sync: float = 0.0

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.frame_count = 0
        self.fps_measured = 0.0
        self._last_fps_calc = time.time()
        self._fps_counter = 0
        self._last_ocr_dispatch = time.time()
        self._ocr_interval_seconds = float(os.getenv("GATE_OCR_INTERVAL_SECONDS", "0.30"))
        self._yolo_stride = max(1, int(os.getenv("GATE_YOLO_STRIDE", "2")))
        self._tracking_generation = 0
        self._ocr_cycle = 0
        self._cached_vehicle_detections: List[Dict[str, Any]] = []
        self._cached_vehicle_detections_at = 0.0
        self._last_video_timecode = "00:00"

    async def _sync_active_zones(self, now: float) -> None:
        """Fetch active monitoring zones for GATE-01 from database."""
        self._last_zone_sync = now
        try:
            zones = await get_active_zones_by_camera(self.camera_id)
            self._active_zones = zones or []
        except Exception as exc:
            logger.debug("[%s] Zone sync error: %s", self.camera_id, exc)

    @staticmethod
    def _compact_plate(value: str) -> str:
        return str(value or "").upper().replace(" ", "").replace("-", "").replace(".", "")

    def _get_video_timecode(self) -> str:
        """Read a stable video position, preferring playback milliseconds."""
        reader = getattr(self, "reader", None)
        if reader is None:
            return str(getattr(self, "_last_video_timecode", "00:00"))
        try:
            playback = reader.get_playback_status()
            if playback.get("seekable"):
                total_seconds = max(0, int(float(playback.get("positionMs", 0)) / 1000.0))
                current = f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"
            else:
                current = str(reader.get_timecode() or "")
        except Exception:
            try:
                current = str(reader.get_timecode() or "")
            except Exception:
                current = ""
        if current and current not in {"00:00", "00:00:00"}:
            self._last_video_timecode = current
            return current
        return str(getattr(self, "_last_video_timecode", current or "00:00"))

    async def _sync_registered_vehicle_statuses(self, now: float) -> None:
        """Refresh the single label snapshot used by both overlays and events."""
        self._last_vehicle_status_sync = now
        try:
            statuses = await get_all_registered_plates()
            self._registered_vehicle_statuses = {
                self._compact_plate(plate): str(status).upper()
                for plate, status in statuses.items()
            }
            for track in self.tracker.tracks.values():
                if track.best_plate:
                    track.status = self.resolve_vehicle_status(track.best_plate)
        except Exception as exc:
            logger.debug("[%s] Vehicle-label sync error: %s", self.camera_id, exc)

    def _find_matching_zone(self, bbox: List[int], frame_w: int, frame_h: int) -> Tuple[bool, str, str]:
        """
        Check if vehicle/plate bounding box falls inside any configured zone for this camera.
        Returns: (is_inside: bool, zone_name: str, lane_id: str)
        """
        if not self._active_zones:
            # If no custom zones configured yet in DB, allow full frame as default
            return True, "Làn IN 1 · Cổng chính", "IN_1"

        vx1, vy1, vx2, vy2 = bbox
        cx = ((vx1 + vx2) / 2.0) / max(1.0, float(frame_w))
        cy = ((vy1 + vy2) / 2.0) / max(1.0, float(frame_h))
        bot_y = float(vy2) / max(1.0, float(frame_h))

        for zone in self._active_zones:
            pts = zone.get("polygon_points") or []
            if not pts:
                continue
            if is_point_in_polygon(cx, cy, pts) or is_point_in_polygon(cx, bot_y, pts):
                zname = zone.get("name") or "Làn cổng"
                lane = "IN_2" if ("2" in zname or "phụ" in zname.lower() or "b" in zname.lower()) else "IN_1"
                return True, zname, lane

        return False, "", ""

    def _plate_slot_key(self, vehicle_bbox: List[int], plate_bbox: List[int]) -> str:
        vx1, vy1, vx2, vy2 = vehicle_bbox
        px1, py1, px2, py2 = plate_bbox
        vw = max(1, vx2 - vx1)
        vh = max(1, vy2 - vy1)
        rcx = (((px1 + px2) / 2.0) - vx1) / float(vw)
        rcy = (((py1 + py2) / 2.0) - vy1) / float(vh)
        col = "L" if rcx < 0.42 else ("R" if rcx > 0.62 else "C")
        row = "B" if rcy > 0.58 else "M"
        return f"{col}{row}"

    def _canonicalize_verified_plate(self, plate: str) -> str:
        """Resolve close OCR variants only against operator-confirmed ground truth."""
        compact = plate.replace(" ", "").replace("-", "").replace(".", "").upper()
        best_plate = plate
        best_distance = 3
        for verified in getattr(self, "_verified_plates", []):
            verified_compact = verified.replace(" ", "").replace("-", "").replace(".", "")
            if len(compact) != len(verified_compact):
                continue
            distance = sum(left != right for left, right in zip(compact, verified_compact))
            if distance < best_distance:
                best_distance = distance
                best_plate = verified
        return best_plate if best_distance <= 2 else plate

    @staticmethod
    def _normalize_min_confidence(value: float) -> float:
        return round(max(0.50, min(0.95, float(value))), 2)

    def _load_min_confidence(self, default: float) -> float:
        fallback = self._normalize_min_confidence(default)
        try:
            if self._config_path.is_file():
                payload = json.loads(self._config_path.read_text(encoding="utf-8"))
                return self._normalize_min_confidence(payload.get("minConfidence", fallback))
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("[%s] Ignoring invalid gate config %s: %s", self.camera_id, self._config_path, exc)
        return fallback

    def update_min_confidence(self, value: float) -> float:
        """Persist the event threshold so Settings survives worker restarts."""
        normalized = self._normalize_min_confidence(value)
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._config_path.with_suffix(f"{self._config_path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps({"minConfidence": normalized}, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(self._config_path)
        self.min_confidence = normalized
        return normalized

    def _event_meets_confidence_threshold(self, confidence: float) -> bool:
        return float(confidence) >= float(getattr(self, "min_confidence", 0.70))

    @staticmethod
    def _is_high_angle_vehicle(vehicle_box: List[int], frame_w: int, frame_h: int) -> bool:
        """Enable the overhead-camera supplement only for close, foreshortened vehicles."""
        if len(vehicle_box) != 4 or frame_w <= 0 or frame_h <= 0:
            return False
        x1, y1, x2, y2 = vehicle_box
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        return (
            y2 >= int(frame_h * 0.94)
            and height >= int(frame_h * 0.42)
            and height >= width * 1.12
        )

    def _resolve_plate_box(
        self,
        observed_plate_box: List[int],
        observed_vehicle_box: List[int],
        current_vehicle_box: List[int],
        zone_fallback: bool,
    ) -> List[int]:
        # A lane fallback crop is already expressed in current frame coordinates.
        # Projecting it through an unrelated YOLO vehicle box moves the overlay away
        # from the plate even though OCR text is correct.
        if zone_fallback:
            return [int(value) for value in observed_plate_box]
        return self.tracker.project_box_between_vehicle_boxes(
            observed_plate_box,
            observed_vehicle_box,
            current_vehicle_box,
        )

    def _dedupe_plate_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        for cand in sorted(candidates, key=lambda item: (item.get("score", 0.0), item.get("confidence", 0.0)), reverse=True):
            bbox = cand.get("bbox_in_crop")
            if not bbox or len(bbox) != 4:
                continue
            overlapping = next(
                (
                    existing
                    for existing in deduped
                    if compute_iou([int(v) for v in bbox], [int(v) for v in existing["bbox_in_crop"]]) >= 0.28
                ),
                None,
            )
            if overlapping is not None:
                overlapping["variant_support"] = int(overlapping.get("variant_support", 1)) + 1
                overlapping.setdefault("variants", []).append({
                    "plate": cand.get("plate", ""),
                    "confidence": float(cand.get("confidence", 0.0)),
                    "source": cand.get("source", ""),
                })
                continue
            candidate = dict(cand)
            candidate["variant_support"] = 1
            candidate["variants"] = [{
                "plate": candidate.get("plate", ""),
                "confidence": float(candidate.get("confidence", 0.0)),
                "source": candidate.get("source", ""),
            }]
            deduped.append(candidate)
        return deduped

    def _recover_localized_candidate(
        self,
        crop: np.ndarray,
        allow_geometry: bool = False,
        on_localized: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """Run the bounded weak-detector/geometry proposals through strict OCR."""
        if not (
            hasattr(self.lpr_reader, "localize_unread_plate_regions")
            or hasattr(self.lpr_reader, "localize_unread_plate_region")
        ):
            return None, []
        if hasattr(self.lpr_reader, "localize_unread_plate_regions"):
            try:
                regions = self.lpr_reader.localize_unread_plate_regions(
                    crop,
                    min_center_y=0.05 if allow_geometry else 0.45,
                )
            except TypeError:
                regions = self.lpr_reader.localize_unread_plate_regions(crop)
        else:
            try:
                localized = self.lpr_reader.localize_unread_plate_region(
                    crop,
                    min_center_y=0.05 if allow_geometry else 0.45,
                )
            except TypeError:
                localized = self.lpr_reader.localize_unread_plate_region(crop)
            regions = [localized] if localized is not None else []
        if not allow_geometry:
            regions = [
                region
                for region in regions
                if region.get("source") != "recessed_plate_geometry"
            ]
        if on_localized is not None:
            published = False
            for region in regions:
                # Only the trained plate detector is safe to expose before OCR.
                if not region.get("source"):
                    on_localized(region)
                    published = True
                    break
            if not published:
                two_line_regions = []
                crop_h, crop_w = crop.shape[:2]
                for region in regions:
                    if region.get("source") != "recessed_plate_geometry":
                        continue
                    x1, y1, x2, y2 = region.get("bbox_in_crop", [0, 0, 0, 0])
                    box_w = max(1, int(x2) - int(x1))
                    box_h = max(1, int(y2) - int(y1))
                    aspect = box_w / float(box_h)
                    center_y = (float(y1) + float(y2)) / (2.0 * max(1, crop_h))
                    if 0.68 <= aspect <= 1.45 and center_y >= 0.45:
                        two_line_regions.append(region)
                if two_line_regions:
                    on_localized(max(
                        two_line_regions,
                        key=lambda item: (
                            (float(item["bbox_in_crop"][1]) + float(item["bbox_in_crop"][3])) / max(1, crop_h),
                            (float(item["bbox_in_crop"][0]) + float(item["bbox_in_crop"][2])) / max(1, crop_w),
                        ),
                    ))
        if not hasattr(self.lpr_reader, "recognize_localized_plate_region"):
            return None, regions

        recovered = None
        for localized in regions:
            candidate = self.lpr_reader.recognize_localized_plate_region(crop, localized)
            if candidate is None:
                continue
            if (
                recovered is None
                or (float(candidate.get("confidence", 0.0)), float(candidate.get("score", 0.0)))
                > (
                    float(recovered.get("confidence", 0.0)),
                    float(recovered.get("score", 0.0)),
                )
            ):
                recovered = candidate
            if float(candidate.get("confidence", 0.0)) >= 0.92:
                break
        return recovered, regions

    @staticmethod
    def _dedupe_vehicle_detections(detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Collapse nested YOLO boxes so one truck cannot consume both OCR slots."""
        kept: List[Dict[str, Any]] = []
        ranked = sorted(
            detections,
            key=lambda item: (item["bbox"][2] - item["bbox"][0]) * (item["bbox"][3] - item["bbox"][1]),
            reverse=True,
        )
        for candidate in ranked:
            box = [int(value) for value in candidate["bbox"]]
            area = max(1, (box[2] - box[0]) * (box[3] - box[1]))
            duplicate = False
            for existing in kept:
                candidate_lane = candidate.get("lane")
                existing_lane = existing.get("lane")
                if candidate_lane and existing_lane and candidate_lane != existing_lane:
                    continue
                other = [int(value) for value in existing["bbox"]]
                ix1, iy1 = max(box[0], other[0]), max(box[1], other[1])
                ix2, iy2 = min(box[2], other[2]), min(box[3], other[3])
                intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                other_area = max(1, (other[2] - other[0]) * (other[3] - other[1]))
                overlap_smaller = intersection / float(min(area, other_area))
                if compute_iou(box, other) >= 0.65 or overlap_smaller >= 0.86:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(candidate)
        return kept

    def _prioritize_ocr_detections(
        self,
        detections: List[Dict[str, Any]],
        now: float,
        limit: int = 2,
    ) -> List[Dict[str, Any]]:
        """Reserve one OCR opportunity per occupied lane before filling spare slots."""
        if limit <= 0:
            return []

        def priority(item: Dict[str, Any]) -> Tuple[float, int, int]:
            track = self.tracker.tracks.get(item.get("_track_id"))
            last_ocr = (
                getattr(track, "last_ocr_at", 0.0)
                if track is not None
                else self._lane_fallback_last_ocr.get(item.get("lane", ""), 0.0)
            )
            area = (item["bbox"][2] - item["bbox"][0]) * (item["bbox"][3] - item["bbox"][1])
            return (last_ocr, 1 if item.get("_zone_fallback") else 0, -area)

        by_lane: Dict[str, List[Dict[str, Any]]] = {}
        for item in detections:
            by_lane.setdefault(str(item.get("lane") or "UNKNOWN"), []).append(item)
        for lane_items in by_lane.values():
            lane_items.sort(key=priority)

        selected = sorted(
            (lane_items[0] for lane_items in by_lane.values() if lane_items),
            key=priority,
        )[:limit]
        if len(selected) < limit:
            selected_ids = {id(item) for item in selected}
            remaining = sorted(
                (item for item in detections if id(item) not in selected_ids),
                key=priority,
            )
            selected.extend(remaining[: limit - len(selected)])

        for item in selected:
            track = self.tracker.tracks.get(item.get("_track_id"))
            if track is not None:
                track.last_ocr_at = now
            elif item.get("_zone_fallback"):
                self._lane_fallback_last_ocr[str(item.get("lane") or "UNKNOWN")] = now
        return selected

    def _zone_fallback_detections(
        self,
        frame_w: int,
        frame_h: int,
        occupied_lanes: set[str],
    ) -> List[Dict[str, Any]]:
        """Create OCR-only zone crops for lanes whose vehicle body was missed by YOLO."""
        fallbacks: List[Dict[str, Any]] = []
        for zone in self._active_zones:
            points = zone.get("polygon_points") or []
            if not points:
                continue
            name = zone.get("name") or "Làn cổng"
            lane = "IN_2" if ("2" in name or "phụ" in name.lower() or "b" in name.lower()) else "IN_1"
            if lane in occupied_lanes:
                continue
            xs = [float(point.get("x", 0.0)) for point in points if isinstance(point, dict)]
            ys = [float(point.get("y", 0.0)) for point in points if isinstance(point, dict)]
            if not xs or not ys:
                continue
            x1 = max(0, min(frame_w - 1, int(min(xs) * frame_w)))
            y1 = max(0, min(frame_h - 1, int(min(ys) * frame_h)))
            x2 = max(1, min(frame_w, int(max(xs) * frame_w)))
            y2 = max(1, min(frame_h, int(max(ys) * frame_h)))
            if (x2 - x1) < 80 or (y2 - y1) < 60:
                continue
            fallbacks.append({
                "class": "truck",
                "bbox": [x1, y1, x2, y2],
                "zone_name": name,
                "lane": lane,
                "_zone_fallback": True,
                "_force_stationary": True,
            })
        return fallbacks

    @staticmethod
    def _plate_edit_distance(left: str, right: str) -> int:
        if not left:
            return len(right)
        if not right:
            return len(left)
        previous = list(range(len(right) + 1))
        for index, char_left in enumerate(left, start=1):
            current = [index]
            for offset, char_right in enumerate(right, start=1):
                current.append(min(
                    current[-1] + 1,
                    previous[offset] + 1,
                    previous[offset - 1] + (char_left != char_right),
                ))
            previous = current
        return previous[-1]

    def _touch_vehicle_passage(
        self,
        track_id: str,
        lane: str,
        now: float,
        track: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Attach short track fragments to one physical vehicle passage."""
        if not hasattr(self, "_lane_passages"):
            self._lane_passages = {}
            self._next_passage_id = 1
        passage = self._lane_passages.get(track_id)
        if passage is None and track is not None:
            compact_plate = self._compact_plate(getattr(track, "best_plate", ""))
            vehicle_box = [int(value) for value in getattr(track, "vehicle_bbox", [])]
            seen_passages: set[str] = set()
            for candidate in self._lane_passages.values():
                passage_id = str(candidate.get("id") or "")
                if not passage_id or passage_id in seen_passages:
                    continue
                seen_passages.add(passage_id)
                if candidate.get("event_plate") or candidate.get("filtered"):
                    continue
                if candidate.get("lane") != lane or (now - float(candidate.get("last_seen", 0.0))) > 4.0:
                    continue
                aggregate = candidate.get("aggregate_track")
                aggregate_plate = self._compact_plate(getattr(aggregate, "best_plate", ""))
                previous_box = candidate.get("last_vehicle_bbox") or []
                same_plate = (
                    compact_plate
                    and aggregate_plate
                    and self._plate_edit_distance(compact_plate, aggregate_plate) <= 2
                )
                spatial_match = False
                strong_iou_match = False
                if len(vehicle_box) == 4 and len(previous_box) == 4:
                    px1, py1, px2, py2 = previous_box
                    vx1, vy1, vx2, vy2 = vehicle_box
                    diagonal = max(1.0, float(np.hypot(px2 - px1, py2 - py1)))
                    distance = float(np.hypot(
                        ((vx1 + vx2) - (px1 + px2)) / 2.0,
                        ((vy1 + vy2) - (py1 + py2)) / 2.0,
                    ))
                    overlap = compute_iou(vehicle_box, previous_box)
                    strong_iou_match = overlap >= 0.25
                    spatial_match = overlap >= 0.08 or distance <= diagonal * 0.45
                track_fragment_without_plate = (
                    not compact_plate
                    and not aggregate_plate
                    and (now - float(candidate.get("last_seen", 0.0))) <= 1.0
                    and strong_iou_match
                )
                if (same_plate and spatial_match) or track_fragment_without_plate:
                    passage = candidate
                    self._lane_passages[track_id] = passage
                    break
        if passage is None or (now - float(passage["last_seen"])) > 6.0:
            passage = {
                "id": f"P{self._next_passage_id:05d}",
                "last_seen": now,
                "event_plate": "",
                "aggregate_track": None,
                "crop": None,
                "best_plate": "",
                "best_confidence": -1.0,
                "lane": lane,
                "zone_name": "Làn cổng",
                "video_timecode": "00:00",
                "last_vehicle_bbox": [],
                "vehicle_observations": 0,
                "first_vehicle_seen": now,
                "high_angle": False,
            }
            self._next_passage_id += 1
            self._lane_passages[track_id] = passage
        else:
            passage["last_seen"] = now
        if track is not None:
            passage["last_vehicle_bbox"] = [int(value) for value in track.vehicle_bbox]
        return passage

    def _emit_unknown_passage(self, passage: Dict[str, Any], now: float) -> bool:
        """Persist one unread result only from an actual recognized plate crop."""
        crop = passage.get("crop")
        if crop is None or not isinstance(crop, np.ndarray) or crop.size == 0:
            passage["filtered"] = True
            return False
        passage["event_plate"] = "UNKNOWN"
        # A physical truck can be fragmented into several tracker IDs. Retire
        # nearby unread fragments in the same lane with the emitted passage.
        for candidate in getattr(self, "_lane_passages", {}).values():
            if candidate is passage or candidate.get("event_plate"):
                continue
            if candidate.get("lane") != passage.get("lane"):
                continue
            if abs(float(candidate.get("last_seen", 0.0)) - float(passage.get("last_seen", 0.0))) <= 8.0:
                candidate["filtered"] = True
        aggregate = passage.get("aggregate_track")
        if aggregate is not None:
            aggregate.mark_event_emitted()
        for track in self.tracker.tracks.values():
            if getattr(track, "passage_id", None) == passage["id"]:
                track.mark_event_emitted()
        asyncio.create_task(
            self._handle_detected_plate(
                plate="UNKNOWN",
                confidence=0.0,
                crop=crop.copy(),
                lane=passage["lane"],
                zone_name=passage["zone_name"],
                now=now,
                event_key=f"{self.camera_id}:{passage['id']}",
                video_timecode=(
                    str(passage.get("video_timecode"))
                    if passage.get("video_timecode") not in {None, "", "00:00", "00:00:00"}
                    else self._get_video_timecode()
                ),
            )
        )
        return True

    def _is_recent_passage_variant(self, plate: str, lane: str, now: float) -> bool:
        compact = self._compact_plate(plate)
        recent = []
        duplicate = False
        for result in getattr(self, "_recent_passage_results", []):
            age = now - float(result["timestamp"])
            if age > 45.0:
                continue
            recent.append(result)
            if result["lane"] == lane and self._plate_edit_distance(compact, result["plate"]) <= 2:
                duplicate = True
        self._recent_passage_results = recent
        return duplicate

    def _remember_passage_result(self, plate: str, confidence: float, lane: str, now: float) -> None:
        if not hasattr(self, "_recent_passage_results"):
            self._recent_passage_results = []
        self._recent_passage_results.append({
            "plate": self._compact_plate(plate),
            "confidence": float(confidence),
            "lane": lane,
            "timestamp": now,
        })

    @staticmethod
    def _select_rear_plate_candidate(
        candidates: List[Dict[str, Any]],
        vehicle_width: int,
        vehicle_height: int,
        high_angle: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Choose the highest confidence verified rear plate on the vehicle, prioritizing trailer plates (R/RM)."""
        if not candidates or vehicle_width <= 0 or vehicle_height <= 0:
            return None

        rear_candidates = []
        for candidate in candidates:
            _x1, y1, _x2, y2 = candidate.get("bbox_in_crop", [0, 0, 0, 0])
            center_y = ((float(y1) + float(y2)) / 2.0) / float(vehicle_height)
            # Rear plate must strictly be in lower half of vehicle (cản sau)
            is_overhead_far_rear = high_angle and str(candidate.get("source", "")).startswith("high_angle_far_rear_")
            if center_y < 0.44 and not is_overhead_far_rear:
                continue
            rear_candidates.append(candidate)

        if not rear_candidates:
            return None

        def candidate_rank(item: Dict[str, Any]) -> Tuple[int, float, float]:
            plate = str(item.get("plate", "")).upper()
            # Trailer plates (e.g. 15R-158.45, 15RM-032.88) are the true rear plates of container trucks
            is_trailer = 1 if ("R-" in plate or "RM-" in plate or "R" in plate) else 0
            conf = float(item.get("confidence", 0.0))
            score = float(item.get("score", 0.0))
            return (is_trailer, conf, score)

        rear_candidates.sort(key=candidate_rank, reverse=True)
        return rear_candidates[0]

    def _save_crop_image(self, crop: np.ndarray, plate: str) -> Optional[str]:
        """Save cropped license plate image to data/crops/."""
        if crop is None or crop.size == 0:
            return None
        try:
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            clean_plate = plate.replace("-", "").replace(".", "").replace(" ", "_")
            filename = f"gate_crop_{ts_str}_{clean_plate}.jpg"
            filepath = self.crops_dir / filename
            cv2.imwrite(str(filepath), crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
            return f"/data/crops/{filename}"
        except Exception as exc:
            logger.error("Failed to save crop image: %s", exc)
            return None

    def _save_event_clip(self, plate: str) -> Optional[str]:
        """Extract 10-second MP4 clip from circular buffer upon plate detection."""
        try:
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            clean_plate = plate.replace("-", "").replace(".", "").replace(" ", "_")
            filename = f"gate_clip_{ts_str}_{clean_plate}.mp4"
            filepath = self.clips_dir / filename

            saved_path = self.buffer.save_clip(
                str(filepath),
                duration_seconds=10.0,
                fps=self.target_fps,
            )
            return f"/data/clips/{filename}" if saved_path else None
        except Exception as exc:
            logger.warning("Clip extraction failed for plate %s (%s). Continuing event logging.", plate, exc)
            return None

    def resolve_vehicle_status(self, plate_str: str) -> str:
        """Resolve labels only from the operator-managed registered-vehicle setting."""
        clean = self._compact_plate(plate_str)
        if not clean:
            return "STRANGER"
        return getattr(self, "_registered_vehicle_statuses", {}).get(clean, "STRANGER")

    async def _handle_detected_plate(
        self,
        plate: str,
        confidence: float,
        crop: np.ndarray,
        lane: str,
        zone_name: str,
        now: float,
        event_key: Optional[str] = None,
        video_timecode: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Process event logging and clip extraction in background."""
        is_unknown = plate.strip().upper() == "UNKNOWN"
        if not is_unknown and confidence < self.min_confidence:
            logger.debug(
                "[%s] Plate %s confidence %.2f is below threshold %.2f. Skipping right-side event logging.",
                self.camera_id,
                plate,
                confidence,
                self.min_confidence,
            )
            return None

        compact_plate = self._compact_plate(plate)
        if not compact_plate:
            return None

        self._recent_events[compact_plate] = now

        # Save the exact crop that will be persisted with the journal event.
        crop_path = await asyncio.to_thread(self._save_crop_image, crop, plate)

        # 1. Database lookup: Check registered_vehicles (AP-01)
        db_status = None
        if not is_unknown:
            try:
                db_status = await get_vehicle_status_by_plate(plate)
            except Exception as exc:
                logger.debug("Database lookup failed (%s). Defaulting status.", exc)

        status = "STRANGER" if db_status is None else str(db_status).upper()

        self._recent_events[compact_plate] = now
        if not is_unknown:
            self._registered_vehicle_statuses[compact_plate] = status
            for track in self.tracker.tracks.values():
                if self._compact_plate(track.best_plate) == compact_plate:
                    track.status = status

        # 2. Save media artifacts
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_plate = plate.replace("-", "").replace(".", "").replace(" ", "_")
        clip_filename = f"gate_clip_{ts_str}_{clean_plate}.mp4"
        clip_filepath = self.clips_dir / clip_filename
        clip_path = f"/data/clips/{clip_filename}"

        # Fire-and-forget non-blocking background clip extraction (never blocks live stream!)
        try:
            asyncio.create_task(
                asyncio.to_thread(self.buffer.save_clip, str(clip_filepath), 10.0, self.target_fps)
            )
        except Exception as bg_err:
            logger.debug("Failed to spawn background clip writer: %s", bg_err)

        # 3. Create Gate Event Record in Database (instant response)
        event_record = None
        event_id = self._event_ids_by_key.get(event_key or "") if event_key else None
        if event_id is None:
            try:
                event_record = await create_gate_event(
                    camera_id=self.camera_id,
                    lane=lane,
                    license_plate=plate,
                    status=status,
                    confidence=confidence,
                    crop_path=crop_path,
                    clip_path=clip_path,
                    zone_name=zone_name,
                    video_timecode=video_timecode,
                    event_timestamp=datetime.now(timezone.utc),
                )
                event_id = event_record.get("id") if event_record else None
            except Exception as exc:
                logger.debug("Could not write gate event to DB (%s). Proceeding with broadcast.", exc)

        if event_key and event_id:
            self._event_ids_by_key[event_key] = event_id

        event_payload = {
            "id": event_id or event_key or f"gate-{int(now * 1000)}",
            "eventKey": event_key,
            "cameraId": self.camera_id,
            "lane": lane,
            "licensePlate": plate,
            "status": "unknown" if is_unknown else ("quen" if status == "KNOWN" else "la"),
            "confidence": confidence,
            "cropPath": crop_path,
            "clipPath": clip_path,
            "time": video_timecode or "00:00",
            "plate": plate,
            "zone": zone_name or ("Làn IN 2 · Làn phụ" if lane == "IN_2" else "Làn IN 1 · Cổng chính"),
            "conf": None if is_unknown else int(confidence * 100),
        }

        # Broadcast gate event via WebSocket to Node.js proxy
        await self.emitter.emit_gate_event(event_payload)
        logger.info("[%s] Logged Gate Event & 10s Clip for plate %s (%s) in zone '%s'", self.camera_id, plate, status, zone_name)
        return event_payload

    def _sync_plate_detection(self, frame: np.ndarray, in_zone_detections: List[Dict[str, Any]], now: float, main_loop: Optional[asyncio.AbstractEventLoop] = None, generation: Optional[int] = None) -> None:
        """Run multi-stage OCR on detected vehicle crops inside active zones and update plate tracker."""
        processing_started = time.monotonic()
        h, w = frame.shape[:2]

        for d in in_zone_detections:
            if generation is not None and generation != self._tracking_generation:
                return
            if d["class"] in ["car", "truck", "bus"]:
                vx1, vy1, vx2, vy2 = d["bbox"]
                vw, vh = vx2 - vx1, vy2 - vy1
                if vw < 50 or vh < 30:
                    continue

                crop = frame[max(0, vy1):min(h, vy2), max(0, vx1):min(w, vx2)]
                if crop.size == 0:
                    continue

                zone_name = d.get("zone_name") or "Làn cổng"
                lane = d.get("lane") or ("IN_2" if ("2" in zone_name or "phụ" in zone_name.lower()) else "IN_1")

                observed_vehicle_box = [vx1, vy1, vx2, vy2]
                if d.get("_track_id"):
                    vehicle_track_id = str(d["_track_id"])
                elif d.get("_zone_fallback"):
                    # Zone-wide OCR must never borrow a physical vehicle track;
                    # otherwise its absolute plate box can migrate to a neighbor.
                    vehicle_track_id = f"ZONE_FALLBACK:{lane}"
                else:
                    vehicle_track_id = self.tracker.match_or_create_track(
                        observed_vehicle_box,
                        now,
                        lane=lane,
                    )
                current_track = self.tracker.tracks.get(vehicle_track_id)
                stationary = bool(d.get("_force_stationary") or (current_track and current_track.is_stationary(now)))
                high_angle = bool(
                    not d.get("_zone_fallback")
                    and (d.get("_top_view_alias") or self._is_high_angle_vehicle(observed_vehicle_box, w, h))
                )

                # A zone-wide crop has no YOLO vehicle box. Try the bounded
                # recessed-plate path first so a stopped truck is not delayed by
                # every expensive stationary ROI. Normal vehicle scans are unchanged.
                quick_recovered = None
                zone_weak_recovered = None
                zone_regions: List[Dict[str, Any]] = []
                allow_geometry = bool(
                    d.get("_zone_fallback")
                    or (high_angle and stationary)
                )

                def publish_provisional(region: Dict[str, Any]) -> None:
                    track_for_box = self.tracker.tracks.get(vehicle_track_id)
                    if track_for_box is None or d.get("_zone_fallback"):
                        return
                    rbx1, rby1, rbx2, rby2 = region.get("bbox_in_crop", [0, 0, 0, 0])
                    observed_box = [
                        max(0, vx1 + int(rbx1)),
                        max(0, vy1 + int(rby1)),
                        min(w, vx1 + int(rbx2)),
                        min(h, vy1 + int(rby2)),
                    ]
                    projected_box = self._resolve_plate_box(
                        observed_box,
                        observed_vehicle_box,
                        track_for_box.vehicle_bbox,
                        False,
                    )
                    self.tracker.update_provisional_plate_box(
                        track_for_box,
                        projected_box,
                        max(now, track_for_box.last_seen),
                    )

                if d.get("_zone_fallback") or high_angle:
                    quick_recovered, zone_regions = self._recover_localized_candidate(
                        crop,
                        allow_geometry=allow_geometry,
                        on_localized=publish_provisional,
                    )
                    if quick_recovered is not None and float(quick_recovered.get("confidence", 0.0)) < 0.90:
                        zone_weak_recovered = quick_recovered
                        quick_recovered = None
                candidates = [quick_recovered] if quick_recovered is not None else []
                if not candidates:
                    candidates = self.lpr_reader.scan_plate_from_frame_or_vehicle(
                        frame,
                        crop,
                        [vx1, vy1, vx2, vy2],
                        stationary=stationary,
                        high_angle=high_angle,
                    )

                best_plate_crop: Optional[np.ndarray] = None
                ranked_candidates = self._dedupe_plate_candidates(candidates)
                rear_candidate = self._select_rear_plate_candidate(
                    ranked_candidates,
                    vw,
                    vh,
                    high_angle=high_angle,
                )
                if (
                    rear_candidate is None
                    and hasattr(self.lpr_reader, "localize_unread_plate_region")
                ):
                    if zone_weak_recovered is not None:
                        recovered_candidate = zone_weak_recovered
                        unread_regions = zone_regions
                    elif zone_regions:
                        recovered_candidate = None
                        unread_regions = zone_regions
                    else:
                        recovered_candidate, unread_regions = self._recover_localized_candidate(
                            crop,
                            allow_geometry=bool(
                                d.get("_zone_fallback")
                                or (high_angle and stationary)
                            ),
                        )
                    unread_region = unread_regions[0] if unread_regions else None
                    if (
                        (d.get("_zone_fallback") or high_angle)
                        and recovered_candidate is not None
                        and float(recovered_candidate.get("confidence", 0.0)) < 0.90
                    ):
                        unread_region = {
                            "bbox_in_crop": recovered_candidate["bbox_in_crop"],
                            "detector_confidence": 0.15,
                        }
                        recovered_candidate = None
                    if recovered_candidate is not None:
                        rear_candidate = recovered_candidate
                    current_track = self.tracker.tracks.get(vehicle_track_id)
                    if (
                        current_track is None
                        and unread_region is not None
                        and d.get("_zone_fallback")
                    ):
                        current_track = self.tracker.update_track(
                            track_id=vehicle_track_id,
                            vehicle_bbox=observed_vehicle_box,
                            plate_bbox=None,
                            plate_text="",
                            status="SCANNING",
                            conf=0.0,
                            now=now,
                        )
                        current_track.lane = lane
                        current_track.zone_name = zone_name
                        current_track.is_zone_fallback = True
                    if (
                        rear_candidate is None
                        and unread_region is not None
                        and current_track is not None
                    ):
                        ubx1, uby1, ubx2, uby2 = unread_region["bbox_in_crop"]
                        unread_box = [
                            max(0, vx1 + int(ubx1) - 2),
                            max(0, vy1 + int(uby1) - 2),
                            min(w, vx1 + int(ubx2) + 2),
                            min(h, vy1 + int(uby2) + 2),
                        ]
                        is_plate_in_zone, _, _ = self._find_matching_zone(unread_box, w, h)
                        if (
                            is_plate_in_zone
                            and unread_box[2] > unread_box[0]
                            and unread_box[3] > unread_box[1]
                        ):
                            unread_crop = frame[
                                unread_box[1]:unread_box[3],
                                unread_box[0]:unread_box[2],
                            ]
                            passage = self._touch_vehicle_passage(
                                vehicle_track_id,
                                lane,
                                max(now, current_track.last_seen),
                                current_track,
                            )
                            current_track.passage_id = passage["id"]
                            passage["zone_name"] = zone_name
                            if d.get("_zone_fallback"):
                                passage["vehicle_observations"] = int(
                                    passage.get("vehicle_observations", 0)
                                ) + 1
                            previous_box = passage.get("unread_last_bbox")
                            stable = bool(
                                previous_box
                                and compute_iou(previous_box, unread_box) >= 0.35
                                and (now - float(passage.get("unread_last_seen", 0.0))) <= 1.5
                            )
                            passage["unread_support"] = (
                                int(passage.get("unread_support", 0)) + 1 if stable else 1
                            )
                            passage["unread_last_bbox"] = unread_box
                            passage["unread_last_seen"] = now
                            if unread_crop.size > 0:
                                gray_crop = cv2.cvtColor(unread_crop, cv2.COLOR_BGR2GRAY)
                                sharpness = float(cv2.Laplacian(gray_crop, cv2.CV_64F).var())
                                brightness = float(np.mean(gray_crop))
                                if (
                                    sharpness >= 8.0
                                    and 18.0 <= brightness <= 238.0
                                    and sharpness > float(passage.get("unread_best_sharpness", -1.0))
                                ):
                                    passage["unread_crop"] = unread_crop.copy()
                                    passage["unread_best_sharpness"] = sharpness
                                    passage["video_timecode"] = str(d.get("_video_timecode") or "00:00")
                            if (
                                int(passage.get("unread_support", 0)) >= 2
                                and isinstance(passage.get("unread_crop"), np.ndarray)
                            ):
                                passage["crop"] = passage["unread_crop"].copy()
                                passage["crop_confidence"] = float(
                                    unread_region.get("detector_confidence", 0.0)
                                )
                                passage["localized_unread_only"] = True
                for cand in [rear_candidate] if rear_candidate is not None else []:
                    plate_text = cand.get("plate", "")
                    plate_text = self._canonicalize_verified_plate(plate_text)
                    conf = float(cand.get("confidence", 0.0))
                    variants = [
                        {
                            **variant,
                            "plate": self._canonicalize_verified_plate(str(variant.get("plate") or "")),
                        }
                        for variant in (cand.get("variants") or [])
                    ]
                    clean_plate = plate_text.replace(" ", "").replace("-", "").replace(".", "")
                    if len(clean_plate) < 6 or conf < 0.42:
                        continue

                    cbx1, cby1, cbx2, cby2 = cand.get("bbox_in_crop", [0, 0, 0, 0])
                    observed_plate_box = [
                        max(0, vx1 + int(cbx1) - 2),
                        max(0, vy1 + int(cby1) - 2),
                        min(w, vx1 + int(cbx2) + 2),
                        min(h, vy1 + int(cby2) + 2),
                    ]
                    if observed_plate_box[2] <= observed_plate_box[0] or observed_plate_box[3] <= observed_plate_box[1]:
                        continue

                    is_plate_in_zone, _, _ = self._find_matching_zone(observed_plate_box, w, h)
                    if not is_plate_in_zone:
                        continue

                    zone_fallback = bool(d.get("_zone_fallback"))
                    completed_at = now + max(0.0, time.monotonic() - processing_started)
                    owner_track_id = None
                    if hasattr(self.tracker, "find_vehicle_track_for_plate"):
                        owner_track_id = self.tracker.find_vehicle_track_for_plate(
                            observed_plate_box,
                            lane,
                            completed_at,
                        )
                        if owner_track_id is not None:
                            previous_track_id = vehicle_track_id
                            vehicle_track_id = owner_track_id
                            if zone_fallback and previous_track_id != owner_track_id:
                                self.tracker.tracks.pop(previous_track_id, None)

                    current_track = self.tracker.tracks.get(vehicle_track_id)
                    current_vehicle_box = current_track.vehicle_bbox if current_track else observed_vehicle_box
                    plate_box = self._resolve_plate_box(
                        observed_plate_box,
                        observed_vehicle_box,
                        current_vehicle_box,
                        zone_fallback,
                    )
                    plate_box = [
                        max(0, min(w - 1, plate_box[0])),
                        max(0, min(h - 1, plate_box[1])),
                        max(1, min(w, plate_box[2])),
                        max(1, min(h, plate_box[3])),
                    ]
                    if plate_box[2] <= plate_box[0] or plate_box[3] <= plate_box[1]:
                        continue
                    update_now = max(completed_at, now, current_track.last_seen) if current_track else completed_at
                    status = self.resolve_vehicle_status(plate_text)
                    if generation is not None and generation != self._tracking_generation:
                        return
                    track = self.tracker.update_track(
                        track_id=vehicle_track_id,
                        vehicle_bbox=current_vehicle_box,
                        plate_bbox=plate_box,
                        plate_text=plate_text,
                        status=status,
                        conf=conf,
                        now=update_now,
                        variants=variants,
                        bbox_quality=float(cand.get("score", conf * 2.0)),
                    )
                    if not zone_fallback and owner_track_id is None and current_track is None:
                        track.last_vehicle_seen = now
                    track.lane = lane
                    track.zone_name = zone_name
                    track.is_zone_fallback = zone_fallback and vehicle_track_id.startswith("ZONE_FALLBACK:")
                    passage = self._touch_vehicle_passage(vehicle_track_id, lane, update_now, track)
                    track.passage_id = passage["id"]
                    passage["zone_name"] = zone_name
                    if zone_fallback:
                        passage["vehicle_observations"] = int(
                            passage.get("vehicle_observations", 0)
                        ) + 1
                    passage["localized_unread_only"] = False
                    passage["unread_support"] = 0
                    if conf > float(passage.get("best_confidence", -1.0)):
                        passage["best_plate"] = plate_text
                        passage["best_confidence"] = conf
                    aggregate = passage.get("aggregate_track")
                    if aggregate is None:
                        passage["aggregate_track"] = track
                        aggregate = track
                    elif aggregate is not track:
                        aggregate.last_seen = update_now
                        aggregate.last_plate_seen = update_now
                        aggregate.add_plate_vote(
                            plate_text,
                            conf,
                            variants=variants,
                            now=update_now,
                        )
                        track.best_plate = aggregate.best_plate
                        track.plate = aggregate.best_plate
                        track.best_conf = aggregate.best_conf
                        track.confidence = aggregate.best_conf

                    pcx1, pcy1, pcx2, pcy2 = [
                        max(0, min(w, int(observed_plate_box[0]) - 2)),
                        max(0, min(h, int(observed_plate_box[1]) - 2)),
                        max(0, min(w, int(observed_plate_box[2]) + 2)),
                        max(0, min(h, int(observed_plate_box[3]) + 2)),
                    ]
                    crop_img = frame[pcy1:pcy2, pcx1:pcx2].copy() if (pcx2 > pcx1 and pcy2 > pcy1) else None
                    if crop_img is not None and crop_img.size > 0:
                        track.latest_plate_crop = crop_img.copy()
                        if conf >= float(passage.get("crop_confidence", -1.0)):
                            passage["crop"] = crop_img.copy()
                            passage["crop_confidence"] = conf
                            passage["video_timecode"] = str(d.get("_video_timecode") or "00:00")
                    if hasattr(self.tracker, "prepare_visual_track"):
                        self.tracker.prepare_visual_track(track)

    async def _run_ai_in_background(self, frame: np.ndarray, in_zone_detections: List[Dict[str, Any]], now: float, generation: Optional[int] = None) -> None:
        """Trigger AI OCR in thread pool."""
        if self._ai_busy:
            return
        self._ai_busy = True
        try:
            main_loop = asyncio.get_running_loop()
            await main_loop.run_in_executor(
                self._executor,
                self._sync_plate_detection,
                frame,
                in_zone_detections,
                now,
                main_loop,
                generation,
            )
        except Exception as exc:
            logger.debug("Background plate detection error: %s", exc)
        finally:
            self._ai_busy = False

    def _schedule_ready_track_events(self, now: float) -> None:
        """Emit gate event as soon as a valid plate is detected and confirmed."""
        if getattr(self, "_ai_busy", False):
            return
        for track_id, track in list(self.tracker.tracks.items()):
            if getattr(track, "passage_id", None):
                continue
            if getattr(track, "event_emitted", False):
                continue
            if not getattr(track, "best_plate", ""):
                continue
            compact_p = self._compact_plate(track.best_plate)
            if not compact_p or len(compact_p) < 6:
                continue
            if not self._event_meets_confidence_threshold(track.best_conf):
                continue
            if (now - self._recent_events.get(compact_p, 0.0)) < 120.0:
                track.mark_event_emitted()
                continue
            crop = track.latest_plate_crop
            if crop is None or crop.size == 0:
                continue

            self._recent_events[compact_p] = now
            confidence = track.best_conf
            plate = track.best_plate
            track.mark_event_emitted()
            passage = getattr(self, "_lane_passages", {}).get(track_id)
            if passage and getattr(track, "passage_id", None) == passage.get("id"):
                passage["event_plate"] = plate

            asyncio.create_task(
                self._handle_detected_plate(
                    plate=plate,
                    confidence=confidence,
                    crop=crop.copy(),
                    lane=track.lane,
                    zone_name=track.zone_name,
                    now=now,
                    event_key=f"{self.camera_id}:{track_id}",
                    video_timecode=self._get_video_timecode(),
                )
            )

    def _schedule_ready_passage_events(self, now: float) -> None:
        """Finalize one aggregate result after every fragmented track in a lane goes quiet."""
        if getattr(self, "_ai_busy", False):
            return
        seen_passage_ids: set[str] = set()
        for passage in list(getattr(self, "_lane_passages", {}).values()):
            passage_id = str(passage.get("id") or "")
            if not passage_id or passage_id in seen_passage_ids:
                continue
            seen_passage_ids.add(passage_id)
            if passage.get("event_plate") or passage.get("filtered") or (now - float(passage["last_seen"])) < 3.0:
                continue
            if passage.get("localized_unread_only"):
                if int(passage.get("unread_support", 0)) < 2:
                    continue
                lane_last_activity = float(
                    getattr(self, "_lane_last_activity", {}).get(passage.get("lane"), 0.0)
                )
                if lane_last_activity > 0.0 and (now - lane_last_activity) < 2.0:
                    continue
            if (
                int(passage.get("vehicle_observations", 3)) < 3
                or (
                    float(passage.get("last_seen", now))
                    - float(passage.get("first_vehicle_seen", float(passage.get("last_seen", now)) - 0.25))
                ) < 0.25
            ):
                continue
            aggregate = passage.get("aggregate_track")
            crop = passage.get("crop")
            if aggregate is None:
                self._emit_unknown_passage(passage, now)
                continue
            if crop is None or crop.size == 0 or not aggregate.has_finalizable_plate(now):
                if (now - float(passage["last_seen"])) >= 4.5:
                    self._emit_unknown_passage(passage, now)
                continue
            plate = str(passage.get("best_plate") or aggregate.best_plate)
            confidence = float(passage.get("best_confidence", aggregate.best_conf))
            compact_p = self._compact_plate(plate)
            if not compact_p:
                self._emit_unknown_passage(passage, now)
                continue
            if self._is_recent_passage_variant(plate, passage["lane"], now):
                passage["event_plate"] = plate
                aggregate.mark_event_emitted()
                continue
            recent_events = getattr(self, "_recent_events", {})
            if (now - recent_events.get(compact_p, 0.0)) < 120.0:
                passage["event_plate"] = plate
                aggregate.mark_event_emitted()
                for track in self.tracker.tracks.values():
                    if getattr(track, "passage_id", None) == passage["id"]:
                        track.mark_event_emitted()
                continue
            if not self._event_meets_confidence_threshold(confidence):
                logger.info(
                    "[%s] Logging unread passage: best plate %s at %.0f%% is below configured %.0f%% threshold",
                    self.camera_id,
                    plate,
                    confidence * 100,
                    self.min_confidence * 100,
                )
                self._emit_unknown_passage(passage, now)
                continue
            passage["event_plate"] = plate
            if not hasattr(self, "_recent_events"):
                self._recent_events = {}
            self._recent_events[compact_p] = now
            self._remember_passage_result(plate, confidence, passage["lane"], now)
            aggregate.mark_event_emitted()
            for track in self.tracker.tracks.values():
                if getattr(track, "passage_id", None) == passage["id"]:
                    track.best_plate = plate
                    track.best_conf = confidence
                    track.mark_event_emitted()
            asyncio.create_task(
                self._handle_detected_plate(
                    plate=plate,
                    confidence=confidence,
                    crop=crop.copy(),
                    lane=passage["lane"],
                    zone_name=passage["zone_name"],
                    now=now,
                    event_key=f"{self.camera_id}:{passage['id']}",
                    video_timecode=(
                        str(passage.get("video_timecode"))
                        if passage.get("video_timecode") not in {None, "", "00:00", "00:00:00"}
                        else self._get_video_timecode()
                    ),
                )
            )

    def process_single_frame(self) -> Dict[str, Any]:
        """
        Synchronous single frame processing for snapshot generation and tests.
        """
        success, frame = self.reader.read_frame()
        if not success or frame is None:
            return {"success": False, "detections": []}

        now = time.time()
        self.buffer.append(frame, now)
        self.frame_count += 1
        h, w = frame.shape[:2]

        raw_detections = self.detector.detect(frame)
        in_zone_vehicles: List[Dict[str, Any]] = []
        for det in raw_detections:
            in_zone, lane, z_name = self._find_matching_zone(det["bbox"], w, h)
            if in_zone:
                det["lane"] = lane
                det["zone_name"] = z_name
                in_zone_vehicles.append(det)

        self._sync_plate_detection(frame, in_zone_vehicles, now)
        if hasattr(self.tracker, "update_visual_tracks"):
            self.tracker.update_visual_tracks(frame, now)
        live_detections = self.tracker.get_live_detections(now, getattr(self, "min_confidence", 0.70))

        return {
            "success": True,
            "camera_id": self.camera_id,
            "timestamp": int(now * 1000),
            "frame": frame,
            "detections": live_detections,
            "fps": self.target_fps,
            "timecode": self._get_video_timecode(),
            "frame_width": w,
            "frame_height": h,
        }

    async def process_gate_frame(self) -> Dict[str, Any]:
        """
        Processes one video frame:
        1. Reads frame from RTSP stream / video file.
        2. Runs YOLO vehicle detection and maps detections into active zones.
        3. Updates continuous vehicle tracking and smooth plate bounding boxes.
        4. Triggers throttled Plate Detection & OCR in background.
        5. Returns streaming frame and real-time bounding boxes.
        """
        success, frame = self.reader.read_frame()
        if not success or frame is None:
            return {"success": False, "detections": []}

        now = time.time()
        self.buffer.append(frame, now)
        self.frame_count += 1
        h, w = frame.shape[:2]

        # 1. Periodically sync active zones for this camera from DB
        if now - self._last_zone_sync >= 4.0:
            asyncio.create_task(self._sync_active_zones(now))
        if now - getattr(self, "_last_vehicle_status_sync", 0.0) >= 1.0:
            self._last_vehicle_status_sync = now
            asyncio.create_task(self._sync_registered_vehicle_statuses(now))

        # 2. Run fast YOLO vehicle detection (cadence-controlled for high 15+ FPS throughput)
        should_run_yolo = (self.frame_count % self._yolo_stride == 0) or (len(self.tracker.tracks) == 0)
        raw_detections = []
        if should_run_yolo:
            det_w = int(os.getenv("GATE_YOLO_WIDTH", "960"))
            det_h = int(os.getenv("GATE_YOLO_HEIGHT", "540"))
            if w > det_w or h > det_h:
                scale_x = w / float(det_w)
                scale_y = h / float(det_h)
                det_input = cv2.resize(frame, (det_w, det_h))
                raw_detections = self.detector.detect(det_input)
                for d in raw_detections:
                    bx1, by1, bx2, by2 = d["bbox"]
                    d["bbox"] = [
                        int(bx1 * scale_x),
                        int(by1 * scale_y),
                        int(bx2 * scale_x),
                        int(by2 * scale_y),
                    ]
            else:
                raw_detections = self.detector.detect(frame)
            if raw_detections:
                self._cached_vehicle_detections = [dict(item) for item in raw_detections]
                self._cached_vehicle_detections_at = now
        cached_at = getattr(self, "_cached_vehicle_detections_at", 0.0)
        if not raw_detections and (now - cached_at) <= 0.25:
            raw_detections = [dict(item) for item in getattr(self, "_cached_vehicle_detections", [])]

        # 3. Filter vehicles strictly inside active configured zones (car/truck/bus only)
        in_zone_vehicles = []
        for d in raw_detections:
            if d["class"] in ["car", "truck", "bus"]:
                vx1, vy1, vx2, vy2 = d["bbox"]
                vw, vh = vx2 - vx1, vy2 - vy1
                if vw < 50 or vh < 30:
                    continue

                is_in_zone, zname, lane = self._find_matching_zone([vx1, vy1, vx2, vy2], w, h)
                if not is_in_zone:
                    # Vehicle is outside configured gate zone -> IGNORE!
                    continue

                d["zone_name"] = zname
                d["lane"] = lane
                in_zone_vehicles.append(d)

        in_zone_vehicles = self._dedupe_vehicle_detections(in_zone_vehicles)
        occupied_lanes = {item["lane"] for item in in_zone_vehicles}
        in_zone_vehicles.extend(self._zone_fallback_detections(w, h, occupied_lanes))
        video_timecode = self._get_video_timecode()
        for item in in_zone_vehicles:
            item["_video_timecode"] = video_timecode
        tracked_vehicles = [item for item in in_zone_vehicles if not item.get("_zone_fallback")]
        if hasattr(self.tracker, "match_detections"):
            assigned_track_ids = self.tracker.match_detections(tracked_vehicles, now)
        else:
            assigned_track_ids = [
                self.tracker.match_or_create_track(item["bbox"], now)
                for item in tracked_vehicles
            ]

        assigned_index = 0
        for d in in_zone_vehicles:
            if d.get("_zone_fallback"):
                continue
            vx1, vy1, vx2, vy2 = d["bbox"]
            track_id = assigned_track_ids[assigned_index]
            assigned_index += 1
            d["_track_id"] = track_id
            # Keep tracking vehicle position smoothly without fake plate boxes
            self.tracker.update_track(
                track_id=track_id,
                vehicle_bbox=[vx1, vy1, vx2, vy2],
                plate_bbox=None,
                plate_text="",
                status="SCANNING",
                conf=0.85,
                now=now,
            )
            vehicle_track = self.tracker.tracks.get(track_id)
            if vehicle_track is not None:
                vehicle_track.lane = d["lane"]
                vehicle_track.zone_name = d["zone_name"]
                passage = self._touch_vehicle_passage(track_id, d["lane"], now, vehicle_track)
                vehicle_track.passage_id = passage["id"]
                passage["zone_name"] = d["zone_name"]
                passage["video_timecode"] = str(d.get("_video_timecode") or video_timecode)
                passage["vehicle_observations"] = int(passage.get("vehicle_observations", 0)) + 1
                passage["high_angle"] = bool(
                    passage.get("high_angle")
                    or d.get("_top_view_alias")
                    or self._is_high_angle_vehicle(vehicle_track.vehicle_bbox, w, h)
                )
                crop_y1 = vy1 if passage["high_angle"] else vy1 + int((vy2 - vy1) * 0.35)
                vehicle_crop = frame[max(0, crop_y1):min(h, vy2), max(0, vx1):min(w, vx2)]
                if vehicle_crop.size > 0:
                    passage["vehicle_crop"] = vehicle_crop.copy()
                self.tracker.update_related_plate_tracks(track_id, vehicle_track.vehicle_bbox, now)

        if hasattr(self.tracker, "update_visual_tracks"):
            self.tracker.update_visual_tracks(frame, now)
        if not hasattr(self, "_lane_last_activity"):
            self._lane_last_activity = {}
        for item in tracked_vehicles:
            self._lane_last_activity[item["lane"]] = now
        if hasattr(self.tracker, "get_visual_active_lanes"):
            for lane in self.tracker.get_visual_active_lanes(now):
                self._lane_last_activity[lane] = now

        # 4. Trigger throttled Plate Detection & OCR in background.
        if (
            not self._ai_busy
            and in_zone_vehicles
            and (now - self._last_ocr_dispatch) >= self._ocr_interval_seconds
        ):
            self._last_ocr_dispatch = now
            self._ocr_cycle = getattr(self, "_ocr_cycle", 0) + 1
            ocr_pool = in_zone_vehicles
            if self._active_zones and (self._ocr_cycle % 3 == 0):
                ocr_pool = self._zone_fallback_detections(w, h, set())
            else:
                physical_ocr_pool = [
                    item for item in in_zone_vehicles if not item.get("_zone_fallback")
                ]
                if physical_ocr_pool:
                    ocr_pool = physical_ocr_pool
            for item in ocr_pool:
                item.setdefault("_video_timecode", video_timecode)
            prioritized_vehicles = self._prioritize_ocr_detections(ocr_pool, now, limit=2)
            asyncio.create_task(
                self._run_ai_in_background(
                    frame.copy(),
                    prioritized_vehicles,
                    now,
                    getattr(self, "_tracking_generation", 0),
                )
            )

        # 5. Finalize tracks after the plate leaves view, then return live overlays.
        self._schedule_ready_passage_events(now)
        self._schedule_ready_track_events(now)
        live_detections = self.tracker.get_live_detections(now, getattr(self, "min_confidence", 0.70))

        # 6. Encode Stream-Optimized JPEG frame to base64
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(os.getenv("GATE_JPEG_QUALITY", "50"))]
        ret, buf = cv2.imencode(".jpg", frame, encode_params)
        b64_str = f"data:image/jpeg;base64,{base64.b64encode(buf.tobytes()).decode('ascii')}" if ret else ""

        self._fps_counter += 1
        elapsed = now - self._last_fps_calc
        if elapsed >= 1.0:
            self.fps_measured = round(self._fps_counter / elapsed, 1)
            self._fps_counter = 0
            self._last_fps_calc = now

        timecode = video_timecode

        return {
            "success": True,
            "camera_id": self.camera_id,
            "timestamp": int(now * 1000),
            "frame": frame,
            "image_base64": b64_str,
            "detections": live_detections,  # Live license plate bounding boxes in zone
            "fps": self.fps_measured or self.target_fps,
            "timecode": timecode,
            "frame_width": w,
            "frame_height": h,
        }

    async def _loop(self) -> None:
        """Continuous video stream emission loop."""
        logger.info("[%s] Gate Universal LPR Pipeline loop started at %.1f FPS.", self.camera_id, self.target_fps)
        interval = 1.0 / self.target_fps

        while self._running:
            start_t = time.time()
            try:
                result = await self.process_gate_frame()

                if result.get("success"):
                    # Emit live frame + live plate detections to /ws/publish/feed/GATE-01
                    await self.emitter.emit_frame(
                        camera_id=self.camera_id,
                        image_base64=result["image_base64"],
                        detections=result["detections"],
                        fps=result["fps"],
                        timecode=result.get("timecode"),
                        frame_width=result.get("frame_width"),
                        frame_height=result.get("frame_height"),
                    )

            except Exception as exc:
                logger.error("[%s] Error in gate pipeline loop: %s", self.camera_id, exc)

            elapsed = time.time() - start_t
            sleep_time = max(0.001, interval - elapsed)
            await asyncio.sleep(sleep_time)

        logger.info("[%s] Gate Universal LPR Pipeline loop ended.", self.camera_id)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    def reset_tracking_state(self) -> None:
        """Reset passage-local state after a playback seek or source discontinuity."""
        self.tracker.tracks.clear()
        self._recent_events.clear()
        self._recent_passage_results.clear()
        self._event_ids_by_key.clear()
        self._lane_passages.clear()
        self._lane_fallback_last_ocr.clear()
        self._lane_last_activity.clear()
        self._recent_unknown_lanes.clear()
        self._tracking_generation += 1
        self._last_ocr_dispatch = 0.0
        self._ocr_cycle = 0
        self._cached_vehicle_detections = []
        self._cached_vehicle_detections_at = 0.0

    async def stop(self) -> None:
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
        self._executor.shutdown(wait=False)
        self.reader.release()
        await self.emitter.close()
        logger.info("[%s] Gate LPR Pipeline stopped cleanly.", self.camera_id)
