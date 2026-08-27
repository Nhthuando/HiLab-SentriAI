# Main and Gate Live Semantic Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the active merge so BAI-KIEM, GATE-01, and Vehicle Settings retain their verified behavior, accuracy, and runtime performance.

**Architecture:** Resolve files by semantic ownership: `main` owns BAI-KIEM behavior, `origin/feature/vs-gate-live` owns GATE-01 recognition behavior, and shared camera/detection/stream contracts are merged additively. Preserve backward-compatible seconds and milliseconds playback endpoints so existing Area and Gate consumers do not need behavioral rewrites.

**Tech Stack:** Python 3.11+/FastAPI/OpenCV/Ultralytics/FastALPR, Node.js/Express/Prisma/PostgreSQL, React 19/TypeScript/Vite, WebSocket.

## Global Constraints

- Do not abort, restart, or replace the active merge.
- Do not accept a whole conflicted file without reviewing the other branch's delta.
- BAI-KIEM defaults remain `1280x720` with environment-driven FPS and `main` Area behavior.
- GATE-01 defaults remain `1600x900` at 15 FPS with the feature branch's LPR behavior.
- Both pipelines activate on subscriber demand and pause without subscribers.
- Preserve database contents; do not execute cleanup scripts or destructive migrations.
- Keep the merge uncommitted until the user reviews the resolved diff and verification evidence.
- Because Git is already in a conflicted merge, use staging checkpoints instead of intermediate commits; the final merge commit is a single user-approved action.

---

### Task 1: Establish the merge baseline and restore regression-test ownership

**Files:**
- Modify: `.gitignore`
- Restore/modify: `backend/python-worker/tests/test_gate_live_e2e.py`
- Restore/modify: `backend/python-worker/tests/test_volvo_lpr.py`
- Verify: all paths returned by `git diff --name-only --diff-filter=U`

**Interfaces:**
- Consumes: merge stages `:1:` (base), `:2:` (`main`), and `:3:` (`origin/feature/vs-gate-live`).
- Produces: union ignore rules and retained Gate regression coverage without resolving production behavior prematurely.

- [ ] **Step 1: Record the exact unresolved baseline**

```powershell
git status --short
git diff --name-only --diff-filter=U
git rev-parse HEAD MERGE_HEAD
```

Expected: `HEAD=b0debc853da375f302bba3bc54f25e3ea85400b6`, `MERGE_HEAD=88b671b515579b6d61713bc37f8624cb1ac256eb`, and the known conflict set remains visible.

- [ ] **Step 2: Resolve `.gitignore` as a normalized union**

Keep all unique rules from both stages, with one entry per rule family. Preserve ignores for `.env`, Python/Node caches, local runtime data, crops, clips, model weights, local media, and build output.

```powershell
git show :2:.gitignore
git show :3:.gitignore
rg -n "^(<<<<<<<|=======|>>>>>>>)" .gitignore
```

Expected after editing: no markers and no previously ignored runtime artifact becomes tracked.

- [ ] **Step 3: Restore the two modify/delete Gate tests from stage 3**

Use the feature versions as the starting assertions because `main` deleted these files while the feature branch continued modifying them. Update imports/assertions only if the merged supported contract requires it.

```powershell
git show :3:backend/python-worker/tests/test_gate_live_e2e.py
git show :3:backend/python-worker/tests/test_volvo_lpr.py
```

- [ ] **Step 4: Stage only the three resolved baseline files**

```powershell
git add .gitignore backend/python-worker/tests/test_gate_live_e2e.py backend/python-worker/tests/test_volvo_lpr.py
git diff --cached --check
```

Expected: no whitespace errors and the modify/delete conflicts are cleared.

---

### Task 2: Merge shared Python detection and stream infrastructure

