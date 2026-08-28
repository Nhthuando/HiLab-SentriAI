# Env Source Hot Reload and Dev Runner Implementation Plan

> **For agentic workers:** Implement this plan task-by-task in the current workspace. Do not dispatch subagents for this plan. The user will run all tests and runtime verification after handoff.

**Goal:** Tự áp dụng thay đổi nguồn video từ `backend/.env` mà không restart Python Worker và chạy toàn bộ SentriAI bằng một lệnh `npm run dev`.

**Architecture:** Một watcher bất đồng bộ chỉ theo dõi hai biến nguồn camera và gọi interface `replace_source()` của pipeline tương ứng. Mỗi pipeline thay `StreamReader` dưới khóa điều khiển nhưng giữ model và service dài hạn; một Node process runner ở repository root quản lý ba dịch vụ và dọn toàn bộ cây tiến trình khi nhận `Ctrl+C`.

**Tech Stack:** Python 3.11+, asyncio, python-dotenv, OpenCV, FastAPI lifespan, Node.js ESM, npm.

## Global Constraints

- Chỉ hot-reload `GATE_CAMERA_URL` và `AREA_CAMERA_URL`.
- Poll `backend/.env` mỗi 1 giây, không làm I/O trong luồng xử lý frame.
- Đường dẫn tương đối được phân giải từ repository root; đường dẫn tuyệt đối vẫn được hỗ trợ.
- File cục bộ phải nằm trong `CLIP_SOURCE_ROOTS`; nguồn mạng chỉ chấp nhận RTSP, HTTP hoặc HTTPS.
- Nguồn mới lỗi phải giữ nguyên reader cũ và không fallback sang synthetic stream.
- Không reload model YOLO/LPR, FastAPI hoặc kết nối database khi đổi nguồn.
- Không xóa lịch sử và không tạo clip tự động.
- `npm run dev` phải dùng `.venv` nằm trong repository và không cần dependency root mới.
- Agent không chạy test, build, replay video hoặc kiểm thử dữ liệu thật; mọi lệnh nghiệm thu trong plan dành cho người dùng chạy sau bàn giao.

---

## File Structure

- Create `backend/python-worker/stream/source_config.py`: phân giải nguồn, kiểm tra allowlist và theo dõi thay đổi của `backend/.env`.
- Modify `backend/python-worker/stream/reader.py`: cung cấp trạng thái reader dùng được và đánh dấu frame đầu tiên sau khi đổi nguồn.
- Modify `backend/python-worker/detection/gate_pipeline.py`: thay nguồn GATE-01 dưới khóa mà không reload detector/LPR.
- Modify `backend/python-worker/detection/area_pipeline.py`: thay nguồn BAI-KIEM, đóng timeline cũ, reset generation/coverage và quản lý rolling archive.
- Modify `backend/python-worker/detection/event_clip_service.py`: dùng cùng quy tắc phân giải `CLIP_SOURCE_ROOTS` ổn định từ repository root.
- Modify `backend/python-worker/main.py`: quản lý watcher theo FastAPI lifespan và hiển thị trạng thái reload trong `/health`.
- Create `scripts/dev.mjs`: chạy và dừng ba dịch vụ bằng đường dẫn tương đối.
- Create `package.json`: expose root command `npm run dev`.
- Modify `backend/.env.example`: bỏ đường dẫn máy cá nhân và mô tả cấu hình portable.
- Modify `README.md`: sửa lệnh Python và hướng dẫn hot-reload/one-command startup.

---

### Task 1: Source configuration boundary

**Files:**
- Create: `backend/python-worker/stream/source_config.py`
- Modify: `backend/python-worker/detection/event_clip_service.py`
- Modify: `backend/.env.example`

**Interfaces:**
- Produces: `ConfiguredSource`, `SourceConfigError`, `resolve_configured_source()`, `load_source_snapshot()`, `SourceConfigWatcher.run()`, `SourceConfigWatcher.stop()`.
- Consumes: `dotenv.dotenv_values`, `Path`, `asyncio`, `CLIP_SOURCE_ROOTS`.

- [ ] **Step 1: Define immutable source metadata**

Create these public types and constants in `stream/source_config.py`:

```python
CAMERA_SOURCE_KEYS = {
    "GATE_CAMERA_URL": "GATE-01",
    "AREA_CAMERA_URL": "BAI-KIEM",
}
NETWORK_SCHEMES = ("rtsp://", "http://", "https://")
VIDEO_SUFFIXES = {".asf", ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".wmv"}

@dataclass(frozen=True)
class ConfiguredSource:
    env_key: str
    camera_id: str
    raw_value: str
    resolved_value: str
    source_kind: str

class SourceConfigError(ValueError):
    pass
```

