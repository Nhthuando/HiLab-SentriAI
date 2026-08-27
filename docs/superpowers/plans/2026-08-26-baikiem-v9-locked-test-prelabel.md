# BAI-KIEM V9 Locked-Test Pre-label Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely pre-label CVAT task 10 with the task-9-only annotation helper while preserving the locked-test data boundary.

**Architecture:** Add a focused locked-test pre-label CLI that reuses the existing CVAT client, hashing, NMS, and rectangle conversion helpers. Keep all locked-test artifacts under the completed 1000-frame helper output and guard every CVAT write with task, media, and checkpoint hashes.

**Tech Stack:** Python 3.12, Ultralytics YOLO11n, PyTorch CUDA, OpenCV, CVAT REST API, `unittest`.

## Global Constraints

- Never add task-10 images or annotations to a train or validation manifest.
- Never calculate task-10 detection metrics before human review or use them to tune the model.
- Never activate the annotation helper in SentriAI runtime paths.
- Use batch 1, zero dataloader workers, and one OpenCV/PyTorch CPU thread.
- Refuse CVAT writes when task 9, task 10, media mapping, or checkpoint hashes differ from the snapshot.

---

### Task 1: Locked-test pure validation and filtering

**Files:**
- Create: `backend/python-worker/training/cvat_locked_test_prelabler.py`
- Create: `backend/python-worker/tests/test_cvat_locked_test_prelabler.py`

**Interfaces:**
- Consumes: `canonical_shape_hash`, `class_agnostic_nms`, and `CANONICAL_CLASSES` from `training.cvat_annotation_assist`.
- Produces: `validate_frame_mapping(...)`, `filter_locked_proposals(...)`, and `build_prediction_shapes(...)`.

- [ ] Write failing unit tests for exact media mapping, class thresholds, cross-class duplicate suppression, and normalized-to-pixel rectangle conversion.
- [ ] Run `python -m unittest discover -s tests -p 'test_cvat_locked_test_prelabler.py' -v` and confirm the missing module/functions fail.
- [ ] Implement the pure functions with explicit type and range validation.
- [ ] Re-run the focused tests and require all to pass.

### Task 2: Snapshot, prediction, audit, and guarded apply stages

**Files:**
- Modify: `backend/python-worker/training/cvat_locked_test_prelabler.py`
- Modify: `backend/python-worker/tests/test_cvat_locked_test_prelabler.py`

**Interfaces:**
- Consumes: locked package `annotation-manifest.json`, task-9 snapshot, training receipt, and helper checkpoint.
- Produces: `locked-review/snapshot.json`, `predictions-low-threshold.json`, `predictions.json`, audit montages, `apply-payload.json`, and `apply-receipt.json`.

- [ ] Add failing tests proving task-10 non-empty snapshots and changed task-9 hashes are rejected.
- [ ] Implement `snapshot`, `predict`, `filter`, `audit`, and `apply` CLI stages.
- [ ] Make apply re-fetch both tasks, verify hashes, write task 10, verify the post-write hash, and rollback on failure.
- [ ] Run both the new test file and existing annotation-assist tests.

### Task 3: Execute and verify the pre-label workflow

**Files:**
- Create runtime artifacts only under `backend/data/training/annotation/baikiem-v9-annotation-assist-1000/locked-review/`.

**Interfaces:**
- Consumes: CVAT task 9, empty task 10, the locked package, and `annotation-helper-best.pt`.
- Produces: editable CVAT task-10 proposals and an evidence receipt.

- [ ] Snapshot task 10 and confirm task 9 still matches the training source hash.
- [ ] Predict all 200 images at low confidence, filter proposals, and render 12 audit samples.
- [ ] Inspect both montages; adjust only annotation-assist thresholds if proposal noise is unusable.
- [ ] Apply proposals and independently verify task-9 hash, task-10 shape/source counts, and job state.
- [ ] Confirm no runtime configuration references the helper checkpoint.