**Files:**
- Modify: `backend/python-worker/detection/detector.py`
- Modify: `backend/python-worker/detection/tracked_detector.py`
- Modify: `backend/python-worker/stream/reader.py`
- Modify: `backend/python-worker/stream/emitter.py`
- Modify: `backend/python-worker/requirements.txt`
- Test: `backend/python-worker/tests/test_stream_pipeline.py`
- Test: `backend/python-worker/tests/test_stream_emitter.py`
- Test: `backend/python-worker/tests/test_area_pipeline.py`
- Test: `backend/python-worker/tests/test_lpr_runtime_and_rear_roi.py`

**Interfaces:**
- Consumes: AreaPipeline's `TrackedYoloDetector`, GatePipeline's `YoloDetector`, seconds-based Area playback, millisecond Gate playback, and both frame payload shapes.
- Produces: `YoloDetector.runtime_info()`, `StreamReader.get_playback_state()`, `request_seek(seconds)`, `preview_frame(seconds)`, `get_playback_status()`, `seek_ms(milliseconds)`, `get_timecode()`, and one additive `StreamEmitter.emit_frame()`.

- [ ] **Step 1: Merge `YoloDetector` without weakening either pipeline**

Retain `main`'s model resolution order and restricted COCO mapping. Add the feature branch's device selection, runtime reporting, CUDA-to-CPU load fallback, opt-in high-angle aliases, and device-qualified inference.

```python
class YoloDetector:
    TOP_VIEW_VEHICLE_ALIASES = {"parking meter", "toilet", "suitcase"}

    def runtime_info(self) -> Dict[str, Any]:
        return {
            "model": os.path.basename(str(self.model_path)),
            "device": self.device,
            "deviceReason": self.device_reason,
        }
```

Keep the constructor signature `__init__(model_path: Optional[str] = None, conf_threshold: float = 0.25, target_classes: Optional[List[str]] = None)`. The default model remains `yolo11n.pt`; `SENTRIAI_BASE_YOLO_MODEL` and `YOLO_MODEL_PATH` still override it.

- [ ] **Step 2: Keep the Area tracker and apply the Gate device delta**

Use `main`'s full `TrackedYoloDetector` implementation, then retain these feature deltas: YOLO11 naming/default and `device=self.device` in tracked inference. Do not replace the 1,500-line Area tracker with the feature branch's old 106-line version.

```python
results = self.model.track(
    frame,
    conf=threshold,
    classes=class_ids,
    persist=True,
    tracker=self.tracker,
    device=self.device,
    verbose=False,
)
```

- [ ] **Step 3: Merge both playback contracts into `StreamReader`**

Keep `main`'s playback lock, real-time local-video pacing, pending seconds seek, preview capture, source context, and loop-reset flag. Retain the Gate branch's maximum three-frame skip and compatibility methods.

```python
def get_playback_status(self) -> dict:
    state = self.get_playback_state()
    return {
        "seekable": bool(state.get("seekable", False)),
        "positionMs": int(float(state.get("positionSeconds", 0.0)) * 1000),
        "durationMs": int(float(state.get("durationSeconds", 0.0)) * 1000),
    }

def seek_ms(self, position_ms: float) -> dict:
    self.request_seek(max(0.0, float(position_ms)) / 1000.0)
    return self.get_playback_status()
```

Keep the existing `get_playback_state()`, `request_seek(position_seconds)`, `preview_frame(position_seconds)`, and `get_timecode()` implementations from the merged Main reader. `seek_ms()` delegates to the synchronized seconds seek path so it cannot race `read_frame()`.

- [ ] **Step 4: Merge the frame payload additively**

```python
async def emit_frame(
    self,
    camera_id: str,
    image_base64: str,
    detections: List[Dict[str, Any]],
    fps: float = 10.0,
    zones: Optional[List[Dict[str, Any]]] = None,
    source_reset: bool = False,
    timecode: Optional[str] = None,
    frame_width: Optional[int] = None,
    frame_height: Optional[int] = None,
) -> bool:
    payload = {
        "type": "frame",
        "cameraId": camera_id,
        "timestamp": int(time.time() * 1000),
        "image": image_base64,
        "fps": round(fps, 1),
        "detections": detections,
    }
    if zones is not None:
        payload["zones"] = zones
    if source_reset:
        payload["sourceReset"] = True
    if timecode is not None:
        payload["timecode"] = timecode
    if frame_width is not None and frame_height is not None:
        payload["frameWidth"] = frame_width
        payload["frameHeight"] = frame_height
    return await self._send_json(f"/ws/publish/feed/{camera_id}", payload)
```

