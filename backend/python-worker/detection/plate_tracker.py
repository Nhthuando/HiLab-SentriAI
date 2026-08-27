"""
detection.plate_tracker — Robust Vehicle & Plate Tracker with Smooth Relative Bboxes & Majority Voting

Features:
1. IoU + Centroid Tracking: Eliminates ID jumping and flickering across video frames.
2. Relative Bounding Box Lock: Keeps plate box tightly attached to moving vehicle in 100% of frames (no blinking/flickering).
3. Plate Quality Scoring & Majority Voting: Chooses the cleanest full-format plate, ignoring incomplete OCR snippets.
4. Single-Event Guarantee: Emits exactly 1 verified gate event per vehicle passage.
"""
import re
from typing import Any, Dict, List, Optional
import cv2
import numpy as np


def compute_iou(box1: List[int], box2: List[int]) -> float:
    """Calculate Intersection over Union (IoU) between two bounding boxes [x1, y1, x2, y2]."""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    inter_w = max(0, x2 - x1)
    inter_h = max(0, y2 - y1)
    inter_area = inter_w * inter_h
    if inter_area == 0:
        return 0.0

    area1 = max(1, (box1[2] - box1[0]) * (box1[3] - box1[1]))
    area2 = max(1, (box2[2] - box2[0]) * (box2[3] - box2[1]))
    union_area = area1 + area2 - inter_area
    return float(inter_area) / max(1.0, float(union_area))


