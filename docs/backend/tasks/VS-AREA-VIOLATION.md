# VS-AREA-VIOLATION Backend Task — Giám sát khu vực: detect + violation event + floating alert

## Task identity

- Slice ID: VS-AREA-VIOLATION
- Task ID: BE-AREA-VIOLATION
- Master plan: `docs/plan/plan.md#vs-area-violation`
- Planning revision: 1.3
- Owner: Hữu Thuận
- Branch: feature/vs-area-violation
- Priority: P0
- Size: L
- Status: blocked
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> pending | planned | team1-plan
  - 2026-08-18T09:03:37+07:00 | pending -> ready | all FDN-* gates verified; redundant VS-GATE-LIVE delivery dependency removed because shared infrastructure is foundation-owned | team1-plan
  - 2026-08-18T09:30:00+07:00 | ready -> in_progress | started execution on feature branch | team1-backend
  - 2026-08-18T09:37:00+07:00 | in_progress -> backend_verified | all acceptance criteria passed with fresh unit and REST integration evidence | team1-backend
  - 2026-08-18 | backend_verified -> invalidated | stabilization changes changed runtime behavior; previous automated evidence is retained as historical only and must be rerun | team1-slice
  - 2026-08-18T15:00:00+07:00 | invalidated -> in_progress | user reported unplayable browser clips and repeated Area events after intermittent tracking loss | team1-backend
  - 2026-08-18T15:00:00+07:00 | in_progress -> blocked | Python unit and Node typecheck passed; standalone Neon REST verifier could not complete because the sandbox rejected TLS credentials and the approved unsandboxed retry timed out | team1-backend

## Inputs and dependencies

- Requirement sources: Product M2 (§3), BR-03, BR-04, BR-06, BR-08, AC-03, AC-04, AC-08, Product §7 (Exceptions)
- Consumed fingerprints:
  - `docs/product/product.md` → `9C2C05C7`
  - `docs/architecture/architecture.md` → `45F59BC5`
  - `docs/database/database.md` → `C635952D`
- Foundation dependencies: FDN-REPO-SCAFFOLD, FDN-DB-MIGRATION, FDN-PYTHON-DB, FDN-WS-PROXY, FDN-PYTHON-STREAM, FDN-API-CONTRACT
- Slice dependencies: none; VS-GATE-LIVE may run in parallel and requires coordination only when editing shared files
- Environment dependencies: `NEON_DATABASE_URL`, `AREA_CAMERA_URL` (path to BAI-KIEM video file or RTSP URL), `NODE_WS_URL`, `CLIPS_DIR`

## Executor contract

### Mandatory read order

The implementation model must read these files in order before editing code. A later source does not override an earlier owner contract unless this task explicitly records the mapping.

1. `docs/plan/plan.md` — slice scope, owner, dependencies, conflict zones.
2. `docs/backend/plan.md` — backend index and current task status.
3. This task file — execution authority for the backend half of the slice.
4. `docs/product/product.md` §3 M2, §5 BR-03/04/05/06/07/08, §7, §9 AC-03/04/08.
5. `docs/architecture/architecture.md` §6.1, §6.2 flows 1/2/4/5, §8.
6. `docs/database/database.md` tables `zones`, `zone_violations`, `object_labels`; AP-02/05/06; §8 data rules.
7. Verified foundation code: `backend/python-worker/stream/`, `backend/python-worker/detection/detector.py`, `backend/python-worker/buffer/circular_buffer.py`, `backend/python-worker/db/repositories.py`, `backend/node-api/src/ws/`, `backend/node-api/src/utils/response.ts`, `backend/node-api/src/prisma/client.ts`.
8. Paired frontend task only to confirm the consumer contract: `docs/frontend/tasks/VS-AREA-VIOLATION.md`.

### Scope and anti-invention rules

- Implement only camera `BAI-KIEM`; do not add LPR, gate events, vehicle lookup, analytics, Q&A, zone CRUD, or label CRUD.
- Reuse the verified stream reader, circular buffer, DB pool, Express envelope, Prisma client, WS channel manager, and frontend foundations. Do not replace them or add another framework.
- New runtime dependencies are forbidden unless an approved source requires them. `ultralytics`, `Shapely`, `asyncpg`, `Prisma`, and `ws` already cover this slice.
- Do not edit `backend/node-api/prisma/schema.prisma` or migrations; the required tables and indexes already exist.
- Do not implement placeholders, mock events, timers that fabricate violations, hard-coded zones, or hard-coded detection boxes in a production path.
- When repository behavior conflicts with a wire contract below, stop and record the exact conflict. Do not silently rename fields, invent fallback payloads, or change public semantics.
- Before editing shared files (`backend/python-worker/main.py`, `backend/python-worker/stream/emitter.py`, `backend/node-api/src/routes/index.ts`, `backend/node-api/src/ws/types.ts`), re-read their current contents and preserve unrelated Gate changes. Keep shared edits additive and Area-specific.

