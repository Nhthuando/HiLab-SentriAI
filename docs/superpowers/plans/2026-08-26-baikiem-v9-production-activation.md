# BAI-KIEM V9 Production Activation Implementation Plan

> **For agentic workers:** Execute this plan task-by-task in the current workspace. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate the reviewed V9 unified model for the BAI-KIEM Area runtime with an audited owner override and a verified V8 rollback path.

**Architecture:** Store V9 as the database `ACTIVE` model while keeping its failed automatic quality gate unchanged and recording a separate manual-production approval. The Python and Node capability loaders accept partial class coverage only for that explicit approval, run V9 once per frame, and leave the configured V8 artifact untouched as the fallback after rollback.

**Tech Stack:** Python 3.12, asyncpg, Ultralytics YOLO11, TypeScript 5.6, Prisma 5, Express, PostgreSQL, unittest.

## Global Constraints

- V9 model SHA-256 must remain `3772e978fc4635a6a2d3dffb59286bd89c0ebbc6cc6e27dc77532b5006eaab52`.
- V9 runtime mode is `UNIFIED`; the Area detector must call one model per frame.
- Automatic `qualityGate.passed` remains `false`; owner approval is stored separately.
- Supported classes are exactly `person`, `car`, `truck`, `forklift`, `reach_stacker`.
- Unsupported registry classes are `UNAVAILABLE`; do not run a second model or coerce their class.
- Do not modify or delete the V8 checkpoint, labels or evaluation.
- Do not change Gate/LPR, zones, events, clips or training data.
- Do not commit, push, merge or deploy outside this local production runtime.

---

### Task 1: Runtime manifest and partial-coverage contract

**Files:**
- Modify: `backend/python-worker/zone/zone_sync.py`
- Modify: `backend/node-api/src/services/detectionCapabilityService.ts`
- Modify: `backend/python-worker/tests/test_zone_sync_capabilities.py`
- Modify: `backend/node-api/src/tests/test_label_capabilities.ts`

**Interfaces:**
- Consumes: model-version `evaluationMetrics.runtimeMode`, `labelMap`, and `manualProductionApproval`.
- Produces: one normalized active model with `runtime_mode=UNIFIED` and explicit `allow_partial_unified`.

- [ ] Add failing Python tests proving a normal partial unified model is rejected and an owner-approved partial model keeps its supported classes while marking unsupported classes unavailable.
- [ ] Add the equivalent Node capability test.
- [ ] Make `_normalize_active_model()` preserve the reviewed runtime mode and manual partial-coverage flag.
- [ ] Resolve relative database artifact paths beneath `backend/data` without accepting paths outside that root.
- [ ] Change the all-or-nothing unified coverage check only when `manualProductionApproval.approved=true` and `allowPartialUnified=true`.
- [ ] Run the two targeted test files and confirm they pass.

### Task 2: Audited activation and rollback utility

**Files:**
- Create: `backend/python-worker/training/activate_v9_production.py`
- Create: `backend/python-worker/tests/test_activate_v9_production.py`

**Interfaces:**
- Consumes: V9 `best.pt`, `labels.json`, `evaluation.json`, immutable dataset manifest and explicit confirmation text.
- Produces: an `ACTIVE` database model version and a JSON rollback receipt under `backend/data/training/activation-backups/`.

- [ ] Write tests for exact hash verification, refusal without confirmation, preservation of failed quality metrics, receipt contents and rollback restoration.
- [ ] Implement a pure `build_activation_metadata()` function that adds `manualProductionApproval` without changing validation or locked-test values.
- [ ] Implement artifact, label-map and path validation before any database mutation.
- [ ] Snapshot current active-model rows, configured V8 identity and object-label registry before mutation.
- [ ] Register the reviewed dataset/training job/model version, deactivate the previous database model, activate V9 and add `Xe nâng container` → `reach_stacker` only when missing.
- [ ] Implement `--rollback <receipt>` to deactivate V9, restore previous active statuses and undo only registry rows created by this activation.
- [ ] Run the utility tests and confirm they pass.

### Task 3: Production metadata and thresholds

**Files:**
- Modify: `backend/data/training/models/baikiem-v9-unified-candidate-final/labels.json`
- Modify: `backend/data/training/models/baikiem-v9-unified-candidate-final/evaluation.json`
- Modify: `backend/.env`
- Modify: `backend/.env.example`

**Interfaces:**
- Consumes: frozen validation thresholds and owner approval from this conversation.
- Produces: production label aliases, audited approval metadata and Area runtime calibration.

- [ ] Preserve canonical model-name mappings and add UI aliases `Người`, `Xe con`, `Xe tải`, `Xe nâng`, `Xe nâng container` to the corresponding five canonical classes.
- [ ] Record owner production approval, partial-coverage permission, exact artifact/dataset hashes and timestamp; keep all failed gates unchanged.
- [ ] Set `AREA_INFERENCE_SIZE=896`.
- [ ] Set class initiation/continuation thresholds so initiation matches frozen validation values and continuation can only retain confirmed tracks.
- [ ] Keep all V8 `CUSTOM_AUGMENT_*` artifact identity settings unchanged so database rollback immediately restores V8 fallback.

### Task 4: Regression gate before database activation

**Files:**
- Verify only; no new production files.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: evidence that activation will not break routing or Area one-pass inference.

- [ ] Run Python taxonomy, policy, zone-sync, V9 workflow and Area-pipeline tests.
- [ ] Run Node activation-gate, taxonomy, label-capability tests and typecheck.
- [ ] Load `best.pt`, compare its embedded class names with the canonical label map and recompute SHA-256.
- [ ] Instantiate the Area benchmark at `imgsz=896` and confirm `runtimeMode=UNIFIED` and end-to-end FPS ≥8.
- [ ] If any check fails, do not mutate the database.

### Task 5: Activate, smoke-test and verify rollback readiness

**Files:**
- Produce: `backend/data/training/activation-backups/baikiem-v9-*.json`
- Produce: runtime logs under `backend/data/training/activation-logs/`.

**Interfaces:**
- Consumes: passing Task 4 evidence and exact confirmation `ACTIVATE_BAIKIEM_V9_PRODUCTION`.
- Produces: active V9 runtime plus a tested rollback receipt.

- [ ] Run the activation utility with the exact confirmation and save the receipt.
- [ ] Query the database read-only and verify exactly one `ACTIVE` model with the V9 hash and `runtimeMode=UNIFIED`.
- [ ] Start node-api and python-worker hidden with separate logs, then check ports 3001 and 8001.
- [ ] Verify logs contain the V9 version, `mode=UNIFIED`, five enabled classes and no second Area model load or reconnect storm.
- [ ] Fetch label capabilities and the BAI-KIEM playback/feed endpoints to confirm supported/unsupported class behavior.
- [ ] Dry-run rollback validation against the receipt without changing active state; confirm the V8 artifact/hash and prior registry snapshot still exist.
- [ ] Leave V9 active and report the rollback receipt and exact stop/restart state to the user.
