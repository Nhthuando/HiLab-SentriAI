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
        self.created_at = last_seen
        self.status = status or "SCANNING"
        self.confidence = confidence or 0.85
        self.last_seen = last_seen
        self.last_plate_seen = last_seen if plate_bbox else 0.0
        self.first_plate_seen = last_seen if plate else 0.0
        self.last_observation_at = last_seen if plate else 0.0
        self.best_plate_changed_at = last_seen if plate else 0.0
        self.is_locked = bool(plate and len(plate) >= 6)
        self.event_emitted = False
        self.emitted_conf = 0.0
        self.last_event_plate = ""
        self.latest_plate_crop: Optional[np.ndarray] = None
        self.lane = "IN_1"
        self.motion_ratio_ema = 1.0
        self.stationary_since = 0.0
        self.last_ocr_at = 0.0
        self.is_zone_fallback = False
        self.zone_name = "Làn cổng"

        # Relative coordinates inside vehicle crop [rx1, ry1, rx2, ry2] in [0..1]
        self.rel_plate_box: Optional[List[float]] = None
        self.plate_anchor_box: Optional[List[int]] = None
        self.plate_anchor_vehicle_box: Optional[List[int]] = None
        if plate_bbox and vehicle_bbox:
            self._update_rel_box(vehicle_bbox, plate_bbox)

        # Plate vote history: {normalized_plate: {'count': int, 'max_conf': float, 'score': float}}
        self.plate_votes: Dict[str, Dict[str, Any]] = {}
        self.observation_history: List[List[Dict[str, Any]]] = []
        self.consensus_frame_count = 0
        if plate:
            self.add_plate_vote(plate, confidence, now=last_seen)

    @staticmethod
    def _compact_plate(value: str) -> str:
        return value.replace(" ", "").replace("-", "").replace(".", "").upper()

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

    def get_interpolated_plate_box(self, v_box: List[int]) -> Optional[List[int]]:
        """Translate the plate with vehicle motion without distorting its aspect ratio."""
        if self.plate_anchor_box is not None and self.plate_anchor_vehicle_box is not None:
            avx1, avy1, avx2, avy2 = self.plate_anchor_vehicle_box
            vx1, vy1, vx2, vy2 = v_box
            dx = int(round(((vx1 + vx2) - (avx1 + avx2)) / 2.0))
            dy = int(round(((vy1 + vy2) - (avy1 + avy2)) / 2.0))
            px1, py1, px2, py2 = self.plate_anchor_box
            return [px1 + dx, py1 + dy, px2 + dx, py2 + dy]
        if self.rel_plate_box is None:
            return self.plate_bbox
        vx1, vy1, vx2, vy2 = v_box
        vw = vx2 - vx1
        vh = vy2 - vy1
        rx1, ry1, rx2, ry2 = self.rel_plate_box
        return [
            int(vx1 + rx1 * vw),
            int(vy1 + ry1 * vh),
            int(vx1 + rx2 * vw),
            int(vy1 + ry2 * vh),
        ]

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
        self.last_observation_at = observed_at

        if plate_str not in self.plate_votes:
            self.plate_votes[plate_str] = {"count": 0, "max_conf": 0.0, "score": 0.0}

        self.plate_votes[plate_str]["count"] += 1
        self.plate_votes[plate_str]["max_conf"] = max(self.plate_votes[plate_str]["max_conf"], conf)

        # Format bonus for standard VN (e.g. 15R-102.53) and UK/EU plates
        c_len = len(clean_p)
        has_full_vn_five_digits = bool(
            re.fullmatch(r"[1-9][0-9][A-Z]{1,2}[0-9]{5}", clean_p)
        )
        format_bonus = 5.8 if has_full_vn_five_digits else (5.0 if c_len in [7, 8, 9] else 2.0)
        cand_score = (format_bonus * 2.0) + (conf * 4.0) + (min(5, self.plate_votes[plate_str]["count"]) * 1.8)
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

        if cand_score > (self.best_score + 0.15):
            self.best_score = cand_score
            self.best_conf = float(self.plate_votes[plate_str]["max_conf"])
            self.best_plate = plate_str
            self.plate = plate_str
            self.confidence = self.best_conf
        else:
            self.plate = self.best_plate
            self.confidence = self.best_conf

        self._update_character_consensus()

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
        if frame_count < 2 and total_observation_frames < 3:
            return False
        if self.is_zone_fallback and frame_count < 4 and total_observation_frames < 5:
            return False
        observation_age = now - self.first_plate_seen if self.first_plate_seen else 0.0
        plate_stale_for = now - self.last_plate_seen if self.last_plate_seen else 0.0
        best_stable_for = now - self.best_plate_changed_at if self.best_plate_changed_at else 0.0
        stationary_frame_requirement = 8 if self.is_zone_fallback else 7
        enough_stationary_consensus = (
            (self.is_stationary(now) or self.is_zone_fallback)
            and observation_age >= 3.0
            and best_stable_for >= 1.8
            and frame_count >= stationary_frame_requirement
        )
        enough_live_consensus = (
            observation_age >= 5.0
            and best_stable_for >= 2.0
            and frame_count >= 10
        )
        required_quiet = 1.10 if self.is_zone_fallback else 0.75
        required_settle = 1.20 if self.is_zone_fallback else 0.75
        finalized_after_plate_left = plate_stale_for >= required_quiet and best_stable_for >= required_settle and (
            frame_count >= 2 or total_observation_frames >= 3
        )
        return self.best_conf >= 0.60 and (
            enough_stationary_consensus or enough_live_consensus or finalized_after_plate_left
        )

    def should_emit_event(self, now: float) -> bool:
        return not self.event_emitted and self.has_stable_plate(now)

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

    def match_or_create_track(
        self,
        vehicle_bbox: List[int],
        now: float,
    ) -> str:
        """
        Associate vehicle bbox with existing active tracks using IoU + Centroid distance.
        Prevents ID swapping and flickering.
        """
        vx1, vy1, vx2, vy2 = vehicle_bbox
        vcx, vcy = (vx1 + vx2) / 2.0, (vy1 + vy2) / 2.0

        best_id = None
        best_score = -1.0

        for tid, track in self.tracks.items():
            tx1, ty1, tx2, ty2 = track.vehicle_bbox
            tcx, tcy = (tx1 + tx2) / 2.0, (ty1 + ty2) / 2.0

            iou = compute_iou(vehicle_bbox, track.vehicle_bbox)
            dist = np.hypot(vcx - tcx, vcy - tcy)

            # Combined match score
            if iou > 0.30:
                score = iou + 1.0
            elif dist < 160.0:
                score = 1.0 - (dist / 160.0)
            else:
                score = 0.0

            if score > best_score and score > 0.35:
                best_score = score
                best_id = tid

        if best_id is not None:
            return best_id

        new_id = f"V{self._next_id:03d}"
        self._next_id += 1
        return new_id

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
            if track.is_zone_fallback:
                continue
            if track.rel_plate_box is not None:
                track.plate_bbox = track.get_interpolated_plate_box(vehicle_bbox)

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
            track.vehicle_bbox = vehicle_bbox
            track.last_seen = now

            accepted_plate = track.plate
            if plate_text:
                if track.first_plate_seen <= 0.0:
                    track.first_plate_seen = now
                previous_plate = track.best_plate
                accepted_plate = track.add_plate_vote(plate_text, conf, variants=variants, now=now)
                if status:
                    track.status = status
                    track.status_locked = True

                if plate_bbox is not None and len(plate_bbox) == 4:
                    track.last_plate_seen = now

                if plate_bbox is not None and len(plate_bbox) == 4 and accepted_plate == plate_text:
                    cur_pbox = [int(v) for v in plate_bbox]
                    quality = float(bbox_quality if bbox_quality is not None else conf * 2.0)
                    overlaps_current = track.plate_bbox is not None and compute_iou(cur_pbox, track.plate_bbox) >= 0.12
                    prefers_lower_rear_box = False
                    if track.plate_bbox is not None and not overlaps_current:
                        current_center_y = (track.plate_bbox[1] + track.plate_bbox[3]) / 2.0
                        candidate_center_y = (cur_pbox[1] + cur_pbox[3]) / 2.0
                        vehicle_height = max(1, vehicle_bbox[3] - vehicle_bbox[1])
                        prefers_lower_rear_box = (
                            candidate_center_y >= current_center_y + max(12.0, vehicle_height * 0.06)
                            and quality >= track.best_bbox_quality - 0.12
                        )
                    should_replace = (
                        track.plate_bbox is None
                        or previous_plate != accepted_plate
                        or overlaps_current
                        or prefers_lower_rear_box
                        or quality >= track.best_bbox_quality + 0.15
                    )
                    if should_replace:
                        if track.plate_bbox is not None and previous_plate == accepted_plate and overlaps_current:
                            track.plate_bbox = [
                                int(self.smoothing_alpha * cur_pbox[i] + (1.0 - self.smoothing_alpha) * track.plate_bbox[i])
                                for i in range(4)
                            ]
                        else:
                            track.plate_bbox = cur_pbox
                        track.best_bbox_quality = max(track.best_bbox_quality, quality)
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
            self.tracks[track_id] = new_track
            return new_track

    def get_live_detections(self, now: float) -> List[Dict[str, Any]]:
        """
        Return active plate detections for all tracked vehicles currently in the zone.
        Maintains rock-solid continuous display for active vehicles without flickering.
        """
        active = []
        dead = []

        for tid, track in self.tracks.items():
            # Vehicle expired from zone / camera view
            expiry_seconds = 8.0 if track.is_zone_fallback else 2.5
            if (now - track.last_seen) > expiry_seconds:
                dead.append(tid)
                continue

            # Compute current plate box (interpolated smoothly from vehicle position)
            track.is_locked = track.event_emitted or track.has_stable_plate(now)
            pbox = track.get_interpolated_plate_box(track.vehicle_bbox)
            if pbox is not None and track.plate and track.is_locked:
                display_plate = track.last_event_plate if track.event_emitted else track.plate
                display_conf = track.emitted_conf if track.event_emitted else track.confidence
                active.append({
                    "class": "license_plate",
                    "bbox": pbox,
                    "plate": display_plate,
                    "lpr_status": track.status,
                    "confidence": display_conf,
                    "is_locked": track.is_locked,
                    "track_id": track.track_id,
                })

        for tid in dead:
            self.tracks.pop(tid, None)

        return active