### Current-state classification

| Capability | State | Repository evidence | Required delta |
|---|---|---|---|
| BAI-KIEM stream, JPEG encoding, YOLO inference, circular buffer | verified foundation | `backend/python-worker/stream/pipeline.py`, `detection/detector.py`, `buffer/circular_buffer.py` | Reuse; add Area-specific tracking/rule/event orchestration without changing Gate semantics |
| Area WS feed/event/alert routing | verified foundation | `backend/node-api/src/ws/server.ts`, `channels.ts`, `types.ts` | Reuse channels; extend payload types additively where required |
| Zone/label/violation persistence helpers | partial | `backend/python-worker/db/repositories.py` | Reuse existing helpers; add only missing filtered query and clip-path update helpers |
| Area REST endpoint | absent | no mounted Area route | Add one Area-owned route and mount it |
| Area OpenAPI and backend handoff | absent | no `area.yaml`, no `docs/backend/backend.md` | Create/update only this slice's contract section |

## Contract checkpoint

- API/interface surface:
  - `GET /api/v1/events/area?limit=N&offset=N&zone_id=:id&status=OPEN|CLOSED` — query zone violations with pagination
  - `WS /ws/feed/area` — real-time JPEG frames + object bbox + zone overlay from Python→Node→Browser
  - `WS /ws/events/area` — real-time violation event notifications
  - `WS /ws/alerts` — floating alert notifications for cross-tab (BR-08)
- Auth and permission: None (single user, no auth)
- Request/response/errors:
  - `GET /api/v1/events/area` → foundation success envelope containing `{ items: AreaViolationDto[], total, limit, offset }`; validation uses the foundation 400 error envelope; unexpected failure uses its sanitized 500 envelope.
  - `WS /ws/feed/area` → JSON foundation frame with JPEG data URL, Area detections/zoneMatches, and active zone metadata.
  - `WS /ws/events/area` → flat JSON `{ type: "zone_violation", action: "STARTED|ENDED", ...AreaViolationDto }`.
  - `WS /ws/alerts` → foundation `AlertMessage` with `type: "alert"`, `level: "critical"`, and Area identifiers under `data`.
- Contract source/output: `backend/node-api/openapi/area.yaml` (planned)
- Gate pass condition: Frontend can fetch violations, receive live area frames with zone overlays, and receive violation/alert push via WS

## Canonical behavior decisions

### Coordinates and zone containment

- DB `zones.polygon_points` is the canonical polygon format: JSON array of `{ "x": number, "y": number }`, normalized to `[0,1]`.
- Detection `bbox` is pixel `[x1,y1,x2,y2]`; `normalized_bbox` is `[x1/w,y1/h,x2/w,y2/h]` in `[0,1]`.
- Test the normalized bottom-center point `((x1+x2)/(2*w), y2/h)` against the zone. Bottom-center represents the object's ground contact more reliably than bbox center for the overhead BAI-KIEM camera.
- Use `Shapely.Polygon(...).covers(Point(...))`; points on the polygon boundary count as inside.
- Ignore and log a zone when it has fewer than 3 points, non-numeric/out-of-range coordinates, or an invalid polygon. Keep processing other valid zones.

### Tracking and entry/exit identity