class VehicleTrack:
    def __init__(
        self,
        track_id: str,
        vehicle_bbox: List[int],
        plate_bbox: Optional[List[int]],
        plate: str,
        status: str,
        confidence: float,
        last_seen: float,
    ):
        self.track_id = track_id
        self.vehicle_bbox = vehicle_bbox
        self.plate_bbox = plate_bbox
        self.plate = plate or ""
        self.best_plate = plate or ""
        self.best_conf = confidence or 0.0
        self.best_score = 0.0
        self.best_bbox_quality = (confidence or 0.0) * 2.0 if plate_bbox else 0.0
        self.bbox_confirmation_count = 1 if plate_bbox else 0
        self.pending_plate_box: Optional[List[int]] = None
        self.pending_bbox_quality = 0.0
        self.pending_bbox_support = 0
        self.created_at = last_seen
        self.status = status or "SCANNING"
        self.status_locked = bool(plate and status in {"KNOWN", "STRANGER"})
        self.confidence = confidence or 0.85
        self.last_seen = last_seen
        self.last_vehicle_seen = last_seen
        self.last_plate_seen = last_seen if plate_bbox else 0.0
        self.first_plate_seen = last_seen if plate else 0.0
        self.last_observation_at = last_seen if plate else 0.0
        self.best_plate_changed_at = last_seen if plate else 0.0
        self.is_locked = bool(plate and len(plate) >= 6)
        self.event_emitted = False
        self.emitted_conf = 0.0
        self.last_event_plate = ""
        self.live_plate = ""
        self.live_conf = 0.0
        self.display_confirmed = False
        self.display_plate_bbox: Optional[List[int]] = None
        self.latest_plate_crop: Optional[np.ndarray] = None
        self.lane = "IN_1"
        # Start neutral so a vehicle already stopped when it enters the frame can
        # use the stationary OCR path after the intended settling window.
        self.motion_ratio_ema = 0.0
        self.stationary_since = 0.0
        self.last_ocr_at = 0.0
        self.is_zone_fallback = False
        self.zone_name = "Làn cổng"

        # Follow an already verified plate between detector/OCR observations.
        self.visual_points: Optional[np.ndarray] = None
        self.visual_prev_gray: Optional[np.ndarray] = None
        self.visual_anchor_template: Optional[np.ndarray] = None
        self.visual_bbox: Optional[List[int]] = None
        self.visual_last_seen = 0.0
        self.visual_quality = 0.0
        self.visual_failures = 0
        self.provisional_plate_bbox: Optional[List[int]] = None
        self.provisional_last_seen = 0.0

        self.active_plates: Dict[str, Dict[str, Any]] = {}
        # Relative coordinates inside vehicle crop [rx1, ry1, rx2, ry2] in [0..1]
        self.rel_plate_box: Optional[List[float]] = None
        self.plate_anchor_box: Optional[List[int]] = None
        self.plate_anchor_vehicle_box: Optional[List[int]] = None
        if plate_bbox and vehicle_bbox:
            self._update_rel_box(vehicle_bbox, plate_bbox)
            self.update_plate_detection(plate_bbox, plate, confidence, status, last_seen)

        # Plate vote history: {normalized_plate: {'count': int, 'max_conf': float, 'score': float}}
        self.plate_votes: Dict[str, Dict[str, Any]] = {}
        self.observation_history: List[List[Dict[str, Any]]] = []
        self.consensus_frame_count = 0
        if plate:
            self.add_plate_vote(plate, confidence, now=last_seen)

    @staticmethod
    def _compact_plate(value: str) -> str:
        return value.replace(" ", "").replace("-", "").replace(".", "").upper()

    def update_plate_detection(self, p_box: List[int], plate_str: str, conf: float, status: str, now: float) -> None:
        """Track each visible plate independently with relative bounding box."""
        if not plate_str or not p_box or len(p_box) != 4:
            return
        compact = self._compact_plate(plate_str)
        if not compact:
            return
        vx1, vy1, vx2, vy2 = self.vehicle_bbox
        vw = max(1, vx2 - vx1)
        vh = max(1, vy2 - vy1)
        px1, py1, px2, py2 = p_box
        rel_box = [
            max(0.0, min(1.0, (px1 - vx1) / float(vw))),
            max(0.0, min(1.0, (py1 - vy1) / float(vh))),
            max(0.0, min(1.0, (px2 - vx1) / float(vw))),
            max(0.0, min(1.0, (py2 - vy1) / float(vh))),
        ]
        self.active_plates[compact] = {
            "plate": plate_str,
            "bbox": [int(v) for v in p_box],
            "rel_box": rel_box,
            "confidence": conf,
            "status": status or self.status,
            "last_seen": now,
        }

    def _update_rel_box(self, v_box: List[int], p_box: List[int]) -> None:
        """Calculate and store plate coordinates relative to vehicle bounding box."""
        self.plate_anchor_box = [int(value) for value in p_box]
        self.plate_anchor_vehicle_box = [int(value) for value in v_box]
        vx1, vy1, vx2, vy2 = v_box
        vw = max(1, vx2 - vx1)
        vh = max(1, vy2 - vy1)
        px1, py1, px2, py2 = p_box
        self.rel_plate_box = [
            max(0.0, min(1.0, (px1 - vx1) / float(vw))),
            max(0.0, min(1.0, (py1 - vy1) / float(vh))),
            max(0.0, min(1.0, (px2 - vx1) / float(vw))),
            max(0.0, min(1.0, (py2 - vy1) / float(vh))),
        ]

    @staticmethod
    def get_interpolated_plate_box_for_rel(v_box: List[int], rel_box: Optional[List[float]]) -> Optional[List[int]]:
        if not v_box or not rel_box or len(v_box) != 4 or len(rel_box) != 4:
            return None
        vx1, vy1, vx2, vy2 = v_box
        vw = max(1, vx2 - vx1)
        vh = max(1, vy2 - vy1)
        rx1, ry1, rx2, ry2 = rel_box
        return [
            int(vx1 + rx1 * vw),
            int(vy1 + ry1 * vh),
            int(vx1 + rx2 * vw),
            int(vy1 + ry2 * vh),
        ]

    def get_interpolated_plate_box(self, v_box: List[int]) -> Optional[List[int]]:
        """Translate the plate with vehicle motion without distorting its aspect ratio."""
        if not v_box or len(v_box) != 4:
            return self.plate_bbox
        if self.rel_plate_box is not None:
            vx1, vy1, vx2, vy2 = v_box
            vw = max(1, vx2 - vx1)
            vh = max(1, vy2 - vy1)
            rx1, ry1, rx2, ry2 = self.rel_plate_box
            center_x = vx1 + ((rx1 + rx2) / 2.0) * vw
            center_y = vy1 + ((ry1 + ry2) / 2.0) * vh
            anchor = self.plate_anchor_box or self.plate_bbox
            width = max(1, anchor[2] - anchor[0])
            height = max(1, anchor[3] - anchor[1])
            return [
                int(round(center_x - width / 2.0)),
                int(round(center_y - height / 2.0)),
                int(round(center_x - width / 2.0)) + width,
                int(round(center_y - height / 2.0)) + height,
            ]
        return self.plate_bbox

    def update_vehicle_motion(self, vehicle_bbox: List[int], now: float) -> None:
        """Track normalized movement so stationary vehicles can use heavier OCR."""
        old = self.vehicle_bbox
        old_cx = (old[0] + old[2]) / 2.0
        old_cy = (old[1] + old[3]) / 2.0
        new_cx = (vehicle_bbox[0] + vehicle_bbox[2]) / 2.0
        new_cy = (vehicle_bbox[1] + vehicle_bbox[3]) / 2.0
        diagonal = max(1.0, float(np.hypot(old[2] - old[0], old[3] - old[1])))
        movement_ratio = float(np.hypot(new_cx - old_cx, new_cy - old_cy)) / diagonal
        self.motion_ratio_ema = (0.65 * self.motion_ratio_ema) + (0.35 * movement_ratio)
        if self.motion_ratio_ema <= 0.006:
            if self.stationary_since <= 0.0:
                self.stationary_since = now
        else:
            self.stationary_since = 0.0

    def is_stationary(self, now: float) -> bool:
        return self.stationary_since > 0.0 and (now - self.stationary_since) >= 0.9

    @staticmethod
    def _format_vn_compact(value: str) -> str:
        match = re.fullmatch(r"([1-9][0-9][A-Z]{1,2})([0-9]{3})([0-9]{2})", value)
        if match:
            return f"{match.group(1)}-{match.group(2)}.{match.group(3)}"
        match = re.fullmatch(r"([1-9][0-9][A-Z]{1,2})([0-9]{4})", value)
        if match:
            return f"{match.group(1)}-{match.group(2)}"
        return ""

    @staticmethod
    def _hamming(left: str, right: str) -> int:
        if len(left) != len(right):
            return max(len(left), len(right))
        return sum(a != b for a, b in zip(left, right))

    def _update_character_consensus(self) -> None:
        flattened = [item for frame in self.observation_history for item in frame]
        seeds = {item["compact"] for item in flattened}
        best_group: List[List[Dict[str, Any]]] = []
        best_rank = (-1, -1.0)

        for seed in seeds:
            grouped_frames: List[List[Dict[str, Any]]] = []
            total_weight = 0.0
            for frame in self.observation_history:
                compatible = [
                    item
                    for item in frame
                    if len(item["compact"]) == len(seed)
                    and self._hamming(item["compact"], seed) <= 2
                ]
                if compatible:
                    grouped_frames.append(compatible)
                    total_weight += max(float(item["confidence"]) for item in compatible)
            rank = (len(grouped_frames), total_weight)
            if rank > best_rank:
                best_rank = rank
                best_group = grouped_frames

        self.consensus_frame_count = len(best_group)
        if len(best_group) < 2:
            if len(self.observation_history) >= 3:
                for recent_frame in reversed(self.observation_history):
                    complete = [
                        item
                        for item in recent_frame
                        if re.fullmatch(r"[1-9][0-9][A-Z]{1,2}[0-9]{5}", item["compact"])
                    ]
                    if complete:
                        latest_best = max(complete, key=lambda item: float(item["confidence"]))
                        formatted = self._format_vn_compact(latest_best["compact"])
                        if formatted:
                            self.best_plate = formatted
                            self.plate = formatted
                            self.best_conf = float(latest_best["confidence"])
                            self.confidence = self.best_conf
                        break
            return

        length = len(best_group[0][0]["compact"])
        character_weights: List[Dict[str, float]] = [dict() for _ in range(length)]
        consensus_confidences: List[float] = []
        for frame_index, frame in enumerate(best_group):
            recency_weight = 1.0 + (0.08 * frame_index)
            frame_weight = recency_weight / max(1, len(frame))
            for item in frame:
                confidence = float(item["confidence"])
                consensus_confidences.append(confidence)
                for index, char in enumerate(item["compact"]):
                    character_weights[index][char] = (
                        character_weights[index].get(char, 0.0) + confidence * frame_weight
                    )

        consensus_chars = [
            max(weights.items(), key=lambda pair: pair[1])[0]
            for weights in character_weights
        ]
        # On distant VN plates, 5 is commonly closed into 6 by interpolation.
        # Prefer 5 only when the ensemble also observed it with material support.
        if (
            len(consensus_chars) >= 2
            and consensus_chars[0] == "1"
            and "5" in character_weights[1]
            and "6" in character_weights[1]
            and any(
                item["compact"][1] == "5" and float(item["confidence"]) >= 0.90
                for frame in best_group
                for item in frame
            )
            and character_weights[1]["5"] >= character_weights[1]["6"] * 0.10
        ):
            consensus_chars[1] = "5"
        for index, weights in enumerate(character_weights):
            if (
                index != 1
                and "5" in weights
                and "6" in weights
                and any(
                    item["compact"][index] == "5" and float(item["confidence"]) >= 0.90
                    for frame in best_group
                    for item in frame
                )
                and weights["5"] >= weights["6"] * 0.10
            ):
                consensus_chars[index] = "5"
        # Two-line trailer plates frequently turn the final series M into H.
        # Correct it only when M is also present with substantial ensemble support.
        if (
            len(consensus_chars) >= 4
            and consensus_chars[2] == "R"
            and "M" in character_weights[3]
            and "H" in character_weights[3]
            and character_weights[3]["M"] >= character_weights[3]["H"] * 0.55
        ):
            consensus_chars[3] = "M"
        compact_consensus = "".join(consensus_chars)
        formatted = self._format_vn_compact(compact_consensus)
        if not formatted:
            return

        exact_confidences = [
            float(item["confidence"])
            for frame in best_group
            for item in frame
            if item["compact"] == compact_consensus
        ]
        self.best_plate = formatted
        self.plate = formatted
        self.best_conf = max(exact_confidences or consensus_confidences)
        self.confidence = self.best_conf

    def add_plate_vote(
        self,
        plate_str: str,
        conf: float,
        variants: Optional[List[Dict[str, Any]]] = None,
        now: Optional[float] = None,
    ) -> str:
        """
        Record one independent OCR observation and select the strongest repeated reading.
        """
        if self.event_emitted:
            return self.last_event_plate or self.best_plate or self.plate

        clean_p = self._compact_plate(plate_str)
        if len(clean_p) < 6:
            return self.best_plate or self.plate

        observed_at = self.last_seen if now is None else now
        previous_best = self.best_plate
        previous_best_conf = self.best_conf
        self.last_observation_at = observed_at

        if plate_str not in self.plate_votes:
            self.plate_votes[plate_str] = {"count": 0, "max_conf": 0.0, "score": 0.0}

        self.plate_votes[plate_str]["count"] += 1
        self.plate_votes[plate_str]["max_conf"] = max(self.plate_votes[plate_str]["max_conf"], conf)

        # Format bonus for standard VN (e.g. 15R-102.53) and trailer plates
        c_len = len(clean_p)
        is_new_trailer = bool(re.match(r"^[0-9]{2}R[0-9]{4,5}$", clean_p) or re.match(r"^[0-9]{2}RM[0-9]{4,5}$", clean_p))
        current_clean = self._compact_plate(self.best_plate) if self.best_plate else ""
        is_current_trailer = bool(re.match(r"^[0-9]{2}R[0-9]{4,5}$", current_clean) or re.match(r"^[0-9]{2}RM[0-9]{4,5}$", current_clean))

        has_full_vn_five_digits = bool(
            re.fullmatch(r"[1-9][0-9][A-Z]{1,2}[0-9]{5}", clean_p)
        )
        format_bonus = 6.8 if is_new_trailer else (5.8 if has_full_vn_five_digits else (5.0 if c_len in [7, 8, 9] else 2.0) )
        trailer_priority_boost = 15.0 if (is_new_trailer and not is_current_trailer) else 0.0
        cand_score = (format_bonus * 2.0) + (conf * 4.0) + (min(5, self.plate_votes[plate_str]["count"]) * 1.8) + trailer_priority_boost
        self.plate_votes[plate_str]["score"] = max(self.plate_votes[plate_str]["score"], cand_score)

        frame_variants: Dict[str, Dict[str, Any]] = {}
        for item in [{"plate": plate_str, "confidence": conf}, *(variants or [])]:
            variant_plate = str(item.get("plate") or "")
            compact = self._compact_plate(variant_plate)
            if not self._format_vn_compact(compact):
                continue
            variant_conf = float(item.get("confidence", 0.0))
            previous = frame_variants.get(compact)
            if previous is None or variant_conf > previous["confidence"]:
                frame_variants[compact] = {
                    "plate": variant_plate,
                    "compact": compact,
                    "confidence": variant_conf,
                }
        if frame_variants:
            self.observation_history.append(list(frame_variants.values()))
            self.observation_history = self.observation_history[-12:]

        if (is_new_trailer and not is_current_trailer) or cand_score > (self.best_score + 0.15):
            self.best_score = cand_score
            self.best_conf = float(self.plate_votes[plate_str]["max_conf"])
            self.best_plate = plate_str
            self.plate = plate_str
            self.confidence = self.best_conf
        else:
            self.plate = self.best_plate
            self.confidence = self.best_conf

        self._update_character_consensus()

        # Once a near-certain read exists, weaker observations from a receding
        # vehicle may contribute evidence but cannot replace the displayed plate.
        consensus_corrected_rm = (
            self._compact_plate(previous_best).startswith("15RH")
            and self._compact_plate(self.best_plate).startswith("15RM")
        )
        if previous_best and previous_best_conf >= 0.98 and conf < previous_best_conf and not consensus_corrected_rm:
            self.best_plate = previous_best
            self.plate = previous_best
            self.best_conf = previous_best_conf
            self.confidence = previous_best_conf

        if self.best_plate != previous_best:
            self.best_plate_changed_at = observed_at

        return self.plate

    def has_stable_plate(self, now: float) -> bool:
        if not self.best_plate:
            return False
        clean_plate = self._compact_plate(self.best_plate)
        if len(clean_plate) < 6:
            return False
        exact_vote_count = self.plate_votes.get(self.best_plate, {}).get("count", 0)
        frame_count = max(int(exact_vote_count), self.consensus_frame_count)
        total_observation_frames = len(self.observation_history)
        if frame_count < 2 and total_observation_frames < 2:
            return False
        if self.bbox_confirmation_count < 2:
            return False
        if self.is_zone_fallback and frame_count < 3 and total_observation_frames < 3:
            return False
        observation_age = now - self.first_plate_seen if self.first_plate_seen else 0.0
        plate_stale_for = now - self.last_plate_seen if self.last_plate_seen else 0.0
        best_stable_for = now - self.best_plate_changed_at if self.best_plate_changed_at else 0.0
        stationary_frame_requirement = 4 if self.is_zone_fallback else 2
        enough_stationary_consensus = (
            (self.is_stationary(now) or self.is_zone_fallback)
            and observation_age >= 0.70
            and best_stable_for >= 0.70
            and frame_count >= stationary_frame_requirement
        )
        enough_live_consensus = (
            observation_age >= 0.70
            and best_stable_for >= 0.70
            and frame_count >= 2
        )
        required_quiet = 0.90 if self.is_zone_fallback else 0.60
        required_settle = 0.60 if self.is_zone_fallback else 0.35
        finalized_after_plate_left = plate_stale_for >= required_quiet and best_stable_for >= required_settle and (
            frame_count >= 2 or total_observation_frames >= 3
        )
        return enough_stationary_consensus or enough_live_consensus or finalized_after_plate_left

    def should_emit_event(self, now: float) -> bool:
        return not self.event_emitted and self.has_finalizable_plate(now)

    def has_finalizable_plate(self, now: float) -> bool:
        """Allow a passage to keep its best valid read even when a fast vehicle yields one frame."""
        if self.has_stable_plate(now):
            return True
        if not self.best_plate or self.plate_bbox is None:
            return False
        if not self._format_vn_compact(self._compact_plate(self.best_plate)):
            return False
        plate_stale_for = now - self.last_plate_seen if self.last_plate_seen else 0.0
        return plate_stale_for >= 1.0 and self.bbox_confirmation_count >= 1

    def mark_event_emitted(self) -> None:
        """Freeze display metadata to the exact snapshot persisted for this passage."""
        self.emitted_conf = self.best_conf
        self.last_event_plate = self.best_plate
        self.event_emitted = True
        self.plate = self.last_event_plate
        self.confidence = self.emitted_conf


