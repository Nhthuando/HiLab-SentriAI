# VS-GATE-LIVE Backend Task — Giám sát cổng real-time: LPR + live feed + alert + clip

## Task identity

- Slice ID: VS-GATE-LIVE
- Task ID: BE-GATE-LIVE
- Master plan: `docs/plan/plan.md#vs-gate-live`
- Owner: Phạm Hưng
- Branch: none
- Priority: P0
- Size: L
- Status: pending
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> pending | planned | team1-plan

## Inputs and dependencies

- Requirement sources: Product M1 (§3), BR-01, BR-02, BR-05, AC-01, AC-02, AC-09, Product §7 (Exceptions)
- Consumed fingerprints:
  - `docs/product/product.md` → `871DEC9C`
  - `docs/architecture/architecture.md` → `45F59BC5`
  - `docs/database/database.md` → `F514CB6D`
- Foundation dependencies: FDN-REPO-SCAFFOLD, FDN-DB-MIGRATION, FDN-PYTHON-DB, FDN-WS-PROXY, FDN-PYTHON-STREAM, FDN-API-CONTRACT
- Slice dependencies: none
- Environment dependencies: `NEON_DATABASE_URL`, `VIDEO_GATE_PATH` (path to GATE-01 video file or RTSP URL)

## Contract checkpoint

- API/interface surface:
  - `GET /api/v1/events/gate?limit=N&offset=N&status=KNOWN|STRANGER&plate=:search` — query gate events with pagination and filters
  - `WS /ws/feed/gate` — real-time JPEG frames + bbox metadata from Python→Node→Browser
  - `WS /ws/events/gate` — real-time gate event notifications (new LPR detection)
  - `GET /api/v1/clips/:id/stream` — stream clip MP4
  - `GET /api/v1/crops/:filename` — serve crop image
- Auth and permission: None (single user, no auth per Product §6)
- Request/response/errors:
  - `GET /api/v1/events/gate` → `200: { data: GateEvent[], total: number }` | `500: { error: string }`
  - `WS /ws/feed/gate` → binary JPEG frame + JSON metadata `{ detections: [{plate, confidence, bbox, status}], camera_id, timestamp }`
  - `WS /ws/events/gate` → JSON `{ type: "gate_event", data: GateEvent }`
- Contract source/output: `node-api/openapi/gate.yaml` (planned)
- Gate pass condition: Frontend can fetch paginated gate events, receive live frames with bbox overlays, and receive real-time event push via WS

## Acceptance criteria

- [ ] Python Worker reads GATE-01 video stream via OpenCV at >= 5 FPS (Architecture §3 row 1)
- [ ] YOLO detects vehicles entering IN zone, PaddleOCR/EasyOCR reads plate number (Architecture §6.2 Flow 3)
- [ ] Plate lookup against `registered_vehicles` table returns KNOWN/STRANGER status (BR-02, AP-01)
- [ ] Gate event written to `gate_events` table with: camera_id, lane, license_plate, status, confidence, crop_path, clip_path, timestamp (AC-02)
- [ ] Crop image saved to `data/crops/` and path stored in DB (Product M1)
- [ ] Clip 10s pre-saved from circular buffer to `data/clips/` when event occurs (BR-05, Architecture §6.2 Flow 3)
- [ ] If clip write fails, event still saved with clip_path = NULL (Product §7, BR-05)
- [ ] Annotated JPEG frames + detection metadata sent via WebSocket to Node.js proxy (Architecture §6.2 Flow 2)
- [ ] Node.js proxy forwards frames to connected browser clients via `WS /ws/feed/gate`
- [ ] Node.js pushes new gate events to browser via `WS /ws/events/gate`
- [ ] `GET /api/v1/events/gate` returns paginated events sorted by timestamp DESC (AP-02)
- [ ] Stream disconnect → Python Worker reconnect loop with backoff, sends disconnect event via WS (AC-09, Architecture §8)
- [ ] Low confidence plate still saved with actual confidence value (Product §7)
- [ ] OpenAPI and backend handoff describe only verified behavior for this slice.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| likely | `python-worker/main.py` | Entry point, starts stream readers and WS server |
| likely | `python-worker/stream/reader.py` | OpenCV stream reader with reconnect |
| likely | `python-worker/detection/yolo_detector.py` | YOLO inference wrapper |
| likely | `python-worker/detection/lpr.py` | PaddleOCR/EasyOCR plate reader |
| likely | `python-worker/detection/gate_pipeline.py` | Gate-specific pipeline: detect → OCR → lookup → event |
| likely | `python-worker/zone/polygon.py` | Point-in-polygon using Shapely |
| likely | `python-worker/buffer/circular_buffer.py` | Circular frame buffer for 10s clip |
| likely | `python-worker/buffer/clip_writer.py` | MP4 clip writer from buffer |
| likely | `python-worker/db/client.py` | asyncpg connection pool (from FDN-PYTHON-DB) |
| likely | `python-worker/db/gate_events.py` | Gate event insert/batch helpers |
| likely | `node-api/src/routes/events.ts` | GET /api/v1/events/gate endpoint |
| likely | `node-api/src/ws/proxy.ts` | WebSocket proxy Python→Browser (from FDN-WS-PROXY) |
| likely | `node-api/src/ws/events.ts` | WS event broadcast to browser |
| exact | `frontend/src/components/GateMonitor.tsx` | Frontend component (integration in FE task) |

## Quality baseline

- Baseline reason: R1 Performance (2 stream YOLO concurrent), R3 Clip storage, R4 OCR accuracy — Architecture §4
- Risk mitigated: Python unit tests for LPR pipeline ensure >= 80% accuracy on clear plates (Product §8)
- Required verifier: Python pytest for detection pipeline + manual test with GATE-01 sample video

## Validation and evidence

- Required evidence kinds: unit_test_output, manual_test_screenshot, api_response_sample
- Planned command/procedure: `cd python-worker && pytest tests/` + `curl GET /api/v1/events/gate` + manual WS frame verification
- Pass criteria: Tests pass, gate events appear in DB, frames render in browser
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
- Exact next action: Wait for FDN-REPO-SCAFFOLD and all foundations to complete, then implement Python gate pipeline
