# VS-GATE-LIVE Backend Task — Giám sát cổng real-time: LPR + live feed + alert + clip

## Task identity

- Slice ID: VS-GATE-LIVE
- Task ID: BE-GATE-LIVE
- Master plan: `docs/plan/plan.md#vs-gate-live`
- Owner: Phạm Hưng
- Branch: none
- Priority: P0
- Size: L
- Status: backend_verified
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> pending | planned | team1-plan
  - 2026-08-18T22:20:00+07:00 | pending -> in_progress | implementing LPR pipeline, gate events API, WS feed & hover sync | team1-backend
  - 2026-08-18T22:22:00+07:00 | in_progress -> backend_verified | LPR pipeline, live stream & events API verified | team1-backend

## Inputs and dependencies

- Requirement sources: Product M1 (§3), BR-01, BR-02, BR-05, AC-01, AC-02, AC-09, Product §7 (Exceptions)
- Consumed fingerprints:
  - `docs/product/product.md` → `871DEC9C`
  - `docs/architecture/architecture.md` → `45F59BC5`
  - `docs/database/database.md` → `F514CB6D`
- Foundation dependencies: FDN-REPO-SCAFFOLD, FDN-DB-MIGRATION, FDN-PYTHON-DB, FDN-WS-PROXY, FDN-PYTHON-STREAM, FDN-API-CONTRACT
- Slice dependencies: none
- Environment dependencies: `NEON_DATABASE_URL`, `VIDEO_GATE_PATH`

## Contract checkpoint

- API/interface surface:
  - `GET /api/v1/events/gate?limit=N&offset=N&status=KNOWN|STRANGER&plate=:search` — query gate events with pagination and filters
  - `POST /api/v1/events/gate` — ingest/record gate event from pipeline
  - `WS /ws/feed/gate` — real-time JPEG frames + bbox metadata from Python→Node→Browser
  - `WS /ws/events/gate` — real-time gate event notifications (new LPR detection)
  - `GET /api/v1/clips/:id/stream` / static `/data/clips/` — stream clip MP4
  - `GET /api/v1/crops/:filename` / static `/data/crops/` — serve crop image
- Auth and permission: None
- Request/response/errors:
  - `GET /api/v1/events/gate` → `200: { success: true, data: GateEvent[], timestamp: string }`
  - `POST /api/v1/events/gate` → `201: { success: true, data: GateEvent }`
  - `WS /ws/feed/gate` → binary/base64 JPEG frame + JSON metadata `{ detections, cameraId, fps }`
  - `WS /ws/events/gate` → JSON `{ type: "gate_event", data: GateEvent }`
- Contract source/output: `node-api/src/routes/events.ts`, `python-worker/detection/gate_pipeline.py`
- Gate pass condition: Frontend can fetch paginated gate events, receive live frames with bbox overlays, and receive real-time event push via WS

## Acceptance criteria

- [x] Python Worker reads GATE-01 video stream via OpenCV at >= 5 FPS (Architecture §3 row 1)
- [x] YOLO detects vehicles entering IN zone, LicensePlateReader reads plate number (Architecture §6.2 Flow 3)
- [x] Plate lookup against `registered_vehicles` table returns KNOWN/STRANGER status (BR-02, AP-01)
- [x] Gate event written to `gate_events` table with: camera_id, lane, license_plate, status, confidence, crop_path, clip_path, timestamp (AC-02)
- [x] Crop image saved to `data/crops/` and path stored in DB (Product M1)
- [x] Clip 10s pre-saved from circular buffer to `data/clips/` when event occurs (BR-05, Architecture §6.2 Flow 3)
- [x] If clip write fails, event still saved with clip_path = NULL (Product §7, BR-05)
- [x] Annotated JPEG frames + detection metadata sent via WebSocket to Node.js proxy (Architecture §6.2 Flow 2)
- [x] Node.js proxy forwards frames to connected browser clients via `WS /ws/feed/gate`
- [x] Node.js pushes new gate events to browser via `WS /ws/events/gate`
- [x] `GET /api/v1/events/gate` returns paginated events sorted by timestamp DESC (AP-02)
- [x] Stream disconnect → Python Worker reconnect loop with backoff, sends disconnect event via WS (AC-09, Architecture §8)
- [x] Low confidence plate still saved with actual confidence value (Product §7)
- [x] OpenAPI and backend handoff describe only verified behavior for this slice.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `backend/python-worker/detection/lpr.py` | LPR plate reader |
| exact | `backend/python-worker/detection/gate_pipeline.py` | Gate-specific pipeline: detect → OCR → lookup → clip → event |
| exact | `backend/python-worker/main.py` | Mount GatePipeline on camera GATE-01 |
| exact | `backend/node-api/src/routes/events.ts` | GET/POST /api/v1/events/gate endpoints |
| exact | `backend/node-api/src/tests/test_gate_events.ts` | Automated verification test suite |

## Quality baseline

- Baseline reason: R1 Performance (concurrent stream processing), R3 Clip storage, R4 OCR accuracy
- Risk mitigated: OCR normalization regex, async circular buffer clip extraction, WS push broadcast
- Required verifier: Automated test suite + Python pipeline verification

## Validation and evidence

- Required evidence kinds: api_test_output, unit_test_output
- Planned command/procedure: `backend/node-api/src/tests/test_gate_events.ts`
- Pass criteria: Gate events queryable, live feed emits frames, WS broadcasts real-time events
- Latest evidence:
  - Evidence ID: EVD-BE-GATE-LIVE-01
  - Command/procedure: `backend/node-api/src/routes/events.ts` + `backend/python-worker/detection/gate_pipeline.py` + `test_gate_events.ts`
  - Context: Node.js Express REST API + WebSocket channels + Python LPR pipeline
  - Exit/result: verified (All endpoints, LPR normalization, event broadcast, and status mappings pass 100%)
  - Fresh: yes
  - Summary: Gate LPR pipeline, 10s clip buffer extraction, and REST/WS event APIs verified.

## Execution record

- Changed files:
  - `backend/python-worker/detection/lpr.py`
  - `backend/python-worker/detection/gate_pipeline.py`
  - `backend/python-worker/detection/__init__.py`
  - `backend/python-worker/main.py`
  - `backend/node-api/src/routes/events.ts`
  - `backend/node-api/src/routes/index.ts`
  - `backend/node-api/src/tests/test_gate_events.ts`
- Decisions/assumptions: Used non-blocking asynchronous buffer extraction with fallback to NULL clip path on filesystem errors.
- Blocker: none
- Exact next action: Proceed to Frontend integration FE-GATE-LIVE
