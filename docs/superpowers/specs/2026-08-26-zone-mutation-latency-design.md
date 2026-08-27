# Zone Mutation Latency, UI Consistency, and On-Demand Event Clips Design

**Date:** 2026-08-26  
**Status:** Approved direction; pending written-spec review

## Goal

Make Zone create, edit, and delete interactions feel immediate and remain correct when a user performs actions quickly. Reduce real API latency. Stop eagerly encoding a separate MP4 for every violation and generate an event clip only when a user requests it. Do not change the V9 model, confidence thresholds, tracking, or zone-boundary behavior.

## Current Evidence

- Direct local measurements show `GET /zones` taking roughly 0.3–0.8 seconds and label/capability reads taking roughly 0.7–1.4 seconds.
- Neon database latency dominates these requests.
- A Zone update currently sends the complete Zone document even when only one property changed. Including `targetLabels` forces capability validation and extra database reads.
- Update and delete routes first read the Zone, then write it. This adds a database round trip.
- Frontend optimistic mutations capture and restore an entire stale camera Zone array. Concurrent responses can therefore overwrite newer UI state.
- A pending update can complete after delete and restore a Zone that no longer exists in the database.
- Success notifications are currently shown before the server confirms persistence.
- The Area worker currently schedules FFmpeg after every violation starts and writes a 10-second MP4 even when nobody watches it.
- The browser already creates the video player only after selection. The expensive eager work is server-side clip encoding, not the event-list button itself.

## Selected Approach

Use coordinated frontend optimistic state and lean backend mutations.

### Frontend mutation coordinator

- Apply the user's change to local state immediately.
- Show a per-Zone `Đang lưu…` state while persistence is pending.
- Show `Đã lưu`, `Đã tạo`, or `Đã xóa` only after the API confirms the operation.
- Assign each Zone mutation a monotonically increasing revision. A response may update UI only when it still matches the latest revision.
- Coalesce rapid updates for the same Zone so only the newest state is persisted.
- Delete has priority over update: deleting a Zone marks it as a tombstone, cancels or invalidates pending updates, removes it locally, and prevents stale responses from restoring it.
- Roll back only the affected Zone and only if no newer user action superseded the failed request. Never restore an entire captured camera Zone array.
- Create uses a temporary client ID and appears immediately. On success, replace the temporary ID with the server ID atomically.
- If a temporary Zone is deleted before create finishes, keep it hidden and delete the real server record immediately after the create response arrives.
- Color-only changes remain local because color is not persisted by the API.

### Minimal API payloads

Translate a UI patch into only the fields that actually changed:

- points -> `polygonPoints`
- name -> `name`
- permission matrix -> `ruleType` and `targetLabels`
- color -> no API request

Geometry and name edits therefore skip label-capability work entirely.

### Backend mutation path

- Update performs one direct Prisma update instead of read-then-update.
- Delete performs one direct Prisma delete instead of read-then-delete.
- Prisma `P2025` is translated into a stable not-found result instead of a 500 error.
- The frontend treats not-found during delete, or a stale update after delete, as an already-synchronized state.
- Detection capability context is held in a bounded in-memory cache for Zone validation.
- Label or model mutations explicitly invalidate that cache before the next validation.
- Concurrent cache misses share one in-flight load to prevent duplicate Neon queries.

## On-Demand Violation Clips

### User experience

- Every eligible Area event displays a `Xem video` button even when no event MP4 exists yet.
- The initial event list contains availability metadata only. It does not mount a video element or request video bytes.
- Clicking `Xem video` starts one on-demand clip request and changes the button/modal state to `Đang tạo video…`.
- When generation succeeds, the UI assigns the returned URL to a newly mounted video player and starts playback.
- Closing the modal removes the video element and its `src`, allowing network and decode resources to be released.
- A generated event MP4 is cached. Later views reuse it immediately instead of generating it again.

### Local video source

- Store the internal source identity and playback position with the violation record when the event starts.
- Do not copy or encode video at event time.
- On request, extract the 10-second event window from the original local video with FFmpeg.
- Prefer stream copy/remux when the source codec and container permit it; use bounded fallback transcoding only when required for browser-compatible MP4.
- The internal source path is never exposed to the frontend.

### Live camera source

