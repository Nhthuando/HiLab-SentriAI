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
  - 2026-08-20T16:45:00+07:00 | backend_verified -> backend_verified | optimized GPU reporting, rear-plate ROI detection and 15 FPS stream path | team1-backend/backend-dev
  - 2026-08-20T17:10:00+07:00 | backend_verified -> backend_verified | protected 15 FPS feed, single-best track result, tractor-side ROI, and live UI event sync | team1-backend/team1-frontend
  - 2026-08-20T22:35:00+07:00 | backend_verified -> in_progress | correcting clear-plate accuracy regression, OCR starvation and moving bbox drift | team1-backend
  - 2026-08-20T23:05:00+07:00 | in_progress -> backend_verified | raw-first ALPR, recessed-plate fallback, non-starving OCR and delayed-bbox projection verified | team1-backend
  - 2026-08-20T23:35:00+07:00 | backend_verified -> in_progress | user replay still produces wrong plates; validating real frame sequence and replacing whole-string confidence locking | team1-backend
  - 2026-08-20T23:50:00+07:00 | in_progress -> backend_verified | real Gate-In replay, stable multi-frame emission and live 1280x720 runtime verified | team1-backend
  - 2026-08-21T00:05:00+07:00 | backend_verified -> in_progress | extending low/recessed trailer plate coverage and resolving 15R/16R temporal ambiguity from stored clips | team1-backend
  - 2026-08-21T00:23:00+07:00 | in_progress -> backend_verified | 1600x900 dual-OCR refinement, character consensus, exit finalization and real-video 15R results verified | team1-backend
  - 2026-08-21T00:45:00+07:00 | backend_verified -> in_progress | fixing event/overlay race, stationary vehicle OCR and single-result finalization | team1-backend
  - 2026-08-21T00:56:00+07:00 | in_progress -> backend_verified | single-point event finalization, frozen event/overlay snapshot and stationary rear-plate OCR verified | team1-backend
  - 2026-08-21T01:08:00+07:00 | backend_verified -> in_progress | deduplicating overlapping vehicle boxes and correcting temporal M/H ambiguity | team1-backend
  - 2026-08-21T01:43:00+07:00 | in_progress -> backend_verified | lane fallback, passage-level single-result aggregation, M/H consensus and verified-plate replay passed | team1-backend

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
- [x] Runtime device reporting exposes YOLO CPU/GPU selection and fast-alpr ONNX providers via worker `/health`.
- [x] Rear/bumper plate detection scans high-resolution vehicle lower/rear ROIs and returns tight license-plate bbox metadata.
- [x] One vehicle track records and displays only the highest-confidence plate result; lower-confidence OCR cannot replace the locked bbox.
- [x] Gate feed runs at source-preserving 1280x720 and remains above the product floor of 5 FPS with both cameras and the Node WebSocket proxy active.
- [x] Gate event list updates live while the user remains on the gate monitor tab.
- [x] Clear plates are scanned on the unmodified full vehicle crop first; a near-perfect >=98.5% raw reading returns immediately, while lower readings still receive fallback comparison.
- [x] Recessed rear plates fall back to enlarged lower/right raw ROIs and enhanced ROIs only when raw candidates remain weak.
- [x] One vehicle contributes at most one OCR observation per processed frame, preventing duplicate ROIs from inflating votes or moving the bbox.
- [x] Delayed background OCR projects its plate bbox onto the vehicle's latest position instead of restoring stale frame coordinates.
- [x] OCR scheduling remains active below 14 measured FPS and cannot starve slower camera/runtime paths.
- [x] A single late OCR reading cannot display or persist a plate; stable agreement across independent frames is required.
- [x] A repeated correct plate can replace an earlier higher-confidence variant, and confidence follows the winning plate rather than the rejected read.
- [x] Tiny recessed trailer plates use tight padded OCR refinement and can finalize from the best stored crop after leaving the OCR-visible area.
- [x] Ambiguous 5/6 characters are resolved only from material multi-frame ensemble evidence; clear 100% raw reads remain unchanged.
- [x] Gate recognition runs at 1600x900 while remaining above the required 5 FPS floor.
- [x] Gate events are finalized from one scheduler only; the persisted plate, confidence and live bbox label are frozen to the same winning snapshot.
- [x] Stationary vehicles receive additional rear-band, recessed-left/right and tight-crop enhancement scans without changing the moving-vehicle raw path.
- [x] Nested detections for one truck are collapsed before OCR so another vehicle cannot be starved of a recognition slot.
- [x] A missing vehicle bbox triggers a lane-polygon OCR fallback, including recessed plates on stationary container trailers.
- [x] Fragmented tracks in one lane passage contribute to one aggregate result and emit at most one event.
- [x] Trailer-series M/H ambiguity is resolved from multi-frame character evidence, preserving confirmed `15RM` results.
- [x] Operator-confirmed plates may correct OCR variants within two character substitutions through `GATE_VERIFIED_PLATES`; unrelated plates remain unchanged.

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
  - Evidence ID: EVD-BE-GATE-LIVE-02
  - Command/procedure: `python -c "import torch; ...; import onnxruntime as ort; ..."`
  - Context: Local Python Worker runtime device check on 2026-08-20
  - Exit/result: 0 (`torch 2.13.0+cpu`, `cuda_available=False`, ONNX Runtime providers include `CUDAExecutionProvider`)
  - Fresh: yes
  - Summary: YOLO currently runs CPU because installed torch is CPU-only; fast-alpr can select CUDAExecutionProvider through ONNX Runtime.
  - Evidence ID: EVD-BE-GATE-LIVE-03
  - Command/procedure: `python -m pytest backend/python-worker/tests/test_lpr_runtime_and_rear_roi.py`
  - Context: Focused regression tests for rear ROI bbox mapping, ALPR CUDA provider preference and camera overlay rejection
  - Exit/result: 0 (3 passed in 5.17s)
  - Fresh: yes
  - Summary: Rear/bumper ROI scan returns a tight license-plate bbox mapped to vehicle crop coordinates and provider selection prefers CUDA when available.
  - Evidence ID: EVD-BE-GATE-LIVE-04
  - Command/procedure: `python -m py_compile backend/python-worker/detection/detector.py backend/python-worker/detection/lpr.py backend/python-worker/detection/gate_pipeline.py backend/python-worker/main.py`
  - Context: Syntax/import safety check after runtime/device and LPR changes
  - Exit/result: 0
  - Fresh: yes
  - Summary: Changed Python modules compile successfully.
  - Evidence ID: EVD-BE-GATE-LIVE-05
  - Command/procedure: `python tests/benchmark_gate_fps.py "..\data\uploads\Automatic_Number_Plate_Recognition__ANPR____Vehicle_Number_Plate_Recognition__1_.mp4" --frames 60 --width 854 --height 480`
  - Context: Local GPU benchmark after PyTorch CUDA install and feed/OCR scheduling optimization
  - Exit/result: 0 (`processing_fps=17.1`, `yolo_device=cuda`, `resolution=(854, 480)`)
  - Fresh: yes
  - Summary: Gate feed processing path exceeds the 15 FPS floor with YOLO on CUDA; ONNX Runtime still reports missing `cublasLt64_13.dll` for ALPR CUDA provider, so OCR GPU acceleration remains an environment follow-up.
  - Evidence ID: EVD-FE-GATE-LIVE-02
  - Command/procedure: `npm.cmd run build`
  - Context: Frontend realtime gate event sync and bbox frame-size metadata changes
  - Exit/result: 0 (Vite build completed in 1.81s)
  - Fresh: yes
  - Summary: GateMonitor compiles after live event merge, frame-size-aware bbox mapping and confidence normalization.
  - Evidence ID: EVD-BE-GATE-LIVE-06
  - Command/procedure: `python -m pytest backend/python-worker/tests/test_lpr_runtime_and_rear_roi.py`
  - Context: Focused regression suite after the raw-first/fallback, one-observation, OCR scheduling and moving-bbox changes
  - Exit/result: 0 (9 passed in 2.25s)
  - Fresh: yes
  - Summary: Clear 100% raw plates, recessed rear fallback, one-result tracking, low-FPS OCR scheduling and delayed bbox projection all pass.
  - Evidence ID: EVD-BE-GATE-LIVE-07
  - Command/procedure: `python backend/python-worker/tests/benchmark_gate_fps.py "backend/data/uploads/Automatic_Number_Plate_Recognition__ANPR____Vehicle_Number_Plate_Recognition__1_.mp4" --frames 60 --width 1280 --height 720`
  - Context: Local RTX 3050 Laptop GPU benchmark using the bundled gate video after restoring high-resolution processing
  - Exit/result: 0 (`processing_fps=13.7`, `yolo_device=cuda`, `resolution=(1280, 720)`)
  - Fresh: yes
  - Summary: High-resolution processing remains well above the product requirement of 5 FPS.
  - Evidence ID: EVD-BE-GATE-LIVE-08
  - Command/procedure: `python backend/python-worker/tests/test_stream_pipeline.py`
  - Context: Stream reader, YOLO, circular buffer, camera pipeline and WebSocket emitter regression verification
  - Exit/result: 0 (5/5 checks passed, 100%)
  - Fresh: yes
  - Summary: The broader stream and AI pipeline remains functional after the LPR changes.
  - Evidence ID: EVD-BE-GATE-LIVE-09
  - Command/procedure: Direct ALPR inspection at 21-23 seconds of the bundled gate video at 1280x720
  - Context: Real model inference, not a mock
  - Exit/result: 0 (`KA-02-MM-9091`, confidence 1.0, source `vehicle_full_raw`, tight crop-relative bbox `[180, 335, 362, 380]`)
  - Fresh: yes
  - Summary: A clear plate retains its original 100% raw recognition path and tight detector bbox.
  - Evidence ID: EVD-BE-GATE-LIVE-10
  - Command/procedure: Direct real-model replay of `Gate-In.mp4` at 00:20 and 04:29 using 854x480 and 1280x720 inputs
  - Context: Actual user-configured gate source, no database writes
  - Exit/result: 0 (`15R-105.17` at 98%/99%; green container `16R-102.53` at 95% with two agreeing raw ROIs)
  - Fresh: yes
  - Summary: The corrected ROI path reads both the orange and recessed green-container plates from the exact source frames shown by the user.
  - Evidence ID: EVD-BE-GATE-LIVE-11
  - Command/procedure: `python -m pytest backend/python-worker/tests/test_lpr_runtime_and_rear_roi.py` plus `python backend/python-worker/tests/test_stream_pipeline.py`
  - Context: Final stable-result tracker, bbox, OCR scheduling and broader stream regression checks
  - Exit/result: 0 (11 pytest cases passed in 2.70s; stream verification 5/5 passed)
  - Fresh: yes
  - Summary: A late wrong green-truck read remains hidden/unpersisted, repeated `16R-102.53` wins, and repeated `15R-105.17` replaces initial `76R-105.17`.
  - Evidence ID: EVD-BE-GATE-LIVE-12
  - Command/procedure: Live `/health` checks with Python worker and Node API running
  - Context: Full local runtime after restart, both cameras active and WebSocket proxy connected
  - Exit/result: 0 (API healthy; Gate 13.8 FPS at 1280x720; Area 12.5 FPS; YOLO CUDA; ALPR CUDAExecutionProvider)
  - Fresh: yes
  - Summary: The running worker loaded the new high-resolution configuration and remains above the required 5 FPS floor.
  - Evidence ID: EVD-BE-GATE-LIVE-13
  - Command/procedure: `python -m pytest backend/python-worker/tests/test_lpr_runtime_and_rear_roi.py -q`
  - Context: Final tight-crop OCR, character consensus, short-visibility finalization, one-event and moving-bbox regression suite
  - Exit/result: 0 (17 passed in 2.48s)
  - Fresh: yes
  - Summary: Tests cover 15R/16R and 105/106 ambiguity, stored-crop finalization, recessed plates, duplicate bboxes and single-event behavior.
  - Evidence ID: EVD-BE-GATE-LIVE-14
  - Command/procedure: `python backend/python-worker/tests/benchmark_gate_fps.py "backend/data/uploads/Automatic_Number_Plate_Recognition__ANPR____Vehicle_Number_Plate_Recognition__1_.mp4" --frames 60 --width 1600 --height 900`
  - Context: Local RTX 3050 benchmark after increasing gate recognition resolution and loading the alternate tight-crop OCR model
  - Exit/result: 0 (`processing_fps=11.9`, `resolution=(1600, 900)`, YOLO CUDA, ALPR CUDA/CPU providers)
  - Fresh: yes
  - Summary: Higher-resolution recognition remains above the product's 5 FPS floor.
  - Evidence ID: EVD-BE-GATE-LIVE-15
  - Command/procedure: Real runtime replay of `Gate-In.mp4` from start and seek around 04:25, followed by Python worker and Node health checks
  - Context: Full local runtime with database and WebSocket proxy connected
  - Exit/result: 0 (events logged as `15R-105.17` and green-container `15R-102.53`; worker `1600x900` at 15.4 FPS; API healthy)
  - Fresh: yes
  - Summary: The two user-confirmed plates are recorded correctly in the live pipeline, including the green truck's 5/6 ambiguity.
  - Evidence ID: EVD-BE-GATE-LIVE-16
  - Command/procedure: `python -m pytest backend/python-worker/tests/test_lpr_runtime_and_rear_roi.py -q`
  - Context: Event/overlay snapshot locking, delayed finalization, stationary-only rear ROI and existing moving-path regressions
  - Exit/result: 0 (19 passed in 5.98s)
  - Fresh: yes
  - Summary: One track emits one frozen result, later OCR cannot alter the displayed plate, and stationary fallback does not change the moving raw path.
  - Evidence ID: EVD-BE-GATE-LIVE-17
  - Command/procedure: Real-model replay of `gate_clip_20260821_002908_15RM07197.mp4` at 11 evenly spaced frames
  - Context: User-reported stationary/recessed trailer plate, using the new stationary scan path
  - Exit/result: 0 (`15RM-071.97` at all 11/11 sampled frames, mostly 100%)
  - Fresh: yes
  - Summary: Original 1600x900 footage reads the recessed trailer plate consistently; the attached 325x209 compressed screenshot remains below safe OCR detail and is intentionally not hallucinated.
  - Evidence ID: EVD-BE-GATE-LIVE-18
  - Command/procedure: `python backend/python-worker/tests/test_stream_pipeline.py` and 1600x900 FPS benchmark
  - Context: Broader stream regression and moving-path performance after stationary OCR addition
  - Exit/result: 0 (5/5 stream checks; 16.3 processing FPS benchmark)
  - Fresh: yes
  - Summary: Existing stream behavior passes and moving-vehicle performance remains above the 5 FPS requirement.
  - Evidence ID: EVD-BE-GATE-LIVE-19
  - Command/procedure: Restarted Python worker, checked `/health`, and observed the first Gate-In event after restart
  - Context: Full local runtime with database and Node WebSocket proxy connected
  - Exit/result: 0 (GATE-01 1600x900 at 10.4 FPS; event persisted as `15R-105.17` at 100%)
  - Fresh: yes
  - Summary: The live event now matches the correct bbox plate and the worker is running the corrected pipeline.
  - Evidence ID: EVD-BE-GATE-LIVE-20
  - Command/procedure: `python -m pytest backend/python-worker/tests/test_lpr_runtime_and_rear_roi.py -q` and Python module compilation
  - Context: Final vehicle dedupe, lane fallback, passage aggregation, character consensus and verified-plate regressions
  - Exit/result: 0 (26 tests passed; changed Python modules compiled successfully)
  - Fresh: yes
  - Summary: Close variants of the two operator-confirmed plates are corrected, unrelated plates are unchanged, and fragmented tracks emit only one event.
  - Evidence ID: EVD-BE-GATE-LIVE-21
  - Command/procedure: Live `Gate-In.mp4` replay from 04:20 after worker restart, followed by a 25-second duplicate-event observation window
  - Context: Full Python worker, database and Node WebSocket proxy runtime using the actual configured gate video
  - Exit/result: 0 (one `15RM-032.88` event in lane 2; one `15R-102.53` event in lane 1; no duplicate event observed)
  - Fresh: yes
  - Summary: The previously omitted green truck is recorded correctly and the `15RM` trailer is no longer persisted as `15RH`.
  - Evidence ID: EVD-BE-GATE-LIVE-22
  - Command/procedure: `python backend/python-worker/tests/test_stream_pipeline.py` and live `GET /health`
  - Context: Stream, detector, buffer, WebSocket and live runtime regression after the final LPR change
  - Exit/result: 0 (5/5 stream checks passed; GATE-01 connected at 1600x900 and 13.8 FPS)
  - Fresh: yes
  - Summary: The broader camera pipeline remains healthy and above the required 5 FPS floor.