Emit `zones`, `sourceReset`, `timecode`, `frameWidth`, and `frameHeight` only under their established conditions. Serialize before opening/reopening a socket so DTO errors cannot create reconnect storms.

- [ ] **Step 5: Merge Python dependencies as a compatible union**

Use `ultralytics>=8.3.0,<9.0.0`; keep `lap==0.5.13`, CUDA PyTorch markers, `fast-alpr==0.4.0`, `onnxruntime==1.29.0`, `imageio-ffmpeg>=0.6.0,<0.7.0`, and all shared framework/database dependencies.

```text
ultralytics>=8.3.0,<9.0.0
lap==0.5.13
fast-alpr==0.4.0
onnxruntime==1.29.0
imageio-ffmpeg>=0.6.0,<0.7.0
```

- [ ] **Step 6: Run shared-infrastructure verification**

```powershell
python -m py_compile backend/python-worker/detection/detector.py backend/python-worker/detection/tracked_detector.py backend/python-worker/stream/reader.py backend/python-worker/stream/emitter.py
python -m pytest backend/python-worker/tests/test_stream_pipeline.py backend/python-worker/tests/test_stream_emitter.py -q
```

Expected: compilation and tests pass with no conflict-marker syntax errors.

- [ ] **Step 7: Stage the shared Python resolution**

```powershell
git add backend/python-worker/detection/detector.py backend/python-worker/detection/tracked_detector.py backend/python-worker/stream/reader.py backend/python-worker/stream/emitter.py backend/python-worker/requirements.txt
git diff --cached --check
```

---

### Task 3: Preserve Gate recognition while integrating Main lifecycle and vehicle data

**Files:**
- Modify: `backend/python-worker/detection/gate_pipeline.py`
- Modify: `backend/python-worker/detection/plate_tracker.py`
- Verify: `backend/python-worker/detection/lpr.py`
- Verify: `backend/python-worker/db/repositories.py`
- Test: `backend/python-worker/tests/test_lpr_runtime_and_rear_roi.py`
- Test: `backend/python-worker/tests/test_gate_event_vehicle_registration.py`
- Test: `backend/python-worker/tests/test_gate_live_e2e.py`
- Test: `backend/python-worker/tests/test_volvo_lpr.py`

**Interfaces:**
- Consumes: Gate branch LPR/tracker/passage state machines and `main` vehicle repository functions.
- Produces: validated GATE-01 events, UNKNOWN filtering, deduplicated passages, live overlays, configurable confidence, database-owned KNOWN/STRANGER state, activation, and playback reset.

- [ ] **Step 1: Use the feature Gate pipeline as the behavioral base**

Preserve its plate candidate selection, temporal consensus, visual bbox tracking, lane fallback, confidence threshold, UNKNOWN filtering, passage deduplication, event freezing, timecode, source dimensions, and reset behavior.

- [ ] **Step 2: Apply `main` vehicle and lifecycle behavior additively**

Retain imports and calls for `get_all_registered_plates`, `get_vehicle_status_by_plate`, and `register_vehicle`. A persisted user label is authoritative; an unregistered successfully persisted known plate is registered as `STRANGER`; an UNKNOWN/filtered event does not create a Vehicle Settings row.

```python
def get_playback_state(self) -> Dict[str, Any]:
    return self.reader.get_playback_state()

def request_seek(self, position_seconds: float) -> Dict[str, Any]:
    state = self.reader.request_seek(position_seconds)
    if state.get("seekable"):
        self.buffer.clear()
        self.reset_tracking_state()
        self._fps_counter = 0
        self._last_fps_calc = time.time()
        self.fps_measured = self.target_fps
    return state

def pause(self) -> None:
    self._active = False
```

