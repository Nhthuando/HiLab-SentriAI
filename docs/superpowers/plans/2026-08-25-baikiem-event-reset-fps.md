# BAI-KIEM Event Reset and Seek FPS Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent Area-event deletion and video seeking from creating per-frame database retry storms, keeping the configured 10 FPS feed responsive.

**Architecture:** `ZoneChecker` gains explicit timeline-drain/reset operations. `AreaPipeline` serializes frame/seek/delete mutations and sends event persistence to a bounded generation-aware background queue. The Python worker performs a coordinated runtime-plus-database Area reset, while Node keeps the public delete contract and media cleanup.

**Tech Stack:** Python 3, `asyncio`, FastAPI, asyncpg, OpenCV, `unittest`; Node.js, TypeScript, Express, Prisma.

## Global Constraints

- Restore BAI-KIEM to at least 8 FPS within five seconds after delete-and-seek on the current 10 FPS configuration.
- Do not change YOLO artifacts, confidence thresholds, tracking thresholds, class arbitration, training data, or the frontend API contract.
- A missing violation row is an idempotent terminal close and is never retried.
- Retry real persistence exceptions outside the video loop after 1, 2, 4, and 8 seconds, then retire the item.
- Serialize concurrent seek and delete operations and invalidate persistence work from deleted runtime generations.
- Do not access locked test data or train another model.

## File Structure

- Create `backend/python-worker/detection/area_event_queue.py`: bounded, generation-aware, background retry queue with no Area business logic.
- Create `backend/python-worker/tests/test_area_event_queue.py`: deterministic queue timing, retry, invalidation, and capacity tests.
- Create `backend/node-api/src/services/areaEventResetService.ts`: typed Python-worker client for coordinated Area deletion.
- Create `backend/node-api/src/tests/test_area_event_reset.ts`: dependency-injected Node service contract tests without touching the shared database.
- Modify `backend/python-worker/zone/zone_checker.py`: drain and clear violation state at timeline boundaries.
- Modify `backend/python-worker/detection/area_pipeline.py`: integrate queue, serialize control mutations, make seek asynchronous, and own coordinated reset.
- Modify `backend/python-worker/db/repositories.py`: camera-scoped deletion of Area violations.
- Modify `backend/python-worker/db/__init__.py`: export the new repository operation.
- Modify `backend/python-worker/main.py`: await seek and expose the BAI-KIEM coordinated delete endpoint.
- Modify `backend/python-worker/tests/test_area_pipeline.py`: state drain, non-blocking publish, seek, missing-row, and reset regression tests.
- Modify `backend/node-api/src/routes/events.ts`: proxy Area deletion to the worker and clean only Area clips.
- Modify `backend/node-api/package.json`: add a focused `test:area-reset` command.

---

### Task 1: Explicit Zone Timeline Drain and Reset

**Files:**
- Modify: `backend/python-worker/zone/zone_checker.py:208-285,596-655`
- Test: `backend/python-worker/tests/test_area_pipeline.py:719-818`

**Interfaces:**
- Produces: `ZoneChecker.end_all(timestamp: Optional[datetime] = None) -> List[ViolationTransition]`
- Produces: `ZoneChecker.clear_runtime_state() -> Tuple[int, int]`, returning `(active_count, pending_count)` cleared.
- Consumes: existing `ActiveViolation`, `PendingViolation`, and `ViolationTransition` dataclasses.

- [ ] **Step 1: Write failing tests for ending and clearing all zone state**

Add these methods to `TestViolationStateMachine` using an active event and a separately keyed pending event:

