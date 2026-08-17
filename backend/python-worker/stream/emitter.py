"""
stream.emitter — Real-Time WebSocket Emitter to Node.js WebSocket Proxy

Publishes video frames with bounding box overlays and detection events to Node.js WS Proxy.
Handles reconnection and graceful degradation if Node.js server is temporarily offline.
"""
import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import websockets
from websockets.protocol import State

logger = logging.getLogger("sentriai.stream.emitter")


class StreamEmitter:
    def __init__(self, node_ws_url: Optional[str] = None):
        self.node_ws_url = node_ws_url or os.getenv("NODE_WS_URL") or "ws://localhost:3001"
        self._connections: Dict[str, Optional[Any]] = {}
        self._lock = asyncio.Lock()
        self._is_stopped = False

    def _is_connected(self, conn: Optional[Any]) -> bool:
        """Check if WebSocket connection is open."""
        if conn is None:
            return False
        state = getattr(conn, "state", None)
        if state is not None:
            return state == State.OPEN or getattr(state, "name", "") == "OPEN"
        return False

    async def get_connection(self, path: str) -> Optional[Any]:
        """Obtain or reconnect WebSocket connection for a given publish path."""
        if self._is_stopped:
            return None

        async with self._lock:
            conn = self._connections.get(path)
            if self._is_connected(conn):
                return conn

            full_url = f"{self.node_ws_url}{path}"
            try:
                # Short timeout to avoid blocking frame pipeline if Node.js is offline
                conn = await asyncio.wait_for(websockets.connect(full_url), timeout=1.5)
                self._connections[path] = conn
                logger.info("Connected publisher WebSocket to %s", full_url)
                return conn
            except Exception as exc:
                # Node.js API might be starting or offline
                logger.debug("Could not connect publisher to %s (%s)", full_url, exc)
                self._connections[path] = None
                return None

    async def emit_frame(
        self,
        camera_id: str,
        image_base64: str,
        detections: List[Dict[str, Any]],
        fps: float = 10.0,
    ) -> bool:
        """
        Send a video frame with bounding box detections to Node.js feed channel.
        """
        path = f"/ws/publish/feed/{camera_id}"
        payload = {
            "type": "frame",
            "cameraId": camera_id,
            "timestamp": int(time.time() * 1000),
            "image": image_base64,
            "fps": round(fps, 1),
            "detections": detections,
        }
        return await self._send_json(path, payload)

    async def emit_gate_event(self, event_data: Dict[str, Any]) -> bool:
        """Publish a gate event notification to Node.js proxy."""
        path = "/ws/publish/events/gate"
        payload = {
            "type": "gate_event",
            **event_data,
        }
        return await self._send_json(path, payload)

    async def emit_area_event(self, event_data: Dict[str, Any]) -> bool:
        """Publish a zone violation notification to Node.js proxy."""
        path = "/ws/publish/events/area"
        payload = {
            "type": "zone_violation",
            **event_data,
        }
        return await self._send_json(path, payload)

    async def _send_json(self, path: str, payload: Dict[str, Any]) -> bool:
        """Send JSON payload over WebSocket connection."""
        conn = await self.get_connection(path)
        if not self._is_connected(conn):
            return False

        try:
            raw = json.dumps(payload)
            await conn.send(raw)
            return True
        except Exception as exc:
            logger.debug("Failed to send WS message on %s: %s", path, exc)
            self._connections[path] = None
            return False

    async def close(self) -> None:
        """Close all active publisher sockets."""
        self._is_stopped = True
        async with self._lock:
            for path, conn in list(self._connections.items()):
                if conn is not None:
                    try:
                        await conn.close()
                    except Exception:
                        pass
            self._connections.clear()
        logger.info("StreamEmitter closed.")
