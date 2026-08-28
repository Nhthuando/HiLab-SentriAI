"""
stream.reader - OpenCV Video Stream Reader with Fallback & Auto-Reconnect

Supports:
- RTSP video streams
- Local MP4 / AVI video files (with seamless loop on EOF and 1.0x real-time pacing)
- Fallback image assets (frontend/public/assets/cam-gate.png, cam-baikiem.png)
- Dynamic synthetic frame generator (for headless / offline dev testing)
"""
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger("sentriai.stream.reader")


class StreamReader:
    def __init__(
        self,
        source: Optional[str] = None,
        camera_id: str = "GATE-01",
        resolution: Tuple[int, int] = (1280, 720),
        target_fps: float = 25.0,
    ):
        self.camera_id = camera_id
        self.target_fps = max(1.0, float(target_fps))
        self.resolution = resolution  # (width, height)
        self.source = source
        self.cap: Optional[cv2.VideoCapture] = None
        self._preview_cap: Optional[cv2.VideoCapture] = None
        self._preview_lock = threading.Lock()
        self.is_image_fallback = False

        self.is_local_file = False
        self.source_fps = 0.0
        self._total_frames = 0.0
        self._duration_seconds = 0.0
        self._current_pos_seconds = 0.0
        self.is_synthetic = False
        self.fallback_frame: Optional[np.ndarray] = None
        self.frame_count = 0
        self.last_frame_time = 0.0
        self.is_connected = False
        self.synthetic_frame_index = 0
        # True only for the first frame after a local video rewinds.
        self.did_loop = False
        self._last_local_frame_at: Optional[float] = None
        self._pending_seek_seconds: Optional[float] = None
        self._source_reset_pending = False
        self._resolve_source()
        self._open_stream()

    @property
    def is_usable_source(self) -> bool:
        """Return whether an explicitly configured source opened successfully."""
        return bool(
            self.is_connected
            and not self.is_synthetic
            and not self.is_image_fallback
            and (self.is_local_file or isinstance(self.source, str))
        )

    def mark_source_reset(self) -> None:
        """Mark the next decoded frame as the start of a new source timeline."""
        self._source_reset_pending = True
        self._last_local_frame_at = None

    def _resolve_source(self) -> None:
        """Resolve valid video source or fallback to available sample assets."""
        if self.source and (
            self.source.startswith("rtsp://")
            or self.source.startswith("http://")
            or self.source.startswith("https://")
        ):
            source_scheme = self.source.split(":", 1)[0].upper()
            logger.info("[%s] Using %s network stream source (URL redacted).", self.camera_id, source_scheme)
            return

        def _optimize_local_video(path_str: str) -> str:
            """Ensure local video files have index tables and zero-base PTS for instant, artifact-free seeking."""
            if "_fastseek" in path_str:
                return path_str
            mp4_candidate = os.path.splitext(path_str)[0] + "_fastseek.mp4"
            if os.path.exists(mp4_candidate) and os.path.getsize(mp4_candidate) > 1024:
                return mp4_candidate
            try:
                import subprocess
                import imageio_ffmpeg
                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
                cmd = [
                    ffmpeg_exe, "-y",
                    "-fflags", "+genpts",
                    "-i", path_str,
                    "-c", "copy",
                    "-avoid_negative_ts", "make_zero",
                    "-movflags", "+faststart",
                    mp4_candidate,
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if res.returncode == 0 and os.path.exists(mp4_candidate) and os.path.getsize(mp4_candidate) > 1024:
                    logger.info("[%s] Auto-indexed video stream to fast-seek container: %s", self.camera_id, mp4_candidate)
                    return mp4_candidate
            except Exception as exc:
                logger.warning("[%s] Could not auto-index video %s (%s). Using original.", self.camera_id, path_str, exc)
            return path_str

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
                    self.source = _optimize_local_video(p)
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
                self._total_frames = max(0.0, float(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)))
                self._duration_seconds = self._total_frames / self.source_fps if self.source_fps > 0 else 0.0
                self._current_pos_seconds = 0.0
                logger.info(
                    "[%s] VideoCapture opened successfully (source FPS: %.2f, duration: %.2fs).",
                    self.camera_id,
                    self.source_fps,
                    self._duration_seconds,
                )
            else:
                logger.warning("[%s] Failed to open VideoCapture for: %s", self.camera_id, self.source)
                self.is_connected = False
                self.is_synthetic = True
        else:
            self.is_connected = True
            self.is_synthetic = True

    def _advance_local_video_for_elapsed_time(self) -> None:
        """
        Advance playback time tracking for local video files.
        Skips frames to match the source video framerate with real wall-clock elapsed time,
        preventing slow-motion playback when target_fps < source_fps or when inference takes time.
        """
        if (
            not self.is_local_file
            or self.cap is None
            or not self.cap.isOpened()
            or self.source_fps <= 0.0
        ):
            return

        now = time.monotonic()
        previous = self._last_local_frame_at
        self._last_local_frame_at = now
        if previous is None:
            return

        elapsed = now - previous
        # If elapsed is too long (e.g. system paused, seeking, or inference delay), do NOT skip massive frames
        if elapsed > 0.4:
            return

        frames_needed = elapsed * self.source_fps
        skip_needed = int(max(0.0, frames_needed - 1.0))
        max_skip = min(3, max(1, int(round(self.source_fps / max(1.0, float(self.target_fps))))))
        skip_count = min(skip_needed, max_skip)
        for _ in range(skip_count):
            if not self.cap.grab():
                break
            self._current_pos_seconds = min(self._duration_seconds, self._current_pos_seconds + (1.0 / self.source_fps))

    def get_playback_state(self) -> dict:
        """Return seek metadata for a local video; live streams are not seekable (cached & thread-safe)."""
        if not self.is_local_file or self.cap is None or not self.cap.isOpened():
            return {"seekable": False, "positionSeconds": 0.0, "durationSeconds": 0.0}

        return {
            "seekable": self._duration_seconds > 0.0,
            "positionSeconds": min(self._current_pos_seconds, self._duration_seconds),
            "durationSeconds": self._duration_seconds,
        }

    def get_source_context(self) -> dict:
        """Return event source metadata without exposing live-stream credentials."""
        if self.is_local_file and self.source:
            return {
                "source_kind": "LOCAL_FILE",
                "source_ref": os.path.abspath(self.source),
                "source_position_seconds": float(self.get_playback_state()["positionSeconds"]),
                "source_timestamp": None,
            }

        if self.source and self.source.startswith(("rtsp://", "http://", "https://")):
            return {
                "source_kind": "LIVE",
                "source_ref": self.camera_id,
                "source_position_seconds": None,
                "source_timestamp": datetime.now(timezone.utc),
            }

        return {
            "source_kind": "UNAVAILABLE",
            "source_ref": None,
            "source_position_seconds": None,
            "source_timestamp": None,
        }

    def request_seek(self, position_seconds: float) -> dict:
        """Queue a safe seek, applied by the pipeline's frame-reading thread."""
        state = self.get_playback_state()
        if not state["seekable"]:
            return state

        target = max(0.0, min(float(position_seconds), float(state["durationSeconds"])))
        self._pending_seek_seconds = target
        state["positionSeconds"] = target
        return state

    def preview_frame(self, position_seconds: float) -> Optional[np.ndarray]:
        """Decode one local-video frame without moving the monitored reader.

        Uses a cached capture instance protected by a thread lock to provide
        instant (< 30ms) seek previews without thrashing disk I/O.
        """
        state = self.get_playback_state()
        if not state["seekable"] or not self.source:
            return None
        target = max(0.0, min(float(position_seconds), float(state["durationSeconds"])))
        with self._preview_lock:
            if self._preview_cap is None or not self._preview_cap.isOpened():
                self._preview_cap = cv2.VideoCapture(self.source)
            if not self._preview_cap.isOpened():
                return None
            fps = self.source_fps or max(0.0, float(self._preview_cap.get(cv2.CAP_PROP_FPS)))
            if fps > 0.0:
                target_frame = max(0, int(round(target * fps)))
                self._preview_cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            else:
                self._preview_cap.set(cv2.CAP_PROP_POS_MSEC, target * 1000.0)
            ok, frame = self._preview_cap.read()
            if not ok or frame is None:
                # Reopen once if stale
                self._preview_cap.release()
                self._preview_cap = cv2.VideoCapture(self.source)
                if self._preview_cap.isOpened():
                    if fps > 0.0:
                        self._preview_cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                    else:
                        self._preview_cap.set(cv2.CAP_PROP_POS_MSEC, target * 1000.0)
                    ok, frame = self._preview_cap.read()
            if not ok or frame is None:
                return None
            return cv2.resize(frame, self.resolution, interpolation=cv2.INTER_LINEAR)

    def _apply_pending_seek(self) -> None:
        if self._pending_seek_seconds is None or self.cap is None or not self.cap.isOpened():
            return
        target = self._pending_seek_seconds
        self._pending_seek_seconds = None
        fps = self.source_fps or max(0.0, float(self.cap.get(cv2.CAP_PROP_FPS)))
        if fps > 0.0:
            target_frame = max(0, int(round(target * fps)))
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        else:
            self.cap.set(cv2.CAP_PROP_POS_MSEC, target * 1000.0)
        self._current_pos_seconds = target
        self._last_local_frame_at = time.monotonic()
        self._source_reset_pending = True

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Read next frame without blocking event loop.
        Fast resize with INTER_LINEAR for smooth, high-definition streaming.
        """
        self.last_frame_time = time.time()
        self.frame_count += 1
        self.did_loop = self._source_reset_pending
        self._source_reset_pending = False

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
            self._apply_pending_seek()
            # Mark the first processed frame after a seek.  Consumers can then
            # replace an unannotated seek preview as soon as AI finishes this
            # exact frame rather than waiting for one additional inference.
            if self._source_reset_pending:
                self.did_loop = True
                self._source_reset_pending = False
            ret, frame = self.cap.read()
            if ret and frame is not None:
                if self.source_fps > 0:
                    self._current_pos_seconds = min(self._duration_seconds, self._current_pos_seconds + (1.0 / self.source_fps))
                resized = cv2.resize(frame, self.resolution, interpolation=cv2.INTER_LINEAR)
                self._advance_local_video_for_elapsed_time()
                return True, resized
            else:
                # End of video file -> rewind to beginning seamlessly.
                self.did_loop = True
                self._last_local_frame_at = None
                self._current_pos_seconds = 0.0
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

    def get_timecode(self) -> str:
        """Return current video playback timecode MM:SS (or real-time clock)."""
        if self.is_local_file:
            total_sec = max(0, int(self.get_playback_state().get("positionSeconds", 0.0)))
            mins = total_sec // 60
            secs = total_sec % 60
            return f"{mins:02d}:{secs:02d}"
        return time.strftime("%H:%M:%S")

    def skip_local_frames(self, count: int) -> int:
        """Advance a local source for background indexing without decoding frames."""
        if not self.is_local_file or self.cap is None or not self.cap.isOpened():
            return 0
        skipped = 0
        for _ in range(max(0, int(count))):
            if not self.cap.grab():
                break
            skipped += 1
            if self.source_fps > 0:
                self._current_pos_seconds = min(
                    self._duration_seconds,
                    self._current_pos_seconds + (1.0 / self.source_fps),
                )
        return skipped

    def get_playback_status(self) -> dict:
        state = self.get_playback_state()
        return {
            "seekable": bool(state.get("seekable", False)),
            "positionMs": int(float(state.get("positionSeconds", 0.0)) * 1000),
            "durationMs": int(float(state.get("durationSeconds", 0.0)) * 1000),
        }

    def seek_ms(self, position_ms: float) -> dict:
        state = self.request_seek(max(0.0, float(position_ms)) / 1000.0)
        self._frame_step_accumulator = 0.0
        return {
            "seekable": bool(state.get("seekable", False)),
            "positionMs": int(float(state.get("positionSeconds", 0.0)) * 1000),
            "durationMs": int(float(state.get("durationSeconds", 0.0)) * 1000),
        }

    def release(self) -> None:
        """Release underlying OpenCV resources."""
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        with self._preview_lock:
            if self._preview_cap is not None:
                self._preview_cap.release()
                self._preview_cap = None
        self.is_connected = False
        logger.info("[%s] StreamReader released.", self.camera_id)
