"""
stream.reader — OpenCV Video Stream Reader with Fallback & Auto-Reconnect

Supports:
- RTSP video streams
- Local MP4 / AVI video files (with seamless loop on EOF)
- Fallback image assets (frontend/public/assets/cam-gate.png, cam-baikiem.png)
- Dynamic synthetic frame generator (for headless / offline dev testing)
"""
import logging
import os
import time
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger("sentriai.stream.reader")


class StreamReader:
    def __init__(
        self,
        source: Optional[str] = None,
        camera_id: str = "GATE-01",
        target_fps: float = 10.0,
        resolution: Tuple[int, int] = (640, 480),
    ):
        self.camera_id = camera_id
        self.target_fps = max(1.0, float(target_fps))
        self.resolution = resolution  # (width, height)
        self.source = source
        self.cap: Optional[cv2.VideoCapture] = None
        self.is_image_fallback = False
        self.fallback_frame: Optional[np.ndarray] = None
        self.frame_count = 0
        self.last_frame_time = 0.0
        self.is_connected = False
        self.synthetic_frame_index = 0

        self._resolve_source()
        self._open_stream()

    def _resolve_source(self) -> None:
        """Resolve valid video source or fallback to available sample assets."""
        if self.source and (
            self.source.startswith("rtsp://")
            or self.source.startswith("http://")
            or self.source.startswith("https://")
        ):
            logger.info("[%s] Using network stream source: %s", self.camera_id, self.source)
            return

        # Check if local video file exists
        if self.source and os.path.exists(self.source):
            logger.info("[%s] Using local video file: %s", self.camera_id, self.source)
            return

        # Check fallback sample assets from frontend or data
        possible_asset_paths = [
            f"frontend/public/assets/cam-{self.camera_id.lower().replace('-01', '').replace('_', '')}.png",
            f"frontend/public/assets/cam-{ 'gate' if 'GATE' in self.camera_id else 'baikiem' }.png",
            "frontend/public/assets/cam-gate.png",
            "frontend/public/assets/cam-baikiem.png",
        ]

        for asset_path in possible_asset_paths:
            if os.path.exists(asset_path):
                img = cv2.imread(asset_path)
                if img is not None:
                    self.is_image_fallback = True
                    self.fallback_frame = cv2.resize(img, self.resolution)
                    logger.info(
                        "[%s] Using fallback image asset for stream: %s (%dx%d)",
                        self.camera_id,
                        asset_path,
                        self.resolution[0],
                        self.resolution[1],
                    )
                    return

        logger.warning(
            "[%s] No physical stream or asset found for '%s'. Using synthetic test video generator.",
            self.camera_id,
            self.source,
        )

    def _open_stream(self) -> None:
        """Open VideoCapture or mark ready for fallback."""
        if self.is_image_fallback:
            self.is_connected = True
            return

        if self.source:
            self.cap = cv2.VideoCapture(self.source)
            if self.cap.isOpened():
                self.is_connected = True
                logger.info("[%s] VideoCapture opened successfully.", self.camera_id)
            else:
                logger.warning("[%s] Failed to open VideoCapture for: %s", self.camera_id, self.source)
                self.is_connected = False
        else:
            self.is_connected = True

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Read the next frame, resized to target resolution (640x480).
        Handles video file loop, synthetic frame generation, and rate throttling.
        """
        now = time.time()
        min_interval = 1.0 / self.target_fps
        elapsed = now - self.last_frame_time
        if elapsed < min_interval:
            time.sleep(max(0.001, min_interval - elapsed))

        self.last_frame_time = time.time()
        self.frame_count += 1

        # 1. Image fallback (creates animated simulation overlay)
        if self.is_image_fallback and self.fallback_frame is not None:
            frame = self.fallback_frame.copy()
            # Add dynamic timestamp and frame counter in top corner
            ts_str = time.strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(
                frame,
                f"CAM: {self.camera_id} | {ts_str} | #{self.frame_count}",
                (15, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 255),
                1,
                cv2.LINE_AA,
            )
            return True, frame

        # 2. OpenCV VideoCapture stream (file or RTSP)
        if self.cap is not None and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret and frame is not None:
                resized = cv2.resize(frame, self.resolution)
                return True, resized
            else:
                # End of video file -> rewind to beginning
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    resized = cv2.resize(frame, self.resolution)
                    return True, resized
                else:
                    logger.warning("[%s] Stream read returned empty frame. Attempting reconnect...", self.camera_id)
                    self._open_stream()

        # 3. Synthetic test generator
        return True, self._generate_synthetic_frame()

    def _generate_synthetic_frame(self) -> np.ndarray:
        """Generate a realistic test frame with moving mock vehicles."""
        self.synthetic_frame_index += 1
        w, h = self.resolution
        frame = np.full((h, w, 3), 35, dtype=np.uint8)

        # Draw road / parking ground
        cv2.rectangle(frame, (0, int(h * 0.4)), (w, h), (60, 60, 60), -1)
        # Lane divider lines
        cv2.line(frame, (0, int(h * 0.7)), (w, int(h * 0.7)), (200, 200, 200), 2)

        # Draw a moving simulated box (vehicle / person)
        x_pos = int((self.synthetic_frame_index * 8) % (w + 100)) - 80
        y_pos = int(h * 0.55)
        cv2.rectangle(frame, (x_pos, y_pos), (x_pos + 90, y_pos + 50), (40, 160, 220), -1)
        cv2.putText(frame, "TEST-VEHICLE", (x_pos + 5, y_pos + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

        # Header info
        ts_str = time.strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(
            frame,
            f"SYNTHETIC STREAM: {self.camera_id} | {ts_str} | #{self.frame_count}",
            (15, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            1,
            cv2.LINE_AA,
        )
        return frame

    def release(self) -> None:
        """Release underlying OpenCV resources."""
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.is_connected = False
        logger.info("[%s] StreamReader released.", self.camera_id)
