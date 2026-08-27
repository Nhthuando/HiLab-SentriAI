# BAI-KIEM V9 Official Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Khôi phục đầy đủ nhãn, zone và thanh tua, đồng thời đặt V9 làm model runtime chính thức mà không còn fallback tự động sang V8.

**Architecture:** Giữ Neon là nguồn dữ liệu duy nhất cho nhãn/zone và giữ V9 `ACTIVE` trong DB. Chuyển configured-model bridge trong `backend/.env` sang chính V9 để cả primary lẫn fallback runtime đều cùng một artifact; sau đó khởi động Node API/Python Worker ngoài sandbox để hai service kết nối Neon bình thường. V8 chỉ tồn tại dưới dạng artifact cứu hộ thủ công.

**Tech Stack:** Node.js 20, Express, Prisma/PostgreSQL Neon, Python 3.12, FastAPI, asyncpg, React/Vite, YOLO11n.

## Global Constraints

- Không xóa, sửa hoặc đổi hash artifact V8.
- Không reset, migrate, seed đè hoặc tạo dữ liệu giả trong Neon.
- Không train thêm hoặc thay đổi confidence/IoU/tracking.
- Runtime Area chỉ chạy một lượt inference V9 `UNIFIED` cho mỗi frame.
- Không thay đổi kết luận quality gate trong báo cáo đánh giá.
- Không commit `backend/.env` hoặc bất kỳ secret nào.

---

## File Map

- Modify: `backend/.env` — đổi configured-model identity từ V8 sang V9; giữ nguyên threshold và inference size.
- Verify only: `backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt` — artifact runtime chính thức.
- Preserve only: `backend/data/training/models/baikiem-reach-reviewed-v8-hardcases-ft-20260824/best.pt` — artifact cứu hộ, không được sửa/xóa.
- Verify only: `backend/data/training/models/baikiem-v9-unified-candidate-final/labels.json` — manifest năm class V9.
- Runtime logs: `backend/data/training/activation-logs/node-api-v9-official.stdout.log`, `node-api-v9-official.stderr.log`, `python-worker-v9-official.stdout.log`, `python-worker-v9-official.stderr.log`.
- No frontend source change is planned because playback polling already retries every second and the live playback endpoint currently returns `seekable: true`.

### Task 1: Pin the configured runtime bridge to V9

**Files:**
- Modify: `backend/.env`
- Verify: `backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt`
- Preserve: `backend/data/training/models/baikiem-reach-reviewed-v8-hardcases-ft-20260824/best.pt`

**Interfaces:**
- Consumes: `CUSTOM_AUGMENT_ARTIFACT`, `CUSTOM_AUGMENT_VERSION_KEY`, `CUSTOM_AUGMENT_SHA256`, `CUSTOM_AUGMENT_FORCE_DEFAULT` read by Node capability routing and Python zone sync.
- Produces: a configured runtime identity that resolves to V9 even if the DB-side ACTIVE lookup is temporarily unavailable.

- [x] **Step 1: Verify both artifact hashes before changing configuration**

```powershell
Get-FileHash -Algorithm SHA256 backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt
Get-FileHash -Algorithm SHA256 backend/data/training/models/baikiem-reach-reviewed-v8-hardcases-ft-20260824/best.pt
```

Expected V9 SHA-256: `3772e978fc4635a6a2d3dffb59286bd89c0ebbc6cc6e27dc77532b5006eaab52`.

Expected V8 SHA-256: `e45d053cadfa46a354674d475a1d61552025b7001d42f2ccfc7c5de836774c91`.

- [x] **Step 2: Replace only the three V8 identity values in `backend/.env`**

```dotenv
CUSTOM_AUGMENT_ARTIFACT=training/models/baikiem-v9-unified-candidate-final/best.pt
CUSTOM_AUGMENT_VERSION_KEY=baikiem-v9-unified-candidate-final
CUSTOM_AUGMENT_SHA256=3772e978fc4635a6a2d3dffb59286bd89c0ebbc6cc6e27dc77532b5006eaab52
CUSTOM_AUGMENT_FORCE_DEFAULT=true
```

Do not modify `AREA_INFERENCE_SIZE=896` or `AREA_CLASS_THRESHOLDS_JSON`.

- [x] **Step 3: Verify runtime configuration no longer references V8**

```powershell
Select-String -Path backend/.env -Pattern '^CUSTOM_AUGMENT_'
Select-String -Path backend/.env -Pattern 'baikiem-reach-reviewed-v8'
```