- [ ] **Step 2: Implement portable path and allowlist resolution**

Add `configured_source_roots(raw_roots: str, repo_root: Path) -> tuple[Path, ...]` to normalize the allowlist and `resolve_configured_source(env_key: str, raw_value: str, *, repo_root: Path, allowed_roots: tuple[Path, ...]) -> ConfiguredSource` to validate one camera source.

Rules:

- Trim whitespace and reject an empty value.
- Return network URLs without exposing them in error/log text.
- Resolve a relative local path as `repo_root / raw_value`.
- Require an existing regular file with a suffix in `VIDEO_SUFFIXES`.
- Require the resolved file to equal an allowed root or be below one.
- Raise `SourceConfigError` without embedding an RTSP credential.

- [ ] **Step 3: Implement snapshot loading and watcher lifecycle**

Add `load_source_snapshot(env_path: Path, *, repo_root: Path) -> dict[str, ConfiguredSource | SourceConfigError]` and a `SourceConfigWatcher` exposing `run(on_change: Callable[[ConfiguredSource], Awaitable[bool]]) -> None` plus synchronous `stop() -> None`.

Watcher behavior:

- Capture initial valid/raw values without firing callbacks.
- Check `st_mtime_ns` once per poll.
- Debounce a changed file before parsing it.
- Compare normalized `resolved_value`, not only file mtime.
- Invoke one callback per changed camera.
- Update the accepted snapshot only when callback returns `True`.
- Keep retrying a rejected new value after a later file save.
- Exit when `stop()` sets an internal `asyncio.Event`.

- [ ] **Step 4: Reuse the allowlist in lazy clip generation**

Replace current working-directory-based path resolution in `EventClipGenerator.__init__` with `configured_source_roots()` using repository root. Keep `backend/data` as an always-allowed internal root. Do not add the current camera file's parent implicitly; a local source must be explicitly covered by `CLIP_SOURCE_ROOTS`.

- [ ] **Step 5: Make `.env.example` portable**

Use repository-relative examples:

```dotenv
GATE_CAMERA_URL=backend/data/samples/gate_sample.mp4
AREA_CAMERA_URL=backend/data/samples/area_sample.mp4
CLIP_SOURCE_ROOTS=backend/data/samples
```

Document that multiple roots use the platform path separator (`;` on Windows, `:` on macOS/Linux) and every local test video must be within an allowed root.

- [ ] **Step 6: Commit the source configuration boundary**

```bash
git add backend/python-worker/stream/source_config.py backend/python-worker/detection/event_clip_service.py backend/.env.example
git commit -m "feat: watch portable camera source config"
```

---

### Task 2: Atomic StreamReader replacement

**Files:**
- Modify: `backend/python-worker/stream/reader.py`

**Interfaces:**
- Produces: `StreamReader.is_usable_source`, `StreamReader.mark_source_reset()`.
- Consumes: existing `StreamReader.release()` and source metadata.

- [ ] **Step 1: Expose strict candidate readiness**

Add a read-only property:

```python
@property
def is_usable_source(self) -> bool:
    return bool(
        self.is_connected
        and not self.is_synthetic
        and (self.is_local_file or isinstance(self.source, str))
    )
```

The hot-reload path constructs a candidate reader and accepts it only when this property is true. Startup fallback behavior remains unchanged.

- [ ] **Step 2: Mark the first frame after replacement**

Add:

```python
def mark_source_reset(self) -> None:
    self._source_reset_pending = True
    self._last_local_frame_at = None
```

This lets WebSocket consumers and pipeline trackers see the new timeline boundary on the first decoded frame.

- [ ] **Step 3: Commit reader support**

```bash
git add backend/python-worker/stream/reader.py
git commit -m "feat: support atomic video reader replacement"
```

---

### Task 3: Gate pipeline source replacement

**Files:**
- Modify: `backend/python-worker/detection/gate_pipeline.py`

**Interfaces:**
- Produces: `async GatePipeline.replace_source(source: str) -> bool`.
- Consumes: `StreamReader.is_usable_source`, `mark_source_reset()`, `reset_tracking_state()`.

- [ ] **Step 1: Add a frame control lock**

Initialize `self._control_lock = asyncio.Lock()` and wrap `process_gate_frame()` inside `_loop()`:

```python
async with self._control_lock:
    result = await self.process_gate_frame()
```

This ensures source replacement never races a frame read.

- [ ] **Step 2: Implement candidate-first replacement**

Add:

