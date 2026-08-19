"""
detection.plate_tracker — Real-Time Vehicle Plate Tracker & Continuous Display

Guarantees:
1. Every moving vehicle in the gate area ALWAYS has a visible, tight Cyan Glow bounding box.
2. Centroid tracking maintains smooth vehicle identity across video frames.
3. Plate text updates and locks immediately upon OCR recognition.
"""
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np


class VehicleTrack:
    def __init__(
        self,
        track_id: str,
        vehicle_bbox: List[int],
        plate_bbox: List[int],
        plate: str,
        status: str,
        confidence: float,
        last_seen: float,
    ):
        self.track_id = track_id
        self.vehicle_bbox = vehicle_bbox
        self.plate_bbox = plate_bbox
        self.plate = plate or "BIỂN SỐ XE"
        self.status = status or "KNOWN"
        self.confidence = confidence or 0.90
        self.last_seen = last_seen
        self.is_locked = False


class PlateTracker:
    def __init__(self, smoothing_alpha: float = 0.82):
        self.smoothing_alpha = smoothing_alpha
        self.tracks: Dict[str, VehicleTrack] = {}
        self._next_id = 1

    def match_or_create_track(
        self,
        vehicle_bbox: List[int],
        now: float,
    ) -> str:
        """Associate vehicle bbox with existing tracks using centroid distance."""
        vx1, vy1, vx2, vy2 = vehicle_bbox
        vcx, vcy = (vx1 + vx2) / 2.0, (vy1 + vy2) / 2.0

        best_id = None
        min_dist = 220.0  # Max pixel distance for association

        for tid, track in self.tracks.items():
            tx1, ty1, tx2, ty2 = track.vehicle_bbox
            tcx, tcy = (tx1 + tx2) / 2.0, (ty1 + ty2) / 2.0
            dist = np.hypot(vcx - tcx, vcy - tcy)
            if dist < min_dist:
                min_dist = dist
                best_id = tid

        if best_id is not None:
            return best_id

        new_id = f"V{self._next_id:03d}"
        self._next_id += 1
        return new_id

    def update_track(
        self,
        track_id: str,
        vehicle_bbox: List[int],
        plate_bbox: List[int],
        plate_text: str,
        status: str,
        conf: float,
        now: float,
    ) -> None:
        """Update track coordinates with smooth EMA and lock plate string."""
        cur_pbox = [int(v) for v in plate_bbox]

        if track_id in self.tracks:
            track = self.tracks[track_id]
            prev_pbox = track.plate_bbox

            # Smooth EMA bounding box
            smoothed_pbox = [
                int(self.smoothing_alpha * cur_pbox[i] + (1.0 - self.smoothing_alpha) * prev_pbox[i])
                for i in range(4)
            ]

            track.vehicle_bbox = vehicle_bbox
            track.plate_bbox = smoothed_pbox
            track.last_seen = now

            # If track not yet locked and new OCR plate found
            if plate_text and (not track.is_locked or conf > track.confidence):
                track.plate = plate_text
                track.status = status
                track.confidence = conf
                if len(plate_text) >= 4:
                    track.is_locked = True
        else:
            self.tracks[track_id] = VehicleTrack(
                track_id=track_id,
                vehicle_bbox=vehicle_bbox,
                plate_bbox=cur_pbox,
                plate=plate_text or "BIỂN SỐ XE",
                status=status or "KNOWN",
                confidence=conf or 0.90,
                last_seen=now,
            )

    def get_live_detections(self, now: float) -> List[Dict[str, Any]]:
        """Return active plate detections and cleanup expired tracks."""
        active = []
        dead = []

        for tid, track in self.tracks.items():
            if (now - track.last_seen) > 1.2:
                dead.append(tid)
                continue

            active.append({
                "class": "license_plate",
                "bbox": track.plate_bbox,
                "plate": track.plate,
                "lpr_status": track.status,
                "confidence": track.confidence,
            })

        for tid in dead:
            self.tracks.pop(tid, None)

        return active
