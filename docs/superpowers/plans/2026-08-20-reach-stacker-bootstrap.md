# Reach-Stacker Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use inline execution in this session. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely turn the supplied Roboflow YOLOv8 reach-stacker archive into an immutable training dataset, train an evaluated custom candidate on the local GPU, and leave the base detector unchanged.

**Architecture:** An external archive is never used in place. Its contents are path-validated, copied into `backend/data/training/datasets/<id>/media`, and represented by the existing manifest schema. The Python runner materializes this immutable snapshot, evaluates only against its supplied held-out split, and creates a candidate only after the quality gate passes.

**Tech Stack:** Node.js/TypeScript, Prisma/Neon development database, Python 3.12, Ultralytics YOLOv8, CUDA, OpenCV.

## Global Constraints

- Preserve the base YOLO/YOLO-World detector and its person/container/vehicle detections.
- Treat `stacker` as `reach stacker`; do not relabel it as an ordinary forklift.
- Reject archive path traversal, malformed YOLO boxes, duplicate split assignments, and unreadable images.
- Keep the camera inactive while training; the runner must pause if a monitor becomes active.
- Do not commit, create a branch, or publish external artifacts.

---

### Task 1: Validate and import the external YOLOv8 archive

**Files:**
- Create: `backend/node-api/src/services/externalYoloDataset.ts`
- Create: `backend/node-api/src/scripts/import-external-yolo.ts`
- Test: `backend/node-api/src/tests/test_external_yolo_dataset.ts`

**Interfaces:**
- Consumes: `importExternalYoloArchive({ archivePath, labelMap })` where `labelMap` is `{ stacker: 'reach stacker' }`.
- Produces: `{ datasetId, manifestPath, sampleCount, sourceCount, contentHash }` and one immutable manifest schema `2` snapshot.

- [ ] **Step 1: Write archive-validation tests**

```ts
expect(() => parseYoloLine('0 0.5 0.5 1.2 0.4')).toThrow('normalized');
expect(() => safeArchiveEntry('../outside.jpg')).toThrow('unsafe');
```

- [ ] **Step 2: Implement safe import**

```ts
const box = { x: centerX - width / 2, y: centerY - height / 2, w: width, h: height };
if (box.x < 0 || box.y < 0 || box.x + box.w > 1 || box.y + box.h > 1) throw new Error('Invalid normalized bbox');
```

- [ ] **Step 3: Persist and verify the immutable dataset row**

Run: `npx ts-node src/scripts/import-external-yolo.ts ../data/external-datasets/reach stacker.v1i.yolov8.zip`

Expected: a `training_datasets` row whose manifest and all media files are under `backend/data/training/datasets/`.

### Task 2: Materialize multi-box source images correctly

**Files:**
- Modify: `backend/python-worker/training/dataset_exporter.py`
- Modify: `backend/python-worker/tests/test_training_dataset_exporter.py`

**Interfaces:**
- Consumes: one or more schema-2 samples that share an image media path.
- Produces: one JPEG and one YOLO label file containing every box for that image.

- [ ] **Step 1: Add a grouped-image test**

```python
lines = (exported / "labels" / "train" / "source.jpg.txt").read_text().splitlines()
assert len(lines) == 2
```

- [ ] **Step 2: Group snapshots by `(mediaPath, mediaKind, frameTimestampMs, split)` before writing files**

```python
groups.setdefault((item["mediaPath"], item["mediaKind"], item.get("frameTimestampMs"), item["split"]), []).append(item)
```

- [ ] **Step 3: Run exporter tests**

Run: `.venv\\Scripts\\python.exe tests\\test_training_dataset_exporter.py`

Expected: every image has all of its labels and no media path escapes the snapshot.

### Task 3: Train and evaluate the reach-stacker candidate

**Files:**
- Modify: `backend/node-api/src/routes/trainingJobs.ts` only if external-dataset metadata needs safe reporting.
- Create: `backend/data/training/models/<job-id>/best.pt` only after training succeeds.
- Create: `backend/data/training/models/<job-id>/evaluation.json` only after held-out evaluation completes.

**Interfaces:**
- Consumes: the imported dataset ID through existing `POST /api/v1/training/jobs` and `/start` endpoints.
- Produces: a `CANDIDATE` only when the runner emits artifact hash and passes mAP50/precision/recall thresholds; otherwise a `REJECTED` version.

- [ ] **Step 1: Confirm both cameras are inactive and dataset is materializable**

Run: `GET /health` and the Python exporter test suite.

Expected: `active: false` for both cameras and no exporter failure.

- [ ] **Step 2: Create and start the existing manual job with `yolov8n.pt`**

```json
{ "datasetId": "<imported dataset id>", "baseModel": "yolov8n.pt" }
```

- [ ] **Step 3: Record the held-out metrics and candidate decision**

Run: `GET /api/v1/training/jobs` and `GET /api/v1/training/jobs/versions`.

Expected: job reaches `SUCCEEDED`; version is `CANDIDATE` only if its evaluation report passes every threshold.

### Task 4: Verify non-regression and keep activation reversible

**Files:**
- Modify: `backend/python-worker/tests/test_area_pipeline.py` only for a missing regression assertion.
- Verify: `backend/node-api/src/routes/trainingJobs.ts`, `backend/python-worker/detection/tracked_detector.py`.

**Interfaces:**
- Consumes: a candidate version from Task 3.
- Produces: an activated custom augmentation or an unchanged base detector if the candidate is rejected.

- [ ] **Step 1: Run API, Python pipeline and frontend builds**

Run: `npm.cmd run test:api`, `.venv\\Scripts\\python.exe tests\\test_area_pipeline.py`, and `npm.cmd run build` in `frontend`.

Expected: all pass; the active candidate cannot suppress base person/container/vehicle detections.

- [ ] **Step 2: Do not activate a rejected candidate**

```ts
if (version.status !== 'CANDIDATE') throw new Error('Candidate quality gate did not pass');
```

- [ ] **Step 3: Report metric and rollback endpoint**

Run: `POST /api/v1/training/jobs/versions/<candidate-id>/use` only after user review; rollback remains `POST /api/v1/training/jobs/versions/return`.

Expected: base-only rollback is always available.

## Self-review

- Archive validation, immutable import, multi-box preservation, GPU-safe training, quality gate, candidate safety and rollback each have one task.
- No external API key is stored or required because the supplied archive is local.
- Activation remains outside this bootstrap run; a reach-stacker candidate does not automatically become live.