- Create `TrackedYoloDetector` as an Area-owned subclass/wrapper around the verified `YoloDetector`; call Ultralytics `model.track(..., persist=True, tracker="bytetrack.yaml")` and emit a stable integer `track_id` with the existing detection fields. Area tracking must not apply the foundation detector's default target-class filter, because any model class without a DB mapping must reach the `CHƯA XÁC ĐỊNH` rule path.
- Do not change `YoloDetector.detect()` behavior used by other slices.
- A detection not yet assigned a ByteTrack ID may be shown in the feed with `trackId = null`, but it cannot open/close a persisted violation or emit an alert until the tracker confirms an ID.
- The in-memory violation state key is `(camera_id, track_id, zone_id)`. One key can have at most one OPEN DB row.
- Open when the key changes from outside/allowed to inside/prohibited. Remaining inside/prohibited updates frame metadata only and never inserts or alerts again.
- Close after 3 consecutive processed frames when the confirmed track is observed outside or allowed. When the tracked detection is absent, keep the event open for 12 wall-clock seconds so intermittent detector loss or a ByteTrack ID change can reconnect to the same violation. Use the last timestamp at which the key was inside/prohibited as `exited_at`.
- A prohibited object must be confirmed continuously for at least one second before creating a DB row, `STARTED` event, alert, or clip job. A detection that exits/disappears before confirmation is discarded and never reaches the event panel.
- On worker startup, close stale `BAI-KIEM` OPEN rows at startup time before accepting new tracks. Preserve their existing `clip_path`; this prevents a restart from leaving permanent OPEN rows or causing duplicate alerts.

### Label resolution and rule matrix

- Refresh active BAI-KIEM zones and all object-label mappings together every 5 seconds. On refresh failure, keep the last good immutable snapshot and log one warning; do not clear active rules.
- Build `base_class -> sorted vietnamese_name[]` from `object_labels`, sorting Unicode names ascending for deterministic output.
- A YOLO class with no DB mapping is displayed as `CHƯA XÁC ĐỊNH`; it is still evaluated against every containing zone.
- When multiple Vietnamese names map to one base class, the candidate set contains all names. For display, prefer the first candidate present in the current zone's `target_labels`; otherwise use the first sorted candidate.
- Normalize rule comparisons by trimming and Unicode case-folding; do not remove Vietnamese accents in stored/displayed labels.

| `rule_type` | Detection candidate relation to `target_labels` | Result |
|---|---|---|
| `PROHIBIT_SPECIFIED` | any candidate is targeted | `VIOLATION` |
| `PROHIBIT_SPECIFIED` | no candidate is targeted | `ALLOWED` |
| `ALLOW_SPECIFIED` | any candidate is targeted | `ALLOWED` |
| `ALLOW_SPECIFIED` | no candidate is targeted, including `CHƯA XÁC ĐỊNH` | `VIOLATION` (BR-04) |

### Clip lifecycle

- Insert the OPEN violation immediately with `clip_path = null`, then schedule one clip job for that violation ID.
- At `entered_at + 10 seconds`, call the existing circular buffer so its latest 10-second window corresponds to approximately `[entered_at, entered_at+10s]`.
- File name is `area_<violation-id>.mp4` under `CLIPS_DIR` (default `backend/data/clips` when the worker is started from `backend/`). Encode H.264 baseline/yuv420p MP4 with fast-start metadata so the browser can play the same static `/data/clips/<filename>` URL. Store the relative path `area_<violation-id>.mp4`, not an absolute machine path.
- If the object exits before ten seconds, close the DB row immediately but keep the clip job running until the ten-second deadline, then update only `clip_path`.
- A failed write or interrupted worker leaves `clip_path = null`; the event and close transition remain successful (BR-05).

## Exact wire contracts

### REST — `GET /api/v1/events/area`

- Query: `limit` integer default `50`, range `1..100`; `offset` integer default `0`, minimum `0`; optional `zone_id` UUID; optional `status` exactly `OPEN|CLOSED`.
- Sort: `entered_at DESC`, then `id DESC` for stable pagination.
- Join `zones` to return `zoneName`; never expose raw Prisma relation objects.
- `clipUrl` is `null` when `clip_path` is null; otherwise return the same-origin relative URL `/data/clips/<URL-encoded filename>`. `total` counts rows after the same `zone_id`/`status` filters and before limit/offset.
- Invalid query returns HTTP 400 with foundation error envelope/code `VALIDATION_ERROR`. Unexpected DB failure uses the global sanitized 500 envelope.

```json
{
  "success": true,
  "data": {
    "items": [{
      "id": "uuid",
      "cameraId": "BAI-KIEM",
      "zoneId": "uuid",
      "zoneName": "Khu vực cấm xe máy",
      "objectLabel": "Xe máy",
      "status": "OPEN",
      "enteredAt": "2026-08-18T02:00:00.000Z",
      "exitedAt": null,
      "durationSeconds": null,
      "clipUrl": null
    }],
    "total": 1,
    "limit": 50,
    "offset": 0
  },
  "timestamp": "2026-08-18T02:00:00.000Z"
}
```

