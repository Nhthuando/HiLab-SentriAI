# SentriAI Detection Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the database object-label registry the strict detection whitelist, route COCO and active custom classes deterministically, improve distant-object inference behind a feature flag, and produce honest BAI-KIEM evaluation evidence without regressing event behavior.

**Architecture:** Store static ontology rules once in `backend/config/detection-taxonomy.json`, then use small Node and Python adapters to derive runtime capability from registry rows and the single active model manifest. The Area worker consumes one atomic detection-control snapshot, runs whitelist-filtered base/custom inference, applies class-aware temporal confirmation and ByteTrack continuity, and passes only registry-resolved observations into unchanged violation lifecycle semantics. Evaluation and ROI are isolated modules so they can be tested and disabled independently.

**Tech Stack:** TypeScript 5.6, Express, Prisma 5, React 19, Python 3.12, OpenCV, Ultralytics YOLO, ByteTrack, NumPy, unittest.

## Global Constraints

- The object-label registry is the system-wide detection whitelist.
- Product COCO classes are exactly `person`, `bicycle`, `car`, `motorcycle`, `bus`, and `truck`.
- Known custom distinctions are `reach_stacker`, `container_truck`, `forklift`, and `mobile_crane`; future non-COCO classes come from an active manifest.
- `container_truck` is displayed as `Xe đầu kéo container`; static container uses `shipping_container` and is never aliased to a vehicle.
- COCO labels always use the base detector; custom models do not own COCO classes.
- A custom class is detectable only when the single `ACTIVE` model manifest contains it.
- Sample count never selects a runtime detector.
- Custom promotion requires two hits in the latest three eligible inference frames.
- Low-confidence observations may continue a confirmed track but may not initiate a track or violation.
- Preserve the one-second violation confirmation, boundary sustain, three-frame observed exit, twelve-second missing reconnect, clips, events, WebSocket, Gate/LPR, and Q&A behavior.
- ROI inference defaults off; tile size defaults to 640 px, overlap to 0.20, and interval to three frames.
- Do not download models, install dependencies, train, activate a model, mutate Neon data, commit, push, or deploy without separate authorization.
- Replace each usual commit checkpoint with tests plus `git diff --check`; leave all changes uncommitted.

---

## File Structure

### Shared control-plane files

- Create `backend/config/detection-taxonomy.json`: static COCO IDs, canonical syntax aliases, known display names, and legacy semantic constraints.
- Create `backend/config/detection-taxonomy-cases.json`: language-neutral parity fixtures consumed by Node and Python tests.
- Create `backend/node-api/src/detection/taxonomy.ts`: JSON loader, normalization, manifest parsing, and pure capability resolver.
- Create `backend/node-api/src/detection/capabilities.ts`: Prisma-backed active-model/registry snapshot loader and label DTO formatter.
- Create `backend/python-worker/detection/taxonomy.py`: Python resolver with the same input/output semantics.
- Create `backend/python-worker/detection/policy.py`: initiation/continuation thresholds and 2-of-3 temporal confirmation.

### Runtime files

- Modify `backend/python-worker/zone/zone_sync.py`: produce one atomic zone, registry, capability, and active-model snapshot without name-based repair.
- Modify `backend/python-worker/detection/area_pipeline.py`: consume the snapshot and remove forced/default custom fallback.
- Modify `backend/python-worker/detection/tracked_detector.py`: strict classes, source thresholds, temporal custom promotion, merge cleanup, and ROI hook.
- Modify `backend/python-worker/zone/zone_checker.py`: exact canonical resolution and initiation eligibility while preserving lifecycle timing.
- Create `backend/python-worker/detection/roi_inference.py`: bounded ROI scheduler, tiling, coordinate remap, and class-aware deduplication.

### API and frontend files

- Modify `backend/node-api/src/routes/labels.ts`: validate canonical classes and return capability fields.
- Modify `backend/node-api/src/routes/zones.ts`: reject unknown or unavailable target labels on writes.
- Modify `frontend/src/types.ts` and `frontend/src/api/labels.ts`: capability contract.
- Modify `frontend/src/App.tsx`: server-authoritative label state with no fabricated fallback.
- Modify `frontend/src/components/Settings/ObjectLabelTab.tsx`: canonical choices and source/unavailable status.
- Modify `frontend/src/components/Settings/ZoneEditorTab.tsx`: disable unavailable labels.
- Modify `frontend/src/components/Settings/ObjectTrainingPanel.tsx` and `frontend/src/api/training.ts`: custom-only training copy/profile.

### Data, evaluation, tests, and documentation

- Modify `backend/node-api/src/training/yardTrainingProfile.ts`: custom-only readiness profile.
- Create `backend/python-worker/training/dataset_audit.py`: reproducible dataset-quality report.
- Create `backend/python-worker/evaluation/golden_dataset.py`: BAI-KIEM extraction and manifest validation.
- Create `backend/python-worker/evaluation/metrics.py`: class, size, confusion, false-alert, FPS, and VRAM metrics.
- Create `backend/python-worker/evaluation/run_golden.py`: prediction/evaluation CLI with explicit blocked states.
- Modify `backend/python-worker/training/benchmark_models.py`: end-to-end Area benchmark matrix and local-asset checks.
- Add focused Node/Python tests beside the existing suites.
- Update `.env.example`, relevant canonical docs, and write evidence reports under `docs/evaluation/`.

