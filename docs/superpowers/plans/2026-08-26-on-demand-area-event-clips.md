# On-Demand Area Event Clips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop creating an MP4 for every Area violation and create one cached 10-second clip only after the user clicks `Xem video`, including for local files and live cameras retained for two hours.

**Architecture:** Persist lightweight source metadata with each violation. Extract local-file clips directly from the original source on demand. For live sources, keep a two-hour compressed rolling segment archive and assemble event MP4s only when requested. A bounded per-camera coordinator deduplicates clicks and allows at most one clip-generation FFmpeg process per camera.

**Tech Stack:** Python 3/FastAPI, asyncio, FFmpeg via imageio-ffmpeg, asyncpg, Node/Express/Prisma, PostgreSQL/Neon, React 19/TypeScript.

## Global Constraints

- Do not change the V9 artifact, active model, confidence thresholds, detection taxonomy, tracker, or ZoneChecker geometry.
- A violation that nobody opens must create no separate event MP4 and launch no event-specific FFmpeg encoding.
- Live archive retention is exactly `7200` seconds (two hours) by default.
- At most one event-clip FFmpeg generation process may run per Area camera.
- Initial event-list loading must not request MP4 bytes or mount `<video>`.
- Existing events without source metadata remain visible; they may show unavailable unless a valid legacy clip already exists.
- Source paths/URLs are server-only and never returned to the browser.
- Do not add a database index for clip metadata; lookup uses the violation primary key.
- Do not create a git commit unless the user explicitly asks.

---

## File Map

- Modify `backend/node-api/prisma/schema.prisma`: source and clip state fields.
- Create `backend/node-api/prisma/migrations/20260826160000_on_demand_area_clips/migration.sql`: nullable metadata/backfill/check constraint.
- Modify `backend/python-worker/db/repositories.py` and `db/__init__.py`: persist/read/claim/complete clip state.
- Modify `backend/python-worker/stream/reader.py`: safe source-context snapshot.
- Create `backend/python-worker/stream/rolling_archive.py`: two-hour stream-copy segment archive.
- Create `backend/python-worker/detection/event_clip_service.py`: local extraction, live assembly, queue/deduplication.
- Modify `backend/python-worker/detection/area_pipeline.py`: persist source metadata and remove eager clip jobs.
- Modify `backend/python-worker/main.py`: lifecycle and clip-generation endpoints.
- Create `backend/python-worker/tests/test_event_clip_service.py`: local generation and coordinator tests.
- Create `backend/python-worker/tests/test_rolling_archive.py`: segment selection/retention tests.
- Modify `backend/python-worker/tests/test_area_pipeline.py`: assert zero eager generation.
- Create `backend/node-api/src/services/areaEventClipService.ts`: worker bridge.
- Modify `backend/node-api/src/routes/events.ts`: clip state DTO and on-demand endpoints.
- Create `backend/node-api/src/tests/test_area_event_clip.ts`: Node contract tests.
- Modify `frontend/src/types.ts`, `frontend/src/api/events.ts`, `frontend/src/hooks/useAreaMonitor.ts`, and `frontend/src/components/AreaMonitor.tsx`: button, polling, modal lifecycle.
- Modify `backend/.env.example`: rolling archive/generation settings.

### Task 1: Add Backward-Compatible Clip Source State

**Interfaces:**

- `ZoneViolation.clipStatus`: `NOT_REQUESTED | QUEUED | GENERATING | READY | FAILED | EXPIRED`.
- Nullable `sourceKind`, `sourceRef`, `sourcePositionSeconds`, `sourceTimestamp`, `clipRequestedAt`, and `clipError`.
- Existing non-null `clipPath` rows are backfilled to `READY`; all others become `NOT_REQUESTED`.

- [ ] **Step 1: Modify the Prisma model**

Add these fields to `ZoneViolation`:

