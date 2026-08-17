"""
buffer.circular_buffer — Rolling Circular Frame Buffer & MP4 Clip Writer

Maintains an in-memory ring buffer of the most recent N seconds of frames
and extracts MP4 video clips when gate / zone violation events are triggered (BR-05).
"""
import collections
import logging
import os
import time
from typing import Deque, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger("sentriai.buffer")


class CircularBuffer:
    def __init__(self, max_seconds: float = 12.0, target_fps: float = 10.0):
        self.max_seconds = max_seconds
        self.target_fps = max(1.0, target_fps)
        self.maxlen = int(self.max_seconds * self.target_fps) + 5
        self.buffer: Deque[Tuple[float, np.ndarray]] = collections.deque(maxlen=self.maxlen)

    def append(self, frame: np.ndarray, timestamp: Optional[float] = None) -> None:
        """Store a frame with its timestamp in the circular buffer."""
        if frame is None:
            return
        ts = timestamp or time.time()
        self.buffer.append((ts, frame))

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Return the most recent frame in the buffer."""
        if not self.buffer:
            return None
        return self.buffer[-1][1].copy()

    def get_frame_count(self) -> int:
        """Return current number of frames stored in buffer."""
        return len(self.buffer)

    def save_clip(
        self,
        output_path: str,
        duration_seconds: float = 10.0,
        fps: Optional[float] = None,
    ) -> Optional[str]:
        """
        Extract up to duration_seconds of buffered frames and write to an MP4 video file.
        Returns output_path on success, or None on failure (fulfills BR-05).
        """
        if not self.buffer:
            logger.warning("Circular buffer is empty. Cannot save clip to %s", output_path)
            return None

        out_fps = fps or self.target_fps
        now = time.time()
        cutoff_time = now - duration_seconds

        # Filter frames within time window
        frames = [f for ts, f in self.buffer if ts >= cutoff_time]
        if not frames:
            # Fallback to all available frames in buffer
            frames = [f for _, f in self.buffer]

        if not frames:
            return None

        try:
            # Ensure output directory exists
            dir_name = os.path.dirname(output_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            h, w = frames[0].shape[:2]

            # Use mp4v fourcc codec for universal MP4 compatibility
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(output_path, fourcc, out_fps, (w, h))

            if not writer.isOpened():
                logger.error("Failed to open VideoWriter for %s", output_path)
                return None

            for frame in frames:
                # Ensure correct frame dimensions
                if frame.shape[:2] != (h, w):
                    frame = cv2.resize(frame, (w, h))
                writer.write(frame)

            writer.release()
            logger.info("Successfully saved %d frames (%.1fs) clip to %s", len(frames), len(frames) / out_fps, output_path)
            return output_path

        except Exception as exc:
            # BR-05: clip writing failure must not crash the application
            logger.error("Failed to write video clip to %s: %s", output_path, exc)
            return None

    def clear(self) -> None:
        """Empty the buffer."""
        self.buffer.clear()