---

### Task 1: Shared Taxonomy and Cross-Runtime Capability Contract

**Files:**
- Create: `backend/config/detection-taxonomy.json`
- Create: `backend/config/detection-taxonomy-cases.json`
- Create: `backend/node-api/src/detection/taxonomy.ts`
- Create: `backend/node-api/src/tests/test_detection_taxonomy.ts`
- Create: `backend/python-worker/detection/taxonomy.py`
- Create: `backend/python-worker/tests/test_detection_taxonomy.py`

**Interfaces:**
- Produces Node `resolveLabelCapability(label, activeModel): DetectionCapability`.
- Produces Python `resolve_label_capability(label, active_model) -> DetectionCapability`.
- `activeModel` contains `versionKey` and a manifest `labelMap` of display label to canonical class.

- [ ] **Step 1: Add the shared taxonomy**

Create JSON with these exact semantic sections:

```json
{
  "schemaVersion": 1,
  "cocoClasses": {
    "person": 0,
    "bicycle": 1,
    "car": 2,
    "motorcycle": 3,
    "bus": 5,
    "truck": 7
  },
  "syntaxAliases": {
    "reach stacker": "reach_stacker",
    "reach-stacker": "reach_stacker",
    "container truck": "container_truck",
    "container-truck": "container_truck",
    "mobile crane": "mobile_crane",
    "shipping container": "shipping_container"
  },
  "recommendedDisplayNames": {
    "person": "Người",
    "bicycle": "Xe đạp",
    "car": "Xe con",
    "motorcycle": "Xe máy",
    "bus": "Xe buýt",
    "truck": "Xe tải",
    "reach_stacker": "Xe nâng container",
    "container_truck": "Xe đầu kéo container",
    "forklift": "Xe nâng hàng",
    "mobile_crane": "Xe cẩu tự hành",
    "shipping_container": "Container tĩnh"
  },
  "legacyNameConstraints": {
    "container": [],
    "xe nâng": ["reach_stacker", "forklift"],
    "xe cẩu": ["mobile_crane"]
  }
}
```

An empty allowed list means the display name is ambiguous and must be renamed. Canonical identifiers must match `^[a-z][a-z0-9_]{1,49}$`; raw `container` is rejected with reason `AMBIGUOUS_CONTAINER`, while explicit `shipping_container` is valid.

- [ ] **Step 2: Write parity fixtures before implementations**

Include cases for COCO with zero samples, active `reach stacker`, inactive custom, future `yard_tug`, custom manifest attempting to own `truck`, static container, and all three legacy DB mismatches. Each case has this expected object:

```json
{
  "canonicalClass": "reach_stacker",
  "detectionSource": "CUSTOM",
  "isDetectable": true,
  "activeModelVersion": "custom-v1",
  "reasonCode": "ACTIVE_CUSTOM_CLASS",
  "reasonText": "Nhận diện bởi model custom custom-v1"
}
```

- [ ] **Step 3: Write failing Node and Python fixture tests**

Both tests must load every JSON case and deep-compare every output field. Add a dedicated assertion proving changing `sampleCount` from `0` to `10_000` does not change the result.

- [ ] **Step 4: Implement syntax normalization and capability resolution in both runtimes**

Use these public types in TypeScript:

```ts
export type DetectionSource = 'COCO' | 'CUSTOM' | 'UNAVAILABLE';
export interface RegistryLabelInput {
  vietnameseName: string;
  baseClass: string;
  sampleCount?: number;
}
export interface ActiveModelInput {
  versionKey: string;
  labelMap: Record<string, string>;
}
export interface DetectionCapability {
  canonicalClass: string | null;
  detectionSource: DetectionSource;
  isDetectable: boolean;
  activeModelVersion: string | null;
  reasonCode: string;
  reasonText: string;
}
```

The Python dataclasses expose the same camel-case fields through `as_dict()` so fixture comparison remains language-neutral.

- [ ] **Step 5: Run parity tests and checkpoint**

Run:

```powershell
cd backend/node-api
npx.cmd ts-node src/tests/test_detection_taxonomy.ts
cd ../python-worker
& '.venv/Scripts/python.exe' -m unittest discover -s tests -p test_detection_taxonomy.py -v
cd ../..
git diff --check
```

Expected: both suites pass; no whitespace errors.

---

### Task 2: Prisma Capability Snapshot and Label API

**Files:**
- Create: `backend/node-api/src/detection/capabilities.ts`
- Modify: `backend/node-api/src/routes/labels.ts`
- Create: `backend/node-api/src/tests/test_label_capabilities.ts`
- Modify: `backend/node-api/src/tests/test_labels.ts`