Expected: the first command shows only V9 identity and `FORCE_DEFAULT=true`; the second command returns no match.

- [x] **Step 4: Re-verify V8 artifact preservation**

```powershell
Get-FileHash -Algorithm SHA256 backend/data/training/models/baikiem-reach-reviewed-v8-hardcases-ft-20260824/best.pt
```

Expected: V8 file still exists and hash remains `e45d053cadfa46a354674d475a1d61552025b7001d42f2ccfc7c5de836774c91`.

### Task 2: Run targeted static and runtime-contract checks

**Files:**
- Test: `backend/node-api/src/tests/test_label_capabilities.ts`
- Test: `backend/python-worker/tests/test_zone_sync_capabilities.py`
- Test: `backend/python-worker/tests/test_activate_v9_production.py`

**Interfaces:**
- Consumes: V9 configured identity and the existing `UNIFIED` capability manifest.
- Produces: evidence that Node/Python agree on active class routing and rollback metadata remains valid.

- [x] **Step 1: Run Node capability tests and typecheck**

```powershell
npx.cmd ts-node src/tests/test_label_capabilities.ts
npm.cmd run typecheck
```

Run from `backend/node-api`. Expected: both commands exit `0`.

- [x] **Step 2: Run Python V9 activation and zone-sync tests**

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p test_zone_sync_capabilities.py -v
.venv\Scripts\python.exe -m unittest discover -s tests -p test_activate_v9_production.py -v
```

Run from `backend/python-worker`. Expected: all selected tests pass.

- [x] **Step 3: Build Node API before restarting production services**

```powershell
npm.cmd run build
```

Run from `backend/node-api`. Expected: TypeScript compilation exits `0` and refreshes `dist/`.

### Task 3: Restart Node API and Python Worker outside sandbox

**Files:**
- Create runtime logs under `backend/data/training/activation-logs/`.

**Interfaces:**
- Consumes: V9 configuration from Task 1 and compiled Node API from Task 2.
- Produces: Node API on port `3001` and Python Worker on port `8001`, both able to access Neon.

- [x] **Step 1: Resolve exact listener PIDs for ports 3001 and 8001**

```powershell
netstat -ano | Select-String ':3001|:8001'
```

Expected: identify only the current Node and Python listener PIDs; do not terminate unrelated processes.

- [x] **Step 2: Stop only the resolved Node API and Python Worker processes**

```powershell
Stop-Process -Id 27484 -Force
Stop-Process -Id 21488 -Force
```

Expected: ports `3001` and `8001` become free. Frontend port `5173` remains running.

- [x] **Step 3: Start Python Worker outside sandbox with hidden window and dedicated logs**

```powershell
Start-Process -FilePath '.venv\Scripts\python.exe' -ArgumentList 'main.py' -WorkingDirectory 'D:\HuuThuan - Project\HiLab-SentriAI\backend\python-worker' -WindowStyle Hidden -RedirectStandardOutput 'D:\HuuThuan - Project\HiLab-SentriAI\backend\data\training\activation-logs\python-worker-v9-official.stdout.log' -RedirectStandardError 'D:\HuuThuan - Project\HiLab-SentriAI\backend\data\training\activation-logs\python-worker-v9-official.stderr.log'
```

Expected: port `8001` listens; startup log confirms DB pool initialized and V9 `UNIFIED` loaded with `person`, `car`, `truck`, `forklift`, `reach_stacker`.

- [x] **Step 4: Start Node API outside sandbox after Worker is ready**

```powershell
Start-Process -FilePath 'node.exe' -ArgumentList 'dist/index.js' -WorkingDirectory 'D:\HuuThuan - Project\HiLab-SentriAI\backend\node-api' -WindowStyle Hidden -RedirectStandardOutput 'D:\HuuThuan - Project\HiLab-SentriAI\backend\data\training\activation-logs\node-api-v9-official.stdout.log' -RedirectStandardError 'D:\HuuThuan - Project\HiLab-SentriAI\backend\data\training\activation-logs\node-api-v9-official.stderr.log'
```

Expected: port `3001` listens, Node connects to Worker, and Prisma can query Neon without TLS/access-denied errors.

### Task 4: Verify API data restoration and official V9 runtime

**Files:**
- Verify runtime logs created in Task 3.
- Verify only: `backend/data/training/activation-backups/baikiem-v9-20260826T102022Z.json`.

**Interfaces:**
- Consumes: live services from Task 3.
- Produces: API and log evidence that data is restored and V8 is not in active runtime.

- [x] **Step 1: Verify health, labels, zone and playback endpoints**

```powershell
curl.exe -f http://127.0.0.1:8001/health
curl.exe -f http://127.0.0.1:3001/api/v1/labels
curl.exe -f 'http://127.0.0.1:3001/api/v1/zones?cameraId=BAI-KIEM'
curl.exe -f http://127.0.0.1:3001/api/v1/cameras/BAI-KIEM/playback
```

Expected: all return HTTP `200`; labels are non-empty, BAI-KIEM zone data is present, and playback returns `seekable: true` with positive duration.

- [x] **Step 2: Verify V9-only runtime identity in logs**

```powershell
Select-String -Path backend/data/training/activation-logs/python-worker-v9-official.stderr.log -Pattern 'V9|baikiem-v9-unified-candidate-final|mode=UNIFIED|person|car|truck|forklift|reach_stacker'
Select-String -Path backend/data/training/activation-logs/python-worker-v9-official.stderr.log -Pattern 'baikiem-reach-reviewed-v8'
```

Expected: V9/UNIFIED/five-class evidence is present; V8 pattern returns no match.

- [x] **Step 3: Confirm V8 remains recoverable but unreferenced**

```powershell
Test-Path backend/data/training/models/baikiem-reach-reviewed-v8-hardcases-ft-20260824/best.pt
Select-String -Path backend/.env -Pattern 'baikiem-reach-reviewed-v8'
```

Expected: `Test-Path` returns `True`; runtime config search returns no match.

### Task 5: Verify the visible UI and BAI-KIEM feed

**Files:**
- No source modification expected.

**Interfaces:**
- Consumes: frontend on port `5173`, restored APIs, and V9 feed.
- Produces: user-visible confirmation that Settings and Area Monitor are complete again.

- [x] **Step 1: Reload Settings and verify real registry data**

Open `http://localhost:5173`, hard reload, navigate to `Cài đặt hệ thống`, then verify:

