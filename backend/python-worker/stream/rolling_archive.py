"""Bounded stream-copy archive for on-demand clips from live Area cameras."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

import imageio_ffmpeg

logger = logging.getLogger("sentriai.stream.rolling_archive")


class RollingArchive:
    def __init__(
        self,
        camera_id: str,
        source_url: str,
        archive_dir: Path | str,
        retention_seconds: int = 7200,
        segment_seconds: int = 2,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.camera_id = camera_id
        self._source_url = source_url
        self.archive_dir = Path(archive_dir).resolve()
        self.retention_seconds = max(60, int(retention_seconds))
        self.segment_seconds = max(1, int(segment_seconds))
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._runner_task: Optional[asyncio.Task[None]] = None
        self._cleanup_task: Optional[asyncio.Task[None]] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._stopping = False
        self._leases: dict[Path, int] = {}
        self.last_error: Optional[str] = None

    @property
    def is_running(self) -> bool:
        return bool(self._runner_task and not self._runner_task.done())

    def start(self) -> None:
        if self.is_running:
            return
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._stopping = False
        self._runner_task = asyncio.create_task(self._run(), name=f"archive:{self.camera_id}")
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(), name=f"archive-clean:{self.camera_id}")

    async def stop(self) -> None:
        self._stopping = True
        process = self._process
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        self._process = None

        tasks = [task for task in (self._runner_task, self._cleanup_task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._runner_task = None
        self._cleanup_task = None

    def _command(self) -> list[str]:
        input_options = ["-rtsp_transport", "tcp"] if self._source_url.lower().startswith("rtsp://") else []
        return [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            *input_options,
            "-i",
            self._source_url,
            "-map",
            "0:v:0",
            "-an",
            "-c:v",
            "copy",
            "-f",
            "segment",
            "-segment_time",
            str(self.segment_seconds),
            "-reset_timestamps",
            "1",
            "-strftime",
            "1",
            str(self.archive_dir / "%Y%m%dT%H%M%S.ts"),
        ]

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stopping:
            try:
                logger.info(
                    "[%s] Starting compressed rolling archive (source URL redacted, retention=%ss).",
                    self.camera_id,
                    self.retention_seconds,
                )
                self._process = await asyncio.create_subprocess_exec(
                    *self._command(),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                return_code = await self._process.wait()
                self._process = None
                if self._stopping:
                    return
                self.last_error = f"FFmpeg archive stopped with code {return_code}"
                logger.warning("[%s] Rolling archive stopped; retrying in %.1fs.", self.camera_id, backoff)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self.last_error = type(exc).__name__
                logger.warning("[%s] Rolling archive unavailable; retrying in %.1fs.", self.camera_id, backoff)

            await asyncio.sleep(backoff)
            backoff = min(30.0, backoff * 2.0)

    async def _cleanup_loop(self) -> None:
        while not self._stopping:
            try:
                self.cleanup()
            except Exception as exc:
                logger.warning("[%s] Rolling archive cleanup failed: %s", self.camera_id, type(exc).__name__)
            await asyncio.sleep(max(5.0, float(self.segment_seconds)))

    @staticmethod
    def _segment_start(path: Path) -> datetime:
        try:
            return datetime.strptime(path.stem, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

    def cleanup(self, now: Optional[datetime] = None) -> int:
        current = now or self._clock()
        cutoff = current.timestamp() - self.retention_seconds
        removed = 0
        if not self.archive_dir.exists():
            return removed
        for path in self.archive_dir.glob("*.ts"):
            if self._leases.get(path, 0) > 0:
                continue
            try:
                if self._segment_start(path).timestamp() + self.segment_seconds < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
        return removed

    def segments_for(self, start: datetime, end: datetime) -> list[Path]:
        if not self.archive_dir.exists() or end <= start:
            return []
        candidates = sorted(self.archive_dir.glob("*.ts"), key=self._segment_start)
        selected = [
            path
            for path in candidates
            if self._segment_start(path).timestamp() < end.timestamp()
            and self._segment_start(path).timestamp() + self.segment_seconds > start.timestamp()
        ]
        if not selected:
            return []
        first_start = self._segment_start(selected[0]).timestamp()
        last_end = self._segment_start(selected[-1]).timestamp() + self.segment_seconds
        tolerance = float(self.segment_seconds)
        if first_start > start.timestamp() + tolerance or last_end < end.timestamp() - tolerance:
            return []
        return selected

    def acquire(self, paths: Iterable[Path]) -> None:
        for raw_path in paths:
            path = Path(raw_path)
            self._leases[path] = self._leases.get(path, 0) + 1

    def release(self, paths: Iterable[Path]) -> None:
        for raw_path in paths:
            path = Path(raw_path)
            count = self._leases.get(path, 0)
            if count <= 1:
                self._leases.pop(path, None)
            else:
                self._leases[path] = count - 1

    def status(self) -> dict[str, object]:
        return {
            "cameraId": self.camera_id,
            "running": self.is_running,
            "retentionSeconds": self.retention_seconds,
            "segmentSeconds": self.segment_seconds,
            "lastError": self.last_error,
        }
