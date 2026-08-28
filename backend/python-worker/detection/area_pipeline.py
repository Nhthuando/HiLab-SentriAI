"""
detection.area_pipeline — Camera BAI-KIEM Area AI Pipeline

Coordinates:
1. StreamReader (video source or synthetic frames)
2. TrackedYoloDetector (ByteTrack multi-object tracking)
3. ZoneSynchronizer (5-second atomic DB sync)
4. ZoneChecker (polygon containment, rule matrix, violation state machine)
5. StreamEmitter (WebSocket frame, event, and alert emission)
6. DB persistence (zone_violations OPEN/CLOSED and lazy clip source metadata)
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import cv2

from db.repositories import (
    close_area_activity_session,
    close_zone_violation,
    create_area_activity_session,
    create_zone_violation,
    delete_area_activity_sessions,
    delete_zone_violations,
    get_area_activity_collection_state,
    touch_area_activity_collection,
    update_area_activity_collection,
)
from detection.area_event_queue import AreaEventQueue, RetryableAreaTransitionError
from detection.event_clip_service import ActivityClipStore, EventClipGenerator, EventClipService
from detection.tracked_detector import TrackedYoloDetector
from stream.emitter import StreamEmitter
from stream.reader import StreamReader
from stream.rolling_archive import RollingArchive
from zone.zone_checker import ViolationTransition, ZoneChecker
from zone.activity_tracker import ActivityTracker, ActivityTransition
from zone.coverage_tracker import ActivityCoverageTracker
from zone.zone_sync import ZoneSnapshot, ZoneSynchronizer

logger = logging.getLogger("sentriai.area.pipeline")
APP_TIME_ZONE = timezone(timedelta(hours=7))


class RepositoryAreaPersistence:
    """Production persistence adapter; benchmarks can inject a no-write sink."""

    async def create(self, **payload: Any) -> Any:
        return await create_zone_violation(**payload)

    async def close(self, **payload: Any) -> Any:
        return await close_zone_violation(**payload)

    async def delete_all(self, camera_id: str) -> int:
        return await delete_zone_violations(camera_id)


class RepositoryActivityPersistence:
    """Activity metadata adapter kept independent from violation persistence."""

    async def create(self, **payload: Any) -> Any:
        return await create_area_activity_session(**payload)

    async def close(self, **payload: Any) -> Any:
        return await close_area_activity_session(**payload)

    async def delete_all(self, camera_id: str) -> int:
        return await delete_area_activity_sessions(camera_id)

    async def touch(self, camera_id: str, observed_at: datetime) -> Any:
        return await touch_area_activity_collection(camera_id, observed_at)

    async def update_coverage(self, **payload: Any) -> Any:
        return await update_area_activity_collection(**payload)

    async def get_coverage(self, camera_id: str) -> Any:
        return await get_area_activity_collection_state(camera_id)


class NoWriteActivityPersistence:
    """Test/benchmark sink used when callers already inject non-production persistence."""

    async def create(self, **payload: Any) -> Dict[str, Any]:
        return {"id": payload["session_id"]}

    async def close(self, **payload: Any) -> Dict[str, Any]:
        return payload

    async def delete_all(self, _camera_id: str) -> int:
        return 0

    async def touch(self, _camera_id: str, _observed_at: datetime) -> None:
        return None

    async def update_coverage(self, **_payload: Any) -> None:
        return None

    async def get_coverage(self, _camera_id: str) -> None:
        return None


class AreaPipeline:
    def __init__(
        self,
        camera_id: str = "BAI-KIEM",
        source: Optional[str] = None,
        target_fps: float = 10.0,
        resolution: Tuple[int, int] = (640, 480),
        jpeg_quality: int = 70,
        clips_dir: Optional[str] = None,
        emitter: Optional[StreamEmitter] = None,
        detector: Optional[TrackedYoloDetector] = None,
        zone_sync: Optional[ZoneSynchronizer] = None,
        zone_checker: Optional[ZoneChecker] = None,
        reader: Optional[Any] = None,
        circular_buffer: Optional[Any] = None,
        persistence: Optional[Any] = None,
        activity_tracker: Optional[ActivityTracker] = None,
        activity_persistence: Optional[Any] = None,
        record_violation_clips: bool = True,
        rolling_archive: Optional[RollingArchive] = None,
        clip_service: Optional[EventClipService] = None,
        activity_clip_service: Optional[EventClipService] = None,
    ):
        self.camera_id = camera_id
        self.target_fps = target_fps
        self.resolution = resolution
        self.jpeg_quality = jpeg_quality
        self.background_frame_stride = max(1, int(os.getenv("AREA_BACKGROUND_FRAME_STRIDE", "1")))

        backend_dir = Path(__file__).resolve().parents[2]
        self._backend_dir = backend_dir

        # Resolve clips directory relative to backend/, independent of process CWD.
        if clips_dir:
            configured_clips_dir = Path(clips_dir)
        else:
            env_clips = os.getenv("CLIPS_DIR")
            configured_clips_dir = Path(env_clips) if env_clips else Path("data") / "clips"
        self.clips_dir = (
            configured_clips_dir
            if configured_clips_dir.is_absolute()
            else backend_dir / configured_clips_dir
        )
        self.clips_dir.mkdir(parents=True, exist_ok=True)

        self.reader = reader or StreamReader(
            source=source,
            camera_id=camera_id,
            target_fps=target_fps,
            resolution=resolution,
        )
        self.detector = detector or TrackedYoloDetector()
        # Compatibility hook only. Raw frames are no longer retained in RAM;
        # event clips are generated lazily from the source/archive.
        self.buffer = circular_buffer
        self.emitter = emitter or StreamEmitter()
        self.zone_sync = zone_sync or ZoneSynchronizer(camera_id=camera_id, sync_interval=5.0)
        self.zone_checker = zone_checker or ZoneChecker(
            camera_id=camera_id,
            grace_frames=3,
            missing_grace_seconds=12.0,
        )
        self.persistence = persistence or RepositoryAreaPersistence()
        self.activity_tracker = activity_tracker or ActivityTracker(
            camera_id=camera_id,
            confirmation_seconds=1.0,
            grace_frames=3,
            missing_grace_seconds=12.0,
        )
        self.activity_persistence = (
            activity_persistence
            or (NoWriteActivityPersistence() if persistence is not None else RepositoryActivityPersistence())
        )
        self.record_violation_clips = False

        source_context = self._get_source_context()
        live_source = getattr(self.reader, "source", None)
        if rolling_archive is not None:
            self.rolling_archive = rolling_archive
        else:
            self.rolling_archive = self._build_rolling_archive(source_context, live_source)
        self.clip_service = clip_service or EventClipService(
            camera_id=self.camera_id,
            generator=EventClipGenerator(self.clips_dir),
            archive=self.rolling_archive,
            queue_limit=int(os.getenv("AREA_CLIP_QUEUE_LIMIT", "8")),
        )
        self.activity_clip_service = activity_clip_service or EventClipService(
            camera_id=self.camera_id,
            generator=EventClipGenerator(self.clips_dir),
            archive=self.rolling_archive,
            queue_limit=int(os.getenv("AREA_CLIP_QUEUE_LIMIT", "8")),
            store=ActivityClipStore(),
        )

        self._running = False
        self._active = False
        self._viewer_active = False
        self._task: Optional[asyncio.Task] = None
        self.frame_count = 0
        self.fps_measured = 0.0
        self._last_fps_calc = time.time()
        self._fps_counter = 0
        self._control_lock = asyncio.Lock()
        self._runtime_generation = 0
        self._event_queue = AreaEventQueue(
            self._process_transition_once,
            self._handle_exhausted_transition,
        )
        self._activity_queue = AreaEventQueue(
            self._process_activity_transition_once,
            self._handle_exhausted_activity_transition,
        )
        self._activity_persisted_ids: Dict[str, str] = {}
        self._activity_replay_session_ids: set[str] = set()
        self._activity_replay_read_only = False
        self._last_activity_persistence_error: Optional[str] = None
        self._activity_heartbeat_task: Optional[asyncio.Task[Any]] = None
        self._last_activity_heartbeat = 0.0
        self.activity_coverage = ActivityCoverageTracker(
            max_contiguous_gap_seconds=max(1.0, 2.5 / max(1.0, self.target_fps)),
        )
        self._reset_activity_coverage_source()
        self._applied_detection_snapshot: Optional[ZoneSnapshot] = None
        self._applied_detection_control: Optional[tuple[object, ...]] = None

    def _get_source_context(self) -> Dict[str, Any]:
        getter = getattr(self.reader, "get_source_context", None)
        if callable(getter):
            try:
                context = getter()
                if isinstance(context, Mapping):
                    return dict(context)
            except Exception:
                pass
        return {
            "source_kind": "UNAVAILABLE",
            "source_ref": None,
            "source_position_seconds": None,
            "source_timestamp": None,
        }

    def _build_rolling_archive(
        self,
        source_context: Mapping[str, Any],
        source: object,
    ) -> Optional[RollingArchive]:
        """Build a live archive for the current reader without starting it."""
        if source_context.get("source_kind") != "LIVE" or not isinstance(source, str):
            return None
        return RollingArchive(
            camera_id=self.camera_id,
            source_url=source,
            archive_dir=self._backend_dir / "data" / "area_archive" / self.camera_id,
            retention_seconds=int(os.getenv("AREA_ARCHIVE_RETENTION_SECONDS", "7200")),
            segment_seconds=int(os.getenv("AREA_ARCHIVE_SEGMENT_SECONDS", "2")),
        )

    def _coverage_source(self) -> Tuple[str, Optional[str], Optional[str], Optional[float]]:
        context = self._get_source_context()
        source_kind = str(context.get("source_kind") or "UNAVAILABLE")
        source_ref = context.get("source_ref") if isinstance(context.get("source_ref"), str) else None
        duration: Optional[float] = None
        state_getter = getattr(self.reader, "get_playback_state", None)
        if callable(state_getter):
            try:
                state = state_getter()
                raw_duration = state.get("durationSeconds") if isinstance(state, Mapping) else None
                duration = float(raw_duration) if raw_duration and float(raw_duration) > 0 else None
            except (TypeError, ValueError):
                duration = None
        identity = source_ref or self.camera_id
        if source_kind == "LOCAL_FILE" and source_ref:
            try:
                stat = os.stat(source_ref)
                identity = f"{os.path.abspath(source_ref)}:{stat.st_size}:{stat.st_mtime_ns}"
            except OSError:
                identity = os.path.abspath(source_ref)
        fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest() if identity else None
        return source_kind, fingerprint, source_ref, duration

    def _reset_activity_coverage_source(self) -> None:
        kind, fingerprint, _source_ref, duration = self._coverage_source()
        self.activity_coverage.reset_source(kind, fingerprint, duration)
        self.activity_coverage.break_continuity()

    def _observe_activity_coverage(self) -> None:
        kind, fingerprint, _source_ref, duration = self._coverage_source()
        self.activity_coverage.reset_source(kind, fingerprint, duration)
        context = self._get_source_context()
        position = context.get("source_position_seconds")
        observed = context.get("source_timestamp")
        self.activity_coverage.observe(
            position_seconds=float(position) if position is not None else None,
            observed_at=observed if isinstance(observed, datetime) else None,
        )

    async def _restore_activity_coverage(self) -> None:
        """Restore coverage only when persistence belongs to the current source."""
        self._activity_replay_read_only = False
        self._reset_activity_coverage_source()
        loader = getattr(self.activity_persistence, "get_coverage", None)
        try:
            saved = await loader(self.camera_id) if callable(loader) else None
        except Exception as exc:
            logger.warning("[%s] Coverage resume unavailable: %s", self.camera_id, exc)
            return
        if not isinstance(saved, Mapping):
            return

        kind, fingerprint, _source_ref, duration = self._coverage_source()
        if saved.get("source_fingerprint") != fingerprint:
            return
        self.activity_coverage.restore(
            source_kind=kind,
            source_fingerprint=fingerprint,
            source_duration_seconds=duration,
            covered_intervals=list(saved.get("covered_intervals") or []),
            last_observed_at=saved.get("last_observed_at"),
            completed_at=saved.get("completed_at"),
        )
        self._activity_replay_read_only = (
            kind == "LOCAL_FILE"
            and self.activity_coverage.snapshot().coverage_status == "COMPLETE"
        )

    def _resolve_active_model(self, active_model: Optional[Mapping[str, Any]]) -> Optional[Dict[str, object]]:
        """Return a verified, absolute ACTIVE artifact or fail closed.

        The database/synchronizer owns ACTIVE selection.  This method merely
        verifies the artifact before it reaches Ultralytics: paths must remain
        below ``backend/data`` and their stored digest must match exactly.
        """
        if not isinstance(active_model, Mapping):
            return None
        version_key = active_model.get("version_key")
        artifact_setting = active_model.get("artifact_path")
        artifact_sha256 = active_model.get("artifact_sha256")
        label_map = active_model.get("label_map")
        runtime_mode = str(active_model.get("runtime_mode", "SUPPLEMENTAL")).strip().upper()
        if (
            not isinstance(version_key, str)
            or not version_key.strip()
            or not isinstance(artifact_setting, str)
            or not artifact_setting.strip()
            or not isinstance(artifact_sha256, str)
            or len(artifact_sha256) != 64
            or any(character not in "0123456789abcdef" for character in artifact_sha256.casefold())
            or not isinstance(label_map, Mapping)
            or runtime_mode not in {"SUPPLEMENTAL", "UNIFIED"}
        ):
            logger.error("[%s] ACTIVE model metadata is incomplete or invalid; custom detection is disabled.", self.camera_id)
            return None

        backend_root = Path(__file__).resolve().parents[2]
        data_root = (backend_root / "data").resolve()
        artifact = Path(artifact_setting)
        candidate = artifact.resolve() if artifact.is_absolute() else (data_root / artifact).resolve()
        if data_root not in candidate.parents or not candidate.is_file():
            logger.error("[%s] ACTIVE model artifact is outside backend/data or missing: %s", self.camera_id, candidate)
            return None

        digest = hashlib.sha256()
        try:
            with candidate.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            logger.error("[%s] Could not read ACTIVE model artifact %s: %s", self.camera_id, candidate, exc)
            return None
        if digest.hexdigest() != artifact_sha256.casefold():
            logger.error("[%s] ACTIVE model artifact checksum mismatch: %s", self.camera_id, candidate)
            return None

        return {
            "version_key": version_key,
            "artifact_path": str(candidate),
            "artifact_sha256": artifact_sha256.casefold(),
            "label_map": dict(label_map),
            "runtime_mode": runtime_mode,
        }

    def _apply_detection_control(self, snapshot: ZoneSnapshot) -> None:
        """Apply the synchronizer's complete control snapshot before a frame."""
        active_model = self._resolve_active_model(snapshot.active_model)
        active_fingerprint: Optional[tuple[object, ...]] = None
        if active_model is not None:
            label_map = active_model["label_map"]
            assert isinstance(label_map, dict)
            active_fingerprint = (
                active_model["version_key"],
                active_model["artifact_path"],
                active_model["artifact_sha256"],
                active_model["runtime_mode"],
                tuple(sorted((str(label), str(canonical)) for label, canonical in label_map.items())),
            )
        control_fingerprint: tuple[object, ...] = (
            tuple(sorted(snapshot.coco_classes)),
            tuple(sorted(snapshot.custom_classes)),
            active_fingerprint,
        )
        if control_fingerprint == self._applied_detection_control:
            return
        self.detector.configure_detection_control(
            coco_classes=snapshot.coco_classes,
            custom_classes=snapshot.custom_classes,
            active_model=active_model,
        )
        self._applied_detection_control = control_fingerprint

    async def prepare(self) -> bool:
        """Load and warm detection control before the first feed subscriber."""
        self.clip_service.start()
        if self.rolling_archive is not None:
            self.rolling_archive.start()
        try:
            if not await self.zone_sync.refresh_now():
                logger.warning("[%s] Area prewarm skipped because initial zone sync failed.", self.camera_id)
                return False
            snapshot = self.zone_sync.get_snapshot()
            self._apply_detection_control(snapshot)
            self._applied_detection_snapshot = snapshot
            await self._restore_activity_coverage()
            await asyncio.to_thread(self.detector.warmup, self.resolution)
            logger.info("[%s] Area detector preloaded and warmed before feed activation.", self.camera_id)
            return True
        except Exception as exc:
            logger.warning(
                "[%s] Area detector prewarm failed; base failover remains available: %s",
                self.camera_id,
                exc,
            )
            return False

    def process_single_frame(self) -> Dict[str, Any]:
        """
        Process a single frame synchronously (read -> track -> buffer -> zone check -> encode).
        Used by the main loop, unit tests, and snapshot endpoint.
        """
        success, frame = self.reader.read_frame()
        if not success or frame is None:
            return {"success": False, "detections": [], "transitions": []}

        activity_transitions: List[ActivityTransition] = []
        if self.reader.did_loop:
            # The first frame after a seek/rewind belongs to a new tracking
            # timeline. Never let ByteTrack IDs or temporal confirmation leak
            # across that discontinuity.
            self.detector.reset_tracking()
            ended_previous_timeline = self.activity_tracker.end_all(datetime.now(timezone.utc))
            if not self._activity_replay_read_only:
                activity_transitions.extend(ended_previous_timeline)
            source_kind, _fingerprint, _source_ref, _duration = self._coverage_source()
            if (
                source_kind == "LOCAL_FILE"
                and self.activity_coverage.snapshot().coverage_status == "COMPLETE"
            ):
                # A completed finite source may keep looping for playback, but
                # later loops must never create new persisted activity rows.
                self._activity_replay_read_only = True
            if self.buffer is not None:
                self.buffer.clear()

        # Use one exact snapshot for both inference routing and zone evaluation.
        # A refresh can atomically publish a new object between frames, never
        # half a whitelist/model combination during a frame.
        snapshot = self.zone_sync.get_snapshot()
        if snapshot is not self._applied_detection_snapshot:
            self._apply_detection_control(snapshot)
            self._applied_detection_snapshot = snapshot

        now_sec = time.time()
        now_dt = datetime.now(timezone.utc)

        # 1. Run ByteTrack multi-object tracking
        raw_detections = self.detector.track(frame)

        # 2. Check detections against zones & advance violation state machine
        annotated_detections, transitions = self.zone_checker.check_detections(
            detections=raw_detections,
            zones=snapshot.zones,
            class_to_labels=snapshot.class_to_labels,
            timestamp=now_dt,
            frame_size=(int(frame.shape[1]), int(frame.shape[0])),
        )
        new_activity_transitions = self.activity_tracker.check_detections(
            annotated_detections,
            self._activity_observed_at(),
        )
        violation_starts = {
            (item.track_id, item.zone_id): item.violation_id
            for item in transitions
            if item.action == "STARTED"
        }
        if not self._activity_replay_read_only:
            for item in new_activity_transitions:
                if item.action == "STARTED" and item.policy_result == "VIOLATION":
                    item.violation_id = violation_starts.get((item.track_id, item.zone_id))
                if item.action == "STARTED":
                    # Freeze the source position while processing this frame. The
                    # persistence queue may retry later; reading the player again
                    # there would shift the replay fingerprint and double-count a
                    # local demo video.
                    item.source_metadata = self._activity_source_metadata(item)
            activity_transitions.extend(new_activity_transitions)

        # 5. Encode JPEG frame to base64
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
        ret, buf = cv2.imencode(".jpg", frame, encode_params)
        if not ret:
            return {
                "success": False,
                "detections": annotated_detections,
                "transitions": transitions,
                "activity_transitions": activity_transitions,
            }

        b64_str = f"data:image/jpeg;base64,{base64.b64encode(buf.tobytes()).decode('ascii')}"

        self.frame_count += 1
        self._fps_counter += 1
        elapsed = now_sec - self._last_fps_calc
        if elapsed >= 1.0:
            self.fps_measured = round(self._fps_counter / elapsed, 1)
            self._fps_counter = 0
            self._last_fps_calc = now_sec

        # Snapshot internals are recursively frozen with MappingProxyType and
        # tuples. Never leak those immutable implementation types into the WS
        # DTO: stdlib json rejects MappingProxyType, which previously caused a
        # connect -> serialize failure -> reconnect storm on every frame.
        feed_zones = self._build_feed_zones(snapshot.zones)

        return {
            "success": True,
            "camera_id": self.camera_id,
            "timestamp": int(now_sec * 1000),
            "frame": frame,
            "image_base64": b64_str,
            "detections": annotated_detections,
            "zones": feed_zones,
            "transitions": transitions,
            "activity_transitions": activity_transitions,
            "fps": self.fps_measured or self.target_fps,
            "source_reset": self.reader.did_loop,
        }

    @staticmethod
    def _build_feed_zones(zones: Any) -> List[Dict[str, Any]]:
        """Convert immutable ZoneSnapshot records to JSON-native feed DTOs."""
        output: List[Dict[str, Any]] = []
        for zone in zones:
            raw_polygon = zone.get("polygon") or zone.get("polygon_points") or ()
            polygon: List[Any] = []
            for point in raw_polygon:
                if isinstance(point, Mapping):
                    polygon.append({"x": float(point["x"]), "y": float(point["y"])})
                elif isinstance(point, (list, tuple)) and len(point) >= 2:
                    polygon.append([float(point[0]), float(point[1])])

            raw_targets = zone.get("targetLabels") or zone.get("target_labels") or ()
            output.append({
                "id": str(zone["id"]),
                "name": str(zone.get("name") or "Zone"),
                "polygon": polygon,
                "ruleType": str(zone.get("ruleType") or zone.get("rule_type") or "PROHIBIT_SPECIFIED"),
                "targetLabels": [str(label) for label in raw_targets],
            })
        return output

    def get_playback_state(self) -> Dict[str, Any]:
        return self.reader.get_playback_state()

    async def request_seek(self, position_seconds: float) -> Dict[str, Any]:
        """End the current timeline and seek without racing frame processing."""
        async with self._control_lock:
            for transition in self.zone_checker.end_all(datetime.now(timezone.utc)):
                self._event_queue.enqueue(transition, self._runtime_generation)
            for transition in self.activity_tracker.end_all(datetime.now(timezone.utc)):
                self._activity_queue.enqueue(transition, self._runtime_generation)

            state = self.reader.request_seek(position_seconds)
            if state.get("seekable"):
                self._reset_activity_coverage_source()
                self.detector.reset_tracking()
                if self.buffer is not None:
                    self.buffer.clear()
                self._fps_counter = 0
                self._last_fps_calc = time.time()
                self.fps_measured = self.target_fps
            return state

    async def replace_source(self, source: str) -> bool:
        """Replace the Area reader without reloading the detector or services."""
        candidate = await asyncio.to_thread(
            StreamReader,
            source=source,
            camera_id=self.camera_id,
            target_fps=self.target_fps,
            resolution=self.resolution,
        )
        if not candidate.is_usable_source:
            candidate.release()
            return False

        candidate_context = candidate.get_source_context()
        next_archive = self._build_rolling_archive(candidate_context, candidate.source)
        previous_reader: Optional[Any] = None
        previous_archive: Optional[RollingArchive] = None
        previous_clip_archive: Optional[RollingArchive] = getattr(self.clip_service, "archive", None)
        swapped = False

        try:
            async with self._control_lock:
                now = datetime.now(timezone.utc)
                for transition in self.zone_checker.end_all(now):
                    self._event_queue.enqueue(transition, self._runtime_generation)
                for transition in self.activity_tracker.end_all(now):
                    self._activity_queue.enqueue(transition, self._runtime_generation)
                await self._event_queue.join()
                await self._activity_queue.join()

                self._runtime_generation += 1
                await self._event_queue.reset_generation(self._runtime_generation)
                await self._activity_queue.reset_generation(self._runtime_generation)
                await self.clip_service.reset()
                await self.activity_clip_service.reset()

                previous_archive = self.rolling_archive
                if previous_archive is not None:
                    await previous_archive.stop()

                previous_reader = self.reader
                candidate.mark_source_reset()
                self.reader = candidate
                self.rolling_archive = next_archive
                clip_archive = next_archive or previous_clip_archive
                self.clip_service.archive = clip_archive
                self.activity_clip_service.archive = clip_archive
                swapped = True

                self.zone_checker.clear_runtime_state()
                self.activity_tracker.clear_runtime_state()
                self._activity_persisted_ids.clear()
                self._activity_replay_session_ids.clear()
                self.detector.reset_tracking()
                if self.buffer is not None:
                    self.buffer.clear()
                self._fps_counter = 0
                self._last_fps_calc = time.time()
                self._last_activity_heartbeat = 0.0
                self.fps_measured = self.target_fps
                await self._restore_activity_coverage()

                if next_archive is not None:
                    next_archive.start()

            try:
                previous_reader.release()
            except Exception as exc:
                logger.warning("[%s] Previous source cleanup failed: %s", self.camera_id, exc)
            return True
        except Exception:
            if next_archive is not None:
                await next_archive.stop()
            if swapped and previous_reader is not None:
                async with self._control_lock:
                    self.reader = previous_reader
                    self.rolling_archive = previous_archive
                    self.clip_service.archive = previous_clip_archive
                    self.activity_clip_service.archive = previous_clip_archive
                    if previous_archive is not None:
                        previous_archive.start()
            elif previous_archive is not None and not previous_archive.is_running:
                previous_archive.start()
            candidate.release()
            raise

    async def delete_all_events(self) -> Dict[str, int]:
        """Atomically retire live Area state before deleting its DB history."""
        async with self._control_lock:
            self._runtime_generation += 1
            await self._event_queue.reset_generation(self._runtime_generation)
            await self._activity_queue.reset_generation(self._runtime_generation)
            await self.clip_service.reset()
            await self.activity_clip_service.reset()

            deleted_records = await self.persistence.delete_all(self.camera_id)
            await self.activity_persistence.delete_all(self.camera_id)
            cleared_active, cleared_pending = self.zone_checker.clear_runtime_state()
            cleared_activity_active, cleared_activity_pending = self.activity_tracker.clear_runtime_state()
            self._activity_persisted_ids.clear()
            self._activity_replay_session_ids.clear()
            self.activity_coverage.clear_progress()
            self._activity_replay_read_only = False

            return {
                "deleted_records": int(deleted_records),
                "cleared_active": cleared_active,
                "cleared_pending": cleared_pending,
            }

    async def _touch_activity_coverage(self) -> None:
        try:
            snapshot = self.activity_coverage.snapshot()
            _kind, _fingerprint, source_ref, _duration = self._coverage_source()
            updater = getattr(self.activity_persistence, "update_coverage", None)
            if callable(updater):
                await updater(
                    camera_id=self.camera_id,
                    source_kind=snapshot.source_kind,
                    source_fingerprint=snapshot.source_fingerprint,
                    source_ref=source_ref,
                    source_duration_seconds=snapshot.source_duration_seconds,
                    covered_intervals=[[left, right] for left, right in snapshot.covered_intervals],
                    coverage_percent=snapshot.coverage_percent,
                    coverage_status=snapshot.coverage_status,
                    observed_at=snapshot.last_observed_at or datetime.now(timezone.utc),
                    completed_at=snapshot.completed_at,
                )
            else:
                await self.activity_persistence.touch(
                    self.camera_id,
                    datetime.now(timezone.utc),
                )
        except Exception as exc:
            logger.warning("[%s] Activity collection heartbeat failed: %s", self.camera_id, exc)

    def _activity_observed_at(self, context: Optional[Mapping[str, Any]] = None) -> datetime:
        """Use source time for local analytics so scan speed cannot change sessions."""
        source = dict(context) if context is not None else self._get_source_context()
        if source.get("source_kind") == "LOCAL_FILE":
            try:
                position = max(0.0, float(source.get("source_position_seconds") or 0.0))
                local_now = datetime.now(APP_TIME_ZONE)
                local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
                return local_midnight.astimezone(timezone.utc) + timedelta(seconds=position)
            except (TypeError, ValueError):
                pass
        timestamp = source.get("source_timestamp")
        return timestamp if isinstance(timestamp, datetime) else datetime.now(timezone.utc)

    def _activity_source_metadata(self, transition: ActivityTransition) -> Dict[str, Any]:
        context = self._get_source_context()
        source_kind = str(context.get("source_kind") or "UNAVAILABLE")
        source_ref = context.get("source_ref")
        position = context.get("source_position_seconds")
        source_timestamp = context.get("source_timestamp")
        fingerprint: Optional[str] = None

        if source_kind == "LOCAL_FILE":
            current_position = float(position or 0.0)
            confirmation_delay = max(
                0.0,
                (self._activity_observed_at(context) - transition.entered_at).total_seconds(),
            )
            position = max(0.0, current_position - confirmation_delay)
            source_identity = str(source_ref or self.camera_id)
            if isinstance(source_ref, str):
                try:
                    stat = os.stat(source_ref)
                    source_identity = f"{os.path.abspath(source_ref)}:{stat.st_size}:{stat.st_mtime_ns}"
                except OSError:
                    source_identity = os.path.abspath(source_ref)
            width, height = self.resolution
            payload = {
                "version": 2,
                "camera": self.camera_id,
                "source": source_identity,
                "zone": transition.zone_id,
                "class": transition.canonical_class,
                # A one-second time bucket and 32px entry grid absorb normal
                # frame/tracker jitter across replays while still separating
                # distinct entries by time and location.
                "timeBucket": round(float(position)),
                "entryGrid": [
                    round(transition.entry_point[0] * width / 32.0),
                    round(transition.entry_point[1] * height / 32.0),
                ],
            }
            fingerprint = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            source_timestamp = None
        elif source_kind == "LIVE":
            position = None
            source_timestamp = transition.entered_at
        else:
            source_kind = "UNAVAILABLE"
            position = None
            source_timestamp = None

        return {
            "source_kind": source_kind,
            "source_ref": source_ref,
            "source_position_seconds": position,
            "source_timestamp": source_timestamp,
            "event_fingerprint": fingerprint,
        }

    async def _process_activity_transition_once(
        self,
        transition: ActivityTransition,
        generation: int,
    ) -> None:
        if generation != self._runtime_generation:
            return
        try:
            if transition.action == "STARTED":
                source = dict(
                    transition.source_metadata
                    or self._activity_source_metadata(transition)
                )
                created = await self.activity_persistence.create(
                    session_id=transition.session_id,
                    camera_id=self.camera_id,
                    zone_id=transition.zone_id,
                    zone_name=transition.zone_name,
                    object_label=transition.object_label,
                    canonical_class=transition.canonical_class,
                    policy_result=transition.policy_result,
                    entered_at=transition.entered_at,
                    last_seen_at=transition.last_seen_at,
                    track_id=transition.track_id,
                    entry_point={"x": transition.entry_point[0], "y": transition.entry_point[1]},
                    violation_id=transition.violation_id,
                    **source,
                )
                if created is None:
                    raise RuntimeError("Area activity session was not persisted")
                self._last_activity_persistence_error = None
                if created.get("was_inserted", True):
                    self._activity_persisted_ids[transition.session_id] = str(created["id"])
                else:
                    # The same local-video moment was already counted. Keep
                    # the historical row fully immutable during this replay,
                    # including its exit timestamp and observed duration.
                    self._activity_replay_session_ids.add(transition.session_id)
            elif transition.action == "ENDED":
                if transition.session_id in self._activity_replay_session_ids:
                    self._activity_replay_session_ids.discard(transition.session_id)
                    return
                persisted_id = self._activity_persisted_ids.pop(
                    transition.session_id,
                    transition.session_id,
                )
                await self.activity_persistence.close(
                    session_id=persisted_id,
                    exited_at=transition.exited_at or transition.last_seen_at,
                    duration_seconds=transition.duration_seconds or 0,
                )
                self._last_activity_persistence_error = None
        except Exception as exc:
            raise RetryableAreaTransitionError(
                f"Failed to persist activity {transition.session_id}: {exc}"
            ) from exc

    async def _handle_exhausted_activity_transition(
        self,
        transition: ActivityTransition,
        generation: int,
        error: BaseException,
    ) -> None:
        self._last_activity_persistence_error = str(error)
        logger.error(
            "[%s] Activity persistence exhausted for %s %s at generation %s: %s",
            self.camera_id,
            transition.action,
            transition.session_id,
            generation,
            error,
        )

    async def _process_transition_once(
        self,
        t: ViolationTransition,
        generation: int,
    ) -> None:
        """Attempt persistence once; the queue owns retry timing."""
        if generation != self._runtime_generation:
            return
        if t.action == "STARTED":
            # 1. DB persistence: insert OPEN violation
            try:
                source_context = self._get_source_context()
                if source_context.get("source_kind") == "LOCAL_FILE":
                    current_position = float(source_context.get("source_position_seconds") or 0.0)
                    confirmation_delay = max(
                        0.0,
                        (datetime.now(timezone.utc) - t.entered_at).total_seconds(),
                    )
                    source_context["source_position_seconds"] = max(
                        0.0,
                        current_position - confirmation_delay,
                    )
                elif source_context.get("source_kind") == "LIVE":
                    source_context["source_timestamp"] = t.entered_at
                created = await self.persistence.create(
                    camera_id=self.camera_id,
                    zone_id=t.zone_id,
                    object_label=t.object_label,
                    entered_at=t.entered_at,
                    clip_path=None,
                    source_kind=source_context.get("source_kind"),
                    source_ref=source_context.get("source_ref"),
                    source_position_seconds=source_context.get("source_position_seconds"),
                    source_timestamp=source_context.get("source_timestamp"),
                    violation_id=t.violation_id,
                )
                if created is None:
                    raise RuntimeError("Zone violation was not persisted")
            except Exception as exc:
                raise RetryableAreaTransitionError(
                    f"Failed to persist OPEN violation {t.violation_id}: {exc}"
                ) from exc

            logger.info(
                "[%s] VIOLATION STARTED: %s in %s (ID: %s)",
                self.camera_id,
                t.object_label,
                t.zone_name,
                t.violation_id,
            )

            # 2. Emit real-time Area event notification. Event-specific MP4
            # generation begins only after an explicit user request.
            iso_entered = t.entered_at.isoformat().replace("+00:00", "Z")
            await self._safe_emit_area_event({
                "action": "STARTED",
                "id": t.violation_id,
                "cameraId": self.camera_id,
                "zoneId": t.zone_id,
                "zoneName": t.zone_name,
                "objectLabel": t.object_label,
                "status": "OPEN",
                "enteredAt": iso_entered,
                "exitedAt": None,
                "durationSeconds": None,
                "clipUrl": None,
                "clipStatus": "NOT_REQUESTED",
            })

            # 3. Emit urgent cross-tab alert (BR-08)
            await self._safe_emit_alert({
                "level": "critical",
                "title": "CẢNH BÁO VI PHẠM ZONE",
                "message": f"Phát hiện {t.object_label} trong {t.zone_name}",
                "cameraId": self.camera_id,
                "timestamp": iso_entered,
                "data": {
                    "violationId": t.violation_id,
                    "zoneId": t.zone_id,
                    "zoneName": t.zone_name,
                    "objectLabel": t.object_label,
                },
            })

        elif t.action == "ENDED":
            # 1. DB persistence: close violation
            try:
                closed = await self.persistence.close(
                    violation_id=t.violation_id,
                    exited_at=t.exited_at,
                    duration_seconds=t.duration_seconds,
                )
            except Exception as exc:
                raise RetryableAreaTransitionError(
                    f"Failed to close violation {t.violation_id}: {exc}"
                ) from exc

            if closed is None:
                logger.warning(
                    "[%s] Violation %s was already deleted; retiring local close.",
                    self.camera_id,
                    t.violation_id,
                )
                return

            logger.info(
                "[%s] VIOLATION ENDED: %s in %s (ID: %s, duration: %ss)",
                self.camera_id,
                t.object_label,
                t.zone_name,
                t.violation_id,
                t.duration_seconds,
            )

            # 2. Emit real-time Area event notification
            iso_entered = t.entered_at.isoformat().replace("+00:00", "Z")
            iso_exited = t.exited_at.isoformat().replace("+00:00", "Z") if t.exited_at else None
            await self._safe_emit_area_event({
                "action": "ENDED",
                "id": t.violation_id,
                "cameraId": self.camera_id,
                "zoneId": t.zone_id,
                "zoneName": t.zone_name,
                "objectLabel": t.object_label,
                "status": "CLOSED",
                "enteredAt": iso_entered,
                "exitedAt": iso_exited,
                "durationSeconds": t.duration_seconds,
                "clipUrl": None,
                "clipStatus": "NOT_REQUESTED",
            })

    async def _safe_emit_area_event(self, payload: Dict[str, Any]) -> None:
        try:
            await self.emitter.emit_area_event(payload)
        except Exception as exc:
            logger.warning(
                "[%s] Persisted Area event %s but realtime emission failed: %s",
                self.camera_id,
                payload.get("id"),
                exc,
            )

    async def _safe_emit_alert(self, payload: Dict[str, Any]) -> None:
        try:
            await self.emitter.emit_alert(payload)
        except Exception as exc:
            logger.warning(
                "[%s] Persisted Area alert for %s but realtime emission failed: %s",
                self.camera_id,
                payload.get("data", {}).get("violationId"),
                exc,
            )

    async def _handle_exhausted_transition(
        self,
        transition: ViolationTransition,
        generation: int,
        error: BaseException,
    ) -> None:
        logger.error(
            "[%s] Area event persistence exhausted for %s %s after bounded retries: %s",
            self.camera_id,
            transition.action,
            transition.violation_id,
            error,
        )
        if generation == self._runtime_generation and transition.action == "STARTED":
            self.zone_checker.discard_started_transition(transition)

    async def _loop(self) -> None:
        """Asynchronous processing and emission loop."""
        logger.info("[%s] Area camera pipeline started (target: %.1f FPS).", self.camera_id, self.target_fps)
        # Startup preparation already loaded the first complete snapshot. Keep
        # this fallback for tests/deployments which construct and start the
        # pipeline without calling prepare().
        if self._applied_detection_snapshot is None:
            try:
                await self.zone_sync.refresh_now()
            except Exception as exc:
                logger.warning("[%s] Initial zone sync failed: %s", self.camera_id, exc)

        interval = 1.0 / self.target_fps

        while self._running:
            if not self._active:
                await asyncio.sleep(0.2)
                continue

            start_t = time.time()
            try:
                async with self._control_lock:
                    result = await asyncio.to_thread(self.process_single_frame)

                await self.publish_result(result)
                if not self._viewer_active and self.background_frame_stride > 1:
                    skipper = getattr(self.reader, "skip_local_frames", None)
                    if callable(skipper):
                        skipper(self.background_frame_stride - 1)

            except Exception as exc:
                logger.error("[%s] Error in Area pipeline loop: %s", self.camera_id, exc)

            elapsed = time.time() - start_t
            sleep_time = max(0.001, interval - elapsed)
            await asyncio.sleep(sleep_time)

        logger.info("[%s] Area camera pipeline loop ended.", self.camera_id)

    async def publish_result(self, result: Mapping[str, Any]) -> None:
        """Run the production feed/event output path for one processed frame."""
        if not result.get("success"):
            return
        self._observe_activity_coverage()
        if self._viewer_active:
            await self.emitter.emit_frame(
                camera_id=self.camera_id,
                image_base64=str(result["image_base64"]),
                detections=result["detections"],
                fps=float(result["fps"]),
                zones=result["zones"],
                source_reset=bool(result.get("source_reset", False)),
            )
        for transition in result.get("transitions", []):
            queued = self._event_queue.enqueue(
                transition,
                self._runtime_generation,
            )
            if not queued:
                await self._handle_exhausted_transition(
                    transition,
                    self._runtime_generation,
                    RuntimeError("Area event queue rejected transition"),
                )
        for transition in result.get("activity_transitions", []):
            if not self._activity_queue.enqueue(transition, self._runtime_generation):
                await self._handle_exhausted_activity_transition(
                    transition,
                    self._runtime_generation,
                    RuntimeError("Activity event queue rejected transition"),
                )
        now = time.monotonic()
        if now - self._last_activity_heartbeat >= 10.0:
            self._last_activity_heartbeat = now
            if self._activity_heartbeat_task is None or self._activity_heartbeat_task.done():
                self._activity_heartbeat_task = asyncio.create_task(
                    self._touch_activity_coverage()
                )

    def start(self) -> None:
        """Start the area pipeline background tasks."""
        self._active = True
        self._fps_counter = 0
        self._last_fps_calc = time.time()
        self.fps_measured = self.target_fps
        if self._running:
            return
        self._running = True
        self._event_queue.start()
        self._activity_queue.start()
        self.clip_service.start()
        self.activity_clip_service.start()
        if self.rolling_archive is not None:
            self.rolling_archive.start()
        self.zone_sync.start()
        self._task = asyncio.create_task(self._loop())

    def set_viewer_active(self, active: bool) -> None:
        """Control rendered frame emission without pausing activity analytics."""
        self._viewer_active = bool(active)

    def pause(self) -> None:
        """Suspend frame processing while retaining the warm model and camera resources."""
        self._active = False
    async def stop(self) -> None:
        """Stop background tasks and release resources cleanly."""
        self._running = False
        self._active = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None

        await self.zone_sync.stop()
        for transition in self.activity_tracker.end_all(datetime.now(timezone.utc)):
            self._activity_queue.enqueue(transition, self._runtime_generation)
        await self._activity_queue.join()
        await self._event_queue.stop()
        await self._activity_queue.stop()
        if self._activity_heartbeat_task is not None:
            try:
                await self._activity_heartbeat_task
            except Exception as exc:
                logger.warning("[%s] Activity heartbeat failed during shutdown: %s", self.camera_id, exc)
            self._activity_heartbeat_task = None
        await self.clip_service.stop()
        await self.activity_clip_service.stop()
        if self.rolling_archive is not None:
            await self.rolling_archive.stop()

        self.reader.release()
        await self.emitter.close()
        logger.info("[%s] Area pipeline stopped cleanly.", self.camera_id)

    def is_running(self) -> bool:
        return self._running

    def get_stats(self) -> Dict[str, Any]:
        """Return operational stats for this camera stream."""
        return {
            "camera_id": self.camera_id,
            "running": self._running,
            "active": self._active,
            "viewer_active": self._viewer_active,
            "activity_coverage": self.activity_coverage.snapshot().coverage_status,
            "frame_count": self.frame_count,
            "fps": self.fps_measured,
            "buffered_frames": self.buffer.get_frame_count() if self.buffer is not None else 0,
            "rolling_archive": self.rolling_archive.status() if self.rolling_archive is not None else None,
            "active_violations": len(self.zone_checker.active_violations),
            "active_activity_sessions": len(self.activity_tracker.active_sessions),
            "pending_activity_sessions": len(self.activity_tracker.pending_sessions),
            "activity_replay_read_only": self._activity_replay_read_only,
            "activity_queue": self._activity_queue.get_stats(),
            "last_activity_persistence_error": self._last_activity_persistence_error,
        }