```prisma
sourceKind            String?   @db.VarChar(20) @map("source_kind")
sourceRef             String?   @db.VarChar(1000) @map("source_ref")
sourcePositionSeconds Float?    @map("source_position_seconds")
sourceTimestamp       DateTime? @db.Timestamptz() @map("source_timestamp")
clipStatus            String    @default("NOT_REQUESTED") @db.VarChar(20) @map("clip_status")
clipRequestedAt       DateTime? @db.Timestamptz() @map("clip_requested_at")
clipError             String?   @db.Text @map("clip_error")
```

Do not add `@@index`.

- [ ] **Step 2: Create the migration SQL**

Use a timestamped migration directory and add columns, then:

```sql
UPDATE "zone_violations"
SET "clip_status" = CASE
  WHEN "clip_path" IS NOT NULL THEN 'READY'
  ELSE 'NOT_REQUESTED'
END;

ALTER TABLE "zone_violations"
ADD CONSTRAINT "chk_zone_violations_clip_status"
CHECK ("clip_status" IN ('NOT_REQUESTED','QUEUED','GENERATING','READY','FAILED','EXPIRED'));
```

Keep all new source fields nullable so existing rows remain readable.

- [ ] **Step 3: Validate and apply the migration**

Run:

```powershell
cd backend/node-api
npx prisma validate
npx prisma generate
npx prisma migrate deploy
npm run typecheck
```

Expected: migration applies once and Prisma generation/typecheck pass.

### Task 2: Persist Source Context and Remove Eager Event Encoding

**Interfaces:**

- Produces `StreamReader.get_source_context() -> dict[str, object]`.
- Extends `create_zone_violation(violation_id, camera_id, zone_id, object_label, entered_at, clip_path, source_kind, source_ref, source_position_seconds, source_timestamp)` with source metadata.
- Area STARTED transition persists metadata and schedules no `_save_clip_job`.

- [ ] **Step 1: Write failing Area pipeline tests**

Extend `test_area_pipeline.py` with:

```python
def test_started_violation_persists_local_source_context_without_eager_clip(self):
    # reader.is_local_file=True, source=<temp mp4>, positionSeconds=42.5
    # process STARTED transition
    # assert persistence.create received source_kind='LOCAL_FILE'
    # assert source_position_seconds is close to the event-entry position
    # assert no save_clip/FFmpeg task was created

def test_live_source_context_never_persists_rtsp_credentials(self):
    # source='rtsp://user:pass@host/stream'
    # assert source_kind='LIVE' and source_ref='BAI-KIEM', not the URL
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
cd backend/python-worker
..\.venv\Scripts\python.exe -m pytest tests/test_area_pipeline.py -k "source_context or eager_clip" -q
```

Expected: FAIL because source metadata and lazy behavior do not exist.

- [ ] **Step 3: Add a safe reader source snapshot**

Implement:

```python
def get_source_context(self) -> dict[str, object]:
    if self.is_local_file and self.source:
        return {
            "source_kind": "LOCAL_FILE",
            "source_ref": os.path.abspath(self.source),
            "source_position_seconds": self.get_playback_state()["positionSeconds"],
            "source_timestamp": None,
        }
    if self.source and self.source.startswith(("rtsp://", "http://", "https://")):
        return {
            "source_kind": "LIVE",
            "source_ref": self.camera_id,
            "source_position_seconds": None,
            "source_timestamp": datetime.now(timezone.utc),
        }
    return {"source_kind": "UNAVAILABLE", "source_ref": None,
            "source_position_seconds": None, "source_timestamp": None}
```

Never return or persist a live URL containing credentials.

- [ ] **Step 4: Extend violation persistence**

Update `create_zone_violation` and `AreaPersistence.create` to accept the four source fields. Insert them with `clip_status='NOT_REQUESTED'`, `clip_path=NULL`, and `clip_error=NULL`.

For a local file, estimate the entry position rather than the later one-second confirmation position:

```python
confirmation_delay = max(0.0, (datetime.now(timezone.utc) - t.entered_at).total_seconds())
entry_position = max(0.0, current_position - confirmation_delay)
```

- [ ] **Step 5: Remove eager clip scheduling**