```python
def test_end_all_returns_one_close_per_active_and_clears_pending(self):
    t0 = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
    self.checker.active_violations[("BAI-KIEM", 7, "zone-1")] = ActiveViolation(
        violation_id="violation-active",
        camera_id="BAI-KIEM",
        track_id=7,
        zone_id="zone-1",
        zone_name="JJJMới 1",
        object_label="Xe nâng",
        entered_at=t0,
        last_seen_inside=t0 + timedelta(seconds=3),
        normalized_bbox=(0.1, 0.1, 0.3, 0.4),
        yolo_class="reach_stacker",
    )
    self.checker.pending_violations[("BAI-KIEM", 8, "zone-1")] = PendingViolation(
        camera_id="BAI-KIEM",
        track_id=8,
        zone_id="zone-1",
        zone_name="JJJMới 1",
        object_label="Người",
        entered_at=t0 + timedelta(seconds=1),
        last_seen_inside=t0 + timedelta(seconds=2),
        normalized_bbox=(0.5, 0.2, 0.55, 0.5),
        yolo_class="person",
    )

    transitions = self.checker.end_all(t0 + timedelta(seconds=10))

    self.assertEqual([item.action for item in transitions], ["ENDED"])
    self.assertEqual(transitions[0].violation_id, "violation-active")
    self.assertEqual(transitions[0].duration_seconds, 10)
    self.assertEqual(self.checker.active_violations, {})
    self.assertEqual(self.checker.pending_violations, {})

def test_clear_runtime_state_reports_counts_without_emitting(self):
    t0 = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
    self.checker.active_violations[("BAI-KIEM", 7, "zone-1")] = ActiveViolation(
        "violation-active", "BAI-KIEM", 7, "zone-1", "JJJMới 1", "Xe nâng", t0, t0
    )
    self.checker.pending_violations[("BAI-KIEM", 8, "zone-1")] = PendingViolation(
        "BAI-KIEM", 8, "zone-1", "JJJMới 1", "Người", t0, t0,
        (0.5, 0.2, 0.55, 0.5), "person"
    )

    self.assertEqual(self.checker.clear_runtime_state(), (1, 1))
    self.assertEqual(self.checker.active_violations, {})
    self.assertEqual(self.checker.pending_violations, {})
```

Update the test import to include `ActiveViolation` and `PendingViolation`.

- [ ] **Step 2: Run the two tests and verify they fail**

Run from `backend/python-worker`:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_area_pipeline.TestViolationStateMachine.test_end_all_returns_one_close_per_active_and_clears_pending tests.test_area_pipeline.TestViolationStateMachine.test_clear_runtime_state_reports_counts_without_emitting -v
```

Expected: both fail with `AttributeError` because the methods do not exist.

- [ ] **Step 3: Implement one canonical transition builder and the two public methods**

Add a private builder so normal exits and timeline drains calculate close fields the same way:

```python
def _build_ended_transition(
    self, active: ActiveViolation, exited_at: datetime
) -> ViolationTransition:
    duration = max(0, int((exited_at - active.entered_at).total_seconds()))
    transition = ViolationTransition(
        action="ENDED",
        violation_id=active.violation_id,
        camera_id=active.camera_id,
        track_id=active.track_id,
        zone_id=active.zone_id,
        zone_name=active.zone_name,
        object_label=active.object_label,
        status="CLOSED",
        entered_at=active.entered_at,
        exited_at=exited_at,
        duration_seconds=duration,
    )
    setattr(transition, "_restore_state", ActiveViolation(**vars(active)))
    return transition

def end_all(self, timestamp: Optional[datetime] = None) -> List[ViolationTransition]:
    exited_at = timestamp or datetime.now(timezone.utc)
    transitions = [
        self._build_ended_transition(active, exited_at)
        for active in self.active_violations.values()
    ]
    self.active_violations.clear()
    self.pending_violations.clear()
    return transitions

def clear_runtime_state(self) -> Tuple[int, int]:
    counts = (len(self.active_violations), len(self.pending_violations))
    self.active_violations.clear()
    self.pending_violations.clear()
    return counts
```

Replace the duplicated normal-exit construction at the bottom of `check_detections()` with `_build_ended_transition(active, exit_ts)`.

- [ ] **Step 4: Run the state-machine suite**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_area_pipeline.TestViolationStateMachine -v
```

Expected: all tests pass, including the existing exact-state restore regression.

- [ ] **Step 5: Commit the state-machine unit**

```powershell
git add backend/python-worker/zone/zone_checker.py backend/python-worker/tests/test_area_pipeline.py
git commit -m "fix: add explicit area violation timeline reset"
```

---

