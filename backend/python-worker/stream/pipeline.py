"""
stream.pipeline — Real-Time Camera AI Inference Pipeline

Coordinates StreamReader, YoloDetector, CircularBuffer, and StreamEmitter
in an asynchronous real-time processing loop per camera stream.
"""
import asyncio
import base64
import logging
import time
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

from buffer.circular_buffer import CircularBuffer
from detection.detector import YoloDetector
from stream.emitter import StreamEmitter
from stream.reader import StreamReader

logger = logging.getLogger("sentriai.stream.pipeline")


class CameraPipeline:
    def __init__(
        self,
        camera_id: str,
        source: Optional[str] = None,
        target_fps: float = 10.0,
        resolution: Tuple[int, int] = (640, 480),
        jpeg_quality: int = 70,
        emitter: Optional[StreamEmitter] = None,
        detector: Optional[YoloDetector] = None,
    ):
        self.camera_id = camera_id
        self.target_fps = target_fps
        self.resolution = resolution
        self.jpeg_quality = jpeg_quality

        self.reader = StreamReader(
            source=source,
            camera_id=camera_id,
            target_fps=target_fps,
            resolution=resolution,
        )
        self.detector = detector or YoloDetector()
        self.buffer = CircularBuffer(max_seconds=12.0, target_fps=target_fps)
        self.emitter = emitter or StreamEmitter()

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.frame_count = 0
        self.fps_measured = 0.0
        self._last_fps_calc = time.time()
        self._fps_counter = 0

    def process_single_frame(self) -> Dict[str, Any]:
        """
        Process a single frame synchronously (read -> detect -> buffer -> encode).
        Useful for unit tests and snapshot generation.
        """
        success, frame = self.reader.read_frame()
        if not success or frame is None:
            return {"success": False, "detections": []}

        now = time.time()
        # 1. Run YOLO object detection
        detections = self.detector.detect(frame)

        # 2. Store in circular buffer (for 10s clip generation)
        self.buffer.append(frame, now)

        # 3. Encode JPEG frame to base64
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
        ret, buf = cv2.imencode(".jpg", frame, encode_params)
        if not ret:
            return {"success": False, "detections": detections}

        b64_str = f"data:image/jpeg;base64,{base64.b64encode(buf.tobytes()).decode('ascii')}"

        self.frame_count += 1
        self._fps_counter += 1
        elapsed = now - self._last_fps_calc
        if elapsed >= 1.0:
            self.fps_measured = round(self._fps_counter / elapsed, 1)
            self._fps_counter = 0
            self._last_fps_calc = now

        return {
            "success": True,
            "camera_id": self.camera_id,
            "timestamp": int(now * 1000),
            "frame": frame,
            "image_base64": b64_str,
            "detections": detections,
            "fps": self.fps_measured or self.target_fps,
        }

    async def _loop(self) -> None:
        """Asynchronous processing and emission loop."""
        logger.info("[%s] Camera pipeline started (target: %.1f FPS).", self.camera_id, self.target_fps)
        interval = 1.0 / self.target_fps

        while self._running:
            start_t = time.time()
            try:
                # Run frame processing in executor if heavy, or directly
                result = await asyncio.to_thread(self.process_single_frame)

                if result["success"]:
                    # Emit frame packet to Node.js proxy via WebSocket
                    await self.emitter.emit_frame(
                        camera_id=self.camera_id,
                        image_base64=result["image_base64"],
                        detections=result["detections"],
                        fps=result["fps"],
                    )
            except Exception as exc:
                logger.error("[%s] Error in camera pipeline loop: %s", self.camera_id, exc)

            elapsed = time.time() - start_t
            sleep_time = max(0.001, interval - elapsed)
            await asyncio.sleep(sleep_time)

        logger.info("[%s] Camera pipeline loop ended.", self.camera_id)

    def start(self) -> None:
        """Start the background pipeline task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop the background pipeline task and release resources."""
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None

        self.reader.release()
        await self.emitter.close()
        logger.info("[%s] Camera pipeline stopped cleanly.", self.camera_id)

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
        }