Delete the STARTED-path call to `_save_clip_job`, `_clip_tasks`, and event-specific buffer extraction. Keep `CircularBuffer` only where another live/snapshot behavior still uses it. Preserve `clipUrl: None` in real-time messages.

- [ ] **Step 6: Run Area tests**

Run:

```powershell
cd backend/python-worker
..\.venv\Scripts\python.exe -m pytest tests/test_area_pipeline.py -q
```

Expected: PASS and no test observes automatic event MP4 creation.

### Task 3: Implement Secure Local-File Clip Extraction

**Interfaces:**

- Produces `LocalClipSource` and `EventClipResult` dataclasses.
- Produces `EventClipGenerator.generate_local(violation) -> EventClipResult`.
- Output path is `backend/data/clips/area_<violation-id>.mp4` and becomes visible only after atomic rename.

- [ ] **Step 1: Write failing local-generation tests**

In `test_event_clip_service.py`, create a short temporary MP4 and cover:

Implement five concrete async tests named `test_local_clip_is_not_created_until_generate_is_called`, `test_local_generate_writes_one_browser_mp4_atomically`, `test_repeat_generate_reuses_existing_clip`, `test_source_outside_allowed_roots_is_rejected`, and `test_missing_source_returns_unavailable_without_partial_file`. Use a temporary clip directory, a generated source MP4, and assertions over output existence, result status, subprocess call count, and absence of `.tmp.mp4` files.

- [ ] **Step 2: Run and verify failure**

Run `..\.venv\Scripts\python.exe -m pytest tests/test_event_clip_service.py -q`.

- [ ] **Step 3: Implement `event_clip_service.py` local extraction**

Define:

```python
@dataclass(frozen=True)
class EventClipResult:
    status: str
    clip_path: str | None = None
    error: str | None = None
```

`EventClipGenerator.generate_local(self, violation: Mapping[str, Any]) -> EventClipResult` performs validation, cached-file reuse, FFmpeg execution in `asyncio.to_thread`, atomic rename, and structured failure mapping described below.

Validate UUID filenames and resolve `source_ref` under roots from `CLIP_SOURCE_ROOTS` plus the configured backend media root. First attempt a bounded stream-copy command; if it fails, use H.264 `veryfast`, baseline, `yuv420p`, `+faststart`. Always write `area_<id>.tmp.mp4`, validate non-zero output, then `os.replace`.

- [ ] **Step 4: Run local-generation tests**

Expected: all local tests PASS and no temporary file remains after failure.

### Task 4: Add a Two-Hour Live Rolling Archive

**Interfaces:**

- Produces `RollingArchive.start()`, `stop()`, `cleanup(now)`, and `segments_for(start, end)`.
- Default `retention_seconds=7200`, `segment_seconds=2`.
- Uses stream copy only; unsupported live streams expose a degraded/unavailable status instead of CPU transcoding continuously.

- [ ] **Step 1: Write failing archive tests**

Create `test_rolling_archive.py` covering:

Implement five tests named `test_cleanup_removes_only_segments_older_than_7200_seconds`, `test_cleanup_preserves_segments_leased_by_generation`, `test_segments_for_returns_ordered_covering_window`, `test_missing_window_reports_expired`, and `test_live_url_is_redacted_from_logs_and_status`. Create timestamped segment files in a temporary directory, inject a fixed clock, lease one segment during cleanup, and capture logs to assert credentials are absent.

- [ ] **Step 2: Run and verify failure**

Run `..\.venv\Scripts\python.exe -m pytest tests/test_rolling_archive.py -q`.

- [ ] **Step 3: Implement the archive lifecycle**

Create `rolling_archive.py`. For RTSP use TCP input; for HTTP omit the RTSP option. The essential command is:

```python
[
    ffmpeg, "-hide_banner", "-loglevel", "warning",
    *input_options, "-i", source,
    "-map", "0:v:0", "-an", "-c:v", "copy",
    "-f", "segment", "-segment_time", "2",
    "-reset_timestamps", "1", "-strftime", "1",
    str(archive_dir / "%Y%m%dT%H%M%S.ts"),
]
```