### WS — `/ws/feed/area`

- Preserve the foundation frame envelope and send the raw JPEG data URL; browser owns all polygon/bbox overlays. Do not burn annotations into the JPEG.
- Add `zones` only as an optional additive field so Gate feed consumers remain unchanged.

```json
{
  "type": "frame",
  "cameraId": "BAI-KIEM",
  "timestamp": 1787018400000,
  "image": "data:image/jpeg;base64,...",
  "fps": 10.0,
  "detections": [{
    "trackId": 17,
    "bbox": [120, 80, 220, 300],
    "normalized_bbox": [0.1875, 0.1667, 0.3438, 0.625],
    "class": "motorcycle",
    "label": "Xe máy",
    "confidence": 0.91,
    "status": "VIOLATION",
    "zoneMatches": [{
      "zoneId": "uuid",
      "zoneName": "Khu vực cấm xe máy",
      "status": "VIOLATION"
    }]
  }],
  "zones": [{
    "id": "uuid",
    "name": "Khu vực cấm xe máy",
    "polygon": [{"x": 0.1, "y": 0.2}],
    "ruleType": "PROHIBIT_SPECIFIED",
    "targetLabels": ["Xe máy"]
  }]
}
```

- `trackId` is `number|null`. `zoneMatches` contains one entry per containing active zone, sorted by `zoneName` then `zoneId`; a single track may therefore open independent violations in multiple zones. Overall detection `status` is `VIOLATION` when any match violates, `ALLOWED` when it is inside a zone without violating, and `OUTSIDE` when `zoneMatches` is empty. Objects outside all zones are not shown as allowed/violating overlays and are not listed in the event panel.

### WS — `/ws/events/area`

- Emit exactly once on OPEN and exactly once on CLOSED. Payload is flat to preserve the verified `AreaEventMessage` foundation.

```json
{
  "type": "zone_violation",
  "action": "STARTED",
  "id": "uuid",
  "cameraId": "BAI-KIEM",
  "zoneId": "uuid",
  "zoneName": "Khu vực cấm xe máy",
  "objectLabel": "Xe máy",
  "status": "OPEN",
  "enteredAt": "2026-08-18T02:00:00.000Z",
  "exitedAt": null,
  "durationSeconds": null,
  "clipUrl": null
}
```

For close, use the same `id`, `action: "ENDED"`, `status: "CLOSED"`, and populated exit/duration fields.

### WS — `/ws/alerts`

- Emit only for `STARTED`, never for repeated frames or `ENDED`.

```json
{
  "type": "alert",
  "level": "critical",
  "title": "CẢNH BÁO VI PHẠM ZONE",
  "message": "Phát hiện Xe máy trong Khu vực cấm xe máy",
  "cameraId": "BAI-KIEM",
  "timestamp": "2026-08-18T02:00:00.000Z",
  "data": {
    "violationId": "uuid",
    "zoneId": "uuid",
    "zoneName": "Khu vực cấm xe máy",
    "objectLabel": "Xe máy"
  }
}
```

## Implementation sequence

Execute in this order. After each step, update this task's changed-files and next-action fields; do not jump to frontend work.

1. Reconcile current shared files and record any concurrent Gate edits; stop if the same public payload was changed incompatibly.
2. Add Area-owned tracking without changing `YoloDetector.detect()`.
3. Add pure zone parsing/rule evaluation/state-transition modules with no DB or WS side effects.
4. Add the 5-second zone/label snapshot synchronizer and the missing repository helpers for filtered reads, stale OPEN close, and clip-path update.
5. Add `AreaPipeline` orchestration for BAI-KIEM and switch only the BAI-KIEM construction in `main.py`; leave GATE-01 construction unchanged.
6. Extend `StreamEmitter` and WS types additively for optional zones, Area actions, and alert publishing; do not change existing paths or Gate fields.
7. Add `areaEvents.ts`, mount it under `/events/area`, and implement the exact paginated DTO with the foundation response/error helpers.
8. Create `backend/node-api/openapi/area.yaml` matching REST and all three WS payload schemas.
9. Update/create the VS-AREA-VIOLATION section in `docs/backend/backend.md`; do not mark unrelated slices ready.
10. Add focused automated checks, run the required backend verifier set, record fresh evidence, and only then consider `backend_verified`.