**Interfaces:**
- Consumes `resolveLabelCapability` from Task 1.
- Produces `loadDetectionContext()` and `toObjectLabelDto()` for labels and zones.

- [ ] **Step 1: Write pure DTO and manifest parsing tests**

Test `evaluationMetrics` values that are null, arrays, missing `labelMap`, malformed maps, and valid maps. A malformed active manifest must not crash a GET; affected non-COCO labels return `UNAVAILABLE` with `INVALID_ACTIVE_MANIFEST`.

- [ ] **Step 2: Implement the detection context service**

Expose these signatures:

```ts
export interface DetectionContext {
  activeModel: ActiveModelInput | null;
  activeArtifactPath: string | null;
  labels: Array<ObjectLabel & { _count: { samples: number } }>;
  capabilitiesByName: Map<string, DetectionCapability>;
}

export async function loadDetectionContext(): Promise<DetectionContext>;
export function parseActiveModel(record: ModelVersion | null): ActiveModelInput | null;
export function toObjectLabelDto(
  record: ObjectLabel & { _count: { samples: number } },
  capability: DetectionCapability,
  index: number,
): ObjectLabelDto;
```

Query `status: 'ACTIVE'` ordered by `activatedAt desc`, take at most one record, and resolve every registry row. Never query `LabelSample` contents or use `_count.samples` in routing.

- [ ] **Step 3: Make label creation/update strict**

Remove the implicit vehicle default `truck`. Require `baseClass`, normalize it, and return HTTP 400 for invalid identifiers, ambiguous `container`, or a legacy display constraint mismatch. Permit valid unavailable non-COCO labels so the UI can expose missing model state.

- [ ] **Step 4: Enrich all label responses**

Return these additional fields on GET/POST/PUT:

```ts
{
  canonicalClass: capability.canonicalClass,
  detectionSource: capability.detectionSource,
  isDetectable: capability.isDetectable,
  activeModelVersion: capability.activeModelVersion,
  capabilityReason: capability.reasonText,
  capabilityReasonCode: capability.reasonCode
}
```

POST and PUT recompute capability using the current active context after persistence.

- [ ] **Step 5: Run API compilation and pure tests**

Run `npm.cmd run typecheck`, `npx.cmd ts-node src/tests/test_detection_taxonomy.ts`, and `npx.cmd ts-node src/tests/test_label_capabilities.ts`. Do not run the mutating `test_labels.ts` against shared Neon; its contract assertions are compiled by typecheck and later exercised only with an isolated test database.

- [ ] **Step 6: Checkpoint**

Run `git diff --check` and inspect `git diff -- backend/node-api/src/detection backend/node-api/src/routes/labels.ts`.

---

### Task 3: Registry-Backed Zone Write Validation

**Files:**
- Create: `backend/node-api/src/detection/zoneLabelValidation.ts`
- Modify: `backend/node-api/src/routes/zones.ts`
- Modify: `backend/node-api/src/tests/test_zone_validation.ts`

**Interfaces:**
- Consumes `DetectionContext.capabilitiesByName` from Task 2.
- Produces `validateDetectableTargetLabels(labels, context): string[]`.

- [ ] **Step 1: Repair the existing camera validation baseline**

Update the stale assertion so `GATE-01` is accepted because the route explicitly supports it. Add an unsupported `WAREHOUSE-99` case that must throw `ZoneValidationError`.

- [ ] **Step 2: Write failing whitelist tests**

Cover exact registered/detectable labels, case-insensitive duplicate input, missing registry label, unavailable custom label, and an empty target list. Expect explicit messages containing the rejected display name.

- [ ] **Step 3: Implement async write validation**

Keep polygon/body parsing pure. Immediately before Prisma create/update, load the detection context and call:

```ts
export function validateDetectableTargetLabels(
  labels: string[],
  capabilitiesByName: ReadonlyMap<string, DetectionCapability>,
): string[];
```

Resolve case-insensitively but return the canonical database display name. Reject missing labels with `LABEL_NOT_REGISTERED` and unavailable labels with `LABEL_NOT_DETECTABLE`. Existing GET responses remain readable even if a previously saved target becomes unavailable.

- [ ] **Step 4: Run zone tests and typecheck**

Run `npx.cmd ts-node src/tests/test_zone_validation.ts`, the new validation test, and `npm.cmd run typecheck`. Expected: pass.

- [ ] **Step 5: Checkpoint**

Run `git diff --check` and verify zone CRUD data shapes are unchanged apart from validation errors.

---

### Task 4: Atomic Python Detection-Control Snapshot

**Files:**
- Modify: `backend/python-worker/zone/zone_sync.py`
- Modify: `backend/python-worker/db/repositories.py`
- Create: `backend/python-worker/tests/test_zone_sync_capabilities.py`

**Interfaces:**
- Consumes Python taxonomy resolver from Task 1.
- Produces `ZoneSnapshot.capabilities_by_label`, `coco_classes`, `custom_classes`, and `active_model`.
- `active_model` uses keys `version_key`, `artifact_path`, `artifact_sha256`, and `label_map`.