Keep the feature implementation of `reset_tracking_state()`. `start()` sets `_active=True`, resets FPS counters, and creates `_loop()` only when it is not already running. `_sync_registered_vehicle_statuses()` refreshes the immutable plate/status snapshot, and `resolve_vehicle_status()` performs exact then punctuation-normalized lookup before returning `STRANGER`.

- [ ] **Step 3: Use the feature PlateTracker and apply Main's live status semantics**

Preserve the feature branch's full visual tracking and temporal voting implementation. Allow authoritative database status refreshes to update an existing track, and default a recognized unregistered plate to `STRANGER`, not a hard-coded sample classification.

```python
if status:
    track.status = status

status=status or ("STRANGER" if plate_text else "SCANNING")
```

- [ ] **Step 4: Compile and run focused Gate regression tests**

```powershell
python -m py_compile backend/python-worker/detection/gate_pipeline.py backend/python-worker/detection/plate_tracker.py backend/python-worker/detection/lpr.py backend/python-worker/db/repositories.py
python -m pytest backend/python-worker/tests/test_lpr_runtime_and_rear_roi.py backend/python-worker/tests/test_gate_event_vehicle_registration.py backend/python-worker/tests/test_volvo_lpr.py -q
```

Expected: all recognition, bbox lifecycle, passage, UNKNOWN, confidence, CUDA-provider, and vehicle-registration assertions pass.

- [ ] **Step 5: Stage the Gate backend resolution**

```powershell
git add backend/python-worker/detection/gate_pipeline.py backend/python-worker/detection/plate_tracker.py
git diff --cached --check
```

---

### Task 4: Merge worker lifecycle and camera HTTP compatibility

**Files:**
- Modify: `backend/python-worker/main.py`
- Modify: `backend/node-api/src/routes/cameras.ts`
- Modify: `frontend/src/api/cameras.ts`
- Verify: `frontend/src/api/zones.ts`
- Test: `backend/node-api/src/tests/test_api_contract.ts`

**Interfaces:**
- Consumes: both pipelines and both frontend playback clients.
- Produces: subscriber activation, Area preview/seconds seek, Gate millisecond seek compatibility, Gate confidence configuration, snapshot, and health/runtime reporting.

- [ ] **Step 1: Merge worker initialization with camera-specific defaults**

```python
gate_target_fps = float(os.getenv("GATE_TARGET_FPS", "15.0"))
area_target_fps = float(os.getenv("AREA_TARGET_FPS", "25.0"))

gate_pipeline = GatePipeline(
    camera_id="GATE-01",
    source=gate_source,
    target_fps=gate_target_fps,
    resolution=(1600, 900),
)
area_pipeline = AreaPipeline(
    camera_id="BAI-KIEM",
    source=area_source,
    target_fps=area_target_fps,
    resolution=(1280, 720),
)
await area_pipeline.prepare()
```

Register both pipelines but do not start either loop during lifespan startup. Preserve activation, Area event reset, Area clip, snapshot, and preview routes.

- [ ] **Step 2: Preserve both worker playback and Gate config APIs**

Keep these route families simultaneously:

```text
GET  /cameras/{camera_id}/playback
POST /cameras/{camera_id}/playback
GET  /cameras/{camera_id}/playback/preview
POST /cameras/{camera_id}/seek
GET  /cameras/{camera_id}/config
POST /cameras/{camera_id}/config
POST /cameras/{camera_id}/activation
```

The seconds contract returns `positionSeconds/durationSeconds`; the compatibility contract returns `positionMs/durationMs`. Seeking resets Gate tracking state and preserves Area's async seek behavior.

- [ ] **Step 3: Merge Node camera proxy routes**