### Task 2: Bounded Background Transition Queue

**Files:**
- Create: `backend/python-worker/detection/area_event_queue.py`
- Create: `backend/python-worker/tests/test_area_event_queue.py`

**Interfaces:**
- Produces: `QueuedAreaTransition(transition: ViolationTransition, generation: int)`.
- Produces: `RetryableAreaTransitionError` used only for retryable handler failures.
- Produces: `AreaEventQueue.start() -> None`, `enqueue(transition, generation) -> bool`, `reset_generation(generation) -> Awaitable[None]`, and `stop() -> Awaitable[None]`.
- Consumes: `handler: Callable[[ViolationTransition, int], Awaitable[None]]`, `on_exhausted: Callable[[ViolationTransition, int, BaseException], Awaitable[None]]`, and injectable `sleep: Callable[[float], Awaitable[None]]`.

- [ ] **Step 1: Write deterministic failing queue tests**

Create `test_area_event_queue.py` with `unittest.IsolatedAsyncioTestCase`. Use this transition factory and cover immediate enqueue, bounded retries, old-generation cancellation, and capacity:

```python
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
        item: ViolationTransition, generation: int, error: BaseException
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

async def test_reset_generation_discards_old_work(self):
    handled: list[str] = []
    gate = asyncio.Event()

    async def handler(item: ViolationTransition, generation: int) -> None:
        await gate.wait()
        handled.append(f"{item.violation_id}:{generation}")

    async def on_exhausted(
        item: ViolationTransition, generation: int, error: BaseException
    ) -> None:
        self.fail(f"Unexpected exhausted transition: {item.violation_id}: {error}")

    queue = AreaEventQueue(handler, on_exhausted)
    queue.start()
    queue.enqueue(transition("old"), generation=0)
    await queue.reset_generation(1)
    gate.set()
    queue.enqueue(transition("new"), generation=1)
    await queue.join()
    await queue.stop()

    self.assertEqual(handled, ["new:1"])
```

Add a capacity test with `max_size=1`: after `reset_generation(1)`, assert an enqueue tagged generation zero returns `False`; then occupy the queue with one generation-one item and assert the newest generation-one enqueue returns `False`. This proves reset drains stale work and current work cannot exceed capacity.

- [ ] **Step 2: Run the new module and verify import failure**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_area_event_queue -v
```

Expected: fail because `detection.area_event_queue` does not exist.

- [ ] **Step 3: Implement the queue with one runner task**

Implement the declared dataclass, error, and lifecycle. The runner skips a queued item's work when `item.generation < self._generation`, retries only `RetryableAreaTransitionError`, calls `on_exhausted()` once after the final failed attempt, calls `task_done()` exactly once per dequeued item, and exposes `join()` for tests and controlled shutdown.

Use these fixed defaults:

```python
DEFAULT_RETRY_DELAYS: Tuple[float, ...] = (1.0, 2.0, 4.0, 8.0)
DEFAULT_MAX_SIZE = 256
```

Use these exact callback types and constructor parameters:

```python
TransitionHandler = Callable[[ViolationTransition, int], Awaitable[None]]
ExhaustedHandler = Callable[
    [ViolationTransition, int, BaseException], Awaitable[None]
]

