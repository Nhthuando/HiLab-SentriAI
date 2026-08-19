"""
stream.reader — OpenCV Video Stream Reader with Fallback & Auto-Reconnect

Supports:
- RTSP video streams
- Local MP4 / AVI video files (with seamless loop on EOF and 1.0x real-time pacing)
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
        self.is_local_file = False
        self.source_fps = 0.0
        self.is_synthetic = False
        self.fallback_frame: Optional[np.ndarray] = None
        self.frame_count = 0
        self.last_frame_time = 0.0
        self.is_connected = False
        self.synthetic_frame_index = 0
        self._frame_step_accumulator = 0.0

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

        # Check if local video file exists or discover in data folders
        if self.source:
            candidate_paths = [
                self.source,
                os.path.abspath(self.source),
                os.path.join(os.getcwd(), self.source),
                os.path.join(os.path.dirname(__file__), "../../data/samples", os.path.basename(self.source)),
                os.path.join(os.path.dirname(__file__), "../../../data/samples", os.path.basename(self.source)),
                os.path.join(os.path.dirname(__file__), "../../data", os.path.basename(self.source)),
            ]
            for p in candidate_paths:
                if os.path.exists(p) and os.path.isfile(p):
                    self.source = p
                    self.is_local_file = True
                    logger.info("[%s] Found and using local video file: %s", self.camera_id, self.source)
                    return

        # Auto-discover video file matching camera_id in data/samples
        search_dirs = [
            os.path.join(os.path.dirname(__file__), "../../data/samples"),
            os.path.join(os.path.dirname(__file__), "../../../data/samples"),
        ]
        cam_prefix = "gate" if "GATE" in self.camera_id.upper() else "area"
        for s_dir in search_dirs:
            if os.path.exists(s_dir) and os.path.isdir(s_dir):
                for f in os.listdir(s_dir):
                    if cam_prefix in f.lower() and f.lower().endswith(('.mp4', '.avi', '.mkv', '.mov')):
                        self.source = os.path.join(s_dir, f)
                        self.is_local_file = True
                        logger.info("[%s] Auto-discovered video file: %s", self.camera_id, self.source)
                        return

        # Check the camera's bundled sample asset relative to the repository root.
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[3]
        asset_name = "cam-gate.png" if "GATE" in self.camera_id else "cam-baikiem.png"
        possible_asset_paths = [
            str(repo_root / "frontend" / "public" / "assets" / asset_name),
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

        self.is_synthetic = True
        logger.warning(
            "[%s] No physical stream or asset found for '%s'. Using synthetic test video generator.",
            self.camera_id,
            self.source,
        )

    def _open_stream(self) -> None:
        """Open VideoCapture or mark ready for fallback."""
        self._frame_step_accumulator = 0.0
        if self.is_image_fallback or self.is_synthetic:
            self.is_connected = True
            return

        if self.source:
            self.cap = cv2.VideoCapture(self.source)
            if self.cap.isOpened():
                self.is_connected = True
                self.source_fps = max(0.0, float(self.cap.get(cv2.CAP_PROP_FPS)))
                logger.info("[%s] VideoCapture opened successfully (source FPS: %.2f).", self.camera_id, self.source_fps)
            else:
                logger.warning("[%s] Failed to open VideoCapture for: %s", self.camera_id, self.source)
                self.is_connected = False
                self.is_synthetic = True
        else:
            self.is_connected = True
            self.is_synthetic = True

    def _advance_local_video_for_elapsed_time(self) -> None:
        """
        Advance playback position for local video files to ensure real-time 1.0x playback speed.
        If source video has higher FPS than target_fps (e.g. 25fps source vs 15fps target),
        skip intervening frames so 1 wall-clock second equals 1 video second.
        """
        if (
            not self.is_local_file
            or self.cap is None
            or not self.cap.isOpened()
            or self.source_fps <= self.target_fps
        ):
            return

        ratio = self.source_fps / self.target_fps
        # 1 frame was already read by cap.read()
        self._frame_step_accumulator += (ratio - 1.0)
        skip_count = int(self._frame_step_accumulator)
        if skip_count > 0:
            self._frame_step_accumulator -= skip_count
            for _ in range(skip_count):
                if not self.cap.grab():
                    break

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Read next frame without blocking event loop.
        Fast resize with INTER_LINEAR for smooth, high-definition streaming.
        """
        self.last_frame_time = time.time()
        self.frame_count += 1

        # 1. Image fallback (creates animated simulation overlay)
        if self.is_image_fallback and self.fallback_frame is not None:
            frame = self.fallback_frame.copy()
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
                resized = cv2.resize(frame, self.resolution, interpolation=cv2.INTER_LINEAR)
                self._advance_local_video_for_elapsed_time()
                return True, resized
            else:
                # End of video file -> rewind to beginning seamlessly
                self._frame_step_accumulator = 0.0
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    resized = cv2.resize(frame, self.resolution, interpolation=cv2.INTER_LINEAR)
                    self._advance_local_video_for_elapsed_time()
                    return True, resized
                else:
                    logger.warning("[%s] Stream read returned empty frame. Attempting reconnect...", self.camera_id)
                    self._open_stream()

        # 3. Synthetic test generator
        return True, self._generate_synthetic_frame()

    def _generate_synthetic_frame(self) -> np.ndarray:
        """Generate a realistic test frame with simulated background."""
        self.synthetic_frame_index += 1
        w, h = self.resolution
        frame = np.full((h, w, 3), 32, dtype=np.uint8)

        # Draw road / parking ground
        cv2.rectangle(frame, (0, int(h * 0.35)), (w, h), (55, 55, 55), -1)
        # Lane divider lines
        cv2.line(frame, (0, int(h * 0.68)), (w, int(h * 0.68)), (190, 190, 190), 2)

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