```text
Danh mục Nhãn đối tượng: non-empty
Vẽ zone: saved BAI-KIEM zone is visible
Cải thiện nhận diện: no "Failed to fetch"
```

- [x] **Step 2: Reload Area Monitor and verify playback controls**

Navigate to `Giám sát khu vực` and verify:

```text
Video frame: visible
V9 detection boxes: visible when objects are present
Playback bar: -10s, pause/resume, +10s, current/duration, slider
```

- [x] **Step 3: Smoke-test seek and feed continuity**

Seek once with `+10s` and once using the slider. Expected: frame position changes, the bar remains visible, feed resumes, and no reconnect/log storm appears.

- [x] **Step 4: Record final status without committing secrets**

Report the API results, V9 runtime identity, UI restoration and V8 preservation. Do not commit `backend/.env`; do not delete the rollback receipt or V8 artifact.

### Task 6: Remove the blocking write side effect from vehicle list reads

**Files:**
- Modify: `backend/node-api/src/routes/vehicles.ts`
- Verify: `backend/python-worker/detection/gate_pipeline.py`

**Interfaces:**
- Consumes: the existing Gate pipeline call to `register_vehicle(...)` when a new plate event is accepted.
- Produces: `GET /api/v1/vehicles` as a read-only list operation that no longer performs one sequential `upsert` for every distinct historical gate plate.

- [x] **Step 1: Verify the Gate pipeline already registers detected vehicles at event creation**

```powershell
rg -n "register_vehicle" backend/python-worker/detection/gate_pipeline.py
```

Expected: the accepted Gate event path calls `register_vehicle(...)`, so the GET-side historical synchronization is redundant.

- [x] **Step 2: Remove the `gateEvent.findMany` and sequential `registeredVehicle.upsert` block from GET `/vehicles`**

The handler must begin parsing filters and then execute only read queries. POST/PATCH/DELETE behavior remains unchanged.

- [x] **Step 3: Typecheck and build Node API**

```powershell
npm.cmd run typecheck
npm.cmd run build
```

Run from `backend/node-api`. Expected: both commands exit `0`.

- [x] **Step 4: Restart only Node API outside sandbox**

Resolve the current port-3001 PID, stop exactly that PID, and start `dist/index.js` with the same official V9 log paths. Python Worker and frontend remain running.

- [x] **Step 5: Verify the complete Settings request burst**

Issue concurrent GET requests for labels, samples, media, vehicles, zones, readiness, Area events and playback for five rounds.

Expected: every response returns `200`; `/vehicles` completes instead of hanging; labels remain non-empty; no Prisma P1001 appears in the new runtime log.