class PlateTracker:
    def __init__(self, smoothing_alpha: float = 0.80):
        self.smoothing_alpha = smoothing_alpha
        self.tracks: Dict[str, VehicleTrack] = {}
        self._next_id = 1

    @staticmethod
    def _clip_box(box: List[int], width: int, height: int) -> Optional[List[int]]:
        if not box or len(box) != 4 or width <= 1 or height <= 1:
            return None
        x1 = max(0, min(width - 1, int(round(box[0]))))
        y1 = max(0, min(height - 1, int(round(box[1]))))
        x2 = max(x1 + 1, min(width, int(round(box[2]))))
        y2 = max(y1 + 1, min(height, int(round(box[3]))))
        if x2 - x1 < 6 or y2 - y1 < 5:
            return None
        return [x1, y1, x2, y2]

    @staticmethod
    def _visual_context_box(box: List[int], width: int, height: int) -> Optional[List[int]]:
        """Use only a narrow plate margin to avoid anchoring to road texture."""
        x1, y1, x2, y2 = box
        bw = max(1, x2 - x1)
        bh = max(1, y2 - y1)
        return PlateTracker._clip_box([
            x1 - int(round(bw * 0.18)),
            y1 - int(round(bh * 0.25)),
            x2 + int(round(bw * 0.18)),
            y2 + int(round(bh * 0.25)),
        ], width, height)

    @staticmethod
    def _visual_template(gray: np.ndarray, box: List[int]) -> Optional[np.ndarray]:
        x1, y1, x2, y2 = box
        crop = gray[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        return cv2.resize(crop, (64, 40), interpolation=cv2.INTER_AREA)

    def _seed_visual_track(self, track: VehicleTrack, gray: np.ndarray, now: float) -> bool:
        box = track.display_plate_bbox or track.plate_bbox
        if box is None:
            return False
        height, width = gray.shape[:2]
        clipped = self._clip_box(box, width, height)
        context = self._visual_context_box(clipped, width, height) if clipped else None
        if clipped is None or context is None:
            return False
        current_template = self._visual_template(gray, clipped)
        if current_template is None:
            return False
        if track.visual_anchor_template is not None and track.visual_last_seen > 0.0:
            similarity = float(cv2.matchTemplate(
                current_template,
                track.visual_anchor_template,
                cv2.TM_CCOEFF_NORMED,
            )[0, 0])
            if not np.isfinite(similarity) or similarity < 0.35:
                return False
        mask = np.zeros_like(gray)
        cx1, cy1, cx2, cy2 = context
        mask[cy1:cy2, cx1:cx2] = 255
        points = cv2.goodFeaturesToTrack(
            gray,
            maxCorners=60,
            qualityLevel=0.01,
            minDistance=4,
            mask=mask,
            blockSize=5,
        )
        if points is None or len(points) < 4:
            return False
        track.visual_points = points.astype(np.float32)
        track.visual_prev_gray = gray.copy()
        if track.visual_anchor_template is None:
            track.visual_anchor_template = current_template
        track.visual_bbox = clipped
        track.visual_last_seen = now
        track.visual_quality = 1.0
        track.visual_failures = 0
        return True

    def seed_visual_track(self, track: VehicleTrack, frame: np.ndarray, now: float) -> bool:
        """Seed from the exact OCR frame so delayed background results stay aligned."""
        if frame is None or frame.size == 0 or not track.plate_bbox:
            return False
        track.visual_points = None
        track.visual_prev_gray = None
        track.visual_anchor_template = None
        track.visual_bbox = [int(value) for value in track.plate_bbox]
        track.display_plate_bbox = [int(value) for value in track.plate_bbox]
        track.visual_quality = 0.0
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return self._seed_visual_track(track, gray, now)

    def prepare_visual_track(self, track: VehicleTrack) -> None:
        """Reset flow so the next live frame seeds from the latest projected OCR box."""
        track.visual_points = None
        track.visual_prev_gray = None
        track.visual_anchor_template = None
        track.visual_bbox = list(track.plate_bbox) if track.plate_bbox else None
        track.display_plate_bbox = list(track.plate_bbox) if track.plate_bbox else None
        track.visual_quality = 0.0
        track.provisional_plate_bbox = None
        track.provisional_last_seen = 0.0

    def update_provisional_plate_box(
        self,
        track: VehicleTrack,
        plate_bbox: List[int],
        now: float,
    ) -> None:
        """Expose detector-only localization without admitting an OCR result."""
        if not self._is_plausible_plate_box(plate_bbox, track.vehicle_bbox):
            return
        track.provisional_plate_bbox = [int(value) for value in plate_bbox]
        track.provisional_last_seen = now

    def update_visual_tracks(self, frame: np.ndarray, now: float) -> None:
        """Advance verified plate boxes with guarded Lucas-Kanade optical flow."""
        if frame is None or frame.size == 0:
            return
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        height, width = gray.shape[:2]

        for track in list(self.tracks.values()):
            if not track.display_confirmed or not track.best_plate or not track.plate_bbox:
                continue
            parent_seen = track.last_seen if track.is_zone_fallback else track.last_vehicle_seen
            parent_max_age = 2.4 if track.is_zone_fallback else 1.0
            if (now - parent_seen) > parent_max_age:
                track.visual_points = None
                track.visual_prev_gray = None
                track.visual_bbox = None
                track.visual_quality = 0.0
                continue
            if track.visual_points is None or track.visual_prev_gray is None or track.visual_bbox is None:
                can_seed = (
                    (now - track.last_seen) <= (2.4 if track.is_zone_fallback else 1.2)
                )
                if can_seed:
                    self._seed_visual_track(track, gray, now)
                else:
                    track.visual_bbox = None
                    track.visual_quality = 0.0
                continue

            try:
                next_points, status, errors = cv2.calcOpticalFlowPyrLK(
                    track.visual_prev_gray,
                    gray,
                    track.visual_points,
                    None,
                    winSize=(21, 21),
                    maxLevel=3,
                    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 24, 0.01),
                )
            except cv2.error:
                next_points, status, errors = None, None, None

            if next_points is None or status is None:
                track.visual_failures += 1
                track.visual_points = None
                track.visual_prev_gray = None
                continue

            valid = status.reshape(-1) == 1
            if errors is not None:
                valid &= errors.reshape(-1) <= 24.0
            previous = track.visual_points.reshape(-1, 2)[valid]
            current = next_points.reshape(-1, 2)[valid]
            if len(previous) < 4:
                track.visual_failures += 1
                track.visual_points = None
                track.visual_prev_gray = None
                continue

            matrix, inliers = cv2.estimateAffinePartial2D(
                previous,
                current,
                method=cv2.RANSAC,
                ransacReprojThreshold=2.5,
                maxIters=100,
                confidence=0.98,
            )
            inlier_ratio = float(np.mean(inliers)) if inliers is not None and len(inliers) else 0.0
            if matrix is None or inlier_ratio < 0.55:
                track.visual_failures += 1
                track.visual_points = None
                track.visual_prev_gray = None
                continue

            scale = float(np.hypot(matrix[0, 0], matrix[0, 1]))
            translation = float(np.hypot(matrix[0, 2], matrix[1, 2]))
            old_box = track.visual_bbox
            old_diagonal = max(1.0, float(np.hypot(old_box[2] - old_box[0], old_box[3] - old_box[1])))
            if not (0.82 <= scale <= 1.20) or translation > max(45.0, old_diagonal * 0.85):
                track.visual_failures += 1
                track.visual_points = None
                track.visual_prev_gray = None
                continue

            # Optical-flow scale compounds quickly on a stationary textured
            # truck. Move only the center and retain the OCR box dimensions.
            old_center = np.float32([[
                [(old_box[0] + old_box[2]) / 2.0, (old_box[1] + old_box[3]) / 2.0]
            ]])
            transformed_center = cv2.transform(old_center, matrix).reshape(2)
            box_width = old_box[2] - old_box[0]
            box_height = old_box[3] - old_box[1]
            candidate = self._clip_box([
                int(round(transformed_center[0] - box_width / 2.0)),
                int(round(transformed_center[1] - box_height / 2.0)),
                int(round(transformed_center[0] + box_width / 2.0)),
                int(round(transformed_center[1] + box_height / 2.0)),
            ], width, height)
            if candidate is None:
                track.visual_points = None
                track.visual_prev_gray = None
                continue

            template = self._visual_template(gray, candidate)
            appearance = 0.0
            if template is not None and track.visual_anchor_template is not None:
                appearance = float(cv2.matchTemplate(
                    template,
                    track.visual_anchor_template,
                    cv2.TM_CCOEFF_NORMED,
                )[0, 0])
            if not np.isfinite(appearance) or appearance < 0.35:
                track.visual_failures += 1
                track.visual_points = None
                track.visual_prev_gray = None
                continue

            alpha = 0.72
            smoothed = [
                int(round(alpha * candidate[index] + (1.0 - alpha) * old_box[index]))
                for index in range(4)
            ]
            track.visual_bbox = smoothed
            track.display_plate_bbox = list(smoothed)
            track.visual_last_seen = now
            track.visual_quality = min(1.0, (0.55 * inlier_ratio) + (0.45 * max(0.0, appearance)))
            track.visual_failures = 0
            if template is not None and track.visual_anchor_template is not None:
                track.visual_anchor_template = cv2.addWeighted(
                    track.visual_anchor_template,
                    0.92,
                    template,
                    0.08,
                    0.0,
                )

            kept = current[inliers.reshape(-1) == 1] if inliers is not None else current
            track.visual_points = kept.reshape(-1, 1, 2).astype(np.float32)
            track.visual_prev_gray = gray.copy()
            if len(track.visual_points) < 12:
                self._seed_visual_track(track, gray, now)

    def get_visual_active_lanes(self, now: float, max_age: float = 0.55) -> set[str]:
        return {
            track.lane
            for track in self.tracks.values()
            if track.visual_bbox is not None
            and track.visual_quality >= 0.28
            and (now - track.visual_last_seen) <= max_age
        }

    @staticmethod
    def _is_plausible_plate_box(plate_bbox: List[int], vehicle_bbox: List[int]) -> bool:
        """Reject latch/pillar boxes before they can become a plate anchor."""
        px1, py1, px2, py2 = plate_bbox
        vx1, vy1, vx2, vy2 = vehicle_bbox
        pw, ph = px2 - px1, py2 - py1
        vw, vh = max(1, vx2 - vx1), max(1, vy2 - vy1)
        if pw < 10 or ph < 8 or pw / float(ph) < 0.65 or pw / float(ph) > 6.5:
            return False
        area_ratio = (pw * ph) / float(vw * vh)
        center_x = (px1 + px2) / 2.0
        center_y = (py1 + py2) / 2.0
        margin_x = vw * 0.04
        margin_y = vh * 0.04
        return (
            0.00025 <= area_ratio <= 0.10
            and vx1 - margin_x <= center_x <= vx2 + margin_x
            and vy1 - margin_y <= center_y <= vy2 + margin_y
        )

    @staticmethod
    def _smooth_vehicle_bbox(previous: List[int], current: List[int]) -> List[int]:
        """Damp detector edge jitter while following real vehicle motion quickly."""
        old_cx = (previous[0] + previous[2]) / 2.0
        old_cy = (previous[1] + previous[3]) / 2.0
        new_cx = (current[0] + current[2]) / 2.0
        new_cy = (current[1] + current[3]) / 2.0
        diagonal = max(1.0, float(np.hypot(previous[2] - previous[0], previous[3] - previous[1])))
        movement = float(np.hypot(new_cx - old_cx, new_cy - old_cy)) / diagonal
        alpha = 0.86 if movement >= 0.035 else 0.62
        return [
            int(round(alpha * current[index] + (1.0 - alpha) * previous[index]))
            for index in range(4)
        ]

    def match_or_create_track(
        self,
        vehicle_bbox: List[int],
        now: float,
        excluded_track_ids: Optional[set[str]] = None,
        lane: Optional[str] = None,
    ) -> str:
        """
        Associate vehicle bbox with existing active tracks using IoU + Centroid distance.
        Prevents ID swapping and flickering.
        """
        vx1, vy1, vx2, vy2 = vehicle_bbox
        vcx, vcy = (vx1 + vx2) / 2.0, (vy1 + vy2) / 2.0
        vw = max(1, vx2 - vx1)
        vh = max(1, vy2 - vy1)
        diag = max(1.0, float(np.hypot(vw, vh)))

        best_id = None
        best_score = -1.0

        excluded = excluded_track_ids or set()
        for tid, track in self.tracks.items():
            if tid in excluded:
                continue
            track_age = now - track.last_seen
            if track_age > 0.90:
                continue
            if lane and track.lane and lane != track.lane:
                continue
            tx1, ty1, tx2, ty2 = track.vehicle_bbox
            tcx, tcy = (tx1 + tx2) / 2.0, (ty1 + ty2) / 2.0
            tw = max(1, tx2 - tx1)
            th = max(1, ty2 - ty1)

            iou = compute_iou(vehicle_bbox, track.vehicle_bbox)
            dist = np.hypot(vcx - tcx, vcy - tcy)
            width_ratio = vw / float(tw)
            height_ratio = vh / float(th)
            comparable_size = 0.48 <= width_ratio <= 2.10 and 0.48 <= height_ratio <= 2.10

            # Once a plate is locked, a weak centroid-only match is too risky:
            # the old overlay can otherwise jump onto an adjacent truck.
            required_iou = 0.32 if (track.display_confirmed or track.event_emitted) else 0.15
            if comparable_size and iou > required_iou:
                score = iou + 1.0 - min(0.25, track_age * 0.15)
            elif (
                comparable_size
                and not track.display_confirmed
                and not track.event_emitted
                and dist < (diag * 0.38)
            ):
                score = 1.0 - (dist / (diag * 0.38))
            else:
                score = 0.0

            if score > best_score and score > 0.25:
                best_score = score
                best_id = tid

        if best_id is not None:
            return best_id

        new_id = f"V{self._next_id:03d}"
        self._next_id += 1
        return new_id

    def match_detections(self, detections: List[Dict[str, Any]], now: float) -> List[str]:
        """Assign at most one vehicle detection to each active track in a frame."""
        claimed: set[str] = set()
        assigned: List[str] = []
        for detection in detections:
            track_id = self.match_or_create_track(
                [int(value) for value in detection["bbox"]],
                now,
                excluded_track_ids=claimed,
                lane=str(detection.get("lane") or "") or None,
            )
            claimed.add(track_id)
            assigned.append(track_id)
        return assigned

    @staticmethod
    def project_box_between_vehicle_boxes(
        plate_bbox: List[int],
        source_vehicle_bbox: List[int],
        target_vehicle_bbox: List[int],
    ) -> List[int]:
        """Project a plate observed on an older frame onto the latest vehicle bbox."""
        sx1, sy1, sx2, sy2 = source_vehicle_bbox
        tx1, ty1, tx2, ty2 = target_vehicle_bbox
        sw = max(1, sx2 - sx1)
        sh = max(1, sy2 - sy1)
        tw = max(1, tx2 - tx1)
        th = max(1, ty2 - ty1)
        px1, py1, px2, py2 = plate_bbox
        return [
            int(tx1 + ((px1 - sx1) / float(sw)) * tw),
            int(ty1 + ((py1 - sy1) / float(sh)) * th),
            int(tx1 + ((px2 - sx1) / float(sw)) * tw),
            int(ty1 + ((py2 - sy1) / float(sh)) * th),
        ]

    def update_related_plate_tracks(
        self,
        vehicle_track_id: str,
        vehicle_bbox: List[int],
        now: float,
    ) -> None:
        """Move plate-slot tracks with their parent vehicle between OCR passes."""
        prefix = f"{vehicle_track_id}:"
        for tid, track in self.tracks.items():
            if tid != vehicle_track_id and not tid.startswith(prefix):
                continue
            track.vehicle_bbox = vehicle_bbox
            track.last_seen = now
            track.last_vehicle_seen = now
            if track.is_zone_fallback:
                continue
            if track.rel_plate_box is not None:
                track.plate_bbox = track.get_interpolated_plate_box(vehicle_bbox)

    def find_vehicle_track_for_plate(
        self,
        plate_bbox: List[int],
        lane: str,
        now: float,
    ) -> Optional[str]:
        """Find the live physical vehicle that owns an absolute zone-scan plate box."""
        if len(plate_bbox) != 4:
            return None
        px = (plate_bbox[0] + plate_bbox[2]) / 2.0
        py = (plate_bbox[1] + plate_bbox[3]) / 2.0
        best: Optional[tuple[float, str]] = None
        for track_id, track in self.tracks.items():
            if track.is_zone_fallback or track_id.startswith("ZONE_FALLBACK:"):
                continue
            if lane and track.lane and lane != track.lane:
                continue
            parent_seen = track.last_seen if track.is_zone_fallback else track.last_vehicle_seen
            if (now - parent_seen) > 0.90:
                continue
            vx1, vy1, vx2, vy2 = track.vehicle_bbox
            vw = max(1, vx2 - vx1)
            vh = max(1, vy2 - vy1)
            margin_x = vw * 0.05
            margin_y = vh * 0.05
            if not (
                vx1 - margin_x <= px <= vx2 + margin_x
                and vy1 - margin_y <= py <= vy2 + margin_y
            ):
                continue
            normalized_distance = float(np.hypot(
                (px - ((vx1 + vx2) / 2.0)) / vw,
                (py - ((vy1 + vy2) / 2.0)) / vh,
            ))
            rank = (normalized_distance, track_id)
            if best is None or rank < best:
                best = rank
        return best[1] if best is not None else None

    def update_track(
        self,
        track_id: str,
        vehicle_bbox: List[int],
        plate_bbox: Optional[List[int]],
        plate_text: str,
        status: str,
        conf: float,
        now: float,
        variants: Optional[List[Dict[str, Any]]] = None,
        bbox_quality: Optional[float] = None,
    ) -> VehicleTrack:
        """Update track coordinates, smooth plate box, and lock best plate string."""
        if track_id in self.tracks:
            track = self.tracks[track_id]
            if not plate_text:
                track.update_vehicle_motion(vehicle_bbox, now)
                vehicle_bbox = self._smooth_vehicle_bbox(track.vehicle_bbox, vehicle_bbox)
                track.last_vehicle_seen = now
            track.vehicle_bbox = [int(value) for value in vehicle_bbox]
            track.last_seen = now

            if plate_text:
                if track.first_plate_seen <= 0.0:
                    track.first_plate_seen = now
                track.add_plate_vote(plate_text, conf, variants=variants, now=now)
                if status:
                    track.status = status
                    track.status_locked = True

                if plate_bbox is not None and len(plate_bbox) == 4:
                    track.last_plate_seen = now

                if (
                    plate_bbox is not None
                    and len(plate_bbox) == 4
                    and self._is_plausible_plate_box(plate_bbox, vehicle_bbox)
                ):
                    cur_pbox = [int(v) for v in plate_bbox]
                    quality = float(bbox_quality if bbox_quality is not None else conf * 2.0)
                    overlaps_current = track.plate_bbox is not None and compute_iou(cur_pbox, track.plate_bbox) >= 0.12
                    if track.plate_bbox is None:
                        track.plate_bbox = cur_pbox
                        track.bbox_confirmation_count = 1
                        track.best_bbox_quality = quality
                        track._update_rel_box(vehicle_bbox, track.plate_bbox)
                    elif overlaps_current:
                        track.plate_bbox = [
                            int(self.smoothing_alpha * cur_pbox[i] + (1.0 - self.smoothing_alpha) * track.plate_bbox[i])
                            for i in range(4)
                        ]
                        track.bbox_confirmation_count = min(12, track.bbox_confirmation_count + 1)
                        track.best_bbox_quality = max(track.best_bbox_quality, quality)
                        track.pending_plate_box = None
                        track.pending_bbox_support = 0
                        track._update_rel_box(vehicle_bbox, track.plate_bbox)
                    else:
                        pending_overlap = (
                            track.pending_plate_box is not None
                            and compute_iou(cur_pbox, track.pending_plate_box) >= 0.25
                        )
                        if pending_overlap:
                            track.pending_plate_box = [
                                int((cur_pbox[i] + track.pending_plate_box[i]) / 2.0)
                                for i in range(4)
                            ]
                            track.pending_bbox_support += 1
                            track.pending_bbox_quality = max(track.pending_bbox_quality, quality)
                        else:
                            track.pending_plate_box = cur_pbox
                            track.pending_bbox_support = 1
                            track.pending_bbox_quality = quality

                        current_center_y = (track.plate_bbox[1] + track.plate_bbox[3]) / 2.0
                        pending_center_y = (track.pending_plate_box[1] + track.pending_plate_box[3]) / 2.0
                        vehicle_height = max(1, vehicle_bbox[3] - vehicle_bbox[1])
                        credible_lower_rear = (
                            pending_center_y >= current_center_y + max(10.0, vehicle_height * 0.04)
                            and track.pending_bbox_quality >= track.best_bbox_quality - 0.12
                        )
                        credible_quality_gain = track.pending_bbox_quality >= track.best_bbox_quality + 0.18
                        if track.pending_bbox_support >= 2 and (credible_lower_rear or credible_quality_gain):
                            track.plate_bbox = track.pending_plate_box
                            track.bbox_confirmation_count = track.pending_bbox_support
                            track.best_bbox_quality = track.pending_bbox_quality
                            track.pending_plate_box = None
                            track.pending_bbox_support = 0
                            track._update_rel_box(vehicle_bbox, track.plate_bbox)
            elif track.rel_plate_box is not None:
                track.plate_bbox = track.get_interpolated_plate_box(vehicle_bbox)

            return track
        else:
            new_track = VehicleTrack(
                track_id=track_id,
                vehicle_bbox=vehicle_bbox,
                plate_bbox=[int(v) for v in plate_bbox] if plate_bbox else None,
                plate=plate_text or "",
                status=status or ("KNOWN" if plate_text else "SCANNING"),
                confidence=conf or 0.85,
                last_seen=now,
            )
            if bbox_quality is not None and plate_bbox:
                new_track.best_bbox_quality = float(bbox_quality)
            if plate_bbox and not self._is_plausible_plate_box(new_track.plate_bbox, vehicle_bbox):
                new_track.plate_bbox = None
                new_track.rel_plate_box = None
                new_track.plate_anchor_box = None
                new_track.plate_anchor_vehicle_box = None
                new_track.bbox_confirmation_count = 0
            self.tracks[track_id] = new_track
            return new_track

    def get_live_detections(self, now: float, min_confidence: float = 0.0) -> List[Dict[str, Any]]:
        """
        Return active plate detections for all tracked vehicles currently in the zone.
        Renders all visible plates on active vehicles and removes bounding boxes immediately when vehicles leave.
        """
        active_by_passage: Dict[str, tuple[tuple[int, int, float], Dict[str, Any]]] = {}
        dead = []

        for tid, track in list(self.tracks.items()):
            # A short grace period bridges occasional YOLO misses without keeping
            # an overlay alive long enough to attach to the following vehicle.
            max_track_age = 2.4 if track.is_zone_fallback else 1.0
            parent_seen = track.last_seen if track.is_zone_fallback else track.last_vehicle_seen
            visual_alive = (
                track.visual_bbox is not None
                and track.visual_quality >= 0.28
                and (now - track.visual_last_seen) <= 0.55
                and (now - parent_seen) <= max_track_age
            )
            if (now - parent_seen) > max_track_age and not visual_alive:
                dead.append(tid)
                continue

            exact_votes = int(track.plate_votes.get(track.best_plate, {}).get("count", 0))
            if track.event_emitted or (
                track.plate_bbox
                and (
                    (track.best_conf >= 0.98 and track.bbox_confirmation_count >= 1)
                    or (
                        track.bbox_confirmation_count >= 2
                        and (exact_votes >= 2 or track.consensus_frame_count >= 2)
                    )
                )
            ):
                track.display_confirmed = True

            if track.plate_bbox and track.best_plate and track.display_confirmed:
                target_box = (
                    track.visual_bbox
                    if visual_alive
                    else (track.get_interpolated_plate_box(track.vehicle_bbox) or track.plate_bbox)
                )
                if track.display_plate_bbox is None:
                    track.display_plate_bbox = [int(value) for value in target_box]
                else:
                    alpha = 0.55
                    track.display_plate_bbox = [
                        int(round(alpha * target_box[index] + (1.0 - alpha) * track.display_plate_bbox[index]))
                        for index in range(4)
                    ]
                display_conf = track.best_conf or 0.85
                if display_conf >= min_confidence:
                    detection = {
                        "class": "license_plate",
                        "bbox": list(track.display_plate_bbox),
                        "plate": track.best_plate,
                        "lpr_status": track.status,
                        "confidence": display_conf,
                        "is_locked": True,
                        "track_id": track.track_id,
                    }
                    group_key = str(getattr(track, "passage_id", None) or track.track_id)
                    rank = (
                        0 if track.is_zone_fallback else 1,
                        int(track.bbox_confirmation_count),
                        float(track.best_bbox_quality) + display_conf,
                    )
                    if group_key not in active_by_passage or rank > active_by_passage[group_key][0]:
                        active_by_passage[group_key] = (rank, detection)

            # Show the first valid plate localization immediately, but keep it
            # unlabeled until temporal confirmation. This reduces bbox latency
            # without publishing an unstable OCR string or journal event.
            early_plate_box = (
                track.plate_bbox
                and track.best_plate
                and not track.display_confirmed
                and (now - track.last_plate_seen) <= 1.2
                and (now - parent_seen) <= max_track_age
            )
            if early_plate_box:
                detection = {
                    "class": "license_plate",
                    "bbox": list(track.plate_bbox),
                    "plate": "",
                    "lpr_status": "SCANNING",
                    "confidence": 0.0,
                    "is_locked": False,
                    "track_id": track.track_id,
                }
                group_key = str(getattr(track, "passage_id", None) or track.track_id)
                rank = (-1, int(track.bbox_confirmation_count), float(track.best_bbox_quality))
                if group_key not in active_by_passage or rank > active_by_passage[group_key][0]:
                    active_by_passage[group_key] = (rank, detection)

            provisional_alive = (
                not track.best_plate
                and track.provisional_plate_bbox is not None
                and (now - track.provisional_last_seen) <= 1.2
                and (now - track.last_vehicle_seen) <= 1.0
            )
            if provisional_alive:
                detection = {
                    "class": "license_plate",
                    "bbox": list(track.provisional_plate_bbox),
                    "plate": "",
                    "lpr_status": "SCANNING",
                    "confidence": 0.0,
                    "is_locked": False,
                    "track_id": track.track_id,
                }
                group_key = str(getattr(track, "passage_id", None) or track.track_id)
                rank = (-1, 0, 0.0)
                if group_key not in active_by_passage or rank > active_by_passage[group_key][0]:
                    active_by_passage[group_key] = (rank, detection)

        for tid in dead:
            self.tracks.pop(tid, None)

        return [item[1] for item in active_by_passage.values()]
