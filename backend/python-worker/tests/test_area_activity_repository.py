"""Contract tests for lightweight Area activity persistence helpers."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

WORKER_DIR = Path(__file__).resolve().parent.parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from db.repositories import (
    close_area_activity_session,
    create_area_activity_session,
    touch_area_activity_collection,
)


class RecordingExecutor:
    def __init__(self) -> None:
        self.query = ""
        self.args = ()

    async def fetchrow(self, query, *args):
        self.query = query
        self.args = args
        return {"id": args[0], "camera_id": args[1] if len(args) > 1 else "BAI-KIEM"}


class TestAreaActivityRepository(unittest.IsolatedAsyncioTestCase):
    async def test_local_insert_is_idempotent_by_fingerprint(self):
        executor = RecordingExecutor()
        entered = datetime(2026, 8, 27, tzinfo=timezone.utc)
        result = await create_area_activity_session(
            session_id="11111111-1111-4111-8111-111111111111",
            camera_id="BAI-KIEM",
            zone_id="22222222-2222-4222-8222-222222222222",
            zone_name="Khu nâng hạ",
            object_label="Xe nâng",
            canonical_class="forklift",
            policy_result="ALLOWED",
            entered_at=entered,
            last_seen_at=entered,
            track_id=8,
            entry_point={"x": 0.42, "y": 0.73},
            source_kind="LOCAL_FILE",
            source_ref="sample.mp4",
            source_position_seconds=84.2,
            source_timestamp=None,
            event_fingerprint="a" * 64,
            conn_or_pool=executor,
        )
        self.assertEqual(str(result["id"]), "11111111-1111-4111-8111-111111111111")
        self.assertIn("ON CONFLICT (event_fingerprint)", executor.query)
        self.assertIn("WHERE event_fingerprint IS NOT NULL", executor.query)

    async def test_close_uses_last_seen_and_non_negative_duration(self):
        executor = RecordingExecutor()
        exited = datetime(2026, 8, 27, tzinfo=timezone.utc) + timedelta(seconds=9)
        await close_area_activity_session(
            "11111111-1111-4111-8111-111111111111",
            exited,
            -3,
            conn_or_pool=executor,
        )
        self.assertIn("GREATEST(0, $3)", executor.query)
        self.assertEqual(executor.args[2], -3)

    async def test_collection_heartbeat_preserves_started_at(self):
        executor = RecordingExecutor()
        await touch_area_activity_collection(
            "BAI-KIEM",
            datetime(2026, 8, 27, tzinfo=timezone.utc),
            conn_or_pool=executor,
        )
        self.assertIn("ON CONFLICT (camera_id) DO UPDATE", executor.query)
        self.assertNotIn("started_at =", executor.query)
        self.assertIn("INTERVAL '60 seconds'", executor.query)


if __name__ == "__main__":
    unittest.main()