## Acceptance criteria

- [x] Python Worker reads BAI-KIEM video stream via OpenCV at >= 5 FPS (Architecture §3)
- [x] YOLO detects objects; class mapping to Vietnamese names via `object_labels` lookup (BR-03)
- [x] Unknown class → label "CHƯA XÁC ĐỊNH", still checked against zone rules (BR-03, BR-04, AC-08)
- [x] Point-in-polygon check for object center against all active zones for BAI-KIEM camera (Architecture §6.2 Flow 4)
- [x] Prohibited object enters zone → open violation event: `zone_violations` with status=OPEN, entered_at, object_label, zone_id, clip buffer starts (BR-06, AC-03)
- [x] While object is inside zone → no duplicate alerts, 1 event per entry/exit (BR-06)
- [x] Object exits zone → close violation: set exited_at, duration_seconds, status=CLOSED, save clip 10s (AC-04)
- [x] Object enters and exits < 1s → no persisted violation, alert, clip, or event-panel row (user acceptance refinement)
- [x] Clip 10s saved from circular buffer starting at entry time; clip_path = NULL if write fails (BR-05)
- [x] Node.js receives violation events from Python WS, pushes to browser via `WS /ws/events/area`
- [x] Node.js pushes floating alert via `WS /ws/alerts` for cross-tab notification (BR-08)
- [x] Raw JPEG frames plus separate zone polygon/object bbox metadata sent via WS; browser renders overlays once
- [x] `GET /api/v1/events/area` returns paginated violations sorted by entered_at DESC (AP-02)
- [x] Zone config and object-label mapping loaded from DB into one atomic snapshot and polled every 5s (BR-07, Architecture §6.2 Flow 1)
- [x] OpenAPI and backend handoff describe only verified behavior for this slice.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| likely | `backend/python-worker/detection/tracked_detector.py` | Area-owned Ultralytics tracking wrapper; preserve foundation detector behavior |
| likely | `backend/python-worker/detection/area_pipeline.py` | BAI-KIEM orchestration: frame → track → classify → zone rule → event/clip/WS |
| likely | `backend/python-worker/zone/zone_checker.py` | Pure polygon normalization, `covers` check, rule matrix, transition state |
| likely | `backend/python-worker/zone/zone_sync.py` | Atomic zone + label snapshot refreshed every 5 seconds |
| exact | `backend/python-worker/db/repositories.py` | Reuse existing zone/violation helpers; add only missing filters/stale-close/clip update |
| exact | `backend/python-worker/main.py` | Instantiate `AreaPipeline` only for BAI-KIEM; preserve GATE-01 pipeline |
| exact | `backend/python-worker/stream/emitter.py` | Add optional `zones` feed metadata and public Area alert emitter |
| exact | `backend/node-api/src/ws/types.ts` | Additive Area feed/action fields matching wire contracts |
| exact | `backend/node-api/src/ws/channels.ts` | Reuse verified area event and alert broadcasts; no route/channel rename |
| likely | `backend/node-api/src/routes/areaEvents.ts` | Area-only REST query, validation, DTO mapping and pagination |
| exact | `backend/node-api/src/routes/index.ts` | Mount `/events/area` without touching other slice mounts |
| likely | `backend/node-api/openapi/area.yaml` | Exact REST and WS schemas for the backend gate |
| likely | `backend/python-worker/tests/test_area_pipeline.py` | Pure rule/tracking/state/clip behavior checks |
| likely | `backend/node-api/src/tests/test_area_events.ts` | REST validation, pagination, sort and response-envelope checks |
| likely | `docs/backend/backend.md` | Partial backend handoff section for this slice |

## Quality baseline

- Baseline reason: R1 Performance, point-in-polygon accuracy, BR-06 no-spam enforcement
- Risk mitigated: Python standard-library unit tests for zone checker + violation state machine; no new test framework dependency
- Required verifier: `unittest` for Area pipeline rules/state + Node typecheck/API contract script + local/test WS integration

## Validation and evidence

- Required evidence kinds: python_unit_output, node_typecheck_output, node_area_api_output, non_production_api_sample, non_production_ws_sample, openapi_handoff_review
- Planned command/procedure, in order:
  1. `python -m unittest discover -s tests -p "test_area_pipeline.py" -v` from `backend/python-worker`.
  2. `npm run typecheck` from `backend/node-api`.
  3. `npx ts-node src/tests/test_area_events.ts` from `backend/node-api`.
  4. Compare implementation, `backend/node-api/openapi/area.yaml`, and the VS-AREA-VIOLATION handoff section field-by-field.
