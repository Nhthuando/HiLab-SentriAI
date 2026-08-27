# Area Activity Analytics and QA Design

## Status

- Approved by HuuThuan in chat on 2026-08-27.
- Scope: BAI-KIEM zone activity for every detectable registry label, including allowed and violating objects.
- Delivery extends the in-progress `VS-QA-CHAT` slice without changing the existing Gate or Area violation contracts.

## Goal

Allow AI Q&A to answer questions such as:

- "Hôm nay có bao nhiêu lượt xe nâng ra vào?"
- "Xe nâng hôm nay làm việc ra sao?"
- "Phương tiện nào đang ở trong khu vực?"
- "Xe nâng làm việc lâu nhất ở zone nào?"

The system records small metadata sessions for objects observed inside BAI-KIEM zones. It does not create an image or MP4 when a session starts. A ten-second evidence clip is generated only after the user explicitly selects `Xem video`.

## Product semantics

### Unit of counting

One activity session is one tracked object entering and then leaving one zone. A tracked object present in two overlapping zones owns two independent sessions. Leaving and later re-entering the same zone creates a new session.

The result is a count of **zone-entry sessions**, not a count of unique physical vehicles. BAI-KIEM does not currently identify a stable asset ID or license plate. AI answers must say `lượt` and must not claim that two sessions are two unique forklifts.

### Included objects

Record every detection that:

1. resolves to a detectable label in the Object Label registry; and
2. is inside an active BAI-KIEM zone.

This includes people, vehicles, and equipment, regardless of whether the zone rule evaluates the observation as `ALLOWED` or `VIOLATION`. Labels outside the registry and labels with unavailable detector capability remain filtered out by the existing detection boundary.

### Activity measures

For a requested date range, label, zone, and optional policy result, the system can report:

- entry-session count;
- completed-exit count;
- currently open session count;
- total observed duration, average duration, and maximum duration;
- first and most recent entry;
- breakdown by zone, object label, and `ALLOWED`/`VIOLATION`;
- recent matching sessions.

Closed duration is `exitedAt - enteredAt`. An open session uses elapsed time up to the query instant and is explicitly described as provisional. Total duration is summed object-session time; overlapping objects contribute independently.

`Hôm nay` uses the `Asia/Bangkok` calendar boundary, consistent with the existing QA tools.

## Considered approaches

### 1. Independent activity-session table — selected

Add `area_activity_sessions` alongside `zone_violations`. It receives activity transitions from the existing detections, while the violation state machine, alerts, APIs, and history remain authoritative for violations.

This preserves current behavior, supports detailed QA and on-demand evidence, and confines new persistence failures to an independent path.

### 2. Generalize `zone_violations` into all zone events

Adding allowed rows to `zone_violations` would reduce table count but would change the meaning of existing counts, alerts, filters, and deletion behavior. It has unacceptable regression risk for this extension.

### 3. Persist daily/hourly aggregates only

Aggregates are smaller but cannot provide individual entry/exit times, open sessions, longest activity, or evidence references. They do not satisfy the approved questions.

## Data model

Add Prisma model `AreaActivitySession`, mapped to `area_activity_sessions`.

