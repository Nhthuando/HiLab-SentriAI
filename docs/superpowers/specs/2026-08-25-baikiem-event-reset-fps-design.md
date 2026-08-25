# BAI-KIEM Event Reset and Seek FPS Recovery Design

## Problem

The Area event delete routes remove `zone_violations` rows and clip files, but the Python worker keeps matching active violations in `ZoneChecker.active_violations`. When a seek or later frame ends one of those violations, `close_zone_violation()` returns no row. The pipeline restores the exact in-memory state and retries the same close on every frame. Each database round trip takes roughly 0.5 seconds, so the feed falls from about 10 FPS to 1.5-1.6 FPS while the GPU remains idle.

Seeking also resets the detector and frame buffer without ending or clearing Area violation state. That lets violation state from one video position leak into a different timeline.

## Goals

- Keep database history, Python in-memory violation state, queued event work, and clip work synchronized when Area events are deleted.
- Treat a missing violation row as an idempotent terminal result, never as a reason for an infinite per-frame retry.
- End the previous violation timeline and reset all tracking/zone state when a seek is committed.
- Keep persistence retries off the video hot path and bound every retry sequence.
- Restore the BAI-KIEM feed to at least 8 FPS within five seconds after delete-and-seek on the current 10 FPS configuration.
- Do not change YOLO artifacts, confidence thresholds, tracking thresholds, class arbitration, or training data.

## Design

### Single owner for an Area reset

The Python Area pipeline becomes the owner of the coordinated Area reset because it already owns live violation state and database writes. It exposes a camera-scoped reset/delete operation used by the Node API.

Under a pipeline control lock, the operation:

1. Stops new Area transitions from being scheduled for the old runtime generation.
2. Clears active and pending `ZoneChecker` state.
3. Invalidates queued persistence work from the old generation.
4. Cancels unfinished clip jobs associated with deleted Area events.
5. Deletes the camera's `zone_violations` rows through the worker repository.
6. Starts a new runtime generation and returns the deleted-record count.

The existing Node `DELETE /api/v1/events/area` and the Area part of `DELETE /api/v1/events/all` call this worker operation before cleaning Area clip files. If coordination fails, Node returns a service-unavailable response before deleting Area or Gate data and does not claim that history was cleared. Gate-event deletion otherwise remains unchanged.

This keeps an event created after the reset in the new generation instead of accidentally deleting or restoring it as part of the old generation.

### Timeline-safe seek

The BAI-KIEM seek operation becomes asynchronous and uses the same pipeline control lock as frame processing. Before changing the reader position, it converts all active violations into final `ENDED` transitions for the old timeline, clears pending violations, and schedules those final transitions for background persistence. It then seeks, resets detector tracking, clears the circular frame buffer, and resets the FPS measurement.

The first frame after the seek therefore starts with no track IDs, pending confirmations, or active violations inherited from the previous video position. A seek does not delete historical events; it closes the old timeline once and allows new violations to be created at the destination.

### Non-blocking, bounded persistence

Frame publishing only queues violation transitions. A dedicated Area persistence task handles database writes in order, so a slow database request cannot hold the inference/emission loop.

Persistence behavior is explicit:

- A close that returns no row is treated as already removed and completes locally with one warning.
- A real exception is retried in the background with bounded exponential delays of 1, 2, 4, and 8 seconds.
- After the final failure, the item is retired with one error; it is never restored into a next-frame hot loop.
- A failed `STARTED` write removes the matching in-memory event only if it still belongs to the same runtime generation.
- Reset invalidates queued items from older generations, preventing deleted events from being recreated after the reset.
- Shutdown cancels and awaits persistence and clip tasks cleanly.

The queue is bounded. If it reaches capacity, the worker drops the oldest stale-generation item first. If none is stale, it rejects the newest transition and logs one operational error; live frame delivery continues.

## Interfaces and ownership

- `ZoneChecker` owns state-machine operations for ending all active violations and clearing pending/active runtime state.
- `AreaPipeline` owns the control lock, runtime generation, transition queue, retry policy, and clip-task lifecycle.
- The Python repository owns camera-scoped Area-event deletion and returns an exact affected-row count.
- The Python HTTP layer validates that coordinated reset is available only for `BAI-KIEM`.
- The Node events route proxies the coordinated operation and owns filesystem cleanup and the public API response.

No frontend contract changes are required. The existing delete buttons and seek controls continue using their current endpoints.

## Failure handling

- Missing DB row during `ENDED`: complete idempotently and never retry.
- Temporary DB/network failure: retry only in the background and stop after four retries.
- Worker unavailable during Area deletion: return 503; keep database rows and clips so the user can retry safely.
- Clip cleanup failure after a successful coordinated reset: return the successful record count plus the actual deleted-file count and log the filesystem error; no live state is restored.
- Concurrent seek and delete: serialize them with the pipeline control lock; whichever acquires the lock second operates on the new generation.
- Worker shutdown: stop accepting transitions, cancel retry waits and clip tasks, and release resources without reconnect or retry storms.

## Verification

Automated tests reproduce the exact regression:

1. Create and persist a violation, delete all Area events, then end/seek it. Assert no repeated close, no restored active state, and no queued old-generation work.
2. Make `close()` return `None`. Assert it is attempted once and treated as terminal.
3. Make persistence raise repeatedly. Assert retry delays and attempt count are bounded while frame publishing continues.
4. Seek with active and pending violations. Assert the old active event is ended once and all detector, buffer, pending, and active state is clean at the destination.
5. Delete concurrently with queued persistence. Assert old-generation items cannot recreate deleted rows.
6. Verify Node Area/all deletion success and worker-unavailable failure contracts.

Runtime acceptance on `KiemHoa-Hik (2).mp4`:

- Start detection, create at least one Area event, press **Xóa tất cả sự kiện**, then seek multiple times.
- No repeating `VIOLATION ENDED` or `Zone violation was not closed` lines for one ID.
- No publisher reconnect storm.
- Reported BAI-KIEM FPS returns to at least 8 FPS within five seconds and remains stable near the configured 10 FPS.
- New violations after the reset persist and close normally.

## Scope exclusions

This change does not improve model precision or recall and does not train V9. It fixes runtime state consistency and prevents database/event administration from throttling the video pipeline.
