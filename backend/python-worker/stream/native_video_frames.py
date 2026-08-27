"""Exact native-video frame decoding for reviewed local datasets."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np


class NativeVideoFrameLoader:
    """Decode reviewed timestamps, using FFmpeg fast seek when configured."""

    def __init__(
        self,
        manifest: Mapping[str, Any],
        video_root: Path,
        *,
        ffmpeg_path: Path | None = None,
        cache_frames: bool = True,
    ) -> None:
        self.video_root = video_root.resolve()
        self.ffmpeg_path = ffmpeg_path.resolve() if ffmpeg_path is not None else None
        if self.ffmpeg_path is not None and not self.ffmpeg_path.is_file():
            raise FileNotFoundError(f"FFmpeg executable is missing: {self.ffmpeg_path}")
        self.cache_frames = cache_frames
        self.sources = {
            str(source.get("sourceId") or ""): dict(source)
            for source in manifest.get("sources", [])
            if isinstance(source, Mapping)
        }
        self.captures: dict[str, cv2.VideoCapture] = {}
        # Lossless PNG payloads make repeated evaluation passes deterministic
        # without retaining uncompressed 2.5K frames in RAM.
        self.encoded_frames: dict[str, bytes] = {}

    def _decode_with_ffmpeg(self, video: Path, timestamp_ms: int, cache_key: str) -> Any:
        encoded = self.encoded_frames.get(cache_key)
        if encoded is None:
            completed = subprocess.run(
                [
                    str(self.ffmpeg_path),
                    "-hide_banner", "-loglevel", "error",
                    "-ss", f"{timestamp_ms / 1000:.3f}",
                    "-i", str(video),
                    "-frames:v", "1",
                    "-f", "image2pipe", "-vcodec", "png", "pipe:1",
                ],
                check=False,
                capture_output=True,
            )
            if completed.returncode != 0 or not completed.stdout:
                detail = completed.stderr.decode("utf-8", errors="replace")[-1000:]
                raise RuntimeError(
                    f"FFmpeg cannot decode native reviewed frame {video.name}@{timestamp_ms}ms: {detail}"
                )
            encoded = completed.stdout
            if self.cache_frames:
                self.encoded_frames[cache_key] = encoded
        return cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)

    def __call__(self, frame: Mapping[str, Any]) -> Any:
        source_id = str(frame.get("sourceId") or "")
        source = self.sources.get(source_id)
        if source is None:
            raise ValueError(f"reviewed source metadata is missing for {source_id}")
        source_file = str(source.get("sourceFile") or "")
        video = (self.video_root / source_file).resolve()
        if self.video_root not in video.parents or not video.is_file():
            raise FileNotFoundError(f"native reviewed video is missing: {video}")
        timestamp_ms = int(frame.get("timestampMs") or 0)
        if self.ffmpeg_path is not None:
            image = self._decode_with_ffmpeg(video, timestamp_ms, str(frame.get("frameId") or ""))
            if image is None:
                raise RuntimeError(f"cannot decode native reviewed frame {source_id}@{timestamp_ms}ms")
            return image

        capture = self.captures.get(source_id)
        if capture is None:
            capture = cv2.VideoCapture(str(video))
            if not capture.isOpened():
                capture.release()
                raise RuntimeError(f"cannot open native reviewed video: {video}")
            self.captures[source_id] = capture
        fps = float(source.get("fps") or capture.get(cv2.CAP_PROP_FPS) or 0)
        if fps > 0:
            capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(timestamp_ms * fps / 1000))))
        else:
            capture.set(cv2.CAP_PROP_POS_MSEC, max(0, timestamp_ms))
        ok, image = capture.read()
        if not ok or image is None:
            raise RuntimeError(f"cannot decode native reviewed frame {source_id}@{timestamp_ms}ms")
        return image

    def close(self) -> None:
        for capture in self.captures.values():
            capture.release()
        self.captures.clear()
        self.encoded_frames.clear()