| Field | Type | Rules and meaning |
|---|---|---|
| `id` | UUID | Server-generated session ID |
| `cameraId` | varchar(50) | `BAI-KIEM` for the current deployment |
| `zoneId` | nullable UUID | Optional relation to the current Zone |
| `zoneName` | varchar(100) | Immutable display snapshot so history survives rename/delete |
| `objectLabel` | varchar(100) | Registry display label snapshot, for example `Xe nâng` |
| `canonicalClass` | varchar(100) | Exact detector class, for example `forklift` |
| `policyResult` | varchar(20) | `ALLOWED` or `VIOLATION` |
| `sessionStatus` | varchar(20) | `OPEN` or `CLOSED` |
| `enteredAt` | timestamptz | First confirmed inside observation |
| `lastSeenAt` | timestamptz | Latest confirmed inside observation |
| `exitedAt` | nullable timestamptz | Last confirmed inside time when closed |
| `durationSeconds` | nullable integer | Set only for closed sessions |
| `trackId` | nullable integer | Diagnostic runtime track ID; never treated as physical identity |
| `entryPoint` | jsonb | Normalized bottom-center used for local-file deduplication |
| `sourceKind` | varchar(20) | `LOCAL_FILE`, `LIVE`, or `UNAVAILABLE` |
| `sourceRef` | nullable varchar(500) | Server-owned source identifier; credentials are never stored |
| `sourcePositionSeconds` | nullable real | Local-video entry timecode |
| `sourceTimestamp` | nullable timestamptz | Live-source entry time |
| `eventFingerprint` | nullable varchar(64) | Unique only for deterministic local-file sessions |
| `violationId` | nullable UUID | Optional unique correlation ID of the existing violation event |
| `clipPath` | nullable varchar(500) | Server-owned generated media path for allowed activity |
| `clipStatus` | varchar(20) | Existing lazy lifecycle: `NOT_REQUESTED`, `QUEUED`, `GENERATING`, `READY`, `FAILED`, `EXPIRED` |
| `clipRequestedAt` | nullable timestamptz | Latest explicit request time |
| `clipError` | nullable text | Sanitized failure reason |
| `createdAt`, `updatedAt` | timestamptz | Audit timestamps |

Constraints and indexes:

- `policyResult IN ('ALLOWED', 'VIOLATION')`.
- `sessionStatus IN ('OPEN', 'CLOSED')`.
- Closed sessions require `exitedAt` and non-negative `durationSeconds`; open sessions keep both null.
- A partial unique index on non-null `eventFingerprint` makes local-file inserts idempotent.
- Index `(enteredAt DESC)`, `(canonicalClass, enteredAt DESC)`, `(zoneId, enteredAt DESC)`, `(policyResult, enteredAt DESC)`, and `(sessionStatus, lastSeenAt DESC)` for QA filters.
- `zoneId` uses `ON DELETE SET NULL`; zone deletion does not break existing settings behavior or erase history.
- `violationId` is nullable and unique but is deliberately not a database foreign key. The two persistence queues can therefore succeed, retry, or fail independently. Application cleanup deletes both histories when the existing Area clear action is used.

The migration backfills one `VIOLATION` activity row for every existing `zone_violations` row. Allowed history before feature activation is unknowable and is not fabricated.

Add one small `area_activity_collection_state` row per camera with `cameraId`, immutable `startedAt`, heartbeat-style `lastObservedAt`, and `updatedAt`. The worker creates the row on its first successfully processed frame and refreshes `lastObservedAt` at a bounded interval rather than every frame. QA uses it to disclose pre-activation coverage and to avoid describing stale data as current. It is not a full camera-uptime ledger; continuous historical availability reporting remains outside this slice.

## Runtime architecture

### Activity state machine

Add an activity tracker that consumes `annotated_detections` after the existing `ZoneChecker`. It does not run another detector and does not reevaluate zone rules.

The state key is `(cameraId, trackId, zoneId)`. Each visible `zoneMatch` supplies the zone ID, zone name, and policy result. The annotation's registry label and canonical class supply object identity attributes.

The tracker uses the existing Area behavior for:

- confirmed observations before opening a persisted session;
- fixed-pixel boundary tolerance and exit grace;
- missing-track grace;
- reidentification after a short occlusion using exact canonical class, bounding-box overlap/distance, and unobserved prior track ID;
- closing at `lastSeenAt`, not after the missing grace interval;
- ending all open sessions on source reset, seek, shutdown, or explicit Area reset.

Activity tracking is independent from `active_violations`. When the existing checker emits a matching violation transition, the activity transition copies its already-generated `violationId` as a correlation value. No foreign-key ordering is required, so a failed activity write cannot suppress or delay violation persistence and alert emission.

### Persistence isolation

Activity transitions use a bounded background queue separate from the existing Area violation queue. Frame processing never waits for network/database I/O. The queue retries transient failures with bounded exponential delays and uses session ID/fingerprint idempotency on every attempt.