Run one process per live Area camera, restart with bounded backoff, track segment time from filenames/mtime, and delete expired unleased segments. Never include the raw source URL in logs or API status.

- [ ] **Step 4: Integrate lifecycle with AreaPipeline**

Start the archive for `LIVE` sources during `prepare()`/startup and stop it during pipeline shutdown. Do not start it for local files, images, or synthetic fallback. Add `.env.example` values:

```dotenv
AREA_ARCHIVE_RETENTION_SECONDS=7200
AREA_ARCHIVE_SEGMENT_SECONDS=2
AREA_CLIP_QUEUE_LIMIT=8
CLIP_SOURCE_ROOTS=D:\video_test
```

- [ ] **Step 5: Run archive and pipeline tests**

Run both focused test files and `test_area_pipeline.py`.

### Task 5: Add the Bounded Clip Job Coordinator and Python API

**Interfaces:**

- `POST /cameras/BAI-KIEM/violations/{id}/clip` returns `READY`, `QUEUED`, `GENERATING`, `EXPIRED`, or `FAILED`.
- `GET /cameras/BAI-KIEM/violations/{id}/clip` returns current state.
- Concurrent requests for one violation share one job.

- [ ] **Step 1: Add failing coordinator tests**

In `test_event_clip_service.py` cover double-click deduplication, one-active-job-per-camera, queue limit, cached READY, local extraction, live assembly, two-hour expiry, and cancellation/reset during delete-all.

- [ ] **Step 2: Add atomic repository operations**

Implement:

Add typed repository functions `get_zone_violation(violation_id)`, `claim_violation_clip(violation_id, requested_at)`, `mark_violation_clip_ready(violation_id, clip_path)`, and `mark_violation_clip_failed(violation_id, status, error)`. Each converts string IDs to UUID, uses parameterized SQL, and returns a normalized dictionary or `None`.

`claim_violation_clip` must use one conditional statement:

```sql
UPDATE zone_violations
SET clip_status = 'QUEUED', clip_requested_at = $2, clip_error = NULL
WHERE id = $1 AND clip_status IN ('NOT_REQUESTED', 'FAILED')
RETURNING *;
```

READY/QUEUED/GENERATING callers reuse current state.

- [ ] **Step 3: Implement `EventClipService`**

Use an `asyncio.Queue(maxsize=8)`, one worker task for BAI-KIEM, and a `jobs_by_violation` map. Local jobs call `generate_local`; live jobs lease covering archive segments and assemble them into the same atomic MP4 output. Mark `EXPIRED` when the two-hour window is gone.

- [ ] **Step 4: Add FastAPI endpoints**

In `main.py`, validate camera aliases and UUIDs, call the Area pipeline's clip service, return 404 for unknown violation, 410-style `EXPIRED` state as structured JSON, and never return source metadata. A READY response includes only:

```json
{
  "violationId": "uuid",
  "status": "READY",
  "clipUrl": "/data/clips/area_uuid.mp4"
}
```

- [ ] **Step 5: Run Python tests**

Run:

```powershell
cd backend/python-worker
..\.venv\Scripts\python.exe -m pytest tests/test_event_clip_service.py tests/test_rolling_archive.py tests/test_area_pipeline.py -q
```

Expected: all PASS.

### Task 6: Expose Clip Status Through Node API

**Interfaces:**

- Produces `requestAreaEventClip(id)` and `getAreaEventClip(id)` service methods.
- Adds `POST /api/v1/events/area/:id/clip` and `GET /api/v1/events/area/:id/clip`.
- Area list items include `clipStatus`, `clipAvailable`, and `clipUrl` only when READY.

- [ ] **Step 1: Write failing Node contract tests**

Create `test_area_event_clip.ts` with a fake worker response. Assert that the list never exposes `sourceRef`, POST forwards one request, READY maps to a media URL, QUEUED/GENERATING are preserved, EXPIRED is explicit, and concurrent clicks do not cause duplicate worker jobs.

