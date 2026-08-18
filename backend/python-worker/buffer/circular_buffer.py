"""
buffer.circular_buffer — Rolling Circular Frame Buffer & MP4 Clip Writer

Maintains an in-memory ring buffer of the most recent N seconds of frames
and extracts MP4 video clips when gate / zone violation events are triggered (BR-05).
"""
import collections
import logging
import os
import subprocess
import threading
import time
from typing import Deque, Optional, Tuple

import cv2
import imageio_ffmpeg
import numpy as np

logger = logging.getLogger("sentriai.buffer")


class CircularBuffer:
    def __init__(self, max_seconds: float = 12.0, target_fps: float = 10.0):
        self.max_seconds = max_seconds
        self.target_fps = max(1.0, target_fps)
        self.maxlen = int(self.max_seconds * self.target_fps) + 5
        self.buffer: Deque[Tuple[float, np.ndarray]] = collections.deque(maxlen=self.maxlen)
        self._lock = threading.Lock()

    def append(self, frame: np.ndarray, timestamp: Optional[float] = None) -> None:
        """Store a frame with its timestamp in the circular buffer."""
        if frame is None:
            return
        ts = timestamp or time.time()
        with self._lock:
            self.buffer.append((ts, frame))

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Return the most recent frame in the buffer."""
        with self._lock:
            if not self.buffer:
                return None
            return self.buffer[-1][1].copy()

    def get_frame_count(self) -> int:
        """Return current number of frames stored in buffer."""
        with self._lock:
            return len(self.buffer)

    def save_clip(
        self,
        output_path: str,
        duration_seconds: float = 10.0,
        fps: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> Optional[str]:
        """
        Extract up to duration_seconds of buffered frames and write to an MP4 video file.
        Returns output_path on success, or None on failure (fulfills BR-05).
        """
        out_fps = fps or self.target_fps
        end_ts = end_time if end_time is not None else time.time()
        start_ts = end_ts - duration_seconds

        with self._lock:
            if not self.buffer:
                logger.warning("Circular buffer is empty. Cannot save clip to %s", output_path)
                return None

            # Snapshot the deque before writing on a background thread.
            captured = [(ts, f) for ts, f in self.buffer if start_ts <= ts <= (end_ts + 0.5)]

        if not captured:
            logger.warning("Circular buffer has no frames for the requested clip window: %s", output_path)
            return None

        frames = [frame for _, frame in captured]
        if len(captured) > 1:
            captured_duration = captured[-1][0] - captured[0][0]
            if captured_duration > 0:
                # Match playback to the real sampling rate. Inference may run well below
                # target FPS, and writing those frames at target FPS shortens the clip.
                out_fps = max(1.0, len(frames) / captured_duration)

        try:
            # Ensure output directory exists
            dir_name = os.path.dirname(output_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            h, w = frames[0].shape[:2]
            temporary_output_path = f"{output_path}.tmp.mp4"
            command = [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "rawvideo",
                "-pixel_format",
                "bgr24",
                "-video_size",
                f"{w}x{h}",
                "-framerate",
                f"{out_fps:.6f}",
                "-i",
                "-",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-profile:v",
                "baseline",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                temporary_output_path,
            ]
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            try:
                for frame in frames:
                    if frame.shape[:2] != (h, w):
                        frame = cv2.resize(frame, (w, h))
                    assert process.stdin is not None
                    process.stdin.write(np.ascontiguousarray(frame).tobytes())
                process.stdin.close()
                stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
                if process.wait() != 0:
                    raise RuntimeError(stderr or "FFmpeg could not encode the H.264 clip")
                os.replace(temporary_output_path, output_path)
            except Exception:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                if process.poll() is None:
                    process.kill()
                process.wait()
                if os.path.exists(temporary_output_path):
                    os.remove(temporary_output_path)
                raise
            finally:
                if process.stderr:
                    process.stderr.close()

            logger.info("Successfully saved %d frames (%.1fs) clip to %s", len(frames), len(frames) / out_fps, output_path)
            return output_path

        except Exception as exc:
            # BR-05: clip writing failure must not crash the application
            logger.error("Failed to write video clip to %s: %s", output_path, exc)
            return None

    def clear(self) -> None:
        """Empty the buffer."""
        with self._lock:
            self.buffer.clear()