- [ ] **Step 1: Write failing snapshot tests**

Mock `get_active_zones_by_camera`, `get_all_object_labels`, and `get_active_custom_model`. Assert:

```python
self.assertEqual(snapshot.coco_classes, frozenset({"person", "truck"}))
self.assertEqual(snapshot.custom_classes, frozenset({"reach_stacker"}))
self.assertNotIn("shipping_container", snapshot.class_to_labels)
self.assertEqual(snapshot.active_model["version_key"], "custom-v1")
```

Add no-active-model and database-refresh-failure cases. Refresh failure must retain the exact previous immutable snapshot.

- [ ] **Step 2: Replace name-based compatibility repair**

Delete the Vietnamese-name rewrites from `ZoneSynchronizer.refresh_now()`. Resolve each raw label through the shared taxonomy, add only detectable capabilities to `class_to_labels`, and retain all capability results for diagnostics/UI parity.

- [ ] **Step 3: Move active model state into the atomic snapshot**

Fetch active model during the same refresh cycle. Normalize `evaluation_metrics.labelMap` and store only serializable metadata; artifact loading stays in AreaPipeline.

- [ ] **Step 4: Run focused tests and checkpoint**

Run the taxonomy tests and `tests.test_zone_sync_capabilities`. Then run `git diff --check`.

---

### Task 5: Threshold Policy and Temporal Confirmation

**Files:**
- Create: `backend/python-worker/detection/policy.py`
- Create: `backend/python-worker/tests/test_detection_policy.py`
- Modify: `backend/.env.example`

**Interfaces:**
- Produces `DetectionThresholds`, `DetectionPolicy`, and `TemporalConfirmationWindow`.
- Consumed by `TrackedYoloDetector` and ZoneChecker tasks.

- [ ] **Step 1: Write failing policy tests**

Test base/custom per-class overrides, safe defaults, invalid environment input, low-confidence continuation, and exact hit sequences:

```python
window = TemporalConfirmationWindow(required_hits=2, window_size=3)
self.assertFalse(window.observe("reach-7", frame_index=10, matched=True))
self.assertFalse(window.observe("reach-7", frame_index=11, matched=False))
self.assertTrue(window.observe("reach-7", frame_index=12, matched=True))
self.assertFalse(window.observe("other", frame_index=12, matched=True))
```

- [ ] **Step 2: Implement immutable threshold policy**

Use safe defaults `base initiation=0.30`, `base continuation=0.14`, `custom initiation=0.45`, `custom continuation=0.25`, and custom `2/3` confirmation. Accept JSON overrides through `AREA_CLASS_THRESHOLDS_JSON`, for example:

```json
{
  "base": {"person": {"initiation": 0.35, "continuation": 0.16}},
  "custom": {"reach_stacker": {"initiation": 0.50, "continuation": 0.28}}
}
```

Reject out-of-range values and require `continuation <= initiation`.

- [ ] **Step 3: Update environment documentation**

Remove obsolete geometry/custom-promotion variables and document the new JSON threshold contract plus `CUSTOM_CONFIRM_HITS=2` and `CUSTOM_CONFIRM_WINDOW=3`. Runtime must reject attempts to configure weaker values for violation initiation.

- [ ] **Step 4: Run tests and checkpoint**

Run `& '.venv/Scripts/python.exe' -m unittest discover -s tests -p test_detection_policy.py -v` and `git diff --check`.

---

### Task 6: Detector Cleanup, Strict Merge, and ByteTrack Continuity

**Files:**
- Modify: `backend/python-worker/detection/tracked_detector.py`
- Modify: `backend/python-worker/detection/detector.py`
- Modify: `backend/python-worker/detection/area_pipeline.py`
- Modify: `backend/python-worker/tests/test_area_pipeline.py`

**Interfaces:**
- Consumes capability sets from Task 4 and policy from Task 5.
- Produces detections with `canonicalClass`, `source`, `confidence`, `trackId`, `canInitiate`, and `customConfirmed`.

- [ ] **Step 1: Replace heuristic expectations with strict semantic tests**

Delete tests that require personnel-carrier canonicalization, cabin/container assembly, shape-based reach-stacker acceptance, or instant promotion. Add assertions that `bus` remains `bus`, `train` is filtered, static container never becomes truck, and overlapping unconfirmed custom detections do not relabel a base track.

- [ ] **Step 2: Add `configure_detection_control()`**

Implement this stable interface:

```python
def configure_detection_control(
    self,
    *,
    coco_classes: frozenset[str],
    custom_classes: frozenset[str],
    active_model: dict[str, object] | None,
) -> None:
    self._enabled_coco_classes = coco_classes
    self._enabled_custom_classes = custom_classes
    if active_model is None or not custom_classes:
        self.configure_custom_model(None, None, {}, frozenset())
        return
    self.configure_custom_model(
        str(active_model["version_key"]),
        str(active_model["artifact_path"]),
        dict(active_model["label_map"]),
        custom_classes,
    )
```