- Pass criteria:
  - All automated commands exit 0 after the latest material backend change.
  - Rule tests cover both rule types, mapped/unmapped labels, polygon boundary, duplicate suppression, sub-second suppression, disappearance close, local-video playback pacing, and clip failure.
  - One entry produces exactly one DB OPEN row, one `STARTED` event and one alert; repeated inside frames produce zero additional inserts/alerts; exit produces one CLOSED update and one `ENDED` event with the same ID.
  - REST pagination/filters/sort and all wire payloads match this task exactly.
  - OpenAPI and backend handoff contain no unimplemented operation or mocked behavior.
- Latest evidence:
  - Evidence ID: EVD-BE-AREA-01
  - Command/procedure: `python tests/test_area_pipeline.py`, `npm run typecheck`, and `NODE_ENV=test npx ts-node src/tests/test_area_events.ts`
  - Context: Local Python unit suite plus Node typecheck. The REST verifier uses the configured Neon database and a disposable Zone/ZoneViolation fixture.
  - Exit/result: Python unit suite exit 0 (17/17 passed, including H.264 MP4 output, intermittent detection/reidentification, boundary-jitter suppression, outside-zone classification, and local-video rewind reset); Node typecheck exit 0. REST verifier did not complete: sandbox rejected Neon TLS credentials and the approved retry timed out after 120 seconds.
  - Fresh: partially fresh; REST/HTTP proof remains unavailable.
  - Summary: The new Area behavior is covered by pure worker tests, but the required REST verifier must be rerun successfully before `backend_verified`.

## Execution record

- Changed files:
  - `backend/python-worker/detection/tracked_detector.py`
  - `backend/python-worker/detection/area_pipeline.py`
  - `backend/python-worker/detection/__init__.py`
  - `backend/python-worker/buffer/circular_buffer.py`
  - `backend/python-worker/requirements.txt`
  - `backend/python-worker/zone/zone_checker.py`
  - `backend/python-worker/zone/zone_sync.py`
  - `backend/python-worker/zone/__init__.py`
  - `backend/python-worker/db/repositories.py`
  - `backend/python-worker/db/__init__.py`
  - `backend/python-worker/stream/emitter.py`
  - `backend/python-worker/main.py`
  - `backend/python-worker/tests/test_area_pipeline.py`
  - `backend/node-api/src/ws/types.ts`
  - `backend/node-api/src/routes/areaEvents.ts`
  - `backend/node-api/src/routes/index.ts`
  - `backend/node-api/src/tests/test_area_events.ts`
  - `backend/node-api/openapi/area.yaml`
  - `docs/backend/backend.md`
  - `docs/backend/tasks/VS-AREA-VIOLATION.md`
- Decisions/assumptions: Standardized on Shapely `covers` on bottom-center point. A confirmed track still uses 3-frame exit grace, while an absent track uses a 12-second reconnect window. Event clips use bundled FFmpeg via `imageio-ffmpeg` to produce browser-compatible H.264 MP4 without changing the public URL contract.
- Blocker: The standalone Node REST verifier has no successful current result because Neon TLS failed in sandbox and the approved retry timed out. Browser acceptance remains user-owned.
- Exact next action: Restart the Python worker so it loads `imageio-ffmpeg`; create a new Area violation, wait at least 10 seconds, then verify one event survives intermittent detection loss and its newly generated clip plays in the browser. Rerun the Node REST verifier successfully before restoring `backend_verified`.

## Stabilization addendum (2026-08-18)

- Fixed the worker startup import, portable Area source configuration, and correct sample-asset lookup.
- Preserved the transition UUID in the inserted `zone_violations` row so CLOSE and clip updates address the same persisted record.
- Removed fallback detections from the production Area pipeline; no violation is fabricated when inference returns no detection.
- Prevented OPEN event, alert, and clip scheduling when the DB insert fails; close failures restore in-memory state for retry.
- Locked circular-buffer reads/writes across the processing and clip-writer threads.
- Tightened Area REST query validation and fixed the route scope to `BAI-KIEM`.
- Static inspection only. No test, typecheck, build, service startup, or browser automation was run after these changes.

## User feedback addendum (2026-08-18)

