# BAI-KIEM Local-Video Unified YOLO11n Implementation Plan

> **For agentic workers:** Execute inline in this session. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reviewed, source-isolated local-video dataset and a one-pass YOLO11n Area detector that distinguishes `reach_stacker` from `truck` while preserving at least 8 end-to-end FPS.

**Architecture:** Prepare a private CVAT/Ultralytics annotation package from `D:\video_test` using source-level train/validation/test locks and model-assisted annotations that remain explicitly unreviewed. Train the same nano architecture on the reviewed domain classes, expose a manifest-declared `UNIFIED` runtime mode, and let the Area detector run that model as the sole tracked inference pass; the existing COCO-plus-supplemental-custom mode remains the rollback path.

**Tech Stack:** Python 3.12, OpenCV, Ultralytics YOLO11, ByteTrack, PyTorch CUDA/FP16, optional TensorRT FP16, TypeScript 5.6, Express, Prisma, unittest.

## Global Constraints

- Keep the object-label registry as the system-wide detection whitelist.
- Never treat pseudo-labels as reviewed ground truth.
- Never place duplicate/transcoded copies of one video source across different splits.
- Keep `KiemHoa-Hik (2)_fastseek.mp4` and `output_test.mp4` out of training.
- Do not upload private BAI-KIEM video or frames to an external service.
- Keep Gate/LPR, clips, Zone lifecycle, Q&A, and frontend behavior intact.
- The final selected runtime must sustain at least 8 end-to-end Area FPS on the RTX 3050 Laptop 4 GB.
- Do not activate a model until local-video precision, recall, temporal continuity, hard-negative false-positive rate, and end-to-end FPS gates pass.
- Do not commit, push, merge, or deploy.

---

### Task 1: Reproducible Local-Video Annotation Package

**Files:**
- Create: `backend/python-worker/training/local_video_dataset.py`
- Create: `backend/python-worker/tests/test_local_video_dataset.py`
- Create: `backend/config/baikiem-local-video-plan.json`
- Create: `docs/evaluation/baikiem-local-video-annotation.md`

**Interfaces:**
- Consumes: local video files, `yolo11n.pt`, and an optional reach-stacker proposal checkpoint.
- Produces: `build_annotation_package(plan_path, output_dir, base_model_path, reach_model_path) -> dict[str, object]`, an Ultralytics/CVAT-compatible image/label tree, `data.yaml`, `annotation-manifest.json`, and `review.csv`.

- [x] **Step 1: Write validation tests**

  Cover source ID uniqueness, duplicate-group split isolation, test-source exclusion from train, portable output paths, supported class order, and deterministic timestamp sampling.

- [x] **Step 2: Run the focused test and verify failure**

  Run: `& '.venv/Scripts/python.exe' -m unittest tests.test_local_video_dataset -v`

  Expected: FAIL because `training.local_video_dataset` does not exist.

- [x] **Step 3: Implement sequential extraction and proposal merging**

  Use sequential `VideoCapture.grab/retrieve`, dHash near-duplicate suppression, and fixed source-level splits. Map base outputs only for currently enabled `person`, `bicycle`, `car`, `motorcycle`, and `truck`; map the proposal checkpoint only to `reach_stacker`. If a reach-stacker proposal overlaps a truck proposal, keep `reach_stacker` and remove the truck proposal. Mark every output record `PENDING_REVIEW` regardless of proposal confidence.

- [x] **Step 4: Add the locked source plan**

  Use `KiemHoa-Hik (1)_fastseek.mp4` for train, one contiguous block from that source for validation, `KiemHoa-Hik (2)_fastseek.mp4` for positive test, June 18/20 BAI-KIEM clips for train/validation hard negatives, short indoor forklift clips for hard negatives, and `output_test.mp4` for negative test. Put every KiemHoa transcode in one duplicate group.

- [x] **Step 5: Run tests and build the package**

  Run the focused test, then invoke the CLI against `backend/data/training/annotation/baikiem-local-v1`. Confirm no source path is emitted outside the local source-plan file and no test image exists under `images/train`.

