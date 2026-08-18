"""
zone.zone_checker — Pure Point-in-Polygon Containment, Rule Matrix, and Violation State Machine

Coordinates:
- DB polygon_points: [{"x": float, "y": float}] in [0, 1]
- Detection: normalized bottom-center point ((x1+x2)/2, y2)
- Containment: Shapely.Polygon.covers(Point) (boundary included)
- Rules: PROHIBIT_SPECIFIED vs ALLOW_SPECIFIED
- State Machine: (camera_id, track_id, zone_id) with entry/exit hysteresis,
  3-frame exit grace, and missing-track reconnect grace
"""
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from shapely.geometry import Point, Polygon

logger = logging.getLogger("sentriai.zone.checker")


def parse_polygon(points_data: Any) -> Optional[Polygon]:
    """
    Parse polygon points from JSON array of {'x': float, 'y': float} or [[x, y], ...].
    Returns a valid Shapely Polygon or None if invalid.
    """
    if not points_data or not isinstance(points_data, (list, tuple)):
        return None

    coords: List[Tuple[float, float]] = []
    for pt in points_data:
        if isinstance(pt, dict) and "x" in pt and "y" in pt:
            try:
                coords.append((float(pt["x"]), float(pt["y"])))
            except (ValueError, TypeError):
                return None
        elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
            try:
                coords.append((float(pt[0]), float(pt[1])))
            except (ValueError, TypeError):
                return None
        else:
            return None

    if len(coords) < 3:
        return None

    if any(
        not math.isfinite(coord) or coord < 0.0 or coord > 1.0
        for point in coords
        for coord in point
    ):
        return None

    try:
        poly = Polygon(coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or len(poly.exterior.coords) < 4:
            return None
        return poly
    except Exception as exc:
        logger.warning("Failed to create Polygon: %s", exc)
        return None


def get_detection_bottom_center(
    normalized_bbox: List[float],
) -> Tuple[float, float]:
    """
    Compute normalized bottom-center point ((x1+x2)/2, y2) in [0, 1].
    Represents ground contact for overhead camera BAI-KIEM.
    """
    x1, y1, x2, y2 = normalized_bbox
    px = (x1 + x2) / 2.0
    py = y2
    return px, py


def evaluate_zone_rule(
    rule_type: str,
    target_labels: List[str],
    candidate_labels: List[str],
) -> str:
    """
    Evaluate zone rule matrix.
    Returns 'VIOLATION' or 'ALLOWED'.
    
    Rule Matrix:
    - PROHIBIT_SPECIFIED:
        any candidate in target_labels -> VIOLATION
        otherwise -> ALLOWED
    - ALLOW_SPECIFIED:
        any candidate in target_labels -> ALLOWED
        otherwise (including CHƯA XÁC ĐỊNH) -> VIOLATION (BR-04)
    """
    norm_targets = {t.strip().casefold() for t in target_labels if t}
    norm_candidates = {c.strip().casefold() for c in candidate_labels if c}

    has_target_match = bool(norm_targets.intersection(norm_candidates))

    norm_rule = rule_type.strip().upper() if rule_type else "PROHIBIT_SPECIFIED"

    if norm_rule == "PROHIBIT_SPECIFIED":
        return "VIOLATION" if has_target_match else "ALLOWED"
    elif norm_rule == "ALLOW_SPECIFIED":
        return "ALLOWED" if has_target_match else "VIOLATION"
    else:
        # Default fallback to PROHIBIT_SPECIFIED
        return "VIOLATION" if has_target_match else "ALLOWED"


def resolve_candidate_labels(
    yolo_class: str,
    coco_label: str,
    class_to_labels: Dict[str, List[str]],
) -> List[str]:
    """
    Resolve candidate Vietnamese names for a YOLO class.
    1. Check class_to_labels (from object_labels table)
    2. If no database mapping exists, return ['CHƯA XÁC ĐỊNH'].
    """
    c_folded = yolo_class.strip().casefold() if yolo_class else ""
    if c_folded in class_to_labels and class_to_labels[c_folded]:
        return class_to_labels[c_folded]

    return ["CHƯA XÁC ĐỊNH"]


def choose_display_label(
    candidate_labels: List[str],
    target_labels: Optional[List[str]] = None,
) -> str:
    """
    Choose the best display label:
    - If any candidate matches target_labels of the zone, prefer it.
    - Otherwise use the first candidate.
    """
    if not candidate_labels:
        return "CHƯA XÁC ĐỊNH"

    if target_labels:
        norm_targets = {t.strip().casefold() for t in target_labels if t}
        for cand in candidate_labels:
            if cand.strip().casefold() in norm_targets:
                return cand

    return candidate_labels[0]


@dataclass
class ActiveViolation:
    violation_id: str
    camera_id: str
    track_id: int
    zone_id: str
    zone_name: str
    object_label: str
    entered_at: datetime
    last_seen_inside: datetime
    consecutive_outside: int = 0
    normalized_bbox: Optional[Tuple[float, float, float, float]] = None
    yolo_class: str = ""


@dataclass
class ViolationTransition:
    action: str  # 'STARTED' or 'ENDED'
    violation_id: str
    camera_id: str
    track_id: int
    zone_id: str
    zone_name: str
    object_label: str
    status: str  # 'OPEN' or 'CLOSED'
    entered_at: datetime
    exited_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None


class ZoneChecker:
    """
    Zone containment evaluation and in-memory violation state machine.
    """

    def __init__(
        self,
        camera_id: str = "BAI-KIEM",
        grace_frames: int = 3,
        missing_grace_seconds: float = 5.0,
        boundary_hysteresis: float = 0.02,
    ):
        self.camera_id = camera_id
        self.grace_frames = max(1, int(grace_frames))
        self.missing_grace_seconds = max(0.0, float(missing_grace_seconds))
        # Coordinates are normalized [0, 1]. At the 640px Area inference width,
        # 0.02 is roughly 13px: enough to absorb detector jitter at a zone edge
        # without treating a genuine exit as inside.
        self.boundary_hysteresis = min(0.1, max(0.0, float(boundary_hysteresis)))
        # Key: (camera_id, track_id, zone_id)
        self.active_violations: Dict[Tuple[str, int, str], ActiveViolation] = {}

    def discard_started_transition(self, transition: ViolationTransition) -> None:
        """Drop a just-opened in-memory event when its DB insert failed."""
        key = (transition.camera_id, transition.track_id, transition.zone_id)
        active = self.active_violations.get(key)
        if active and active.violation_id == transition.violation_id:
            del self.active_violations[key]

    def restore_ended_transition(self, transition: ViolationTransition) -> None:
        """Restore a close transition so the next absent frame can retry persistence."""
        key = (transition.camera_id, transition.track_id, transition.zone_id)
        if key in self.active_violations:
            return

        last_seen = transition.exited_at or transition.entered_at
        self.active_violations[key] = ActiveViolation(
            violation_id=transition.violation_id,
            camera_id=transition.camera_id,
            track_id=transition.track_id,
            zone_id=transition.zone_id,
            zone_name=transition.zone_name,
            object_label=transition.object_label,
            entered_at=transition.entered_at,
            last_seen_inside=last_seen,
            consecutive_outside=max(0, self.grace_frames - 1),
        )

    @staticmethod
    def _bbox_iou(
        first: Tuple[float, float, float, float],
        second: Tuple[float, float, float, float],
    ) -> float:
        left = max(first[0], second[0])
        top = max(first[1], second[1])
        right = min(first[2], second[2])
        bottom = min(first[3], second[3])
        intersection = max(0.0, right - left) * max(0.0, bottom - top)
        if intersection <= 0.0:
            return 0.0

        first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
        second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
        union = first_area + second_area - intersection
        return intersection / union if union > 0.0 else 0.0

    @staticmethod
    def _bbox_center_distance(
        first: Tuple[float, float, float, float],
        second: Tuple[float, float, float, float],
    ) -> float:
        first_x = (first[0] + first[2]) / 2.0
        first_y = (first[1] + first[3]) / 2.0
        second_x = (second[0] + second[2]) / 2.0
        second_y = (second[1] + second[3]) / 2.0
        return math.hypot(first_x - second_x, first_y - second_y)

    def _find_reidentified_active_key(
        self,
        track_id: int,
        zone_id: str,
        object_label: str,
        yolo_class: str,
        normalized_bbox: Tuple[float, float, float, float],
        observed_track_ids: Set[int],
        now: datetime,
    ) -> Optional[Tuple[str, int, str]]:
        """Reconnect a just-renumbered ByteTrack identity before opening a duplicate event."""
        best_key: Optional[Tuple[str, int, str]] = None
        best_iou = 0.0

        for key, active in self.active_violations.items():
            if (
                active.camera_id != self.camera_id
                or active.zone_id != zone_id
                or active.track_id == track_id
                or active.track_id in observed_track_ids
                or (now - active.last_seen_inside).total_seconds() >= self.missing_grace_seconds
                or active.object_label.casefold() != object_label.casefold()
                or active.yolo_class != yolo_class
                or active.normalized_bbox is None
            ):
                continue

            iou = self._bbox_iou(active.normalized_bbox, normalized_bbox)
            distance = self._bbox_center_distance(active.normalized_bbox, normalized_bbox)
            if (iou >= 0.2 or distance <= 0.08) and iou >= best_iou:
                best_key = key
                best_iou = iou

        return best_key

    def check_detections(
        self,
        detections: List[Dict[str, Any]],
        zones: List[Dict[str, Any]],
        class_to_labels: Dict[str, List[str]],
        timestamp: Optional[datetime] = None,
    ) -> Tuple[List[Dict[str, Any]], List[ViolationTransition]]:
        """
        Process detections against active zones for one frame:
        1. Annotates each detection with zoneMatches and overall status (VIOLATION/ALLOWED).
        2. Advances in-memory violation state machine and returns any STARTED/ENDED transitions.
        """
        now = timestamp or datetime.now(timezone.utc)
        parsed_zones: List[Tuple[Dict[str, Any], Optional[Polygon], Optional[Any]]] = []

        for z in zones:
            poly = parse_polygon(z.get("polygon_points") or z.get("polygon"))
            buffered_poly = (
                poly.buffer(self.boundary_hysteresis)
                if poly is not None and self.boundary_hysteresis > 0.0
                else poly
            )
            parsed_zones.append((z, poly, buffered_poly))

        # Track keys present in this frame with VIOLATION status
        current_violations_in_frame: Dict[
            Tuple[str, int, str],
            Tuple[Dict[str, Any], str, Tuple[float, float, float, float], str],
        ] = {}
        observed_track_ids: Set[int] = set()

        annotated_detections: List[Dict[str, Any]] = []

        for det in detections:
            bbox = det.get("bbox", [0, 0, 0, 0])
            norm_bbox = det.get("normalized_bbox")
            if not norm_bbox:
                # Fallback if normalized_bbox missing
                w, h = 640, 480
                norm_bbox = [
                    round(bbox[0] / w, 4),
                    round(bbox[1] / h, 4),
                    round(bbox[2] / w, 4),
                    round(bbox[3] / h, 4),
                ]

            px, py = get_detection_bottom_center(norm_bbox)
            det_point = Point(px, py)

            yolo_cls = det.get("class", "")
            coco_lbl = det.get("label", "")
            candidates = resolve_candidate_labels(yolo_cls, coco_lbl, class_to_labels)
            raw_track_id = det.get("trackId")
            track_id = int(raw_track_id) if raw_track_id is not None else None
            if track_id is not None:
                observed_track_ids.add(track_id)

            zone_matches: List[Dict[str, Any]] = []
            has_violation = False
            first_violating_label = None

            for z_dict, poly, buffered_poly in parsed_zones:
                if poly is None:
                    continue

                rule_type = z_dict.get("rule_type") or z_dict.get("ruleType") or "PROHIBIT_SPECIFIED"
                target_labels = z_dict.get("target_labels") or z_dict.get("targetLabels") or []
                if isinstance(target_labels, str):
                    target_labels = [target_labels]

                match_status = evaluate_zone_rule(rule_type, target_labels, candidates)
                zone_id = str(z_dict["id"])
                zone_name = z_dict.get("name", "Zone")
                key = (self.camera_id, track_id, zone_id) if track_id is not None else None

                # Opening remains strict: only an exact polygon hit can create a
                # violation. For an already-open violation, a small outward
                # buffer avoids false exits/reopens when the detector jitters
                # around the polygon edge.
                exact_inside = poly.covers(det_point)
                sustained_inside = (
                    key is not None
                    and key in self.active_violations
                    and match_status == "VIOLATION"
                    and buffered_poly is not None
                    and buffered_poly.covers(det_point)
                )
                if not exact_inside and not sustained_inside:
                    continue

                zone_matches.append({
                    "zoneId": zone_id,
                    "zoneName": zone_name,
                    "status": match_status,
                })

                if match_status == "VIOLATION":
                    has_violation = True
                    disp_lbl = choose_display_label(candidates, target_labels)
                    if first_violating_label is None:
                        first_violating_label = disp_lbl

                    # Only tracks with valid trackId can open/maintain persisted violations
                    if track_id is not None:
                        current_violations_in_frame[key] = (
                            z_dict,
                            disp_lbl,
                            tuple(float(value) for value in norm_bbox),
                            yolo_cls,
                        )

            # Sort zoneMatches by zoneName then zoneId
            zone_matches.sort(key=lambda m: (m["zoneName"], m["zoneId"]))

            overall_status = "VIOLATION" if has_violation else "ALLOWED"
            chosen_label = first_violating_label or choose_display_label(candidates)

            annotated_det = dict(det)
            annotated_det["label"] = chosen_label
            annotated_det["status"] = overall_status
            annotated_det["zoneMatches"] = zone_matches
            annotated_detections.append(annotated_det)

        # ---------------------------------------------------------------------
        # State Machine Transitions
        # ---------------------------------------------------------------------
        transitions: List[ViolationTransition] = []

        # 1. Check current violations in frame (OPEN / SUSTAIN)
        for key, (z_dict, obj_label, norm_bbox, yolo_class) in current_violations_in_frame.items():
            cam_id, track_id, zone_id = key
            zone_name = z_dict.get("name", "Zone")

            if key in self.active_violations:
                # Sustained inside -> reset grace counter, update last_seen
                active = self.active_violations[key]
                active.last_seen_inside = now
                active.consecutive_outside = 0
                active.normalized_bbox = norm_bbox
                active.yolo_class = yolo_class
            else:
                prior_key = self._find_reidentified_active_key(
                    track_id,
                    zone_id,
                    obj_label,
                    yolo_class,
                    norm_bbox,
                    observed_track_ids,
                    now,
                )
                if prior_key is not None:
                    # ByteTrack can assign a fresh ID after a brief occlusion. Keep the
                    # persisted violation open and move its in-memory key to the new ID.
                    active = self.active_violations.pop(prior_key)
                    active.track_id = track_id
                    active.last_seen_inside = now
                    active.consecutive_outside = 0
                    active.normalized_bbox = norm_bbox
                    active.yolo_class = yolo_class
                    self.active_violations[key] = active
                else:
                    # New transition: OPEN
                    vid = str(uuid.uuid4())
                    active = ActiveViolation(
                        violation_id=vid,
                        camera_id=cam_id,
                        track_id=track_id,
                        zone_id=zone_id,
                        zone_name=zone_name,
                        object_label=obj_label,
                        entered_at=now,
                        last_seen_inside=now,
                        consecutive_outside=0,
                        normalized_bbox=norm_bbox,
                        yolo_class=yolo_class,
                    )
                    self.active_violations[key] = active

                    transitions.append(ViolationTransition(
                        action="STARTED",
                        violation_id=vid,
                        camera_id=cam_id,
                        track_id=track_id,
                        zone_id=zone_id,
                        zone_name=zone_name,
                        object_label=obj_label,
                        status="OPEN",
                        entered_at=now,
                    ))

        # 2. Check active violations not seen as violating in this frame.
        # A confirmed track seen outside/allowed is a real exit candidate and uses the
        # short frame grace. A missing track is held by wall-clock time so intermittent
        # detector loss or ByteTrack renumbering cannot repeatedly reopen the same event.
        keys_to_remove: List[Tuple[str, int, str]] = []
        for key, active in list(self.active_violations.items()):
            if key not in current_violations_in_frame:
                should_close = False
                if active.track_id in observed_track_ids:
                    active.consecutive_outside += 1
                    should_close = active.consecutive_outside >= self.grace_frames
                else:
                    missing_seconds = (now - active.last_seen_inside).total_seconds()
                    should_close = missing_seconds >= self.missing_grace_seconds

                if should_close:
                    # Transition: CLOSED
                    exit_ts = active.last_seen_inside
                    dur = max(0, int((exit_ts - active.entered_at).total_seconds()))

                    transitions.append(ViolationTransition(
                        action="ENDED",
                        violation_id=active.violation_id,
                        camera_id=active.camera_id,
                        track_id=active.track_id,
                        zone_id=active.zone_id,
                        zone_name=active.zone_name,
                        object_label=active.object_label,
                        status="CLOSED",
                        entered_at=active.entered_at,
                        exited_at=exit_ts,
                        duration_seconds=dur,
                    ))
                    keys_to_remove.append(key)

        for key in keys_to_remove:
            del self.active_violations[key]

        return annotated_detections, transitions
