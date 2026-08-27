# BAI-KIEM V9 600-Frame Annotation-Assist Implementation Plan

> **For agentic workers:** Execute inline. No subagent is authorized for this run. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fine-tune the temporary helper on task-9 frames 0-599 and safely refresh only frames 600-999.

**Architecture:** Reuse the existing snapshot/export/train/predict/filter/audit/apply CLI with a configurable boundary and run name. The 210-frame helper is only an initialization checkpoint; the new artifact remains isolated and inactive.

**Tech Stack:** Python, Ultralytics YOLO11n, requests, OpenCV, unittest, CVAT REST API.

## Global Constraints

- Task 10 is read-only and never supplies training, validation, or prediction images.
- Frames 0-599 must remain unchanged in CVAT.
- Only frames 600-999 may receive new auto rectangles.
- Use batch 1, workers 0, no cache, bounded threads, and BelowNormal priority.
- Never activate either annotation-helper checkpoint.
- Keep `container_truck` excluded; loaded and unloaded trucks use `truck`.

---

### Task 1: Generalize the helper iteration

**Files:**
- Modify: `backend/python-worker/training/cvat_annotation_assist.py`
- Modify: `backend/python-worker/tests/test_cvat_annotation_assist.py`

- [ ] Add a failing test for boundary-specific run naming and fine-tune learning rate.
- [ ] Derive the run name from the boundary and allow the prior isolated helper as initialization.
- [ ] Make audit-frame sampling cover the current remaining range.
- [ ] Run the focused tests.

### Task 2: Snapshot and train

**Files:**
- Generate: `backend/data/training/annotation/baikiem-v9-annotation-assist-600/`

- [ ] Snapshot task 9 and prove task 10 is empty.
- [ ] Export exactly 600 native frames and audit class coverage in train/validation.
- [ ] Fine-tune for at most 25 epochs with the 210-frame helper checkpoint.
- [ ] Verify the new checkpoint is isolated and record metrics/hashes.

### Task 3: Predict, filter, and visually audit

**Files:**
- Generate: `backend/data/training/annotation/baikiem-v9-annotation-assist-600/predictions.json`
- Generate: `backend/data/training/annotation/baikiem-v9-annotation-assist-600/audit/`

- [ ] Predict frames 600-999 sequentially.
- [ ] Apply balanced confidence gates and cross-class NMS.
- [ ] Render evenly spaced audit montages and inspect false-positive density.
- [ ] Tighten filters and repeat the audit if the first montage is noisy.

### Task 4: Apply and verify

**Files:**
- Generate: `backend/data/training/annotation/baikiem-v9-annotation-assist-600/apply-receipt.json`

- [ ] Recheck the live full-task hash and locked-task emptiness.
- [ ] Replace only frames 600-999.
- [ ] Verify the 0-599 prefix hash is unchanged or automatically roll back.
- [ ] Run focused/related tests and report metrics, counts, and the frame-601 CVAT link.