- [ ] **Step 2: Run and verify failure**

Run `npx ts-node src/tests/test_area_event_clip.ts` from `backend/node-api`.

- [ ] **Step 3: Implement the worker bridge**

Create `areaEventClipService.ts` using the configured Python Worker URL and a bounded timeout. Validate the worker JSON into:

```ts
export type AreaClipStatus = 'NOT_REQUESTED' | 'QUEUED' | 'GENERATING' | 'READY' | 'FAILED' | 'EXPIRED';
export interface AreaClipState {
  violationId: string;
  status: AreaClipStatus;
  clipUrl: string | null;
  message?: string;
}
```

- [ ] **Step 4: Add routes and DTO fields**

Before proxying POST, verify the violation exists. GET may read current Prisma state directly. Return no internal source fields. For area list, map legacy `clipPath` to READY and otherwise return the persisted state.

- [ ] **Step 5: Run Node tests/build**

Run:

```powershell
cd backend/node-api
npx ts-node src/tests/test_area_event_clip.ts
npm run typecheck
npm run build
```

### Task 7: Load and Mount Video Only After User Request

**Interfaces:**

- Frontend `AreaViolationDto` and `AreaEvent` carry `clipStatus` and optional `clipUrl`.
- `requestAreaEventClip(id)` starts generation; `getAreaEventClipStatus(id)` polls it.
- `AreaMonitor` mounts `<video>` only when status is READY and the modal is open.

- [ ] **Step 1: Extend frontend types/API**

Add `AreaClipStatus` and API methods in `events.ts`. Do not call `getClipUrl` during initial list mapping unless status is READY and a path exists.

- [ ] **Step 2: Add clip request state to `useAreaMonitor`**

Expose:

```ts
requestEventClip(eventId: string): Promise<void>;
closeEventClip(): void;
selectedClip: { eventId: string; status: AreaClipStatus; url: string | null; message?: string } | null;
```

POST once, poll GET every 750ms only while QUEUED/GENERATING, stop on READY/FAILED/EXPIRED/unmount, and ignore stale responses after another event is selected.

- [ ] **Step 3: Replace the existing Clip-only button/modal**

- Show `Xem video` for every persisted violation event, not only rows with `clipUrl`.
- While processing show `Đang tạo video…` and prevent duplicate clicks for that event.
- Mount `<video src={url} controls autoPlay preload="metadata">` only for READY.
- On close, pause the element, remove its `src`, call `load()`, clear selected state, and stop polling.
- Show explicit messages for `EXPIRED`, `FAILED`, and legacy unavailable events.

- [ ] **Step 4: Build frontend**

Run:

```powershell
cd frontend
npm run build
npm run lint
```

Expected: PASS.

### Task 8: End-to-End Resource and Retention Verification

- [ ] **Step 1: Verify a local video event**

Create/observe one disposable Area violation. Before clicking, assert there is no `area_<id>.mp4` and no event-specific FFmpeg process. Click once, observe QUEUED/GENERATING, then READY and playback. Click again and confirm instant reuse with no new process.

- [ ] **Step 2: Verify simultaneous events**

Create multiple events without viewing and confirm zero MP4 outputs. Request two clips and confirm only one generation process for BAI-KIEM while the second waits.

- [ ] **Step 3: Verify live archive behavior**

With a safe test network stream, confirm rolling `.ts` segments remain bounded to two hours, expired segments are removed, a retained event assembles successfully, and an older ungenerated event reports EXPIRED.

- [ ] **Step 4: Verify deletion/reset**

Delete Area events while one clip is queued. Confirm queue state is retired, partial output is removed, generated event files are deleted, and archive segments unrelated to event records remain under rolling retention management.

- [ ] **Step 5: Run full focused regression and report**

Run Python clip/Area tests, Node clip/event tests and builds, and frontend build/lint. Report CPU/process observations before/after and confirm V9 checksum/configuration is unchanged.
