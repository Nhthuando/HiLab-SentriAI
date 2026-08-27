"""Regression tests for persistent Python-to-Node publisher sockets."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest.mock import AsyncMock, patch

from websockets.protocol import State

WORKER_DIR = Path(__file__).resolve().parent.parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from stream.emitter import StreamEmitter


class StreamEmitterTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_one_open_publisher_connection_across_frames(self) -> None:
        connection = AsyncMock()
        connection.state = State.OPEN
        emitter = StreamEmitter("ws://node.test")

        with patch("stream.emitter.websockets.connect", AsyncMock(return_value=connection)) as connect:
            first = await emitter.emit_frame("BAI-KIEM", "data:image/jpeg;base64,AA==", [])
            second = await emitter.emit_frame("BAI-KIEM", "data:image/jpeg;base64,AA==", [])

        self.assertTrue(first)
        self.assertTrue(second)
        connect.assert_awaited_once()
        self.assertEqual(connection.send.await_count, 2)

    async def test_non_json_payload_fails_before_opening_connection(self) -> None:
        emitter = StreamEmitter("ws://node.test")
        with patch.object(emitter, "get_connection", AsyncMock()) as get_connection:
            sent = await emitter._send_json("/ws/publish/feed/BAI-KIEM", {
                "zone": MappingProxyType({"id": "zone-1"}),
            })

        self.assertFalse(sent)
        get_connection.assert_not_awaited()


if __name__ == "__main__":
    unittest.main(verbosity=2)