- [x] **Step 6: Document the human review contract**

  Record the exact package path, class list, frame count, CVAT import/export format, and the rule that all boxes and empty frames must be reviewed before training.

### Task 2: Reviewed-Dataset Gate and Audit

**Files:**
- Modify: `backend/python-worker/training/local_video_dataset.py`
- Modify: `backend/python-worker/training/dataset_audit.py`
- Modify: `backend/python-worker/tests/test_local_video_dataset.py`
- Modify: `backend/python-worker/tests/test_dataset_audit.py`

**Interfaces:**
- Consumes: the returned CVAT Ultralytics YOLO ZIP/directory and `annotation-manifest.json`.
- Produces: `finalize_reviewed_package(...)` with a content-addressed training snapshot and a machine-readable audit report.

- [x] **Step 1: Add failing review-gate tests**

  Assert that missing images, invalid normalized boxes, unknown class IDs, incomplete review rows, duplicate source leakage, and train/test SHA overlap all block finalization.

- [x] **Step 2: Implement strict reviewed import**

  Require one explicit reviewed row per frame, preserve the locked split/source metadata, recompute image hashes, and reject any path traversal or unexpected file.

- [x] **Step 3: Extend the audit**

  Report per-class boxes, positive/negative frames, small/medium/large object buckets, source counts, split counts, duplicate hashes, and `truck`/`reach_stacker` overlap candidates.

- [x] **Step 4: Run the focused audit tests**

  Run: `& '.venv/Scripts/python.exe' -m unittest tests.test_local_video_dataset tests.test_dataset_audit -v`

  Expected: PASS.

### Task 3: Unified Model Manifest and Routing

**Files:**
- Modify: `backend/node-api/src/detection/capabilities.ts`
- Modify: `backend/node-api/src/services/detectionCapabilityService.ts`
- Modify: `backend/node-api/src/tests/test_detection_taxonomy.ts`
- Modify: `backend/python-worker/detection/taxonomy.py`
- Modify: `backend/python-worker/tests/test_detection_taxonomy.py`
- Modify: `backend/python-worker/zone/zone_sync.py`
- Modify: `backend/python-worker/tests/test_zone_sync_capabilities.py`

**Interfaces:**
- Consumes: ACTIVE `evaluationMetrics.runtimeMode` equal to `UNIFIED` and its exact `labelMap`.
- Produces: an atomic detection snapshot that marks manifest-owned COCO and custom classes as `UNIFIED`, while legacy manifests continue to resolve as base COCO plus supplemental custom.

- [x] **Step 1: Add failing routing-matrix tests**

  Cover `UNIFIED` ownership of every currently enabled COCO class plus `reach_stacker` and `forklift`, incomplete unified manifests, legacy supplemental manifests, malformed runtime modes, and no-active-model fallback.

- [x] **Step 2: Implement strict manifest parsing**

  Accept only `SUPPLEMENTAL` or `UNIFIED`; default old manifests to `SUPPLEMENTAL`. A unified model is usable only when it covers every currently enabled detectable label, otherwise fail closed to base COCO.

- [x] **Step 3: Keep Node/Python parity**

  Return the same canonical classes, source, active version, and reason codes from both implementations.

- [x] **Step 4: Run parity and API tests**

  Run Python taxonomy/zone tests and Node detection-capability tests. Expected: PASS.

### Task 4: One-Pass Unified Tracking Runtime

**Files:**
- Modify: `backend/python-worker/detection/tracked_detector.py`
- Modify: `backend/python-worker/detection/area_pipeline.py`
- Modify: `backend/python-worker/tests/test_area_pipeline.py`
- Modify: `backend/python-worker/tests/test_detection_policy.py`
- Modify: `backend/python-worker/training/benchmark_models.py`

**Interfaces:**
- Consumes: the unified detection snapshot and checksum-verified model artifact.
- Produces: `configure_unified_model(...)` and a single ByteTrack-backed inference path with exact canonical output mapping.

- [x] **Step 1: Add failing single-pass tests**

  Assert that unified mode calls one model exactly once per processed frame, never calls the base model, preserves ByteTrack IDs, uses class-specific initiation/continuation thresholds, and reverts to the existing base path when the unified artifact is invalid.