The implementation maps COCO names to IDs from the shared taxonomy, unloads custom state when `active_model` is absent, and skips custom inference when `custom_classes` is empty.

- [ ] **Step 3: Make base inference registry-driven**

Run YOLO11 with only enabled COCO IDs at the continuation threshold. Mark a detection `canInitiate=true` only when its raw/smoothed confidence meets its class initiation threshold or it belongs to an already confirmed compatible track.

- [ ] **Step 4: Integrate the atomic snapshot and remove fallback loading**

Delete AreaPipeline `_default_custom_model`, `_force_default_custom_model`, `CUSTOM_AUGMENT_FORCE_DEFAULT`, the independent active-model polling loop, and all fallback branches. On a changed `ZoneSnapshot`, call:

```python
def _apply_detection_control(self, snapshot: ZoneSnapshot) -> None:
    active_model = self._resolve_active_model(snapshot.active_model)
    self.detector.configure_detection_control(
        coco_classes=snapshot.coco_classes,
        custom_classes=snapshot.custom_classes,
        active_model=active_model,
    )
```

`_resolve_active_model()` returns a copy whose `artifact_path` is absolute. Resolve artifacts strictly below `backend/data`; verify existence and stored SHA-256 before load. No active model calls `configure_custom_model(None, None, {}, frozenset())`. Replace the old fallback tests with assertions that environment fallback variables have no effect.

- [ ] **Step 5: Make custom inference exact and temporal**

Normalize model names syntactically, discard outputs outside `custom_classes`, and require the policy 2-of-3 window. Remove instant-confidence bypasses and aspect/area special cases.

- [ ] **Step 6: Replace semantic merge with class-aware merge**

Keep same-class IoU/NMS. An exact confirmed custom vehicle distinction may supersede an overlapping generic `truck`, `bus`, or `car` observation while retaining the existing track ID; it must never merge unrelated custom classes. A custom-only confirmed candidate uses the existing association cache to maintain identity.

- [ ] **Step 7: Delete forbidden methods and mappings**

Remove `_assemble_container_trucks`, small-truck-to-car stabilization, `bus/train -> truck`, static suppression based solely on a bbox being stationary, and all World prompt mappings from the Area default path. Static physical objects are rejected by class capability, not by motion heuristics that could suppress stopped vehicles.

- [ ] **Step 8: Run detector and stream tests**

Run the complete `tests.test_area_pipeline` module. Repair the existing stream frame-skip expectation to reflect the reader's actual target/source FPS contract, without weakening rewind and source-speed assertions.

- [ ] **Step 9: Checkpoint**

Run `git diff --check` and inspect removal of every forbidden symbol with:

```powershell
rg -n "assemble_container|personnel carrier|shipping container|container handler|train.*truck|bus.*truck|REACH_STACKER_" backend/python-worker/detection backend/python-worker/zone
```

Expected: no runtime semantic/geometry hack remains.

---

### Task 7: Exact Zone Resolution and Initiation Gate

**Files:**
- Modify: `backend/python-worker/zone/zone_checker.py`
- Modify: `backend/python-worker/tests/test_area_pipeline.py`

**Interfaces:**
- Consumes canonical detector outputs and `class_to_labels` from Task 4.
- Preserves `ViolationTransition` and persistence-facing event shapes.

- [ ] **Step 1: Write exact-resolution tests**

Assert `resolve_candidate_labels("truck", "Xe tải", {"truck": ["Xe tải"], "reach_stacker": ["Xe nâng container"]})` returns only `Xe tải`. Verify no relation between truck, container truck, shipping container, forklift, reach stacker, or crane.

- [ ] **Step 2: Add low-confidence lifecycle tests**

A `canInitiate=false` observation inside a prohibited zone must not create pending state. The same observation may sustain an already-open event only when track ID and canonical class match. Re-identification must require canonical class compatibility.

- [ ] **Step 3: Remove alias matrices and generic fallback labels**

Delete semantic candidate expansions and `Xe nâng`/`Xe cẩu` fallbacks. Choose a display label only from the exact registry snapshot. Unknown detections are dropped before zone evaluation.

- [ ] **Step 4: Gate pending/open transitions**

At the point that a new prohibited presence enters pending state, require `detection.get("canInitiate") is True`. Do not change one-second confirmation, boundary buffer, three-frame observed exit, or twelve-second missing grace.

- [ ] **Step 5: Run lifecycle regression tests and checkpoint**

Run `TestViolationStateMachine`, `TestZoneRuleMatrix`, and `TestZonePolygonAndPoints`, then `git diff --check`.

---

### Task 8: ROI/Tile Inference Behind a Feature Flag

**Files:**
- Create: `backend/python-worker/detection/roi_inference.py`
- Create: `backend/python-worker/tests/test_roi_inference.py`
- Modify: `backend/python-worker/detection/tracked_detector.py`
- Modify: `backend/.env.example`

**Interfaces:**
- Produces `RoiSpec`, `TileWindow`, `RoiScheduler`, `build_tiles()`, and `remap_detection()`.
- Detector supplies base/custom callbacks; scheduler returns full-frame-coordinate candidates.

