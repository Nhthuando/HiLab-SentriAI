# Monitor UI and Annotation Source Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GATE playback controls match BAI-KIEM, remove legacy demo annotation media, and make monitor controls readable in light theme.

**Architecture:** Keep all video behavior inside the existing monitor components and preserve the current APIs. Treat the upload API as the only persistent media source, migrate only known demo entries out of local storage, and render an explicit empty annotation state.

**Tech Stack:** React 19, TypeScript 6, Vite 8, inline CSS using existing theme tokens.

## Global Constraints

- Do not modify Python Worker, Node API, database, detector, LPR, event, or stream behavior.
- GATE pause is display-only and must keep WebSocket processing alive.
- Preserve every server-returned or genuinely user-uploaded annotation source.
- Do not commit or push the active merge without explicit user approval.

---

### Task 1: Remove legacy annotation demo data

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Settings/ObjectLabelTab.tsx`

**Interfaces:**
- Consumes: `getMediaSources(): Promise<any[]>` and `AnnotationSource`.
- Produces: annotation state containing only uploaded sources and an empty-safe editor.

- [ ] **Step 1: Record the failing conditions**

Run:

```powershell
rg -n "INITIAL_ANN_SOURCES|INITIAL_ANN_SAMPLES|src1|src2" frontend/src/App.tsx frontend/src/mockData.ts
```

Expected before the fix: `App.tsx` initializes and re-merges demo sources.

- [ ] **Step 2: Implement source cleanup in App**

Initialize annotation sources and samples as empty arrays. When loading local storage, remove only entries whose `id` is `src1` or `src2` and whose `isDefault` flag is true. Replace merge-on-fetch with server media plus unsaved local uploads, never with `INITIAL_ANN_SOURCES`.

- [ ] **Step 3: Implement the empty editor state**

Change `ObjectLabelTab` to use `AnnotationSource | null` for `currentSource`. Guard drawing, playback, box filtering, and media rendering when it is null. Render an upload instruction in the canvas and reset `activeSourceId` when the selected source disappears.

- [ ] **Step 4: Verify the annotation fix**

Run:

```powershell
npm run build
npm run lint
```

Expected: both commands pass, and an empty media API response leaves no demo thumbnails.

### Task 2: Match GATE playback controls to BAI-KIEM

**Files:**
- Modify: `frontend/src/components/GateMonitor.tsx`

**Interfaces:**
- Consumes: existing `getCameraPlayback('GATE-01')`, `seekCamera('GATE-01', positionMs)`, `frameImage`, and `detections`.
- Produces: local `togglePause()`, frozen display state, bounded ten-second seeking, and matching playback controls.

- [ ] **Step 1: Add display-only pause state**

Add `isPaused`, `frozenFrame`, and `frozenDetections`. `togglePause()` captures the current frame and detections when pausing and releases them when resuming. Render `displayFrame` and `displayDetections` without changing the WebSocket hook.

- [ ] **Step 2: Add the timestamp pause button**

Add the same pause/resume button and paused status treatment used by BAI-KIEM beside `displayedTimecode`.

- [ ] **Step 3: Replace the GATE seek row**

Use the BAI-KIEM visual layout with `-10s`, pause/resume, `+10s`, combined current/total time, and the existing range input. Convert ten seconds to `10_000` milliseconds and clamp every target to `[0, durationMs]`.

- [ ] **Step 4: Verify GATE TypeScript behavior**

Run:

```powershell
npm run build
npm run lint
```

Expected: both commands pass with no changes to API signatures.

### Task 3: Fix light-theme monitor contrast and perform regression checks

**Files:**
- Modify: `frontend/src/components/AreaMonitor.tsx`
- Modify: `frontend/src/components/GateMonitor.tsx`

**Interfaces:**
- Consumes: existing CSS variables from `frontend/src/index.css`.
- Produces: theme-safe text and neutral button colors.

- [ ] **Step 1: Replace hard-coded neutral white styles**

Use `var(--ink)` for status-bar titles and unpaused timestamp buttons, `var(--raise)` or `var(--card)` for neutral backgrounds, and `var(--p1q)` for paused backgrounds. Keep white only on solid accent/status backgrounds where it has sufficient contrast.

- [ ] **Step 2: Run final frontend verification**

Run:

```powershell
npm run build
npm run lint
```

Expected: both commands pass.

- [ ] **Step 3: Inspect scope and merge health**

Run:

```powershell
git diff --name-only --diff-filter=U
git diff --check
git status -sb
```

Expected: no unmerged paths, no whitespace errors, and only frontend/docs files added by this fix beyond the already staged merge.