Retain `main` timeouts, validation, preview image handling, and seconds routes. Add the feature branch's `/seek` and `/config` proxies with the same 5-second timeout and normalized camera IDs. Remove the unused `AREA_CAMERA_ID` import if neither branch uses it after resolution.

- [ ] **Step 4: Merge the frontend camera API exports**

`frontend/src/api/cameras.ts` exports `CameraPlaybackState`, `getCameraPlayback`, `seekCameraPlayback`, `getCameraPlaybackPreview`, `CameraConfig`, `getCameraConfig`, and `updateCameraConfig`. Existing millisecond helpers in `api/zones.ts` remain backward compatible until consumers are consolidated in a separate change.

- [ ] **Step 5: Verify Python and Node contracts**

```powershell
python -m py_compile backend/python-worker/main.py
npm.cmd run typecheck
```

Run the Node command from `backend/node-api`. Expected: zero TypeScript errors.

- [ ] **Step 6: Stage runtime/API resolution**

```powershell
git add backend/python-worker/main.py backend/node-api/src/routes/cameras.ts frontend/src/api/cameras.ts
git diff --cached --check
```

---

### Task 5: Merge React state, Gate Monitor, and Vehicle Settings

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/GateMonitor.tsx`
- Modify: `frontend/src/components/Settings/VehicleLabelTab.tsx`
- Modify: `frontend/src/hooks/useCameraFeed.ts`
- Modify: `frontend/src/types.ts`
- Verify: `frontend/src/api/vehicles.ts`
- Verify: `frontend/src/api/events.ts`

**Interfaces:**
- Consumes: Area app state from `main`, backend-owned vehicles, merged frame metadata, Gate events, crop URLs, playback APIs, and confidence config APIs.
- Produces: one buildable UI retaining all Area, Gate, and Vehicle Settings flows.

- [ ] **Step 1: Merge types and feed metadata additively**

Keep every Area/ObjectKind field from `main`; add Gate event keys, nullable confidence, UNKNOWN state, crop/event metadata, timecode, and source dimensions from the feature branch. `useCameraFeed()` returns both `sourceReset` behavior and `timecode/frameWidth/frameHeight`.

```ts
type GateStatus = 'quen' | 'la' | 'unknown';

