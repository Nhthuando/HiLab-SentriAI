"""Generate and cache Area violation clips only after an explicit user request."""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

import imageio_ffmpeg

from db.repositories import (
    claim_area_activity_clip,
    claim_violation_clip,
    get_area_activity_session,
    get_zone_violation,
    mark_area_activity_clip_failed,
    mark_area_activity_clip_generating,
    mark_area_activity_clip_ready,
    mark_violation_clip_failed,
    mark_violation_clip_generating,
    mark_violation_clip_ready,
)
from stream.rolling_archive import RollingArchive
from stream.source_config import configured_source_roots

logger = logging.getLogger("sentriai.detection.event_clip")


class ViolationClipStore:
    id_field = "violationId"

    async def get(self, event_id: str):
        return await get_zone_violation(event_id)

    async def claim(self, event_id: str):
        return await claim_violation_clip(event_id)

    async def mark_generating(self, event_id: str):
        return await mark_violation_clip_generating(event_id)

    async def mark_ready(self, event_id: str, clip_path: str):
        return await mark_violation_clip_ready(event_id, clip_path)

    async def mark_failed(self, event_id: str, status: str, error: str):
        return await mark_violation_clip_failed(event_id, status, error)


class ActivityClipStore:
    id_field = "activityId"

    async def get(self, event_id: str):
        return await get_area_activity_session(event_id)

    async def claim(self, event_id: str):
        return await claim_area_activity_clip(event_id)

    async def mark_generating(self, event_id: str):
        return await mark_area_activity_clip_generating(event_id)

    async def mark_ready(self, event_id: str, clip_path: str):
        return await mark_area_activity_clip_ready(event_id, clip_path)

    async def mark_failed(self, event_id: str, status: str, error: str):
        return await mark_area_activity_clip_failed(event_id, status, error)


@dataclass(frozen=True)
class EventClipResult:
    status: str
    clip_path: Optional[str] = None
    error: Optional[str] = None