- Reported false-positive detections on walls/equipment, repeated event rows for one object, and 10-second clips opening at `0:00`.
- Area inference now requests only YOLO `person` and `truck` classes at confidence `0.45`; `truck` remains mapped to the business label `Container` through `object_labels`.
- The zone state machine reconnects a fresh ByteTrack ID to an active violation when the same class/label remains spatially continuous during the grace window, preserving one violation ID until the object exits and re-enters.
- Worker and Node API resolve relative `CLIPS_DIR` from the shared `backend/` root. Clip playback FPS is derived from captured timestamps so slow inference does not compress a ten-second window into a short/empty-looking MP4.
- Formal verification remains intentionally pending; the exact next action is manual browser retest with the configured video, followed by the normal verifier set later.

## Browser clip and continuity stabilization (2026-08-18)

- Replaced the worker's FMP4/mp4v clip writer with H.264 baseline/yuv420p MP4 through `imageio-ffmpeg`, including `faststart` metadata for browser streaming.
- Existing FMP4 historical files are not retroactively transcoded. Generate a new event after restarting the Python worker to test playback.
- Split event closing into two paths: a known track observed outside/allowed closes after 3 frames; an absent track has a 12-second identity-reconnect window.
- Reidentification only moves an active event to a new track ID when the original track is absent and the class/label plus bbox continuity match, preventing duplicate event rows during temporary loss.

## Boundary jitter stabilization (2026-08-18)

- Reported symptom: one visibly continuous person near a polygon edge repeatedly produced `STARTED`/`ENDED` transitions and multiple event rows.
- Decision: opening remains an exact `Polygon.covers(bottom_center)` check. For the same already-open track and still-violating rule result, sustain containment accepts a `0.02` normalized outward polygon buffer (approximately 13px at the configured 640px inference width). A point beyond that buffer continues through the existing 3-frame close path.
- Scope: this only changes Area worker in-memory event continuity; no REST/WS schema, stored rows, or Zone CRUD behavior changes.
- Regression coverage: an event remains one violation through more than three frames of boundary jitter, then emits exactly one `ENDED` after three frames clearly outside the buffer.
- Evidence: `python tests/test_area_pipeline.py` from `backend/python-worker` passed 17/17 on 2026-08-18. No browser test was run.

## Detection presentation stabilization (2026-08-18)

- Area uses the worker's native 640×480 (4:3) feed geometry in the browser so normalized zone polygons and bbox overlays align with the decoded image; the live HUD sits above the image rather than obscuring it.
- The worker emits `OUTSIDE` for detections that do not intersect any zone. The frontend renders no allowed/violation overlay or panel item for this state.
- An in-zone presentation track survives a fully missing detector result for up to 12 seconds and reconnects a spatially continuous replacement ByteTrack ID. A track visibly detected outside a zone is removed immediately; violation persistence still closes it after the normal 3 observed-frame grace.
- Evidence: Node typecheck and frontend production build passed after this change; browser testing remains user-owned.
- On a local MP4 rewind, the first `/ws/feed/area` frame carries optional `sourceReset: true`; the frontend clears only its presentation detection cache before rendering that new playback cycle.

## Playback and event confirmation stabilization (2026-08-18)

- Local MP4 sources now advance by the number of source frames corresponding to the elapsed wall-clock time. This preserves playback speed when a 50 FPS file is processed by the AI loop at a lower FPS.
- A violation remains pending for one continuous second before the `STARTED` transition. A person/object that appears for less than one second is discarded without a database row, WS alert, event-panel row, or clip job.
- Evidence: `python tests/test_area_pipeline.py` passed 20/20 on 2026-08-18. Browser testing remains user-owned.

## YOLO-World detector trial (2026-08-18)

- Area can switch from the original YOLOv8n detector to YOLO-World using `AREA_DETECTOR_KIND=world`; prompts come from `AREA_DETECTOR_CLASSES`.
- Current trial prompts: `person`, `forklift`, `mobile crane`, `car`, `truck`, `bus`, `motorcycle`; the standard YOLO path remains the fallback when the flag is `yolov8`.
- `yolov8s-world.pt` was downloaded locally and loaded successfully. A single-frame smoke check on the configured video returned a `car` detection at confidence `0.713`; no browser acceptance has been claimed.
- Python unit suite remains green at 20/20. Compare live FPS and forklift/crane precision manually before deciding whether to keep or revert this trial.