```python
async def replace_source(self, source: str) -> bool:
    candidate = await asyncio.to_thread(
        StreamReader,
        source=source,
        camera_id=self.camera_id,
        target_fps=self.target_fps,
        resolution=self.resolution,
    )
    if not candidate.is_usable_source:
        candidate.release()
        return False

    async with self._control_lock:
        previous = self.reader
        candidate.mark_source_reset()
        self.reader = candidate
        self.buffer.clear()
        self.reset_tracking_state()
        self._fps_counter = 0
        self._last_fps_calc = time.time()
        self.fps_measured = self.target_fps
    previous.release()
    return True
```

Do not change `_active`, detector, LPR reader, emitter or executor.

- [ ] **Step 3: Commit Gate replacement**

```bash
git add backend/python-worker/detection/gate_pipeline.py
git commit -m "feat: hot swap gate video source"
```

---

### Task 4: Area pipeline source replacement

**Files:**
- Modify: `backend/python-worker/detection/area_pipeline.py`

**Interfaces:**
- Produces: `async AreaPipeline.replace_source(source: str) -> bool`.
- Consumes: existing `_control_lock`, queues, trackers, `_reset_activity_coverage_source()`, `RollingArchive`, and clip services.

- [ ] **Step 1: Extract reusable archive construction**

Create `_build_rolling_archive(self, source_context: Mapping[str, Any], source: object) -> Optional[RollingArchive]`.

Use this helper in `__init__` and source replacement. It returns an archive only for a `LIVE` source string and preserves the existing archive directory, retention and segment configuration.

- [ ] **Step 2: Extract coverage restore for the current reader**

Move the persistence restore block from `prepare()` into `async _restore_activity_coverage(self) -> None`.

The method resets `_activity_replay_read_only` before loading saved coverage. It restores only when the saved source fingerprint equals the new reader fingerprint and sets replay read-only only for a complete local file.

- [ ] **Step 3: Implement candidate-first area replacement**

Add `async replace_source(source: str) -> bool` with this order:

1. Construct and validate the candidate `StreamReader` in `asyncio.to_thread` before acquiring `_control_lock`.
2. Acquire `_control_lock` so no frame is being processed.
3. End all active violation and activity transitions and enqueue them under the current generation.
4. Await both queue joins so the old timeline is durably closed.
5. Increment `_runtime_generation`, reset both queue generations, and reset both lazy clip services to cancel stale jobs.
6. Stop the old rolling archive if present.
7. Mark the candidate source reset and atomically replace `self.reader`.
8. Clear zone/activity runtime state, persisted-ID caches, detector tracking and optional buffer.
9. Reset and restore activity coverage for the candidate fingerprint.
10. Build/start the archive required by the new source and assign it to both clip services.
11. Release the old reader after the swap.

Preserve `_running`, `_active`, `_viewer_active`, detector, zone synchronizer, persistence objects and emitters.

- [ ] **Step 4: Keep old-source lazy clips authorized**

Do not mutate `CLIP_SOURCE_ROOTS` during a switch. Both clip generators retain their stable allowlist so an activity from a previous local source remains requestable when its file still exists.

- [ ] **Step 5: Commit Area replacement**

```bash
git add backend/python-worker/detection/area_pipeline.py
git commit -m "feat: hot swap area video source"
```

---

### Task 5: FastAPI watcher lifecycle and health state

**Files:**
- Modify: `backend/python-worker/main.py`

**Interfaces:**
- Produces: `apply_source_change(source: ConfiguredSource) -> bool`, watcher lifespan task, redacted `sourceReload` health data.
- Consumes: `SourceConfigWatcher`, `GatePipeline.replace_source()`, `AreaPipeline.replace_source()`.

- [ ] **Step 1: Define stable repository paths and reload status**

At module level derive:

```python
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ENV_PATH = REPO_ROOT / "backend" / ".env"
source_reload_status: Dict[str, Dict[str, Any]] = {}
```

Use `load_source_snapshot()` for initial pipeline sources so startup and reload share exactly the same path rules.

- [ ] **Step 2: Implement the watcher callback**

Add `async apply_source_change(source: ConfiguredSource) -> bool`.

The callback looks up `pipelines[source.camera_id]`, calls `replace_source(source.resolved_value)`, records `APPLIED` or `REJECTED` with UTC timestamp and `source_kind`, and logs only camera ID/env key. It updates `os.environ[source.env_key]` only after a successful switch.

- [ ] **Step 3: Own watcher lifecycle in FastAPI lifespan**

After pipelines are registered and BAI-KIEM starts:

```python
source_watcher = SourceConfigWatcher(BACKEND_ENV_PATH, REPO_ROOT)
source_watcher_task = asyncio.create_task(
    source_watcher.run(apply_source_change),
    name="camera-source-config-watcher",
)
```

