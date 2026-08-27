# NRMM Reach-Stacker Candidate Implementation Plan

> **For agentic workers:** Execute inline in this session. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely filter the supplied NRMM v22 YOLO11 archive, combine its useful reach-stacker evidence with the current immutable snapshot, train a YOLO11n candidate, and keep the active model unchanged unless local evidence supports activation.

**Architecture:** The importer scans the untrusted ZIP without extracting it wholesale, identifies canonical `Reach Stacker` positives, samples confusing equipment as empty-label hard negatives, and reassigns splits by pre-augmentation source so augmented siblings never leak. An optional schema-2 `negativeMedia` collection lets the existing materializer create empty YOLO label files. A composer copies immutable media into a new content-addressed snapshot and canonicalizes the single trainable class to `Xe nâng container` / `reach_stacker`.

**Tech Stack:** Python 3.12, `zipfile`, OpenCV, PyYAML, Ultralytics YOLO11n, CUDA, `unittest`.

## Global Constraints

- Do not upload BAI-KIEM or NRMM data.
- Do not trust Roboflow's supplied train/valid/test split when augmented siblings share a source.
- Do not train the other 13 NRMM classes as custom production classes.
- Keep 20–30% hard-negative images after filtering.
- Preserve the existing active model and rollback artifacts.
- Do not activate a candidate using external validation alone.
- Do not commit, push, merge, or deploy.

---

### Task 1: Filter large multi-class YOLO archives safely

**Files:**
- Modify: `backend/python-worker/training/external_yolo_importer.py`
- Test: `backend/python-worker/tests/test_external_yolo_importer.py`

**Interfaces:**
- Consumes: `import_external_yolo_archive(archive_path: Path, output_root: Path)`.
- Produces: a schema-2 manifest containing `requiredClasses`, positive `samples`, optional `negativeMedia`, origin audit metadata, source-clean splits, and the existing result summary.

- [ ] Add a failing fixture with `Reach Stacker`, `Dump Truck`, augmented `.rf.*` siblings, and original split leakage.
- [ ] Assert aliases `stacker` and `Reach Stacker` both map to `Xe nâng container` / `reach_stacker`.
- [ ] Assert all augmented siblings of one pre-augmentation source receive exactly one rebuilt split.
- [ ] Assert other classes are ignored as positives and selected confuser images become `negativeMedia` records.
- [ ] Replace the 512 MiB whole-archive rejection with bounded metadata, per-entry, selected-byte, compression-ratio, and path checks; never extract unselected media.
- [ ] Run `& '.\.venv\Scripts\python.exe' -m unittest tests.test_external_yolo_importer -v` through discovery if the tests directory is not a package.

### Task 2: Materialize hard negatives without changing existing snapshots

**Files:**
- Modify: `backend/python-worker/training/dataset_exporter.py`
- Test: `backend/python-worker/tests/test_training_dataset_exporter.py`
- Test: `backend/python-worker/tests/test_dataset_audit.py`

**Interfaces:**
- Consumes: optional schema-2 `negativeMedia: list[{negativeId, sourceId, mediaKind, frameTimestampMs, mediaPath, mediaSha256, split, reasonClasses}]`.
- Produces: one copied image and one empty `.txt` label file per negative image, with source-split leakage rejected across positives and negatives.

- [ ] Add a failing materialization test for one positive and one hard negative.
- [ ] Include negative records in source-split validation and media safety checks.
- [ ] Write empty label files and include negative-only splits in `data.yaml`.
- [ ] Verify `dataset_audit.py` reports the expected negative count and ratio.

### Task 3: Compose current and NRMM snapshots

**Files:**
- Create: `backend/python-worker/training/dataset_composer.py`
- Create: `backend/python-worker/tests/test_dataset_composer.py`

**Interfaces:**
- Consumes: two or more schema-2 immutable manifest paths and an output datasets root.
- Produces: `compose_snapshots(manifests: list[Path], output_root: Path) -> dict[str, object]` with copied/hash-verified media, canonical class contract, de-duplicated media, preserved source-clean splits, and content-addressed manifest.

- [ ] Add a failing test that composes a legacy `Xe nâng` / `reach stacker` snapshot with a canonical NRMM snapshot.
- [ ] Canonicalize both spellings to `Xe nâng container` / `reach_stacker`.
- [ ] Reject one source assigned to multiple splits across input snapshots.
- [ ] Copy only referenced positive/negative media and verify every SHA-256.
- [ ] Return positive box, positive image, negative image, source, and split counts.

### Task 4: Import, audit, and gate the supplied archive

**Files:**
- Create runtime artifact: `backend/data/training/datasets/<content-hash>/manifest.json`
- Create runtime report: `backend/data/training/reports/nrmm-v22-filtered-audit.json`
- Create runtime report: `backend/data/training/reports/nrmm-v22-filtered-audit.md`

- [ ] Import `backend/data/external-datasets/NRMM.v22i.yolov11.zip`.
- [ ] Confirm the input evidence: 4,028 images, 547 reach-stacker boxes on 378 augmented images, 26 pre-augmentation reach sources, and no cross-split source leakage after rebuilding.
- [ ] Audit the filtered snapshot and require valid boxes, readable images, train/val/test coverage, and 20–30% hard-negative images.
- [ ] Compose it with the existing snapshot `826106ce49746e9a5e3dd934c4bc711333549d1a9e38f82e8ea2a3f818a64c12`.

### Task 5: Train and evaluate a YOLO11n candidate

**Files:**
- Create runtime run: `backend/data/training/runs/<job-id>/`
- Create runtime model: `backend/data/training/models/<job-id>/best.pt`
- Create runtime evaluation: `backend/data/training/models/<job-id>/evaluation.json`

- [ ] Confirm the Area camera is inactive or stop only the project-owned background worker before GPU training.
- [ ] Run `training.runner` with local `backend/python-worker/yolo11n.pt`, the composed manifest, and 60 epochs under the existing 4 GB GPU safeguards.
- [ ] Evaluate on the source-clean held-out split and record precision, recall, mAP50, mAP50-95, artifact SHA-256, and class map.
- [ ] Compare candidate and active models on the local BAI-KIEM golden candidate frames, reporting local accuracy as blocked while annotations remain pending.
- [ ] Keep the candidate inactive unless local reviewed evidence passes precision ≥ 90%, recall ≥ 85%, truck→reach-stacker < 5%, and Area end-to-end ≥ 8 FPS.

## Self-review

- The plan handles the observed 3.2 GB archive without weakening extraction safety.
- It prevents the observed 23/26 cross-split reach-source leak.
- It uses NRMM only as auxiliary evidence because visual inspection shows satellite/top-down domain mismatch with BAI-KIEM CCTV.
- It preserves hard negatives in standard YOLO form as empty label files.
- It cannot silently replace the active production model.
