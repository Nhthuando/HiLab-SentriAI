"""
detection.area_pipeline — Camera BAI-KIEM Area AI Pipeline

Coordinates:
1. StreamReader (video source or synthetic frames)
2. TrackedYoloDetector (ByteTrack multi-object tracking)
3. ZoneSynchronizer (5-second atomic DB sync)
4. ZoneChecker (polygon containment, rule matrix, violation state machine)
5. CircularBuffer (10s MP4 clip generation)
6. StreamEmitter (WebSocket frame, event, and alert emission)
7. DB persistence (zone_violations OPEN/CLOSED and clip_path updates)
"""
import asyncio
import base64
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import cv2

from buffer.circular_buffer import CircularBuffer
from db.repositories import (
    close_zone_violation,
    create_zone_violation,
    update_violation_clip_path,
)
from detection.tracked_detector import TrackedYoloDetector
from stream.emitter import StreamEmitter
from stream.reader import StreamReader
from zone.zone_checker import ViolationTransition, ZoneChecker
from zone.zone_sync import ZoneSynchronizer

logger = logging.getLogger("sentriai.area.pipeline")


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
    ):
        self.camera_id = camera_id
        self.target_fps = target_fps
        self.resolution = resolution
        self.jpeg_quality = jpeg_quality

        backend_dir = Path(__file__).resolve().parents[2]

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

        self.reader = StreamReader(
            source=source,
            camera_id=camera_id,
            target_fps=target_fps,
            resolution=resolution,
        )
        self.detector = detector or TrackedYoloDetector()
        self.buffer = CircularBuffer(max_seconds=15.0, target_fps=target_fps)
        self.emitter = emitter or StreamEmitter()
        self.zone_sync = zone_sync or ZoneSynchronizer(camera_id=camera_id, sync_interval=5.0)
        self.zone_checker = zone_checker or ZoneChecker(
            camera_id=camera_id,
            grace_frames=3,
            missing_grace_seconds=12.0,
        )

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._clip_tasks: Set[asyncio.Task] = set()
        self.frame_count = 0
        self.fps_measured = 0.0
        self._last_fps_calc = time.time()
        self._fps_counter = 0

    def process_single_frame(self) -> Dict[str, Any]:
        """
        Process a single frame synchronously (read -> track -> buffer -> zone check -> encode).
        Used by the main loop, unit tests, and snapshot endpoint.
        """
        success, frame = self.reader.read_frame()
        if not success or frame is None:
            return {"success": False, "detections": [], "transitions": []}

        now_sec = time.time()
        now_dt = datetime.now(timezone.utc)

        # 1. Run ByteTrack multi-object tracking
        raw_detections = self.detector.track(frame)

        # 2. Store in circular buffer for 10-second clip generation
        self.buffer.append(frame, now_sec)

        # 3. Get latest zone & label snapshot
        snapshot = self.zone_sync.get_snapshot()

        # 4. Check detections against zones & advance violation state machine
        annotated_detections, transitions = self.zone_checker.check_detections(
            detections=raw_detections,
            zones=snapshot.zones,
            class_to_labels=snapshot.class_to_labels,
            timestamp=now_dt,
        )

        # 5. Encode JPEG frame to base64
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
        ret, buf = cv2.imencode(".jpg", frame, encode_params)
        if not ret:
            return {
                "success": False,
                "detections": annotated_detections,
                "transitions": transitions,
            }

        b64_str = f"data:image/jpeg;base64,{base64.b64encode(buf.tobytes()).decode('ascii')}"

        self.frame_count += 1
        self._fps_counter += 1
        elapsed = now_sec - self._last_fps_calc
        if elapsed >= 1.0:
            self.fps_measured = round(self._fps_counter / elapsed, 1)
            self._fps_counter = 0
            self._last_fps_calc = now_sec

        # Format zones for WS feed output matching AreaZoneFeedDto
        feed_zones = []
        for z in snapshot.zones:
            feed_zones.append({
                "id": z["id"],
                "name": z["name"],
                "polygon": z.get("polygon") or z.get("polygon_points") or [],
                "ruleType": z.get("ruleType") or z.get("rule_type") or "PROHIBIT_SPECIFIED",
                "targetLabels": z.get("targetLabels") or z.get("target_labels") or [],
            })

        return {
            "success": True,
            "camera_id": self.camera_id,
            "timestamp": int(now_sec * 1000),
            "frame": frame,
            "image_base64": b64_str,
            "detections": annotated_detections,
            "zones": feed_zones,
            "transitions": transitions,
            "fps": self.fps_measured or self.target_fps,
            "source_reset": self.reader.did_loop,
        }

    async def _handle_transition(self, t: ViolationTransition) -> None:
        """Handle violation state machine transitions (DB persistence + WS emission + clip)."""
        if t.action == "STARTED":
            logger.info(
                "[%s] VIOLATION STARTED: %s in %s (ID: %s)",
                self.camera_id,
                t.object_label,
                t.zone_name,
                t.violation_id,
            )

            # 1. DB persistence: insert OPEN violation
            try:
                created = await create_zone_violation(
                    camera_id=self.camera_id,
                    zone_id=t.zone_id,
                    object_label=t.object_label,
                    entered_at=t.entered_at,
                    clip_path=None,
                    violation_id=t.violation_id,
                )
                if created is None:
                    raise RuntimeError("Zone violation was not persisted")
            except Exception as exc:
                logger.error("[%s] Failed to persist OPEN violation to DB: %s", self.camera_id, exc)
                self.zone_checker.discard_started_transition(t)
                return

            # 2. Schedule 10-second circular buffer clip job
            entered_sec = t.entered_at.timestamp()
            clip_task = asyncio.create_task(
                self._save_clip_job(t.violation_id, entered_sec)
            )
            self._clip_tasks.add(clip_task)
            clip_task.add_done_callback(self._clip_tasks.discard)

            # 3. Emit real-time Area event notification
            iso_entered = t.entered_at.isoformat().replace("+00:00", "Z")
            await self.emitter.emit_area_event({
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
            })

            # 4. Emit urgent cross-tab alert (BR-08)
            await self.emitter.emit_alert({
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
            logger.info(
                "[%s] VIOLATION ENDED: %s in %s (ID: %s, duration: %ss)",
                self.camera_id,
                t.object_label,
                t.zone_name,
                t.violation_id,
                t.duration_seconds,
            )

            # 1. DB persistence: close violation
            try:
                closed = await close_zone_violation(
                    violation_id=t.violation_id,
                    exited_at=t.exited_at,
                    duration_seconds=t.duration_seconds,
                )
                if closed is None:
                    raise RuntimeError("Zone violation was not closed")
            except Exception as exc:
                logger.error("[%s] Failed to close violation in DB: %s", self.camera_id, exc)
                self.zone_checker.restore_ended_transition(t)
                return

            # 2. Emit real-time Area event notification
            iso_entered = t.entered_at.isoformat().replace("+00:00", "Z")
            iso_exited = t.exited_at.isoformat().replace("+00:00", "Z") if t.exited_at else None
            await self.emitter.emit_area_event({
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
            })

    async def _save_clip_job(self, violation_id: str, entered_sec: float) -> None:
        """
        Background worker that waits until entered_sec + 10s has passed,
        extracts the 10-second MP4 clip from circular buffer, writes to disk,
        and updates DB clip_path (BR-05).
        """
        target_end_time = entered_sec + 10.0
        now = time.time()
        wait_seconds = max(0.1, target_end_time - now)
        try:
            await asyncio.sleep(wait_seconds)
        except asyncio.CancelledError:
            return

        filename = f"area_{violation_id}.mp4"
        file_path = str(self.clips_dir / filename)

        try:
            # Save 10s clip up to target_end_time
            saved_path = await asyncio.to_thread(
                self.buffer.save_clip,
                output_path=file_path,
                duration_seconds=10.0,
                end_time=target_end_time,
            )

            if saved_path and os.path.isfile(saved_path):
                logger.info("[%s] Saved violation clip: %s", self.camera_id, filename)
                # Store relative filename area_<id>.mp4 in DB
                await update_violation_clip_path(violation_id, filename)
            else:
                logger.warning("[%s] Clip save produced no file for violation %s", self.camera_id, violation_id)
        except Exception as exc:
            logger.warning("[%s] Failed to write violation clip (%s). clip_path remains NULL.", self.camera_id, exc)

    async def _loop(self) -> None:
        """Asynchronous processing and emission loop."""
        logger.info("[%s] Area camera pipeline started (target: %.1f FPS).", self.camera_id, self.target_fps)
        # Immediate initial sync so first frames have DB labels
        try:
            await self.zone_sync.refresh_now()
        except Exception as exc:
            logger.warning("[%s] Initial zone sync failed: %s", self.camera_id, exc)

        interval = 1.0 / self.target_fps

        while self._running:
            start_t = time.time()
            try:
                result = await asyncio.to_thread(self.process_single_frame)

                if result["success"]:
                    # 1. Emit live video frame with detection and zone overlays
                    await self.emitter.emit_frame(
                        camera_id=self.camera_id,
                        image_base64=result["image_base64"],
                        detections=result["detections"],
                        fps=result["fps"],
                        zones=result["zones"],
                        source_reset=result.get("source_reset", False),
                    )

                    # 2. Handle state machine transitions (STARTED / ENDED)
                    for trans in result.get("transitions", []):
                        await self._handle_transition(trans)

            except Exception as exc:
                logger.error("[%s] Error in Area pipeline loop: %s", self.camera_id, exc)

            elapsed = time.time() - start_t
            sleep_time = max(0.001, interval - elapsed)
            await asyncio.sleep(sleep_time)

        logger.info("[%s] Area camera pipeline loop ended.", self.camera_id)

    def start(self) -> None:
        """Start the area pipeline background tasks."""
        if self._running:
            return
        self._running = True
        self.zone_sync.start()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop background tasks and release resources cleanly."""
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None

        await self.zone_sync.stop()

        # Cancel any pending clip tasks
        for ct in list(self._clip_tasks):
            ct.cancel()
        self._clip_tasks.clear()

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
            "frame_count": self.frame_count,
            "fps": self.fps_measured,
            "buffered_frames": self.buffer.get_frame_count(),
            "active_violations": len(self.zone_checker.active_violations),
        }