def _as_utc(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


class EventClipGenerator:
    def __init__(
        self,
        clips_dir: Path | str,
        allowed_source_roots: Optional[list[Path | str]] = None,
        duration_seconds: float = 10.0,
    ) -> None:
        self.clips_dir = Path(clips_dir).resolve()
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.duration_seconds = max(1.0, float(duration_seconds))
        self._process_lock = threading.Lock()
        self._active_processes: set[subprocess.Popen[bytes]] = set()
        backend_root = Path(__file__).resolve().parents[2]

        repo_root = backend_root.parent
        configured_roots: list[Path] = []
        if allowed_source_roots is not None:
            for value in allowed_source_roots:
                candidate = Path(value).expanduser()
                if not candidate.is_absolute():
                    candidate = repo_root / candidate
                configured_roots.append(candidate.resolve())
        else:
            configured = os.getenv("CLIP_SOURCE_ROOTS", "")
            configured_roots.extend(configured_source_roots(configured, repo_root))
        configured_roots.append(backend_root / "data")
        self.allowed_source_roots = tuple(root.expanduser().resolve() for root in configured_roots)

    @staticmethod
    def _safe_id(value: Any) -> str:
        return str(uuid.UUID(str(value)))

    def _paths(self, violation_id: Any) -> tuple[str, Path, Path]:
        safe_id = self._safe_id(violation_id)
        filename = f"area_{safe_id}.mp4"
        return filename, self.clips_dir / filename, self.clips_dir / f"area_{safe_id}.tmp.mp4"

    def _resolve_local_source(self, value: Any) -> Optional[Path]:
        if not isinstance(value, str) or not value.strip():
            return None
        candidate = Path(value).expanduser().resolve()
        if not candidate.is_file():
            return None
        if not any(candidate == root or root in candidate.parents for root in self.allowed_source_roots):
            return None
        return candidate

    def _run_command(self, command: list[str]) -> bool:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with self._process_lock:
            self._active_processes.add(process)
        try:
            return process.wait(timeout=120) == 0
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            return False
        finally:
            with self._process_lock:
                self._active_processes.discard(process)

    def cancel_all(self) -> None:
        """Terminate only event-specific FFmpeg processes, never the live archive."""
        with self._process_lock:
            processes = list(self._active_processes)
        for process in processes:
            if process.poll() is not None:
                continue
            try:
                process.terminate()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass

    def _encode_local(self, source: Path, start_seconds: float, temp_path: Path) -> bool:
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        common = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start_seconds:.3f}", "-i", str(source),
            "-t", f"{self.duration_seconds:.3f}", "-map", "0:v:0", "-an",
        ]
        copy_command = [*common, "-c:v", "copy", "-movflags", "+faststart", str(temp_path)]
        if self._run_command(copy_command) and temp_path.exists() and temp_path.stat().st_size > 1024:
            return True
        temp_path.unlink(missing_ok=True)
        encode_command = [
            *common,
            "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "baseline",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temp_path),
        ]
        return self._run_command(encode_command) and temp_path.exists() and temp_path.stat().st_size > 1024

    async def generate_local(self, violation: Mapping[str, Any]) -> EventClipResult:
        try:
            filename, final_path, temp_path = self._paths(violation.get("id"))
        except (ValueError, TypeError):
            return EventClipResult("FAILED", error="Invalid violation id")
        if final_path.exists() and final_path.stat().st_size > 1024:
            return EventClipResult("READY", clip_path=filename)

        source = self._resolve_local_source(violation.get("source_ref"))
        if source is None:
            return EventClipResult("FAILED", error="Local source is missing or outside allowed roots")
        try:
            position = max(0.0, float(violation.get("source_position_seconds") or 0.0))
        except (TypeError, ValueError):
            position = 0.0
        temp_path.unlink(missing_ok=True)
        try:
            ok = await asyncio.to_thread(self._encode_local, source, position, temp_path)
            if not ok:
                return EventClipResult("FAILED", error="FFmpeg could not extract the local clip")
            os.replace(temp_path, final_path)
            return EventClipResult("READY", clip_path=filename)
        except Exception as exc:
            logger.warning("Local clip generation failed for %s: %s", violation.get("id"), type(exc).__name__)
            return EventClipResult("FAILED", error="Local clip generation failed")
        finally:
            temp_path.unlink(missing_ok=True)

    def _encode_live(
        self,
        segments: list[Path],
        start: datetime,
        archive: RollingArchive,
        temp_path: Path,
        concat_path: Path,
    ) -> bool:
        first_start = archive._segment_start(segments[0])
        seek_offset = max(0.0, (start - first_start).total_seconds())
        concat_path.write_text(
            "".join(f"file '{str(path).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for path in segments),
            encoding="utf-8",
        )
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        common = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_path),
            "-ss", f"{seek_offset:.3f}", "-t", f"{self.duration_seconds:.3f}", "-an",
        ]
        copy_command = [*common, "-c:v", "copy", "-movflags", "+faststart", str(temp_path)]
        if self._run_command(copy_command) and temp_path.exists() and temp_path.stat().st_size > 1024:
            return True
        temp_path.unlink(missing_ok=True)
        encode_command = [
            *common,
            "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "baseline",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temp_path),
        ]
        return self._run_command(encode_command) and temp_path.exists() and temp_path.stat().st_size > 1024

    async def generate_live(
        self,
        violation: Mapping[str, Any],
        archive: Optional[RollingArchive],
    ) -> EventClipResult:
        if archive is None:
            return EventClipResult("FAILED", error="Live rolling archive is unavailable")
        start = _as_utc(violation.get("source_timestamp")) or _as_utc(violation.get("entered_at"))
        if start is None:
            return EventClipResult("FAILED", error="Live event timestamp is unavailable")
        end = start + timedelta(seconds=self.duration_seconds)
        now = datetime.now(timezone.utc)
        if end > now:
            await asyncio.sleep(min(self.duration_seconds, (end - now).total_seconds()))
        if datetime.now(timezone.utc) - start > timedelta(seconds=archive.retention_seconds):
            return EventClipResult("EXPIRED", error="Live event is outside the two-hour archive window")

        segments = archive.segments_for(start, end)
        if not segments:
            return EventClipResult("EXPIRED", error="Live archive no longer contains this event window")
        try:
            filename, final_path, temp_path = self._paths(violation.get("id"))
        except (ValueError, TypeError):
            return EventClipResult("FAILED", error="Invalid violation id")
        if final_path.exists() and final_path.stat().st_size > 1024:
            return EventClipResult("READY", clip_path=filename)
        concat_path = self.clips_dir / f"area_{self._safe_id(violation.get('id'))}.concat.txt"
        temp_path.unlink(missing_ok=True)
        archive.acquire(segments)
        try:
            ok = await asyncio.to_thread(
                self._encode_live,
                segments,
                start,
                archive,
                temp_path,
                concat_path,
            )
            if not ok:
                return EventClipResult("FAILED", error="FFmpeg could not assemble the live clip")
            os.replace(temp_path, final_path)
            return EventClipResult("READY", clip_path=filename)
        except Exception as exc:
            logger.warning("Live clip generation failed for %s: %s", violation.get("id"), type(exc).__name__)
            return EventClipResult("FAILED", error="Live clip generation failed")
        finally:
            archive.release(segments)
            concat_path.unlink(missing_ok=True)
            temp_path.unlink(missing_ok=True)


