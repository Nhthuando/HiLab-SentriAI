# VS-AREA-VIOLATION Backend Task — Giám sát khu vực: detect + violation event + floating alert

## Task identity

- Slice ID: VS-AREA-VIOLATION
- Task ID: BE-AREA-VIOLATION
- Master plan: `docs/plan/plan.md#vs-area-violation`
- Owner: Hữu Thuận
- Branch: none
- Priority: P0
- Size: L
- Status: pending
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> pending | planned | team1-plan

## Inputs and dependencies

- Requirement sources: Product M2 (§3), BR-03, BR-04, BR-06, BR-08, AC-03, AC-04, AC-08, Product §7 (Exceptions)
- Consumed fingerprints:
  - `docs/product/product.md` → `871DEC9C`
  - `docs/architecture/architecture.md` → `45F59BC5`
  - `docs/database/database.md` → `F514CB6D`
- Foundation dependencies: FDN-REPO-SCAFFOLD, FDN-DB-MIGRATION, FDN-PYTHON-DB, FDN-WS-PROXY, FDN-PYTHON-STREAM, FDN-API-CONTRACT
- Slice dependencies: VS-GATE-LIVE (shared Python stream infrastructure)
- Environment dependencies: `NEON_DATABASE_URL`, `VIDEO_AREA_PATH` (path to BAI-KIEM video file or RTSP URL)

## Contract checkpoint

- API/interface surface:
  - `GET /api/v1/events/area?limit=N&offset=N&zone_id=:id&status=OPEN|CLOSED` — query zone violations with pagination
  - `WS /ws/feed/area` — real-time JPEG frames + object bbox + zone overlay from Python→Node→Browser
  - `WS /ws/events/area` — real-time violation event notifications
  - `WS /ws/alerts` — floating alert notifications for cross-tab (BR-08)
- Auth and permission: None (single user, no auth)
- Request/response/errors:
  - `GET /api/v1/events/area` → `200: { data: ZoneViolation[], total: number }` | `500: { error: string }`
  - `WS /ws/feed/area` → binary JPEG frame + JSON metadata `{ detections: [{label, bbox, status, zone_id}], zones: [{id, name, polygon}], camera_id }`
  - `WS /ws/events/area` → JSON `{ type: "violation_start|violation_end", data: ZoneViolation }`
  - `WS /ws/alerts` → JSON `{ type: "floating_alert", data: { id, title, message, zone, time, camId } }`
- Contract source/output: `node-api/openapi/area.yaml` (planned)
- Gate pass condition: Frontend can fetch violations, receive live area frames with zone overlays, and receive violation/alert push via WS

## Acceptance criteria

- [ ] Python Worker reads BAI-KIEM video stream via OpenCV at >= 5 FPS (Architecture §3)
- [ ] YOLO detects objects; class mapping to Vietnamese names via `object_labels` lookup (BR-03)
- [ ] Unknown class → label "CHƯA XÁC ĐỊNH", still checked against zone rules (BR-03, BR-04, AC-08)
- [ ] Point-in-polygon check for object center against all active zones for BAI-KIEM camera (Architecture §6.2 Flow 4)
- [ ] Prohibited object enters zone → open violation event: `zone_violations` with status=OPEN, entered_at, object_label, zone_id, clip buffer starts (BR-06, AC-03)
- [ ] While object is inside zone → no duplicate alerts, 1 event per entry/exit (BR-06)
- [ ] Object exits zone → close violation: set exited_at, duration_seconds, status=CLOSED, save clip 10s (AC-04)
- [ ] Object enters and exits < 1s → still create violation event (Product §7)
- [ ] Clip 10s saved from circular buffer starting at entry time; clip_path = NULL if write fails (BR-05)
- [ ] Node.js receives violation events from Python WS, pushes to browser via `WS /ws/events/area`
- [ ] Node.js pushes floating alert via `WS /ws/alerts` for cross-tab notification (BR-08)
- [ ] Annotated JPEG frames sent via WS with zone polygon overlays and object bboxes
- [ ] `GET /api/v1/events/area` returns paginated violations sorted by entered_at DESC (AP-02)
- [ ] Zone config loaded from DB; Python Worker polls every 5s or receives WS notification on change (BR-07, Architecture §6.2 Flow 1)
- [ ] OpenAPI and backend handoff describe only verified behavior for this slice.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| likely | `python-worker/detection/area_pipeline.py` | Area-specific pipeline: detect → classify → zone check → violation |
| likely | `python-worker/zone/zone_checker.py` | Zone rule engine: check object against zone rules |
| likely | `python-worker/zone/zone_sync.py` | Poll zone config from DB every 5s |
| likely | `python-worker/db/zone_violations.py` | Zone violation insert/update helpers |
| likely | `python-worker/db/object_labels.py` | Object label lookup helpers |
| likely | `node-api/src/routes/events.ts` | GET /api/v1/events/area endpoint (extend from VS-GATE-LIVE) |
| likely | `node-api/src/ws/alerts.ts` | Floating alert WS broadcast |
| exact | `frontend/src/components/AreaMonitor.tsx` | Frontend component (integration in FE task) |
| exact | `frontend/src/components/FloatingAlert.tsx` | Floating alert component (integration in FE task) |

## Quality baseline

- Baseline reason: R1 Performance, point-in-polygon accuracy, BR-06 no-spam enforcement
- Risk mitigated: Python tests for zone checker + violation state machine
- Required verifier: Python pytest for area pipeline + manual test with BAI-KIEM sample video

## Validation and evidence

- Required evidence kinds: unit_test_output, manual_test_screenshot, api_response_sample
- Planned command/procedure: `cd python-worker && pytest tests/` + `curl GET /api/v1/events/area` + manual WS verification
- Pass criteria: Tests pass, violations appear in DB with correct enter/exit/duration, frames render with zone overlays
- Latest evidence:
  - Evidence ID: none
  - Command/procedure: not_run
  - Context: not_run
  - Exit/result: not_run
  - Fresh: no
  - Summary: not_run

## Execution record

- Changed files: none
- Decisions/assumptions: none
- Blocker: none
- Exact next action: Wait for all foundations and VS-GATE-LIVE shared stream infrastructure, then implement Python area pipeline