During shutdown, call `source_watcher.stop()`, await the task, then stop pipelines and close the database. Ensure cancellation does not skip normal pipeline cleanup.

- [ ] **Step 4: Add redacted health visibility**

Add `sourceReload` to each camera's `/health` record. Return only:

```json
{
  "status": "APPLIED",
  "changedAt": "2026-08-28T12:00:00+00:00",
  "sourceKind": "LOCAL_FILE"
}
```

Never return raw URL, credential or full local path.

- [ ] **Step 5: Commit watcher integration**

```bash
git add backend/python-worker/main.py
git commit -m "feat: reload camera sources from env"
```

---

### Task 6: One-command development runner

**Files:**
- Create: `scripts/dev.mjs`
- Create: `package.json`

**Interfaces:**
- Produces: root command `npm run dev`.
- Consumes: local Python venv, backend/frontend npm scripts.

- [ ] **Step 1: Add the root npm command**

Create:

```json
{
  "name": "sentriai",
  "private": true,
  "version": "0.1.0",
  "scripts": {
    "dev": "node scripts/dev.mjs"
  }
}
```

No root dependency or install step is required.

- [ ] **Step 2: Validate prerequisites in the runner**

In `scripts/dev.mjs`, resolve paths from `import.meta.url` and verify:

- `backend/.env` exists.
- Platform-specific `.venv` Python exists.
- `backend/node-api/node_modules` exists.
- `frontend/node_modules` exists.

Print one actionable error and exit non-zero when a prerequisite is missing.

- [ ] **Step 3: Spawn and prefix three services**

Use `child_process.spawn` without `shell: true`:

```javascript
const services = [
  { name: 'worker', command: pythonExe, args: ['main.py'], cwd: workerDir },
  { name: 'api', command: npmExe, args: ['run', 'dev'], cwd: apiDir },
  { name: 'web', command: npmExe, args: ['run', 'dev'], cwd: frontendDir },
];
```

Use `npm.cmd` on Windows and `npm` elsewhere. Pipe stdout/stderr line-by-line with `[worker]`, `[api]`, `[web]` prefixes.

- [ ] **Step 4: Implement clean shutdown**

Track child PIDs and guard shutdown against duplicate signals. On Windows, invoke `taskkill /PID <pid> /T /F` for each owned child tree. On POSIX, create process groups and send `SIGTERM`, then `SIGKILL` only after a short timeout. If a child exits unexpectedly, stop the other children and return that non-zero exit code.

- [ ] **Step 5: Commit the runner**

```bash
git add package.json scripts/dev.mjs
git commit -m "feat: run all development services together"
```

---

### Task 7: README and user handoff

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents: individual worker commands, `npm run dev`, source hot-reload and self-test checklist.

- [ ] **Step 1: Correct standalone worker commands**

Use:

```powershell
cd backend/python-worker
.\.venv\Scripts\python.exe main.py
```

and:

```bash
cd backend/python-worker
.venv/bin/python main.py
```

- [ ] **Step 2: Make one-command startup the default**

Add from repository root:

```bash
npm run dev
```

Explain the three log prefixes and one-time `Ctrl+C` shutdown.

- [ ] **Step 3: Document source hot-reload**

Explain that saving either camera URL in `backend/.env` applies automatically within approximately two seconds. Include portable relative examples and explain that invalid sources leave the current stream running.

- [ ] **Step 4: Give the user a manual acceptance checklist without executing it**

Handoff checklist:

1. Start with `npm run dev` and confirm ports 8001, 3001 and 5173.
2. Change only `AREA_CAMERA_URL`; confirm BAI-KIEM switches and GATE-01 does not.
3. Change only `GATE_CAMERA_URL`; confirm GATE-01 switches and BAI-KIEM does not.
4. Enter a missing file path; confirm the current video continues.
5. Query AI before and after a BAI-KIEM switch; confirm activities are not mixed across sources.
6. Confirm no clip file is created until **Xem video** is selected.
7. Press `Ctrl+C` once and confirm all three ports are released.

- [ ] **Step 5: Review changes without executing tests**

Inspect the final diff for unrelated files, secrets, absolute personal paths, incomplete text and mismatched interfaces. Do not run test, build, replay, service startup or real-data commands.

- [ ] **Step 6: Commit documentation**

```bash
git add README.md
git commit -m "docs: explain source reload and unified startup"
```

---

## User-Run Verification Commands

The following commands are documented for the user and must not be executed by the implementing agent:

```powershell
npm run dev
```

After the services are running, the user follows the acceptance checklist in Task 7 and may independently run the project's existing automated test commands if desired.
