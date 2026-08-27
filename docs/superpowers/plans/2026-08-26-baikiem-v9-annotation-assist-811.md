# BAI-KIEM V9 811-Frame Annotation-Assist Implementation Plan

> **For agentic workers:** Execute inline. No subagent is authorized for this run. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fine-tune the helper on reviewed frames 0-810, preserve manually propagated suffix boxes, and refresh auto proposals on frames 811-999.

**Architecture:** Extend the existing guarded merge with a protected-manual suffix contract and add pre-fine-tune baseline validation. Continue using isolated, hashed artifacts and rollback payloads.

**Tech Stack:** Python, Ultralytics YOLO11n, requests, OpenCV, unittest, CVAT REST API.

## Global Constraints

- Frames 0-810 are the only training/validation inputs.
- All manual suffix rectangles survive the apply unchanged.
- Only suffix auto rectangles may be replaced.
- Task 10 remains read-only and empty.
- The helper remains inactive in SentriAI.

---

### Task 1: Protect suffix manual annotations

**Files:**
- Modify: `backend/python-worker/training/cvat_annotation_assist.py`
- Modify: `backend/python-worker/tests/test_cvat_annotation_assist.py`

- [ ] Test that stale auto suffix shapes are replaced while manual suffix shapes survive.
- [ ] Test that an overlapping prediction cannot duplicate a protected manual rectangle.
- [ ] Record and verify a separate protected-suffix hash before and after apply.
- [ ] Run focused tests.

### Task 2: Snapshot, baseline, and fine-tune

**Files:**
- Generate: `backend/data/training/annotation/baikiem-v9-annotation-assist-811/`

- [ ] Export exactly 811 reviewed frames and snapshot the full task.
- [ ] Evaluate the 600-frame helper on the new validation split.
- [ ] Fine-tune for at most 15 epochs and record before/after metric deltas.
- [ ] Verify the helper artifact is isolated and inactive.

### Task 3: Refresh remaining proposals

- [ ] Predict frames 811-999 sequentially and filter low-confidence noise.
- [ ] Render and inspect evenly spaced audit frames.
- [ ] Apply only after the task hash is unchanged.
- [ ] Verify prefix and protected-suffix hashes, task-10 emptiness, job state, and tests.

