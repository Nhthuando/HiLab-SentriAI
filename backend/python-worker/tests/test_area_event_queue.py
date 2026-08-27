"""Deterministic tests for Area transition background persistence."""
from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

WORKER_DIR = Path(__file__).resolve().parent.parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from detection.area_event_queue import AreaEventQueue, RetryableAreaTransitionError
from zone.zone_checker import ViolationTransition


def transition(violation_id: str) -> ViolationTransition:
    entered_at = datetime(2026, 8, 25, tzinfo=timezone.utc)
    return ViolationTransition(
        action="ENDED",
        violation_id=violation_id,
        camera_id="BAI-KIEM",
        track_id=1,
        zone_id="zone-1",
        zone_name="JJJMới 1",
        object_label="Xe nâng",
        status="CLOSED",
        entered_at=entered_at,
        exited_at=entered_at + timedelta(seconds=5),
        duration_seconds=5,
    )


class TestAreaEventQueue(unittest.IsolatedAsyncioTestCase):
    async def test_successful_transition_runs_once(self):
        handled: list[str] = []
        exhausted: list[str] = []

        async def handler(item: ViolationTransition, generation: int) -> None:
            handled.append(f"{item.violation_id}:{generation}")

        async def on_exhausted(
            item: ViolationTransition,
            generation: int,
            error: BaseException,
        ) -> None:
            exhausted.append(f"{item.violation_id}:{generation}:{error}")

        queue = AreaEventQueue(handler, on_exhausted)
        queue.start()
        self.assertTrue(queue.enqueue(transition("v1"), generation=0))
        await queue.join()
        await queue.stop()

        self.assertEqual(handled, ["v1:0"])
        self.assertEqual(exhausted, [])

    async def test_retry_is_bounded_and_uses_exact_delays(self):
        attempts: list[str] = []
        delays: list[float] = []
        exhausted: list[str] = []

        async def handler(item: ViolationTransition, generation: int) -> None:
            attempts.append(f"{item.violation_id}:{generation}")
            raise RetryableAreaTransitionError("database offline")

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        async def on_exhausted(
            item: ViolationTransition,
            generation: int,
            error: BaseException,
        ) -> None:
            exhausted.append(f"{item.violation_id}:{generation}:{type(error).__name__}")

        queue = AreaEventQueue(
            handler,
            on_exhausted,
            sleep=fake_sleep,
            retry_delays=(1, 2, 4, 8),
        )
        queue.start()
        self.assertTrue(queue.enqueue(transition("v1"), generation=0))
        await queue.join()
        await queue.stop()

        self.assertEqual(len(attempts), 5)
        self.assertEqual(delays, [1, 2, 4, 8])
        self.assertEqual(exhausted, ["v1:0:RetryableAreaTransitionError"])

    async def test_reset_generation_discards_in_flight_and_queued_old_work(self):
        handled: list[str] = []
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(item: ViolationTransition, generation: int) -> None:
            started.set()
            await release.wait()
            handled.append(f"{item.violation_id}:{generation}")

        async def on_exhausted(
            item: ViolationTransition,
            generation: int,
            error: BaseException,
        ) -> None:
            self.fail(f"Unexpected exhausted transition: {item.violation_id}: {error}")

        queue = AreaEventQueue(handler, on_exhausted)
        queue.start()
        queue.enqueue(transition("in-flight-old"), generation=0)
        queue.enqueue(transition("queued-old"), generation=0)
        await asyncio.wait_for(started.wait(), timeout=0.2)

        await queue.reset_generation(1)
        release.set()
        self.assertFalse(queue.enqueue(transition("late-old"), generation=0))
        self.assertTrue(queue.enqueue(transition("new"), generation=1))
        await queue.join()
        await queue.stop()

        self.assertEqual(handled, ["new:1"])

    async def test_capacity_is_bounded_for_current_generation(self):
        async def handler(item: ViolationTransition, generation: int) -> None:
            return None

        async def on_exhausted(
            item: ViolationTransition,
            generation: int,
            error: BaseException,
        ) -> None:
            self.fail(f"Unexpected exhausted transition: {item.violation_id}: {error}")

        queue = AreaEventQueue(handler, on_exhausted, max_size=1)
        await queue.reset_generation(1)

        self.assertFalse(queue.enqueue(transition("stale"), generation=0))
        self.assertTrue(queue.enqueue(transition("current"), generation=1))
        self.assertFalse(queue.enqueue(transition("overflow"), generation=1))
        self.assertEqual(queue.qsize(), 1)
        await queue.stop()


if __name__ == "__main__":
    unittest.main()
