# BAI-KIEM V9 210-Frame Annotation-Assist Implementation Plan

> **For agentic workers:** Execute this plan inline and track every checkbox. No subagent is authorized for this run.

**Goal:** Train a temporary YOLO11n helper from task-9 frames 0-209 and safely refresh only frames 210-999 with better CVAT pre-labels.

**Architecture:** One focused CLI owns snapshot/export, low-resource training, proposal generation, and guarded CVAT replacement. Pure conversion, hashing, NMS, and merge functions are separated and unit tested; external CVAT and Ultralytics operations are orchestrated around immutable JSON receipts.

**Tech Stack:** Python 3, requests, Ultralytics YOLO11n, OpenCV/Pillow image metadata, pytest, CVAT REST API.

## Global Constraints

- Never read, train, validate, or predict with locked task 10 images.
- Never activate the helper checkpoint in the application.
- Preserve task-9 frames 0-209 exactly.
- Replace only task-9 frames 210-999 after a concurrent-edit guard succeeds.
- Use native task-package images and low-memory execution (`batch=1`, `workers=0`, no cache).
- Do not create or use `container_truck` proposals; both truck variants remain `truck`.
- Persist snapshot, rollback payload, dataset manifest, metrics, and apply receipt.

---

### Task 1: Pure annotation-assist contracts

**Files:**
- Create: `backend/python-worker/training/cvat_annotation_assist.py`
- Create: `backend/python-worker/tests/test_cvat_annotation_assist.py`

**Interfaces:**
- Produces: `canonical_shape_hash`, `shape_to_yolo`, `deterministic_split`, `class_agnostic_nms`, `merge_preserving_prefix`.

- [ ] Write tests proving frame-boundary preservation, deterministic split, valid YOLO conversion, and cross-class overlap suppression.
- [ ] Run `pytest tests/test_cvat_annotation_assist.py -q` and verify the new tests fail because the module is absent.
- [ ] Implement the pure functions with explicit validation and stable canonical ordering.
- [ ] Re-run the focused tests and verify they pass.

### Task 2: Snapshot and reviewed-prefix export

**Files:**
- Modify: `backend/python-worker/training/cvat_annotation_assist.py`
- Modify: `backend/python-worker/tests/test_cvat_annotation_assist.py`

**Interfaces:**
- Produces: `snapshot_and_export(config) -> dict`, a complete rollback snapshot and a 210-frame YOLO package.

- [ ] Test rejection of unknown labels, non-rectangle annotations, missing task-package frames, and reviewed-prefix bus/container labels when their intended count is zero.
- [ ] Implement CVAT login/read helpers, source-package frame mapping, exact snapshot serialization, prefix class counts, deterministic train/val materialization, `data.yaml`, and a hashed manifest.
- [ ] Verify the focused tests pass and run the command in snapshot/export-only mode against task 9.
- [ ] Confirm exactly 210 images are exported and the live bus annotation deleted by the user is absent.

### Task 3: Low-resource helper training

**Files:**
- Modify: `backend/python-worker/training/cvat_annotation_assist.py`
- Modify: `backend/python-worker/tests/test_cvat_annotation_assist.py`

**Interfaces:**
- Produces: `train_helper(config, dataset) -> Path` and `training-receipt.json`.

- [ ] Test that training arguments force YOLO11n pretrained initialization, batch 1, workers 0, no cache, AMP, bounded threads, and a non-activation artifact directory.
- [ ] Implement low-priority Windows process configuration, CUDA detection, training call, best-checkpoint validation, metric serialization, and artifact hashing.
- [ ] Run tests, then train the helper once from the exported 210 frames.
- [ ] Verify `best.pt`, metrics, class map, and dataset hash exist without modifying active model configuration.

### Task 4: Remaining-frame proposals

**Files:**
- Modify: `backend/python-worker/training/cvat_annotation_assist.py`
- Modify: `backend/python-worker/tests/test_cvat_annotation_assist.py`

**Interfaces:**
- Produces: `predict_remaining(config, best_path) -> list[dict]` for CVAT frames 210-999.

- [ ] Test helper-class conversion, absent-class confidence gates, global cross-class NMS, no `container_truck`, and no proposal before frame 210.
- [ ] Implement sequential batch-1 prediction over the existing 790 images and conservative reuse of absent-class proposal details.
- [ ] Persist per-frame and per-class proposal statistics and validate every box against native dimensions.
- [ ] Run the focused test suite and generate remaining-frame predictions.

### Task 5: Guarded CVAT apply and audit

**Files:**
- Modify: `backend/python-worker/training/cvat_annotation_assist.py`
- Modify: `backend/python-worker/tests/test_cvat_annotation_assist.py`

**Interfaces:**
- Produces: `apply_guarded(config, snapshot, predictions) -> dict` and `restore_snapshot(config, snapshot_path)`.

- [ ] Test concurrent-edit abort, exact prefix preservation, task-10 empty guard, rollback serialization, and post-write verification failure behavior.
- [ ] Implement live version/prefix-hash comparison, full-task merge, CVAT PUT, immediate GET verification, locked-task check, and restore command.
- [ ] Apply the new proposals only if every precondition passes.
- [ ] Confirm the prefix hash is unchanged, task 10 is empty, and write the final audit receipt with the CVAT resume URL.

### Task 6: Final verification

**Files:**
- Verify: `backend/python-worker/tests/test_cvat_annotation_assist.py`
- Verify: generated ignored artifacts under `backend/data/training/annotation/baikiem-v9-annotation-assist-210/`

- [ ] Run the focused tests and the related CVAT package tests.
- [ ] Inspect task-9 counts split at frame 210 and prove no active model path changed.
- [ ] Report helper metrics, before/after counts, safety hashes, locked-task status, and the frame-211 resume link.

