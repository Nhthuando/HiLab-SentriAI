"""Bounded background delivery for Area violation transitions."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Tuple

from zone.zone_checker import ViolationTransition

logger = logging.getLogger("sentriai.area.event_queue")

DEFAULT_RETRY_DELAYS: Tuple[float, ...] = (1.0, 2.0, 4.0, 8.0)
DEFAULT_MAX_SIZE = 256


class RetryableAreaTransitionError(RuntimeError):
    """A persistence attempt failed and may be retried in the background."""


@dataclass(frozen=True)
class QueuedAreaTransition:
    transition: ViolationTransition
    generation: int


TransitionHandler = Callable[[ViolationTransition, int], Awaitable[None]]
ExhaustedHandler = Callable[
    [ViolationTransition, int, BaseException], Awaitable[None]
]
SleepFunction = Callable[[float], Awaitable[None]]


class AreaEventQueue:
    """Deliver transitions serially without blocking the video hot path."""

    def __init__(
        self,
        handler: TransitionHandler,
        on_exhausted: ExhaustedHandler,
        *,
        max_size: int = DEFAULT_MAX_SIZE,
        retry_delays: Tuple[float, ...] = DEFAULT_RETRY_DELAYS,
        sleep: SleepFunction = asyncio.sleep,
    ) -> None:
        self._handler = handler
        self._on_exhausted = on_exhausted
        self._retry_delays = tuple(float(delay) for delay in retry_delays)
        self._sleep = sleep
        self._queue: asyncio.Queue[QueuedAreaTransition] = asyncio.Queue(
            maxsize=max(1, int(max_size))
        )
        self._generation = 0
        self._running = False
        self._runner: Optional[asyncio.Task[None]] = None
        self._capacity_warning_emitted = False

    @property
    def generation(self) -> int:
        return self._generation

    def qsize(self) -> int:
        return self._queue.qsize()

    def start(self) -> None:
        if self._runner is not None and not self._runner.done():
            return
        self._running = True
        self._runner = asyncio.create_task(self._run())

    def enqueue(self, transition: ViolationTransition, generation: int) -> bool:
        if generation < self._generation:
            return False
        try:
            self._queue.put_nowait(QueuedAreaTransition(transition, generation))
            return True
        except asyncio.QueueFull:
            if not self._capacity_warning_emitted:
                logger.error(
                    "Area event queue is full (%d); rejecting newest transition.",
                    self._queue.maxsize,
                )
                self._capacity_warning_emitted = True
            return False

    async def join(self) -> None:
        await self._queue.join()

    async def reset_generation(self, generation: int) -> None:
        """Cancel in-flight old work, drain it, and advance the runtime epoch."""
        was_running = self._running
        self._running = False
        await self._cancel_runner()
        self._drain()
        self._generation = max(self._generation, int(generation))
        self._capacity_warning_emitted = False
        if was_running:
            self.start()

    async def stop(self) -> None:
        self._running = False
        await self._cancel_runner()
        self._drain()
        self._capacity_warning_emitted = False

    async def _cancel_runner(self) -> None:
        runner = self._runner
        self._runner = None
        if runner is None:
            return
        runner.cancel()
        try:
            await runner
        except asyncio.CancelledError:
            pass

    def _drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            else:
                self._queue.task_done()

    async def _run(self) -> None:
        while self._running:
            queued = await self._queue.get()
            self._capacity_warning_emitted = False
            try:
                if queued.generation >= self._generation:
                    await self._deliver(queued)
            finally:
                self._queue.task_done()

    async def _deliver(self, queued: QueuedAreaTransition) -> None:
        last_error: Optional[BaseException] = None
        attempts = len(self._retry_delays) + 1
        for attempt in range(attempts):
            if queued.generation < self._generation:
                return
            try:
                await self._handler(queued.transition, queued.generation)
                return
            except asyncio.CancelledError:
                raise
            except RetryableAreaTransitionError as exc:
                last_error = exc
                if attempt < len(self._retry_delays):
                    await self._sleep(self._retry_delays[attempt])
                    continue
            except Exception as exc:
                last_error = exc
                logger.exception(
                    "Unexpected Area transition handler failure for %s.",
                    queued.transition.violation_id,
                )
            break

        if last_error is not None and queued.generation >= self._generation:
            await self._on_exhausted(
                queued.transition,
                queued.generation,
                last_error,
            )
