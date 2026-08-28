"""Pure lifecycle tracking for every registry object observed inside an Area zone."""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple


Box = Tuple[float, float, float, float]
Key = Tuple[str, int, str]


@dataclass
class PendingActivity:
    camera_id: str
    track_id: int
    zone_id: str
    zone_name: str
    object_label: str
    canonical_class: str
    policy_result: str
    entered_at: datetime
    last_seen_at: datetime
    normalized_bbox: Box
    entry_point: Tuple[float, float]


@dataclass
class ActiveActivity(PendingActivity):
    session_id: str = ""
    consecutive_outside: int = 0


@dataclass
class ActivityTransition:
    action: str
    session_id: str
    camera_id: str
    track_id: int
    zone_id: str
    zone_name: str
    object_label: str
    canonical_class: str
    policy_result: str
    entered_at: datetime
    last_seen_at: datetime
    entry_point: Tuple[float, float]
    exited_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    violation_id: Optional[str] = None
    source_metadata: Optional[Dict[str, Any]] = None


class ActivityTracker:
    """Track independent `(camera, track, zone)` sessions without persistence I/O."""

    def __init__(
        self,
        camera_id: str = "BAI-KIEM",
        confirmation_seconds: float = 1.0,
        grace_frames: int = 3,
        missing_grace_seconds: float = 12.0,
    ) -> None:
        self.camera_id = camera_id
        self.confirmation_seconds = max(0.0, float(confirmation_seconds))
        self.grace_frames = max(1, int(grace_frames))
        self.missing_grace_seconds = max(0.0, float(missing_grace_seconds))
        self.pending_sessions: Dict[Key, PendingActivity] = {}
        self.active_sessions: Dict[Key, ActiveActivity] = {}

    @staticmethod
    def _box(value: Any) -> Optional[Box]:
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            return None
        try:
            box = tuple(float(item) for item in value)
        except (TypeError, ValueError):
            return None
        return box if all(math.isfinite(item) for item in box) else None  # type: ignore[return-value]

    @staticmethod
    def _entry_point(box: Box) -> Tuple[float, float]:
        return ((box[0] + box[2]) / 2.0, box[3])

    @staticmethod
    def _iou(first: Box, second: Box) -> float:
        left, top = max(first[0], second[0]), max(first[1], second[1])
        right, bottom = min(first[2], second[2]), min(first[3], second[3])
        intersection = max(0.0, right - left) * max(0.0, bottom - top)
        first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
        second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
        union = first_area + second_area - intersection
        return intersection / union if union > 0 else 0.0

    @staticmethod
    def _center_distance(first: Box, second: Box) -> float:
        return math.hypot(
            (first[0] + first[2] - second[0] - second[2]) / 2.0,
            (first[1] + first[3] - second[1] - second[3]) / 2.0,
        )

    def _find_reidentified_key(
        self,
        track_id: int,
        zone_id: str,
        canonical_class: str,
        bbox: Box,
        observed_track_ids: Set[int],
        now: datetime,
    ) -> Optional[Key]:
        best: Optional[Key] = None
        best_iou = -1.0
        for key, active in self.active_sessions.items():
            if (
                active.zone_id != zone_id
                or active.canonical_class != canonical_class
                or active.track_id == track_id
                or active.track_id in observed_track_ids
                or (now - active.last_seen_at).total_seconds() >= self.missing_grace_seconds
            ):
                continue
            iou = self._iou(active.normalized_bbox, bbox)
            distance = self._center_distance(active.normalized_bbox, bbox)
            if (iou >= 0.2 or distance <= 0.08) and iou > best_iou:
                best, best_iou = key, iou
        return best

    @staticmethod
    def _ended(active: ActiveActivity) -> ActivityTransition:
        return ActivityTransition(
            action="ENDED",
            session_id=active.session_id,
            camera_id=active.camera_id,
            track_id=active.track_id,
            zone_id=active.zone_id,
            zone_name=active.zone_name,
            object_label=active.object_label,
            canonical_class=active.canonical_class,
            policy_result=active.policy_result,
            entered_at=active.entered_at,
            last_seen_at=active.last_seen_at,
            entry_point=active.entry_point,
            exited_at=active.last_seen_at,
            duration_seconds=max(0, int((active.last_seen_at - active.entered_at).total_seconds())),
        )

    def check_detections(
        self,
        detections: List[Dict[str, Any]],
        timestamp: Optional[datetime] = None,
    ) -> List[ActivityTransition]:
        now = timestamp or datetime.now(timezone.utc)
        observed_track_ids: Set[int] = set()
        inside: Dict[Key, Tuple[Dict[str, Any], Mapping[str, Any], Box, str]] = {}

        for detection in detections:
            raw_track_id = detection.get("trackId")
            if not isinstance(raw_track_id, int):
                continue
            observed_track_ids.add(raw_track_id)
            bbox = self._box(detection.get("normalized_bbox"))
            if bbox is None:
                continue
            canonical = detection.get("canonicalClass") or detection.get("class")
            if not isinstance(canonical, str) or not canonical.strip():
                continue
            canonical = canonical.strip().casefold()
            for match in detection.get("zoneMatches") or []:
                if not isinstance(match, Mapping):
                    continue
                zone_id = match.get("zoneId")
                status = match.get("status")
                if not isinstance(zone_id, str) or status not in {"ALLOWED", "VIOLATION"}:
                    continue
                inside[(self.camera_id, raw_track_id, zone_id)] = (detection, match, bbox, canonical)

        transitions: List[ActivityTransition] = []
        for key, (detection, match, bbox, canonical) in inside.items():
            _, track_id, zone_id = key
            if key in self.active_sessions:
                active = self.active_sessions[key]
                active.last_seen_at = now
                active.normalized_bbox = bbox
                active.consecutive_outside = 0
                continue

            prior_key = self._find_reidentified_key(
                track_id, zone_id, canonical, bbox, observed_track_ids, now,
            )
            if prior_key is not None:
                active = self.active_sessions.pop(prior_key)
                active.track_id = track_id
                active.last_seen_at = now
                active.normalized_bbox = bbox
                active.consecutive_outside = 0
                self.active_sessions[key] = active
                continue

            pending = self.pending_sessions.get(key)
            if pending is None:
                if detection.get("canInitiate") is not True:
                    continue
                label = detection.get("label") or canonical
                pending = PendingActivity(
                    camera_id=self.camera_id,
                    track_id=track_id,
                    zone_id=zone_id,
                    zone_name=str(match.get("zoneName") or "Zone"),
                    object_label=str(label),
                    canonical_class=canonical,
                    policy_result=str(match["status"]),
                    entered_at=now,
                    last_seen_at=now,
                    normalized_bbox=bbox,
                    entry_point=self._entry_point(bbox),
                )
                self.pending_sessions[key] = pending
            else:
                # A strong observation opens pending state. Subsequent frames
                # commonly carry only continuation confidence; they must still
                # advance confirmation for the same track/class. If neither
                # gate is present, discard the pending candidate immediately.
                if not (
                    detection.get("canContinue") is True
                    or detection.get("canInitiate") is True
                ):
                    del self.pending_sessions[key]
                    continue
                pending.last_seen_at = now
                pending.normalized_bbox = bbox

            if (now - pending.entered_at).total_seconds() >= self.confirmation_seconds:
                active = ActiveActivity(**vars(pending), session_id=str(uuid.uuid4()))
                self.active_sessions[key] = active
                del self.pending_sessions[key]
                transitions.append(ActivityTransition(
                    action="STARTED",
                    session_id=active.session_id,
                    camera_id=active.camera_id,
                    track_id=active.track_id,
                    zone_id=active.zone_id,
                    zone_name=active.zone_name,
                    object_label=active.object_label,
                    canonical_class=active.canonical_class,
                    policy_result=active.policy_result,
                    entered_at=active.entered_at,
                    last_seen_at=active.last_seen_at,
                    entry_point=active.entry_point,
                ))

        for key in list(self.pending_sessions):
            if key not in inside:
                del self.pending_sessions[key]

        for key, active in list(self.active_sessions.items()):
            if key in inside:
                continue
            should_close = False
            if active.track_id in observed_track_ids:
                active.consecutive_outside += 1
                should_close = active.consecutive_outside >= self.grace_frames
            else:
                should_close = (now - active.last_seen_at).total_seconds() >= self.missing_grace_seconds
            if should_close:
                transitions.append(self._ended(active))
                del self.active_sessions[key]

        return transitions

    def end_all(self, _timestamp: Optional[datetime] = None) -> List[ActivityTransition]:
        transitions = [self._ended(active) for active in self.active_sessions.values()]
        self.active_sessions.clear()
        self.pending_sessions.clear()
        return transitions

    def clear_runtime_state(self) -> Tuple[int, int]:
        counts = (len(self.active_sessions), len(self.pending_sessions))
        self.active_sessions.clear()
        self.pending_sessions.clear()
        return counts