- [ ] **Step 1: Write geometry and scheduling tests**

Cover normalized ROI clipping, 640-px tiles, 0.20 overlap, deterministic tile bounds, maximum tile count, coordinate remap, every-third-frame scheduling, and disabled-state zero calls.

- [ ] **Step 2: Implement bounded tile generation**

Use these dataclasses:

```python
@dataclass(frozen=True)
class RoiSpec:
    name: str
    polygon: Sequence[tuple[float, float]]
    detectors: frozenset[str]

@dataclass(frozen=True)
class TileWindow:
    roi_name: str
    x1: int
    y1: int
    x2: int
    y2: int
```

Reject polygons outside `[0,1]`, fewer than three points, invalid detector names, overlap outside `[0,0.5)`, and nonpositive intervals.

- [ ] **Step 3: Implement class-aware ROI deduplication**

Remap each bbox before merge. Deduplicate same canonical class by IoU. Let confirmed exact custom distinctions supersede generic COCO vehicles only through Task 6's merge policy.

- [ ] **Step 4: Integrate without changing the default path**

Read `AREA_ROI_ENABLED=false`, `AREA_ROI_CONFIG_JSON=[]`, `AREA_ROI_INTERVAL=3`, `AREA_ROI_TILE_SIZE=640`, `AREA_ROI_TILE_OVERLAP=0.20`, and `AREA_ROI_MAX_TILES=8`. When disabled, detector call counts and outputs must match the non-ROI baseline.

- [ ] **Step 5: Run tests and checkpoint**

Run ROI tests plus detector tests; run `git diff --check`.

---