- A live camera cannot reconstruct old frames unless compressed footage is retained. Maintain one rolling compressed archive per live Area camera.
- The archive uses small time-based segments and keeps at most two hours of footage.
- Prefer copying the camera's compressed stream without re-encoding. If stream copy is unsupported, the archive reports an explicit unsupported/degraded state rather than silently starting unlimited CPU-heavy encoding.
- A live violation stores its wall-clock event window and source identity, but does not create a per-event MP4.
- On request, assemble the relevant archive segments into one browser-compatible 10-second MP4.
- Archive cleanup continuously removes segments older than two hours, except files currently used by a generation job.
- If an event is older than the retained archive and no event MP4 was previously generated, return a clear `Video đã hết thời gian lưu tạm` state.

### Clip API and job control

- Add an idempotent on-demand clip endpoint for one Area violation.
- If a clip already exists, return it immediately.
- If generation is already running, return the same job state instead of starting another FFmpeg process.
- Bound clip generation to one active FFmpeg job per Area camera; additional requests wait in a small queue.
- A request made before the complete post-event window exists remains in `Đang tạo video…` until enough footage is available or the bounded timeout is reached.
- Failed and expired requests produce explicit states and may be retried only when source footage is still available.
- Event deletion cancels queued generation, waits for/cancels active work safely, and removes any generated event MP4.

### Persistence metadata

- Persist source kind, internal source identity, source event position/time, clip status, and generated clip path on the violation record.
- Clip states are `NOT_REQUESTED`, `QUEUED`, `GENERATING`, `READY`, `FAILED`, or `EXPIRED`.
- State transitions are atomic so concurrent clicks cannot create duplicate files.
- Existing events without source metadata remain readable but show `Video không khả dụng` unless they already have a valid clip path.

## Database Index Decision

No new index is added.

- `zones.id` is already the primary-key index used by update and delete.
- `(camera_id, is_active)` and `(camera_id, name)` indexes already cover Zone lookup constraints.
- the ACTIVE model already has a partial unique index.
- object label names already have a unique index.

The observed delay comes from repeated remote database round trips and frontend response races, not table scans. Extra indexes would add write overhead without materially improving these mutations.

On-demand clip lookup also uses the violation primary key, so the new clip metadata does not require another index. Rolling archive cleanup is filesystem time-segment cleanup and does not scan the event table.

## Error and Concurrency Rules

- The server remains the persistence authority; optimistic UI never reports success early.
- Network failure restores only the affected entity when safe and displays a retryable error.
- An older success or failure response cannot overwrite a newer edit.
- Delete is idempotent from the user's perspective.
- Create-name conflicts restore/remove only the temporary Zone and keep other Zones untouched.
- Cache invalidation is explicit for label/model changes; a bounded TTL is a fallback, not the primary correctness mechanism.
- Clip generation never runs once per event automatically.
- Clip source paths are server-only and validated to remain inside configured media/source roots.
- Generated output is written atomically through a temporary file and exposed only after FFmpeg succeeds.
- A closed browser modal does not cancel a generation already requested; the completed result remains cached for the next view.

## Verification

- Frontend production build and TypeScript checks pass.
- Node API typecheck/build and Zone validation tests pass.
- Add regression coverage for direct `P2025` handling and capability-cache invalidation.
- Exercise rapid sequences: update-update-update, update-delete, add-delete-before-create-completes, delete repeated, and two Zones edited concurrently.
- Verify UI never resurrects a deleted Zone and never rolls another Zone backward.
- Measure before/after API timings. Normal name/geometry update and delete must use one database mutation round trip.
- Verify that creating violations starts zero per-event FFmpeg clip jobs.
- Verify local-file extraction, live rolling-segment assembly, cached repeat viewing, concurrent double-click deduplication, two-hour expiry, and deletion during queued generation.
- Verify no video request occurs before `Xem video` is clicked and the player releases its source on close.
- Load-test simultaneous violations to confirm clip work remains zero until requested and on-demand jobs remain bounded.
- Confirm the V9 artifact, model configuration, inference thresholds, tracking, and zone geometry are unchanged; Python changes remain isolated to clip capture/generation control and event metadata.

## Success Criteria

- Zone changes render immediately without visible jumping.
- Success feedback is shown only after persistence succeeds.
- Repeated fast actions converge to the user's latest state in both UI and database.
- Delete no longer produces a stale update `P2025` error followed by UI resurrection.
- Normal update/delete paths no longer perform a preliminary Zone read.
- A violation that nobody opens creates no separate event MP4 and launches no event-specific FFmpeg encoding.
- Clicking `Xem video` creates or reuses exactly one 10-second event MP4 and opens it only after it is ready.
- Live camera footage remains eligible for on-demand generation for two hours; older ungenerated clips fail clearly without unbounded storage growth.
- At most one clip-generation FFmpeg process runs per Area camera.
- No regression to the V9 runtime or area detection behavior.