- [x] **Step 2: Implement unified loading and tracking**

  Reuse checksum/root validation, run `.track(..., persist=True)` on the unified YOLO11n, normalize exact manifest class names, and pass results through the existing whitelist and temporal policy. Do not run supplemental ROI or a second model in unified mode.

- [x] **Step 3: Reset safely on seek/config changes**

  Clear ByteTrack and temporal evidence on seek, source reset, or model-version change; an equivalent snapshot must not reset state.

- [x] **Step 4: Extend the production benchmark**

  Add unified PyTorch FP16 and TensorRT FP16 cells, reporting decode, inference, merge/tracking, serialization, end-to-end FPS, p95 latency, and VRAM.

- [x] **Step 5: Run the Python regression suite**

  Run: `& '.venv/Scripts/python.exe' -m unittest discover -s tests -v`

  Expected: all tests PASS.

### Task 5: Train, Evaluate, Export, and Activation Gate

**Files:**
- Modify: `backend/python-worker/training/runner.py`
- Modify: `backend/python-worker/training/finalize_checkpoint.py`
- Modify: `backend/python-worker/evaluation/metrics.py`
- Create: `docs/evaluation/baikiem-local-v1-results.md`
- Create: `backend/data/training/reports/baikiem-local-v1-results.json`

**Interfaces:**
- Consumes: the finalized reviewed snapshot from Task 2.
- Produces: a YOLO11n checkpoint and manifest with `runtimeMode: UNIFIED`, optional TensorRT FP16 engine, video-level evaluation, and either a rejected candidate or an activation-ready candidate.

- [x] **Step 1: Add failing unified-training manifest tests**

  Assert exact class order, `runtimeMode: UNIFIED`, source-grouped split provenance, artifact hash, training args, and rejection when any acceptance metric is undefined.

- [ ] **Step 2: Train YOLO11n with realistic augmentation**

  Train at `imgsz=896` with early stopping and conservative brightness, blur, compression, and scale augmentation. Do not use unrealistic rotations or duplicate augmented siblings across splits.

- [ ] **Step 3: Calibrate at inference sizes 640, 768, and 896**

  Select per-class initiation/continuation thresholds from validation PR curves; use the locked test videos only once after selection.

- [ ] **Step 4: Run video-level acceptance**

  Require reach-stacker precision and recall at least 0.90, no truck-to-reach false promotion on the locked negative videos, no detection gap longer than 0.5 seconds while a reviewed target is visible, and at least 8 end-to-end FPS.

- [ ] **Step 5: Export and benchmark TensorRT FP16**

  Export with current Ultralytics precision syntax (`quantize=16`), compare accuracy with PyTorch FP16, and retain PyTorch if export changes predictions beyond the gate.

- [ ] **Step 6: Register without automatic activation**

  Save the version as `CANDIDATE` with complete metrics. Activate only after every gate passes and a rollback version is recorded; otherwise leave the current runtime untouched and document the blocker.

### Task 6: Full Regression and Operator Handoff

**Files:**
- Modify: `docs/evaluation/2026-08-22-detection-acceptance.md`
- Modify: `docs/backend/tasks/VS-OBJECT-MODEL-VERSION.md`
- Modify: `docs/backend/tasks/VS-AREA-VIOLATION.md`

**Interfaces:**
- Consumes: all implementation, dataset, model, and benchmark artifacts.
- Produces: a reproducible operator runbook and final evidence table.

- [ ] **Step 1: Run all regression gates**

  Run Python unittest discovery, Node API tests/typecheck, and the frontend production build. Confirm Gate/LPR and Area seek/playback smoke checks.

- [ ] **Step 2: Record exact results and rollback**

  Document dataset hash, split sources, checkpoint hash, selected thresholds, runtime mode, FPS, VRAM, false positives per video-hour, activation state, and rollback command.

- [ ] **Step 3: Self-review against `improve.md`**

  Verify every invariant, scan for placeholder claims, and do not report completion while reviewed local annotations or acceptance metrics are missing.