interface CameraFeedState {
  timecode?: string;
  frameWidth?: number;
  frameHeight?: number;
}
```

- [ ] **Step 2: Keep `App.tsx` Area state and backend-owned vehicle loading**

Preserve zones, registry capabilities, mutation state, Area alerts, snapshots, media sources, and `ObjectKind`. Initialize vehicles/labels without mock Gate data, refresh them from `getVehicles()`, and preserve optimistic status updates with error handling.

- [ ] **Step 3: Merge all Gate Monitor controls**

Keep normalized/deduplicated Gate events, UNKNOWN rendering, crop modal, playback slider/timecode, correct overlay scaling from source dimensions, live WebSocket updates, hover synchronization, filters/search, clip playback, and `main`'s clear-history confirmation/toast. Clearing history must not clear Vehicle Settings rows unless the existing backend endpoint explicitly owns that behavior.

- [ ] **Step 4: Merge Vehicle Settings behavior**

Keep real CRUD, ten-row pagination, cross-page selection, sticky bulk actions, sort/filter, and Main's current sample/annotation behavior. Add the Gate confidence slider/load/save flow from the feature branch. Do not reintroduce mock production data.

- [ ] **Step 5: Build and lint the frontend**

```powershell
npm.cmd run build
npm.cmd run lint
```

Run from `frontend`. Expected: TypeScript/Vite build exits 0; lint has no errors introduced by the merge.

- [ ] **Step 6: Stage frontend resolution**

```powershell
git add frontend/src/App.tsx frontend/src/components/GateMonitor.tsx frontend/src/components/Settings/VehicleLabelTab.tsx frontend/src/hooks/useCameraFeed.ts frontend/src/types.ts
git diff --cached --check
```

---

### Task 6: Complete conflict cleanup and run zero-regression verification

**Files:**
- Verify: every staged/non-conflicted file brought by the feature branch
- Verify: `backend/node-api/prisma/schema.prisma`
- Verify: `backend/node-api/prisma/migrations/20260824113000_gate_event_context/migration.sql`
- Verify: `backend/node-api/prisma/migrations/20260824160000_backfill_detected_vehicles/migration.sql`
- Verify: `docs/backend/tasks/VS-GATE-LIVE.md`
- Verify: `docs/frontend/tasks/VS-GATE-LIVE.md`
- Verify: `docs/frontend/tasks/VS-SETTINGS-VEHICLE.md`

**Interfaces:**
- Consumes: all resolved files and pre-merged feature additions.
- Produces: an uncommitted, fully resolved merge plus reproducible verification evidence.

- [ ] **Step 1: Prove the conflict set is empty**

```powershell
git diff --name-only --diff-filter=U
rg -n "^(<<<<<<<|=======|>>>>>>>)" . -g '!node_modules/**' -g '!.git/**'
git diff --check
git diff --cached --check
```

Expected: no unmerged paths, no conflict markers, and no whitespace errors.

- [ ] **Step 2: Run focused BAI-KIEM regression tests**

```powershell
python -m pytest backend/python-worker/tests/test_area_pipeline.py backend/python-worker/tests/test_event_clip_service.py backend/python-worker/tests/test_area_event_queue.py backend/python-worker/tests/test_zone_sync_capabilities.py backend/python-worker/tests/test_detection_policy.py backend/python-worker/tests/test_stream_pipeline.py backend/python-worker/tests/test_stream_emitter.py -q
```

Expected: Area tracking, rule evaluation, reset, clip, stream, loop, zone capability, and activation tests pass.

- [ ] **Step 3: Run focused GATE-01 regression tests**

```powershell
python -m pytest backend/python-worker/tests/test_lpr_runtime_and_rear_roi.py backend/python-worker/tests/test_gate_event_vehicle_registration.py backend/python-worker/tests/test_volvo_lpr.py -q
```

Expected: all Gate LPR, bbox, tracking, passage, UNKNOWN, threshold, vehicle status, and runtime assertions pass.

- [ ] **Step 4: Run Node verification**

```powershell
npm.cmd run typecheck
npx.cmd ts-node src/tests/test_gate_events.ts
npx.cmd ts-node src/tests/test_area_event_reset.ts
npx.cmd ts-node src/tests/test_area_event_clip.ts
npx.cmd ts-node src/tests/test_vehicles.ts
```

Run from `backend/node-api`. Expected: typecheck and tests exit 0; environment-dependent database failures are reported separately from compile/contract failures.

- [ ] **Step 5: Run frontend verification**

```powershell
npm.cmd run build
npm.cmd run lint
```

Run from `frontend`. Expected: production build and lint exit 0.

- [ ] **Step 6: Run Gate performance/replay benchmark when the configured source and database are available**

```powershell
python backend/python-worker/tests/benchmark_gate_fps.py "$env:VIDEO_GATE_PATH" --frames 120 --width 1600 --height 900 --realtime
```

Expected: processing remains above the product floor of 5 FPS, runtime reports the intended CUDA providers on the production machine, and known replay plates/overlay spans match the feature branch's recorded evidence. If `VIDEO_GATE_PATH`, database access, GPU, or model weights are unavailable, record that exact environment blocker and do not claim runtime parity from unit tests alone.

- [ ] **Step 7: Inspect semantic branch coverage in the final staged diff**

```powershell
git diff --cached --stat
git diff --cached --name-status
git status --short
```

Confirm all feature additions remain present, all resolved paths are staged, the design/plan documents are included, and no unrelated user file is altered.

- [ ] **Step 8: Hand the uncommitted merge to the user**

Report passed/failed/skipped commands, benchmark evidence, remaining environment-only checks, and the exact `git status`. Do not run `git commit` until the user explicitly approves the resolved merge.
