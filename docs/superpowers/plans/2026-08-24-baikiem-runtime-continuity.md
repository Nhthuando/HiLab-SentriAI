# BAI-KIEM Runtime Detection Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove BAI-KIEM cold-start delay, reach-stacker label dropout, generic `truck` fallback, and box jumping without retraining or adding inference passes.

**Architecture:** Preload and warm the Area detection control during worker startup. Give supplemental custom detections their own spatially associated identity, retain confirmed state for a bounded gap, smooth their boxes, and arbitrate overlapping generic vehicle output in favor of the confirmed custom class.

**Tech Stack:** Python 3.12, FastAPI, OpenCV, NumPy, Ultralytics YOLO11, unittest.

## Global Constraints

- Do not train or change any dataset/model artifact.
- Keep custom initiation confidence 0.40 and continuation confidence 0.25.
- Keep 2-of-3 initial custom confirmation.
- Keep `CUSTOM_AUGMENT_INTERVAL=2` and `CUSTOM_AUGMENT_TILE_ENABLED=false`.
- Add no extra inference pass per processed frame.
- Preserve base-only failover, seek/reset behavior, Gate/LPR behavior, events, clips, and database semantics.
- Leave all changes uncommitted and run `git diff --check`.

---

### Task 1: Lock continuity behavior with detector tests

**Files:**
- Modify: `backend/python-worker/tests/test_area_pipeline.py`

**Interfaces:**
- Consumes: `TrackedYoloDetector._apply_custom_augmentation(frame, detections, width, height)`.
- Produces: regression coverage for stable negative custom IDs, sticky confirmation, expiry, smoothing, and generic suppression.

- [ ] **Step 1: Update the two-hit promotion assertion**

Assert that a promoted custom object receives a negative ID independent of base track ID 11:

```python
self.assertLess(second[0]["trackId"], 0)
self.assertEqual(second[0]["canonicalClass"], "reach_stacker")
```

- [ ] **Step 2: Add changing-base-ID continuity coverage**

Feed matching custom boxes while base IDs change from 11 to 27 and then disappear. Assert one unchanged negative custom ID, no overlapping `truck`, and `reach_stacker` on every frame after initial confirmation.

- [ ] **Step 3: Add bounded hold and expiry coverage**

Return no custom candidates through the configured bounded hold and assert retention; after the hold and base-support grace both expire, assert removal.

- [ ] **Step 4: Add box smoothing coverage**

Move the raw custom box by 10 pixels and assert the emitted box moves by 6-7 pixels with EMA alpha 0.65 rather than jumping the full distance.

- [ ] **Step 5: Run the focused tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_area_pipeline.py" -v
```

Expected: the new continuity assertions fail against base-owned evidence keys and two-miss deconfirmation.

### Task 2: Implement custom-owned stable tracks

**Files:**
- Modify: `backend/python-worker/detection/tracked_detector.py`
- Test: `backend/python-worker/tests/test_area_pipeline.py`

**Interfaces:**
- Produces: `_custom_evidence_key(custom, target) -> str` which ignores target identity and selects a one-to-one spatial candidate.
- Produces: `_active_custom_records() -> list[dict[str, Any]]` for bounded confirmed output.
- Produces: `_retain_confirmed_custom_tracks(detections) -> list[dict[str, Any]]` which suppresses only overlapping generic vehicles.

- [ ] **Step 1: Add validated continuity settings**

Read `CUSTOM_TRACK_HOLD_OPPORTUNITIES` with default 8/minimum 1, `CUSTOM_TRACK_BOX_EMA_ALPHA` with default 0.65, and `CUSTOM_TRACK_MAX_EDGE_STEP_RATIO` with default 0.015.

- [ ] **Step 2: Allocate spatial custom identity**

Remove the `base:<trackId>` evidence-key branch. Select the best eligible same-class/same-clock candidate by IoU then center distance, skip records already observed at the current opportunity, and allocate a negative synthetic ID for a new candidate.

- [ ] **Step 3: Apply sticky confirmation and EMA**

Retain `confirmed=True` after initial promotion until `current_opportunity - last_seen > hold`. Smooth current box and normalized box with:

```python
smoothed = round(previous * (1.0 - alpha) + current * alpha)
```

Continue an already confirmed custom record with one-to-one spatially matching generic base geometry. Translate/scale the custom box from base motion, retain the synthetic custom ID/class, and expire after twelve unsupported base frames.

- [ ] **Step 4: Arbitrate output**

Emit confirmed custom records using their negative IDs, suppress overlapping `truck`/`bus`/`car`, preserve unrelated detections, and remove the old base-ID carry-forward behavior.

- [ ] **Step 5: Run focused tests**

Run the Task 1 unittest command. Expected: PASS.

### Task 3: Preload and prewarm Area detection

**Files:**
- Modify: `backend/python-worker/detection/area_pipeline.py`
- Modify: `backend/python-worker/detection/tracked_detector.py`
- Modify: `backend/python-worker/main.py`
- Test: `backend/python-worker/tests/test_area_pipeline.py`

**Interfaces:**
- Produces: `TrackedYoloDetector.warmup(frame_shape: tuple[int, int]) -> None`.
- Produces: `AreaPipeline.prepare() -> Awaitable[bool]`.

- [ ] **Step 1: Add failing preparation test**

Use an `AsyncMock` zone refresh plus a detector mock. Assert `prepare()` applies the initial snapshot, invokes `warmup((1280, 720))`, resets tracking, and does not consume a reader frame.

- [ ] **Step 2: Implement detector warmup**

Create one zero-valued frame at the configured resolution, call the normal `track()` path once, and reset tracking in `finally`.

- [ ] **Step 3: Implement pipeline preparation**

Refresh the snapshot, apply/remember its detection control, and run warmup via `asyncio.to_thread`. Return false on failure while logging the fallback.

- [ ] **Step 4: Prepare during worker startup**

Await `area_pipeline.prepare()` after construction and before publishing the pipeline in the global map.

- [ ] **Step 5: Run focused tests**

Run the Task 1 command. Expected: PASS.

### Task 4: Regression and live-video verification

**Files:**
- Verify: `backend/python-worker/tests/`
- Verify: `backend/node-api/src/`
- Inspect: `backend/data/runtime-logs/`

**Interfaces:**
- Consumes the production REST/WebSocket paths without changing their contract.

- [ ] **Step 1: Run the Python worker suite**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

Expected: all tests pass.

- [ ] **Step 2: Run Node type checking**

```powershell
npm.cmd run typecheck
```

Expected: exit code 0.

- [ ] **Step 3: Restart only the Python worker and inspect startup**

Confirm one V8 load, one manual-candidate warning, no custom inference failure, and no `half deprecated` warning.

- [ ] **Step 4: Exercise the first 30 seconds through `/ws/feed/area`**

Seek to zero, collect emitted detections, and assert first custom output within one second of emitted video, one negative custom track ID, no overlapping generic vehicle fallback, and no custom dropout after confirmation.

- [ ] **Step 5: Check formatting and hand off**

Run `git diff --check`, preserve V7 rollback, and report measured continuity/FPS instead of claiming universal camera accuracy.