If the queue is full or retries are exhausted, the worker emits a sanitized diagnostic and continues live monitoring. Existing violation behavior is unchanged.

### Local-file replay deduplication

The same activity in a looping or manually replayed demo video must not count again.

For `LOCAL_FILE`, compute `eventFingerprint` as SHA-256 over a versioned canonical payload containing:

- camera ID;
- server-derived source identity (normalized source reference plus file size and modification timestamp when available);
- zone ID;
- canonical class;
- entry timecode quantized to the source frame/timebase;
- normalized entry bottom-center quantized to the inference pixel grid.

The fingerprint excludes wall-clock time and ByteTrack ID, so a rewind or manual replay resolves to the same row. Entry time uses a documented coarse bucket tolerant of normal frame-sampling jitter; the entry point uses a documented inference-pixel bucket. Before insert, persistence also matches an existing row for the same source/zone/class within those exact time and spatial tolerances. The entry point prevents two same-class objects entering the same zone at the same source time but different positions from collapsing into one session. Database uniqueness is the final concurrency boundary for retries and concurrent delivery.

For `LIVE`, `eventFingerprint` is null. Every confirmed real entry receives a UUID and is counted. RTSP credentials are never copied into `sourceRef`; use the camera ID as in the existing reader.

## Node API and QA tools

### Activity read API

Add `GET /api/v1/area-activities` with bounded pagination and filters for date range, label/canonical class, zone, policy result, and session status. The API returns metadata only and never starts clip generation.

### Gemini tools

Add three read-only function tools:

- `get_area_activity_summary`: aggregates matching sessions and returns the exact query window and timezone.
- `get_area_activity_sessions`: returns bounded recent session details.
- `get_current_area_activity`: returns currently open sessions.

All filters are validated enums/IDs/date ranges. Gemini cannot submit SQL. Tool output includes both Vietnamese label and canonical class so the model can explain the result without inventing taxonomy mappings.

Prompt requirements:

- Explain that counts are entry sessions, not unique physical assets.
- For a broad question such as "xe nâng hôm nay", report allowed and violating sessions separately.
- For "hợp lệ", filter `policyResult = ALLOWED`.
- Mark open-session duration as provisional.
- If the requested range predates `area_activity_collection_state.startedAt`, state that allowed activity was not recorded before activation.
- If `lastObservedAt` is stale, do not describe database rows as current live state.
- Use `Không tìm thấy thông tin` only when the tool returns no matching rows; do not equate `NOT_REQUESTED` with a missing clip.

### QA evidence contract

Preserve the existing optional `clip` contract for already-generated Gate/violation media. Add an optional additive `evidence` object for deferred activity evidence:

```json
{
  "type": "area_activity",
  "eventId": "uuid",
  "title": "Xe nâng — Zone A",
  "cam": "BAI-KIEM",
  "from": "00:01:24",
  "to": "00:01:34",
  "clipStatus": "NOT_REQUESTED",
  "canRequestClip": true,
  "clipId": null
}
```

Only one best matching/recent evidence item is attached to an assistant answer in this slice, preserving the current one-card chat layout. Text may list additional sessions. `chat_messages.clip_reference` stores a server token such as `activity:<uuid>`, never a filesystem path; history hydration resolves current evidence/clip state.

## Lazy clip generation

Add:

- `POST /api/v1/area-activities/:id/clip` to explicitly request evidence;
- `GET /api/v1/area-activities/:id/clip` to poll the state.

For an `ALLOWED` session, Node delegates to the Python worker's existing event-clip machinery using the session's source metadata. For a session linked to `violationId`, Node delegates to the existing Area violation clip request/status path. The session and violation therefore never create two physical files for the same event.

The endpoints are idempotent:

- `NOT_REQUESTED`, retryable `FAILED`, or requestable `EXPIRED` may queue one job;
- `QUEUED`/`GENERATING` returns the current state without adding a job;
- `READY` returns the existing clip reference.

Generic clip stream/download resolution adds `AreaActivitySession` after the existing GateEvent and ZoneViolation lookups. It serves only a resolved `READY` path and never triggers generation.