class EventClipService:
    def __init__(
        self,
        camera_id: str,
        generator: EventClipGenerator,
        archive: Optional[RollingArchive] = None,
        queue_limit: int = 8,
        store: Optional[Any] = None,
    ) -> None:
        self.camera_id = camera_id
        self.generator = generator
        self.archive = archive
        self.store = store or ViolationClipStore()
        self._queue: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=max(1, int(queue_limit)))
        self._worker: Optional[asyncio.Task[None]] = None
        self._jobs: set[str] = set()
        self._generation = 0
        self._request_lock = asyncio.Lock()

    def start(self) -> None:
        if self._worker and not self._worker.done():
            return
        self._worker = asyncio.create_task(self._run(), name=f"event-clips:{self.camera_id}")

    async def stop(self) -> None:
        self._generation += 1
        cancel_all = getattr(self.generator, "cancel_all", None)
        if callable(cancel_all):
            await asyncio.to_thread(cancel_all)
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None
        self._jobs.clear()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def reset(self) -> None:
        was_running = bool(self._worker and not self._worker.done())
        await self.stop()
        for partial in self.generator.clips_dir.glob("area_*.tmp.mp4"):
            partial.unlink(missing_ok=True)
        if was_running:
            self.start()

    def _state(self, record: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
        if not record:
            return None
        status = str(record.get("clip_status") or ("READY" if record.get("clip_path") else "NOT_REQUESTED"))
        clip_path = record.get("clip_path") if status == "READY" else None
        return {
            self.store.id_field: str(record.get("id")),
            "status": status,
            "clipUrl": f"/data/clips/{Path(str(clip_path)).name}" if clip_path else None,
            "message": record.get("clip_error"),
        }

    async def get_state(self, event_id: str) -> Optional[dict[str, Any]]:
        return self._state(await self.store.get(event_id))

    async def request(self, event_id: str) -> Optional[dict[str, Any]]:
        async with self._request_lock:
            record = await self.store.get(event_id)
            if not record or str(record.get("camera_id")) != self.camera_id:
                return None
            current = self._state(record)
            assert current is not None
            if current["status"] == "READY":
                clip_path = record.get("clip_path")
                cached = self.generator.clips_dir / Path(str(clip_path)).name if clip_path else None
                if cached and cached.is_file() and cached.stat().st_size > 1024:
                    return current
                await self.store.mark_failed(event_id, "FAILED", "Cached clip file is missing")
            elif current["status"] in {"QUEUED", "GENERATING"}:
                if event_id in self._jobs:
                    return current
                # Recover a request left behind by a previous worker process.
                await self.store.mark_failed(event_id, "FAILED", "Previous clip job was interrupted")
            elif current["status"] == "EXPIRED":
                return current

            claimed = await self.store.claim(event_id)
            if claimed is None:
                return await self.get_state(event_id)
            self.start()
            try:
                self._queue.put_nowait(event_id)
                self._jobs.add(event_id)
            except asyncio.QueueFull:
                failed = await self.store.mark_failed(
                    event_id,
                    "FAILED",
                    "Clip queue is full; try again",
                )
                return self._state(failed)
            return self._state(claimed)

    async def _run(self) -> None:
        generation = self._generation
        while True:
            event_id = await self._queue.get()
            if event_id is None:
                self._queue.task_done()
                return
            try:
                if generation != self._generation:
                    continue
                record = await self.store.mark_generating(event_id)
                if not record:
                    continue
                source_kind = str(record.get("source_kind") or "UNAVAILABLE")
                if source_kind == "LOCAL_FILE":
                    result = await self.generator.generate_local(record)
                elif source_kind == "LIVE":
                    result = await self.generator.generate_live(record, self.archive)
                else:
                    result = EventClipResult("FAILED", error="No retained source is available for this event")

                if generation != self._generation:
                    continue
                if result.status == "READY" and result.clip_path:
                    await self.store.mark_ready(event_id, result.clip_path)
                else:
                    await self.store.mark_failed(
                        event_id,
                        "EXPIRED" if result.status == "EXPIRED" else "FAILED",
                        result.error or "Clip generation failed",
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Clip job failed for %s: %s", event_id, type(exc).__name__)
                try:
                    await self.store.mark_failed(event_id, "FAILED", "Clip generation failed")
                except Exception:
                    pass
            finally:
                self._jobs.discard(event_id)
                self._queue.task_done()