### Task 9: Frontend Server Authority and Capability UX

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api/labels.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Settings/ObjectLabelTab.tsx`
- Modify: `frontend/src/components/Settings/ZoneEditorTab.tsx`
- Modify: `frontend/src/components/Settings/ObjectTrainingPanel.tsx`
- Modify: `frontend/src/api/training.ts`

**Interfaces:**
- Consumes Task 2 label DTO.
- Produces no new backend contract.

- [ ] **Step 1: Extend the `ObjectLabel` type**

Add:

```ts
canonicalClass: string | null;
detectionSource: 'COCO' | 'CUSTOM' | 'UNAVAILABLE';
isDetectable: boolean;
activeModelVersion: string | null;
capabilityReason: string;
capabilityReasonCode: string;
```

Remove the API client's implicit `truck` default and require `baseClass` for create.

- [ ] **Step 2: Make App label state server-authoritative**

Initialize `objLabels` to `[]`. On GET success, replace state even when the response is empty. On create/update/delete failure, keep prior state and expose the existing settings error UI. Only apply server-returned objects after successful writes.

- [ ] **Step 3: Replace class choices and ambiguous copy**

Offer fixed COCO classes and explicit known custom names. Permit a normalized custom identifier input. Replace `Container` with separate `Xe đầu kéo container (container_truck)` and `Container tĩnh (shipping_container)` meanings.

- [ ] **Step 4: Render capability status**

Show `COCO`, `Custom · <version>`, or `Chưa có model nhận diện`. The unavailable state includes `capabilityReason` and never suggests that adding samples immediately enables detection.

- [ ] **Step 5: Enforce Zone Editor availability**

Render only labels received from the API. Disable unavailable checkboxes, clear unavailable labels from new write payloads, and visibly mark legacy zones that already reference an unavailable label without silently changing the saved zone.

- [ ] **Step 6: Correct training messaging**

The training panel lists only non-COCO classes requested for the selected custom profile. Remove claims that base YOLO detects static containers and remove `Xe tải` from custom readiness.

- [ ] **Step 7: Build and visually smoke-test**

Run `npm.cmd run build`. Start the existing local frontend only if a server is already configured, then inspect Settings labels and Zone Editor at desktop and narrow widths. Verify loading, empty, error, unavailable, COCO, and custom states.

- [ ] **Step 8: Checkpoint**

Run `git diff --check` and confirm no `setObjLabels` write occurs in an API catch branch.

---

### Task 10: Custom-Only Training Profile and Dataset Audit

**Files:**
- Modify: `backend/node-api/src/training/yardTrainingProfile.ts`
- Modify: `backend/node-api/src/routes/trainingDatasets.ts`
- Modify: `backend/node-api/src/tests/test_yard_training_profile.ts`
- Modify: `backend/python-worker/training/dataset_exporter.py`
- Create: `backend/python-worker/training/dataset_audit.py`
- Create: `backend/python-worker/tests/test_dataset_audit.py`
- Create: `docs/evaluation/reach-stacker-dataset-audit.md`

**Interfaces:**
- Training readiness is independent from runtime capability.
- Audit CLI accepts a snapshot directory and emits JSON plus Markdown.

- [ ] **Step 1: Replace the three-class yard profile**

Use profile key `YARD_CUSTOM_V2` with a single initial requirement:

```ts
const YARD_CUSTOM_LABELS = [
  { label: 'Xe nâng container', baseClass: 'reach_stacker', minimumSamples: 60, minimumSources: 5 },
] as const;
```

Keep source-grouped split assignment. Readiness reports sample/source/split coverage but is never imported by capability routing.

- [ ] **Step 2: Update exporter evaluation gates**

Derive required classes from the selected training profile/manifest instead of hardcoded container, truck, and forklift labels. Preserve source grouping and media provenance.

- [ ] **Step 3: Write dataset audit tests**

Use a temporary fixture with positives, empty label files, duplicate images, multiple source IDs, and small/large boxes. Assert exact duplicate groups, split leakage, negative ratio, source counts, and bbox area buckets.

- [ ] **Step 4: Implement audit CLI**

Report image count, bbox count, per-class count, per-source count, split distribution, exact SHA duplicates, dHash near duplicates, bbox area percentiles, edge-touch count, resolution distribution, negative ratio, and source/split leakage. Do not infer semantic background categories from pixels.

- [ ] **Step 5: Audit the existing snapshot and document evidence**

Run the tool on `backend/data/training/datasets/826106ce49746e9a5e3dd934c4bc711333549d1a9e38f82e8ea2a3f818a64c12`. Record the verified 200 images, 222 boxes, zero negatives, no boxes below 1%, 54.60948% median area, 58 edge-touching boxes, and external archive provenance. The deterministic value supersedes the earlier 54.77% planning estimate; retain both values in the generated report's reconciliation evidence rather than silently rewriting history.

- [ ] **Step 6: Run tests and checkpoint**

Run Node yard-profile test, Python exporter/audit tests, typecheck, and `git diff --check`.

---

### Task 11: BAI-KIEM Golden Dataset Preparation

**Files:**
- Create: `backend/python-worker/evaluation/__init__.py`
- Create: `backend/python-worker/evaluation/golden_dataset.py`
- Create: `backend/python-worker/tests/test_golden_dataset.py`
- Create: `docs/evaluation/bai-kiem-annotation-checklist.md`
- Modify: `.gitignore`

**Interfaces:**
- Produces versioned `golden-manifest.json` with source/time metadata and annotation status.
- Does not fabricate annotations.

- [ ] **Step 1: Define and test the manifest schema**

Each frame record contains:

```json
{
  "frameId": "bai-kiem-000120000",
  "sourceId": "BAI-KIEM-20260820",
  "timestampMs": 120000,
  "imagePath": "images/bai-kiem-000120000.jpg",
  "sha256": "<64 lowercase hex characters>",
  "perceptualHash": "<16 lowercase hex characters>",
  "annotationStatus": "PENDING",
  "labelsPath": null,
  "tags": ["interval"]
}
```

The validator accepts `PENDING`, `ANNOTATED`, and `NEGATIVE`; only annotated/negative records enter evaluation.

- [ ] **Step 2: Implement deterministic extraction**

Accept source path, output directory, interval seconds, hard-case timestamp list, dHash distance threshold, and JPEG quality. Seek sequentially to avoid the observed HEVC random-seek reference warnings. Deduplicate by SHA then dHash and preserve original timestamps.

- [ ] **Step 3: Add annotation checklist**

Document exact class definitions, partial/occluded box policy, small/far tagging, static shipping container negatives, truck-versus-reach-stacker examples, ignore-region rules, double-review procedure, and the 20-30% negative target.

- [ ] **Step 4: Extract candidate frames without annotating them**

Use `D:\video_test\KiemHoa-Hik (1).mp4`, a 10-second interval, and additional hard-case timestamps identified from a sequential contact scan. Store generated images in an ignored local artifact directory; commit neither source video nor extracted frames. Keep the manifest and audit summary only if they contain no machine-specific absolute paths.

- [ ] **Step 5: Report the ground-truth gate honestly**

Mark class-accuracy acceptance as `BLOCKED/NOT EVALUATED — annotationStatus contains PENDING frames` until a human completes labels. Performance-only benchmarking may proceed.

- [ ] **Step 6: Run tests and checkpoint**

Run `tests.test_golden_dataset`, validate the generated manifest, and run `git diff --check`.

---

### Task 12: Golden Metrics and End-to-End Benchmarking

**Files:**
- Create: `backend/python-worker/evaluation/metrics.py`
- Create: `backend/python-worker/evaluation/run_golden.py`
- Create: `backend/python-worker/tests/test_golden_metrics.py`
- Modify: `backend/python-worker/training/benchmark_models.py`
- Create: `docs/evaluation/bai-kiem-baseline-report.md`

**Interfaces:**
- Consumes validated golden manifest, YOLO-format annotations, and prediction/event JSONL.
- Produces machine-readable JSON plus a Markdown PASS/FAIL/BLOCKED report.

- [ ] **Step 1: Write deterministic metric tests**

Use tiny fixtures with known IoU matches to assert per-class TP/FP/FN, precision, recall, F1, AP50, small/far buckets, truck/reach confusion, static-container false positives, and false alerts per minute. Zero-denominator metrics return `null` plus a reason, never a fabricated 0 or 1.

- [ ] **Step 2: Implement evaluator matching**

Match predictions to ground truth by canonical class and descending confidence at IoU 0.50. Record cross-class overlaps separately for the truck/reach confusion matrix. Define small as normalized bbox area below 1% and far by annotation tag.

- [ ] **Step 3: Add performance instrumentation**

Record decoded frames, processed frames, warm-up count, wall time, end-to-end FPS, detector latency percentiles, ROI latency, and peak CUDA allocation/reservation. Reset CUDA peak statistics before each matrix cell and synchronize around timed regions.

- [ ] **Step 4: Extend the benchmark matrix safely**

Test locally present model/runtime combinations only:

```text
models: yolo11n.pt, yolo11s.pt if present
imgsz: 640, 896, 960
runtime: PyTorch FP16, TensorRT if an engine is present
roi: disabled, enabled
```

Emit `BLOCKED_MISSING_LOCAL_ASSET` for YOLO11s or TensorRT when absent. Do not trigger Ultralytics automatic downloads by passing a non-existent model name.

- [ ] **Step 5: Benchmark the BAI-KIEM source**

Run a fixed sequential segment with ROI off and on, recording RTX 3050 4 GB FPS/VRAM. Keep the Area event path enabled in the timed loop but redirect persistence to an in-memory/no-write evaluator sink.

- [ ] **Step 6: Write the baseline report**

Report performance cells and blocked assets. Report precision/recall/confusion/false-alert criteria as blocked until annotations exist. Compare against the required `>=8 FPS` target without extrapolating from per-model-only latency.

- [ ] **Step 7: Run tests and checkpoint**

Run metric tests, benchmark CLI `--help`, one short smoke matrix cell, and `git diff --check`.

---

### Task 13: Full Regression, Documentation, and Honest Acceptance Report

**Files:**
- Modify: `docs/product/product.md`
- Modify: `docs/architecture/architecture.md`
- Modify: `docs/backend/backend.md`
- Modify: `docs/backend/tasks/VS-AREA-VIOLATION.md`
- Modify: `docs/backend/tasks/VS-OBJECT-TRAIN-DATASET.md`
- Modify: `docs/backend/tasks/VS-OBJECT-MODEL-VERSION.md`
- Create: `docs/evaluation/2026-08-22-detection-acceptance.md`

**Interfaces:**
- Documents the implemented contracts and evidence paths; introduces no runtime interface.

- [ ] **Step 1: Run the complete Python suite**

Run:

```powershell
cd backend/python-worker
& '.venv/Scripts/python.exe' -m unittest discover -s tests -v
```

Expected: all tests pass. Do not remove Gate/LPR, clip, stream, zone lifecycle, dataset exporter, importer, or training runner coverage to achieve green status.

- [ ] **Step 2: Run Node verification**

Run typecheck and every pure test script. Do not run API tests that write shared Neon. If an isolated database is available, run the complete API contract suite against it and record the database identifier as non-production.

- [ ] **Step 3: Run frontend verification**

Run `npm.cmd run build` outside the sandbox only if Vite again requires access to `node_modules/.vite-temp`. Record bundle warnings separately from failures.

- [ ] **Step 4: Perform targeted smoke checks**

Verify Label GET capability output, unavailable Zone Editor state, a COCO-only Area frame, no-active-custom behavior, active-manifest fixture behavior, event timing, clip encoding, and unchanged Gate/LPR code paths.

- [ ] **Step 5: Update canonical documentation**

Replace sample-count routing and ambiguous container language with the implemented registry/capability contract. Document configuration defaults, ROI flag, custom 2-of-3 confirmation, initiation/continuation semantics, evaluation commands, and operational failure behavior.

- [ ] **Step 6: Write the acceptance report**

For each `improve.md` target, state `PASS`, `FAIL`, or `BLOCKED/NOT EVALUATED`, the exact command, artifact path, hardware, and measured value. Explicitly retain blockers for missing annotations, YOLO11s, or TensorRT.

- [ ] **Step 7: Final repository audit**

Run:

```powershell
git diff --check
git status --short
rg -n "CUSTOM_AUGMENT_FORCE_DEFAULT|assemble_container|container handler|personnel carrier" backend frontend
```

Expected: only intended source/docs/artifact manifests are modified; `improve.md` remains user-owned and unmodified; no forbidden runtime fallback/hack remains.

---

## Execution Order and Gates

1. Tasks 1-3 establish the API/control-plane truth source.
2. Tasks 4-7 replace runtime routing and semantics while retaining event lifecycle.
3. Task 8 adds disabled-by-default ROI infrastructure.
4. Task 9 exposes the capability contract safely in the UI.
5. Tasks 10-12 create honest data/evaluation/performance evidence.
6. Task 13 is the full regression and documentation gate.

Do not start Task 8 before Tasks 4-7 pass. Do not activate or train a model as part of any task. Do not label extracted frames automatically. Do not claim class-accuracy acceptance while the golden manifest contains pending annotations.