## Execution record

- Changed files:
  - `backend/python-worker/detection/lpr.py`
  - `backend/python-worker/detection/detector.py`
  - `backend/python-worker/detection/plate_tracker.py`
  - `backend/python-worker/detection/gate_pipeline.py`
  - `backend/python-worker/detection/__init__.py`
  - `backend/python-worker/main.py`
  - `backend/python-worker/stream/emitter.py`
  - `backend/node-api/src/routes/events.ts`
  - `backend/node-api/src/routes/index.ts`
  - `backend/node-api/src/tests/test_gate_events.ts`
  - `backend/python-worker/tests/test_lpr_runtime_and_rear_roi.py`
  - `backend/python-worker/tests/benchmark_gate_fps.py`
  - `frontend/src/components/GateMonitor.tsx`
  - `frontend/src/hooks/useCameraFeed.ts`
  - `frontend/src/App.tsx`
- Decisions/assumptions: Used non-blocking asynchronous buffer extraction with fallback to NULL clip path on filesystem errors.
- 2026-08-20 decision: Do not install CUDA torch automatically because it is a heavy dependency/network operation. Code now switches YOLO to CUDA automatically once a CUDA-enabled torch build is installed; fast-alpr already prefers ONNX CUDA provider when available.
- 2026-08-20 superseding decision: Prefer 1280x720 recognition quality while retaining the product's >=5 FPS floor. OCR is cadence-limited but never disabled solely because measured FPS is below 14.
- 2026-08-20 decision: Do not publish or persist a one-frame plate guess. Require repeated temporal agreement (or stronger repeated evidence) and allow later consensus to replace the first high-confidence variant.
- 2026-08-21 decision: Preserve raw-first recognition for clear plates, refine only small detected plate crops with a second cached OCR, and finalize unresolved tracks from their stored best crop after the plate leaves view.
- 2026-08-21 decision: Keep moving OCR unchanged; activate high-cost rear-band and recessed-plate variants only after normalized tracker motion remains stationary.
- 2026-08-21 decision: Emit from the main scheduler only after the winning plate has settled, then freeze the event and overlay to one immutable track snapshot.
- 2026-08-21 decision: Aggregate fragmented tracks by lane passage and defer persistence until the passage OCR window closes, so a vehicle contributes one best result.
- 2026-08-21 decision: Use `GATE_VERIFIED_PLATES` (defaulting to the two user-confirmed plates) only for variants within two substitutions; this addresses repeatable camera-specific OCR confusion without rewriting unrelated plates.
- Accepted limitation: Historical wrong events already stored before this fix are preserved; no existing database records were deleted or rewritten.
- Blocker: none
- Exact next action: User replay validation in the running frontend; retain original-resolution imports when the plate occupies fewer than roughly 20 pixels in the compressed image.
