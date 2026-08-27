# BAI-KIEM 12 FPS and Outside-Zone Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run BAI-KIEM at a 12 FPS target and show detections outside every Zone without changing V9 accuracy or violation semantics.

**Architecture:** The Python Worker keeps the existing V9/ZoneChecker pipeline and receives only a target-rate configuration change. The React monitor consumes the existing `OUTSIDE` DTO state and assigns it a neutral visual presentation instead of filtering it out; Zone events remain backend-driven and unchanged.

**Tech Stack:** Python/FastAPI worker configuration, React 19, TypeScript 6, Vite 8.

## Global Constraints

- Keep `backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt` unchanged.
- Keep inference size 896, confidence thresholds, ByteTrack, ZoneChecker, Zone geometry, and JPEG quality unchanged.
- Set only BAI-KIEM to 12 FPS; keep GATE-01 at 10 FPS.
- An `OUTSIDE` detection is visible but never allowed to create or appear as a Zone event.
- Do not stage or commit unrelated files from the existing dirty worktree.

---

### Task 1: Increase the BAI-KIEM target rate

**Files:**
- Modify: `backend/.env:58`

**Interfaces:**
- Consumes: `AREA_TARGET_FPS` read by `backend/python-worker/main.py` during worker startup.
- Produces: a target rate of `12.0` passed to `AreaPipeline` without changing inference parameters.

- [ ] **Step 1: Record the current production value**

Run: `rg -n "^AREA_TARGET_FPS=" backend/.env`

Expected before implementation: `AREA_TARGET_FPS=10.0`.

- [ ] **Step 2: Apply the minimal configuration change**

Change exactly:

```dotenv
AREA_TARGET_FPS=12.0
```

- [ ] **Step 3: Verify protected inference settings**

Run:

```powershell
rg -n "^(AREA_TARGET_FPS|GATE_TARGET_FPS|AREA_INFERENCE_SIZE|AREA_TRACK_INITIATION_CONFIDENCE|AREA_TRACK_CONTINUATION_CONFIDENCE|AREA_CLASS_THRESHOLDS_JSON)=" backend/.env
```

Expected: only `AREA_TARGET_FPS` changes; `GATE_TARGET_FPS=10.0` and `AREA_INFERENCE_SIZE=896` remain unchanged.

### Task 2: Render detections outside every Zone

**Files:**
- Modify: `frontend/src/components/AreaMonitor.tsx:545`
- Modify: `frontend/src/hooks/useAreaMonitor.ts:98`

**Interfaces:**
- Consumes: `AreaDetectionDto.status` and `AreaDetectionDto.zoneMatches`.
- Produces: existing violation/allowed overlay styles for Zone matches and a neutral overlay labeled `NGOÀI ZONE` for all other detections.

- [ ] **Step 1: Preserve the existing backend contract**

Confirm `frontend/src/types.ts` already permits:

```ts
status: 'VIOLATION' | 'ALLOWED' | 'OUTSIDE' | string;
```

- [ ] **Step 2: Preserve outside detections in the presentation stabilizer**

Allow every tracked detection into `stableDetections`. Keep the existing short
presentation grace period, and allow replacement track IDs to match when both
the previous and current detection are outside every Zone. Event rows and KPIs
remain Zone-only because their existing selectors still require a non-empty
`zoneMatches` array.

- [ ] **Step 3: Stop discarding outside detections in the component**

Replace the filtered render chain with a direct map over `displayDetections`:

```tsx
{displayDetections.map((det, idx) => {
```

- [ ] **Step 4: Select an explicit neutral presentation**

Inside the render callback, derive presentation without changing DTO state:

```tsx
const isOutside = det.status === 'OUTSIDE' || !det.zoneMatches?.length;
const isViolation = !isOutside && det.status === 'VIOLATION';
const color = isOutside ? '#94a3b8' : isViolation ? '#f43f5e' : '#10b981';
const fill = isOutside
  ? 'rgba(148,163,184,0.10)'
  : isViolation
    ? 'rgba(244,63,94,0.22)'
    : 'rgba(16,185,129,0.12)';
const statusText = isOutside ? 'NGOÀI ZONE' : isViolation ? 'VI PHẠM ZONE' : 'ĐƯỢC PHÉP';
```

Build `labelText` from `statusText`. Do not mutate `det.status`, `det.zoneMatches`, event state, KPIs, or API calls.

- [ ] **Step 5: Typecheck and build the frontend**

Run: `npm run build`

Working directory: `frontend`

Expected: TypeScript and Vite production build succeed.

- [ ] **Step 6: Lint the frontend**

Run: `npm run lint`

Working directory: `frontend`

Expected: no new lint error caused by the overlay change.

### Task 3: Verify runtime behavior and protected V9 artifact

**Files:**
- Read: `backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt`
- Read: `backend/python-worker/main.py`

**Interfaces:**
- Consumes: restarted Python Worker `/health` response and live BAI-KIEM WebSocket feed.
- Produces: evidence that the new target is active and the V9 artifact is unchanged.

- [ ] **Step 1: Verify the V9 checksum**

Run:

```powershell
(Get-FileHash -Algorithm SHA256 -LiteralPath 'backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt').Hash
```

Expected: `3772E978FC4635A6A2D3DFFB59286BD89C0EBBC6CC6E27DC77532B5006EAAB52`.

- [ ] **Step 2: Restart only the Python Worker**

Stop the existing process listening on port 8001, then start `backend/python-worker/.venv/Scripts/python.exe main.py` from `backend/python-worker`. Do not restart Node API or Vite unless they are unavailable.

- [ ] **Step 3: Sample runtime health**

Query `http://127.0.0.1:8001/health` repeatedly after a BAI-KIEM feed subscriber connects.

Expected: startup logs confirm the 12 FPS target. The measured rate approaches
that target when the machine can sustain it; no inference setting is reduced to
force the displayed number. GATE-01 remains inactive unless its feed has a
subscriber.

- [ ] **Step 4: Verify the boundary presentation**

Observe a frame where a detected object has an empty `zoneMatches` array.

Expected: the box is visible in neutral gray with `NGOÀI ZONE`; the Area event count and event list do not change because of that detection.