The QA frontend reuses the existing Area Monitor request/poll behavior through a shared hook or service:

- `NOT_REQUESTED`: show `Xem video`;
- `QUEUED`/`GENERATING`: disable duplicate actions and poll;
- `READY`: render native video and download actions;
- `FAILED`/`EXPIRED`: show a sanitized reason and retry only when the source remains available;
- unavailable source: show that evidence cannot be generated for this session.

No `<video src>` assignment, QA tool call, history load, or assistant response may cause clip generation.

## Failure and consistency behavior

- Activity DB outage does not stop the camera feed, detection, or violation alert path.
- Duplicate queue delivery and concurrent clip clicks are idempotent.
- If an OPEN row cannot be closed immediately, retry by ID; aggregation treats it as open until closure succeeds.
- If a zone is renamed/deleted, the historical snapshot name remains available and `zoneId` may become null.
- A clip generation failure never removes or changes the activity metadata.
- Existing violations are backfilled; pre-activation allowed activity is explicitly unavailable.
- The existing Area clear-history action deletes both `zone_violations` and `area_activity_sessions`, and resets their in-memory states/queues under the current generation guard. It does not delete unrelated Gate or chat history.
- All errors returned to the browser omit source paths, RTSP credentials, stack traces, and Gemini/API secrets.

## Verification

### Python worker

- Unit-test allowed and violating sessions, enter/exit/re-entry, overlapping zones, and all detectable registry labels.
- Verify pending confirmation, boundary grace, missing-track reconnection, and closure at last seen time.
- Verify reset, seek, shutdown, and Area clear behavior.
- Verify independent queue retry/exhaustion and no effect on violation transitions.
- Process the real BAI-KIEM file for more than one loop and assert that the second loop does not increase persisted activity count.
- Confirm no additional model inference and retain the current Area FPS acceptance baseline.

### Database and Node

- Apply migration to a database with current Gate, Zone, violation, training, and chat data; verify no existing row is changed or lost.
- Verify violation backfill, collection-state timestamps, unique/fuzzy local replay matching, constraints, indexes, `SET NULL`, and idempotent upsert/close.
- Contract-test all activity filters, pagination, Bangkok day boundaries, open provisional duration, and empty results.
- Test Gemini tool schemas and deterministic aggregation against seeded sessions.
- Test activity clip request/status, violation delegation, concurrent request idempotency, ready range streaming, failure, expiry, and unavailable source.
- Run all existing Gate/Area/QA tests and Node typecheck/build/OpenAPI lint.

### Frontend and end-to-end

- Render summary, detail, no-data, partial-history disclosure, open-session, and error answers.
- Verify `NOT_REQUESTED -> QUEUED/GENERATING -> READY` only after an explicit click.
- Verify failure/expiry/retry and history reload hydration.
- Verify existing Gate clips and Area Monitor violation clips are unchanged.
- With real approved development data, compare Gemini answers to direct DB aggregation and verify that a repeated local-video loop does not alter totals.

## Rollout and compatibility

1. Apply the additive migration and backfill violations.
2. Deploy worker activity tracking and persistence.
3. Deploy Node read/tools/clip APIs.
4. Deploy the additive QA evidence UI.
5. Run a real BAI-KIEM one-loop/two-loop acceptance test and the existing regression suites.

Rollback may disable the activity writer and QA tools without removing the table. Existing Gate, Area violation, and chat contracts continue to operate. The migration does not delete or rewrite user event/media data.

## Success criteria

- QA accurately answers the approved forklift and other-object activity questions from saved metadata.
- Counts remain unchanged after the same local video segment is replayed.
- Allowed and violating sessions are distinguishable and violations keep their current alert/history behavior.
- No activity clip file exists before explicit user action.
- A requested activity clip reaches `READY` or a clear terminal state without duplicate jobs/files.
- Existing Gate monitoring, Area violation monitoring, settings, training, and QA answers pass regression checks.
- BAI-KIEM retains its current inference/FPS baseline because the feature adds state tracking and transition writes, not another inference pass.