def __init__(
    self,
    handler: TransitionHandler,
    on_exhausted: ExhaustedHandler,
    *,
    max_size: int = DEFAULT_MAX_SIZE,
    retry_delays: Tuple[float, ...] = DEFAULT_RETRY_DELAYS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    self._handler = handler
    self._on_exhausted = on_exhausted
    self._retry_delays = retry_delays
    self._sleep = sleep
    self._queue: asyncio.Queue[QueuedAreaTransition] = asyncio.Queue(max_size)
```

`reset_generation()` must cancel and await the current runner, drain every queued item with matching `task_done()` calls, update `_generation`, and restart the runner only if the queue was previously running. `stop()` performs the same cancellation/drain without restarting.

- [ ] **Step 4: Run queue tests and Python static compilation**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_area_event_queue -v
.\.venv\Scripts\python.exe -m compileall detection\area_event_queue.py
```

Expected: all queue tests pass and compilation exits zero.

- [ ] **Step 5: Commit the queue unit**

```powershell
git add backend/python-worker/detection/area_event_queue.py backend/python-worker/tests/test_area_event_queue.py
git commit -m "feat: queue area event persistence off the video loop"
```

---

### Task 3: Integrate Non-Blocking Persistence and Timeline-Safe Seek

**Files:**
- Modify: `backend/python-worker/detection/area_pipeline.py:15-115,213-337,339-455,490-575`
- Modify: `backend/python-worker/main.py:165-177`
- Test: `backend/python-worker/tests/test_area_pipeline.py:872-1118`

**Interfaces:**
- Consumes: `AreaEventQueue`, `RetryableAreaTransitionError`, `ZoneChecker.end_all()` from Tasks 1-2.
- Produces: `AreaPipeline.request_seek(position_seconds: float) -> Awaitable[Dict[str, Any]]`.
- Produces: `AreaPipeline._process_transition_once(transition, generation) -> Awaitable[None]`.
- Preserves: the existing Node/public `POST /cameras/:id/playback` response body.

- [ ] **Step 1: Replace the synchronous-publish expectation with a non-blocking test**

Update `test_publish_result_uses_injected_no_write_persistence_and_emitter` so the pipeline starts its queue, publishes a frame, waits for `pipeline._event_queue.join()`, then stops it. Add a separate test whose persistence `create()` waits on an `asyncio.Event`; assert `publish_result()` finishes before the event is released and the frame emitter already received one frame.

```python
async def scenario():
    pipeline._event_queue.start()
    await asyncio.wait_for(pipeline.publish_result(result), timeout=0.2)
    self.assertEqual(len(emitter.frames), 1)
    await asyncio.wait_for(persistence_started.wait(), timeout=0.2)
    self.assertFalse(release_persistence.is_set())
    release_persistence.set()
    await pipeline._event_queue.join()
    await pipeline._event_queue.stop()
```

Set `persistence_started` inside the fake `create()` immediately before it waits. The completed `publish_result()` call plus the still-unset `release_persistence` event proves frame publishing did not wait for the database.

- [ ] **Step 2: Add missing-row and real-exception tests**

Add one `ENDED` test where `persistence.close()` returns `None`. Wait for queue completion and assert:

```python
self.assertEqual(persistence.close_calls, 1)
self.assertEqual(pipeline.zone_checker.active_violations, {})
self.assertEqual(retry_delays, [])
```

Add another where `close()` raises `ConnectionError` five times, inject a no-wait sleep recorder into the queue, and assert attempts are five, delays are `[1.0, 2.0, 4.0, 8.0]`, and ten consecutive `publish_result()` frame calls complete without awaiting the failing close operation.

- [ ] **Step 3: Add a timeline-safe seek test**

Construct one active and one pending violation, mock `reader.request_seek`, `detector.reset_tracking`, and `buffer.clear`, then await seek:

```python
state = asyncio.run(pipeline.request_seek(181.0))
self.assertTrue(state["seekable"])
self.assertEqual(pipeline.zone_checker.active_violations, {})
self.assertEqual(pipeline.zone_checker.pending_violations, {})
reader.request_seek.assert_called_once_with(181.0)
detector.reset_tracking.assert_called_once_with()
pipeline.buffer.clear.assert_called_once_with()
```

After queue completion, assert the active violation was closed exactly once and the pending violation produced no DB call.

- [ ] **Step 4: Run the new tests and verify failure before implementation**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_area_pipeline.TestAreaPipelineControl -v
```

Expected: the non-blocking and async-seek assertions fail against the current inline `_handle_transition()` implementation.

- [ ] **Step 5: Integrate queue lifecycle and one-attempt transition handling**

In `AreaPipeline.__init__`, add:

```python
self._control_lock = asyncio.Lock()
self._runtime_generation = 0
self._event_queue = AreaEventQueue(
    self._process_transition_once,
    self._handle_exhausted_transition,
)
```

Start the queue with the pipeline and stop it before closing persistence dependencies. Change `publish_result()` to emit the frame and call `enqueue()` for each transition without awaiting database persistence.

Refactor `_handle_transition()` into `_process_transition_once()`:

- `STARTED`: `create() is None` raises `RetryableAreaTransitionError`; a real persistence exception is wrapped in the same error. After persistence succeeds, schedule the clip and emit Area event/alert. Emitter errors are logged but never cause the DB operation to repeat.
- `ENDED`: `close() is None` logs one warning and returns successfully. A real exception raises `RetryableAreaTransitionError`. Emit the Area event only after a real close result.
- Remove `restore_ended_transition()` from the persistence-failure path so a failed close can never re-enter the next video frame.
- Implement `_handle_exhausted_transition()`: on terminal `STARTED` exhaustion, call `discard_started_transition()` only when the queue item generation is still current; for `ENDED`, log one terminal error and do not restore it into `ZoneChecker`.

- [ ] **Step 6: Serialize frame processing and make seek asynchronous**

Wrap only `process_single_frame()` in `_control_lock`; do not hold the lock while emitting a frame or while background persistence runs:

```python
async with self._control_lock:
    result = await asyncio.to_thread(self.process_single_frame)
await self.publish_result(result)
```

Implement `async request_seek()` under the same lock. Queue `zone_checker.end_all(datetime.now(timezone.utc))`, then call reader seek and reset detector, buffer, and FPS counters. Update FastAPI to await it:

```python
return {"cameraId": cid, **await pipeline.request_seek(float(payload["positionSeconds"]))}
```

- [ ] **Step 7: Run focused and full Python Area tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_area_event_queue tests.test_area_pipeline -v
```

Expected: all tests pass with no pending-task or un-awaited-coroutine warning.

- [ ] **Step 8: Commit the pipeline integration**

```powershell
git add backend/python-worker/detection/area_pipeline.py backend/python-worker/main.py backend/python-worker/tests/test_area_pipeline.py
git commit -m "fix: keep area persistence off the frame hot path"
```

---

### Task 4: Coordinated Python Reset and Node Delete Contract

**Files:**
- Modify: `backend/python-worker/db/repositories.py:316-375`
- Modify: `backend/python-worker/db/__init__.py:8-68`
- Modify: `backend/python-worker/detection/area_pipeline.py`
- Modify: `backend/python-worker/main.py:152-180`
- Modify: `backend/python-worker/tests/test_area_pipeline.py`
- Create: `backend/node-api/src/services/areaEventResetService.ts`
- Create: `backend/node-api/src/tests/test_area_event_reset.ts`
- Modify: `backend/node-api/src/routes/events.ts:289-355`
- Modify: `backend/node-api/package.json:8-15`

**Interfaces:**
- Produces: `delete_zone_violations(camera_id: str, conn_or_pool: Optional[DbExecutor] = None) -> Awaitable[int]`.
- Produces: `AreaPipeline.delete_all_events() -> Awaitable[Dict[str, int]]` with `deleted_records`, `cleared_active`, and `cleared_pending`.
- Produces: Python `DELETE /cameras/BAI-KIEM/violations` returning camel-case JSON.
- Produces: Node `deleteAreaEventsViaWorker(fetchImpl: typeof fetch = fetch) -> Promise<AreaEventResetResult>`.
- Preserves: public Node `DELETE /api/v1/events/area` and `/api/v1/events/all` URLs.

- [ ] **Step 1: Write the repository and coordinated-reset failing tests**

Add an async fake executor test that returns `DELETE 3` and verifies exact camera scoping:

```python
executor = AsyncMock()
executor.execute.return_value = "DELETE 3"
count = await delete_zone_violations("BAI-KIEM", conn_or_pool=executor)
self.assertEqual(count, 3)
query, camera_id = executor.execute.await_args.args
self.assertIn("WHERE camera_id = $1", query)
self.assertEqual(camera_id, "BAI-KIEM")
```

Add an Area pipeline test with an active violation, a pending violation, one blocked old-generation queue item, and one clip task. Call `delete_all_events()` and assert:

```python
self.assertEqual(result, {
    "deleted_records": 3,
    "cleared_active": 1,
    "cleared_pending": 1,
})
self.assertEqual(pipeline._runtime_generation, 1)
self.assertEqual(pipeline.zone_checker.active_violations, {})
self.assertEqual(pipeline.zone_checker.pending_violations, {})
self.assertTrue(clip_task.cancelled())
self.assertEqual(old_generation_handler_calls, [])
```

- [ ] **Step 2: Run focused Python tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_area_pipeline.TestAreaPipelineControl.test_delete_all_events_invalidates_runtime_generation -v
```

Expected: fail because the repository and pipeline delete methods do not exist.

- [ ] **Step 3: Implement camera-scoped repository deletion and export it**

Use one parameterized query and parse asyncpg's command tag:

```python
async def delete_zone_violations(
    camera_id: str,
    conn_or_pool: Optional[DbExecutor] = None,
) -> int:
    executor = _get_executor(conn_or_pool)
    result = await executor.execute(
        "DELETE FROM zone_violations WHERE camera_id = $1",
        camera_id,
    )
    return int(result.rsplit(" ", 1)[-1])
```

Export it from `db/__init__.py` and add `delete_all(camera_id)` to `RepositoryAreaPersistence`.

- [ ] **Step 4: Implement `AreaPipeline.delete_all_events()` and Python endpoint**

Under `_control_lock`, increment `_runtime_generation`, await `_event_queue.reset_generation()`, call `clear_runtime_state()`, cancel all clip tasks, await them with `asyncio.gather(*tasks, return_exceptions=True)`, clear the task set, and await `persistence.delete_all(camera_id)`. Return exact counts. Add:

```python
@app.delete("/cameras/{camera_id}/violations")
async def delete_camera_violations(camera_id: str):
    cid = normalize_camera_id(camera_id)
    if cid != "BAI-KIEM":
        raise HTTPException(status_code=409, detail="Coordinated violation reset is available only for BAI-KIEM")
    pipeline = pipelines.get(cid)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    result = await pipeline.delete_all_events()
    return {
        "cameraId": cid,
        "deletedRecords": result["deleted_records"],
        "clearedActive": result["cleared_active"],
        "clearedPending": result["cleared_pending"],
    }
```

Normalize the new endpoint with the same BAI-KIEM aliases already accepted by playback; do not refactor unrelated camera routes in this fix.

- [ ] **Step 5: Write failing Node worker-client contract tests**

Create `areaEventResetService.ts` test cases with injected fetch functions. Success returns worker counts; non-2xx and thrown network errors both reject with `AreaEventResetUnavailableError`:

```typescript
const calls: Array<{ url: string; init?: RequestInit }> = [];
const successFetch: typeof fetch = async (input, init) => {
  calls.push({ url: String(input), init });
  return new Response(JSON.stringify({
    cameraId: 'BAI-KIEM', deletedRecords: 4, clearedActive: 1, clearedPending: 2,
  }), { status: 200, headers: { 'Content-Type': 'application/json' } });
};

const result = await deleteAreaEventsViaWorker(successFetch);
assert.deepStrictEqual(result, {
  cameraId: 'BAI-KIEM', deletedRecords: 4, clearedActive: 1, clearedPending: 2,
});
assert.strictEqual(calls[0].init?.method, 'DELETE');
assert.match(calls[0].url, /\/cameras\/BAI-KIEM\/violations$/);
```

Set `PYTHON_WORKER_HTTP_URL=http://worker.test:8001` before the call and assert the exact base URL. For failure, return `Response` status 503 and separately throw `new Error('offline')`.

- [ ] **Step 6: Run the Node test and verify module failure**

```powershell
npx.cmd ts-node src/tests/test_area_event_reset.ts
```

Run from `backend/node-api`. Expected: TypeScript module resolution fails because the service does not exist.

- [ ] **Step 7: Implement the typed Node worker client and route coordination**

Implement a five-second timeout and strict response-shape validation in `areaEventResetService.ts`. Export `AreaEventResetUnavailableError` for route mapping.

In `/events/area`, call `deleteAreaEventsViaWorker()` first, then remove only files whose names start with `area_` and end with `.mp4`. Do not call `prisma.zoneViolation.deleteMany()` in Node.

In `/events/all`, complete the coordinated Area call before deleting Gate rows/files. If the Area call fails, return `503 AREA_RESET_UNAVAILABLE` before deleting Gate data. Preserve current success-envelope field names and source `deletedAreaRecords` from the worker result.

Add this script:

```json
"test:area-reset": "ts-node src/tests/test_area_event_reset.ts"
```

- [ ] **Step 8: Run Python, Node service, and type checks**

```powershell
# backend/python-worker
.\.venv\Scripts\python.exe -m unittest tests.test_area_event_queue tests.test_area_pipeline -v

# backend/node-api
npm.cmd run test:area-reset
npm.cmd run typecheck
```

Expected: all commands exit zero. The Node test does not connect to Neon or delete real clips.

- [ ] **Step 9: Commit coordinated deletion**

```powershell
git add backend/python-worker/db/repositories.py backend/python-worker/db/__init__.py backend/python-worker/detection/area_pipeline.py backend/python-worker/main.py backend/python-worker/tests/test_area_pipeline.py backend/node-api/src/services/areaEventResetService.ts backend/node-api/src/tests/test_area_event_reset.ts backend/node-api/src/routes/events.ts backend/node-api/package.json
git commit -m "fix: coordinate area event deletion with worker state"
```

---

### Task 5: Full Regression and Live Acceptance

**Files:**
- Modify only if verification exposes a defect: files already listed in Tasks 1-4.
- Runtime evidence: `backend/data/runtime-logs/` remains untracked and is never committed.

**Interfaces:**
- Consumes: completed coordinated reset, async seek, and background transition queue.
- Produces: test output and live acceptance evidence for the exact reported sequence.

- [ ] **Step 1: Run the full Python worker regression suite**

```powershell
Set-Location 'D:\HuuThuan - Project\HiLab-SentriAI\backend\python-worker'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: all tests pass. Tests requiring unavailable external services must be reported separately rather than silently ignored.

- [ ] **Step 2: Run Node and frontend compile gates**

```powershell
Set-Location 'D:\HuuThuan - Project\HiLab-SentriAI\backend\node-api'
npm.cmd run test:area-reset
npm.cmd run typecheck

Set-Location 'D:\HuuThuan - Project\HiLab-SentriAI\frontend'
npm.cmd run lint
npm.cmd run build
```

Expected: all commands exit zero.

- [ ] **Step 3: Restart only the Node API and Python worker with fresh runtime logs**

Resolve PIDs listening on ports 3001 and 8001, stop those exact processes, verify the ports are free, then start the project commands already used by this workspace with stdout/stderr redirected to distinct files under `backend/data/runtime-logs`. Do not terminate unrelated Python or Node processes.

- [ ] **Step 4: Reproduce the exact browser workflow**

Open BAI-KIEM using `D:\video_test\KiemHoa-Hik (2).mp4`, wait for a persisted Area event, press **Xóa tất cả sự kiện**, seek forward and backward several times, and let the feed run for at least 30 seconds after the final seek.

- [ ] **Step 5: Verify health and logs quantitatively**

```powershell
$health = Invoke-RestMethod -Uri 'http://localhost:8001/health' -TimeoutSec 5
$health.cameras.'BAI-KIEM' | ConvertTo-Json -Depth 5
rg -n "Zone violation was not closed|VIOLATION ENDED|Connected publisher WebSocket|deprecated.*half" backend/data/runtime-logs/python-worker-event-reset*.log
```

Acceptance:

- BAI-KIEM reports at least 8 FPS within five seconds after the final seek and remains near 10 FPS for 30 seconds.
- A single violation ID has at most one persisted/logged `ENDED` transition.
- No `Zone violation was not closed` retry storm appears.
- No repeated publisher connection lines appear per frame.
- A new post-reset violation is inserted and later closes normally.

- [ ] **Step 6: Inspect the final diff and commit any verification-only correction**

```powershell
git diff --check
git status --short
```

Stage only files changed for this FPS fix. Preserve every unrelated dirty-worktree change. If no correction was needed, do not create an empty commit.
