# SentriAI Detection Reliability Design

**Date:** 2026-08-22  
**Status:** Approved in conversation  
**Scope:** AREA/BAI-KIEM object-label routing, detection, tracking, ROI inference, evaluation, training data quality, and Settings/Zone UI integration

## 1. Objective

Make the object-label registry the system-wide detection whitelist and replace the current heuristic detector routing with an explicit, testable capability contract. Improve small/far-object performance on the BAI-KIEM camera without weakening event correctness, inventing labels, or claiming acceptance metrics without representative ground truth.

The change must preserve gate/LPR behavior, zone CRUD, event persistence, clip generation, WebSocket delivery, and Q&A behavior.

## 2. Verified Current State

- The configured BAI-KIEM source is `D:\video_test\KiemHoa-Hik (1).mp4`: 2688x1520, 25 FPS, 14,981 frames, about 599 seconds.
- The configured base model is local `yolo11n.pt` with the standard 80 COCO classes.
- Neon currently has no `ModelVersion` with status `ACTIVE`.
- Runtime configuration nevertheless forces `training/models/01e3e77b-d843-4765-b951-a8219ca6e47c/best.pt` as a custom model.
- That custom artifact is a one-class YOLOv8n model whose output name is `Xe nâng`.
- The registry currently contains legacy semantic mismatches including `Container -> truck`, `Xe nâng -> truck`, and `Xe cẩu -> truck`.
- The current 222-box dataset contains 200 external still images, one class, no negative images, and no objects below 1% normalized image area. The initial audit note recorded a 54.77% median bbox area; the deterministic Task 10 auditor recomputed the same 222 manifest/YOLO boxes at 54.60948% (54.61%), which supersedes that earlier estimate. This dataset is not representative of the distant objects in BAI-KIEM.
- Current Python baseline is 53/59 passing tests. Node typecheck and frontend build pass; the standalone zone-validation test fails.

## 3. Business Invariants

1. `ObjectLabel` records are the detection whitelist. An output that cannot resolve to a registry entry must not be displayed, offered in zone rules, or used to create an event.
2. Runtime capability is derived from registry membership and model availability, never from sample count.
3. A supported COCO class always uses the base detector. A custom manifest does not take ownership of COCO classes.
4. A non-COCO class uses a custom detector only when an `ACTIVE` model manifest contains that canonical class.
5. A non-COCO class without an active supporting model is `UNAVAILABLE` and is shown as `Chưa có model nhận diện`.
6. `container_truck` means a tractor/container-carrying truck and is displayed as `Xe đầu kéo container`. A static shipping container is not a vehicle and has no vehicle-class alias.
7. A low-confidence observation may continue an already confirmed track but may not initiate a track, promote a custom class, or open a violation.
8. Custom classification requires at least two matching observations in a rolling three-frame window before promotion or event initiation.
9. No class may be inferred from bbox aspect ratio, size, adjacency to a container, or a semantically different detector prompt.
10. Acceptance criteria remain unverified until evaluated on representative annotated BAI-KIEM data.

## 4. Canonical Taxonomy and Capability Contract

A shared, versioned JSON taxonomy under `backend/config/` defines static facts used by both Node and Python:

- COCO classes allowed by this product: `person`, `bicycle`, `car`, `motorcycle`, `bus`, `truck`.
- Known custom distinctions for the current product: `reach_stacker`, `container_truck`, `forklift`, `mobile_crane`. Other non-COCO canonical classes may be supplied by a future active manifest without changing source code.
- COCO numeric IDs.
- Vietnamese recommended display names.
- Syntax-only aliases such as `reach stacker -> reach_stacker` and `container truck -> container_truck`.
- Reserved ambiguous legacy terms that must be reviewed instead of silently remapped.

The taxonomy must not define semantic aliases between `truck`, `container_truck`, `reach_stacker`, `forklift`, `mobile_crane`, or static `shipping_container`. `shipping_container` is an explicit non-vehicle class and is unavailable unless a future active custom manifest contains it.

For each registry label, Node and Python independently derive the same capability result:

```text
canonicalClass
detectionSource: COCO | CUSTOM | UNAVAILABLE
isDetectable: boolean
activeModelVersion: string | null
reasonCode
reasonText
```

Resolution order:

1. Reject or mark unavailable an invalid/ambiguous canonical mapping.
2. If the registry canonical class is a product-supported COCO class, return `COCO` and ignore any same-name custom output.
3. If an active model manifest explicitly maps the registry label to the same canonical non-COCO class, return `CUSTOM`.
4. If the registry canonical non-COCO class occurs in the active custom manifest, return `CUSTOM`.
5. Otherwise return `UNAVAILABLE`.

`evaluationMetrics.labelMap` remains the active model manifest source in the existing schema. No database migration is required for capability state because it is derived and would otherwise become stale.

## 5. Runtime Data Flow

```text
ObjectLabel registry + ACTIVE ModelVersion manifest
                    |
                    v
          capability snapshot
             /             \
   COCO-enabled set     custom-enabled set
          |                    |
  full-frame base       active custom only
          |                    |
          +---- class-aware merge ----+
                         |
                ByteTrack continuity
                         |
          initiation/continuation gate
                         |
               registry-label resolve
                         |
                    ZoneChecker
                         |
              events / clips / WebSocket
```

The Area pipeline refreshes registry and active-model state on startup and periodically. Refresh failure keeps the last known-good capability snapshot for a bounded interval. If no snapshot has ever succeeded, the worker fails closed for zone/event evaluation rather than enabling unregistered classes.

There is no artifact fallback when the database reports no active model. A missing, unreadable, or checksum-invalid active artifact disables its custom classes and emits an operational error; it does not fall back to another directory.

## 6. Detection and Tracking

### Base detector

- Default model remains YOLO11n until benchmark evidence justifies YOLO11s.
- Base inference only requests COCO IDs present in the current capability snapshot.
- `boat`, `train`, static `container`, World-model prompts, and non-COCO aliases are excluded from the Area base path.
- `bus` stays `bus`; `train` is never rewritten to `truck`.

### Custom detector

- Loads only the database-selected active artifact.
- Runs only if its manifest has an intersection with enabled custom registry classes.
- Filters every output through that intersection.
- Uses per-class initiation and continuation thresholds.
- Requires two hits in the latest three eligible inference frames before a custom-only track can be emitted or a generic base class can be replaced.

### Merge and track policy

- Detections are deduplicated using class-aware IoU/NMS.
- An overlapping custom candidate cannot replace a base candidate before temporal confirmation.
- After confirmation, an exact custom distinction may supersede an overlapping generic COCO vehicle while preserving track continuity.
- A custom-only candidate receives a stable identity through existing ByteTrack/association infrastructure only after satisfying initiation policy.
- Low-confidence observations carry `canInitiate=false`. ZoneChecker may use them to sustain a matching existing track but not to enter its pending/open state.
- Remove geometry-based class stabilization, cabin/container assembly, semantic alias expansion, and instant custom promotion paths.

Thresholds are configuration values grouped by source and canonical class. Defaults must be conservative and covered by tests; BAI-KIEM-specific values are selected only from golden-set threshold sweeps.

## 7. ROI/Tile Inference

ROI inference is behind a feature flag and off by default until benchmarked.

- Each configured ROI is a normalized polygon or rectangle with an explicit detector scope (`base`, `custom`, or both).
- A scheduler runs ROI inference every two or three source frames according to configuration.
- Large ROIs are tiled around 640 px with 0.20 overlap and a bounded tile count.
- Coordinates are remapped to the full frame before class-aware deduplication.
- Full-frame base inference remains available; ROI inference supplements rather than changes semantics.
- Metrics record ROI count, tiles executed, latency per engine, total end-to-end FPS, and peak CUDA memory.

The benchmark matrix covers YOLO11n and any locally available YOLO11s artifact, image sizes 640/896/960, full frame versus ROI, and PyTorch FP16 versus a locally available TensorRT engine. Missing models or runtimes are reported as blocked; they are not downloaded or installed without permission.

## 8. API and UI Contract

`GET /api/v1/labels` is enriched with the capability fields defined above. Create/update endpoints accept product COCO classes or normalized non-COCO identifiers. They reject ambiguous legacy `container` mappings and require the explicit non-vehicle `shipping_container` or vehicle `container_truck` meaning. A valid non-COCO label may be saved while unavailable so that the UI can show its missing-model state.

Zone create/update performs a database-backed check that every target label:

- exists in the registry;
- appears once after normalization;
- is currently detectable.

The frontend:

- renders only server-returned registry labels;
- disables unavailable labels in Zone Editor and displays `Chưa có model nhận diện`;
- shows source badges for COCO/custom and active model version where relevant;
- stops fabricating or mutating local label state after failed API writes;
- distinguishes `Xe đầu kéo container` from static container;
- updates training copy so COCO labels are not presented as custom-training requirements.

Legacy remote rows are audited and surfaced as unavailable. No production/Neon data is silently rewritten by application startup.

## 9. Dataset and Golden Evaluation

The repository gains reproducible tools and documentation for:

1. Extracting candidate frames from BAI-KIEM at regular intervals and configured hard-case timestamps.
2. Rejecting exact and perceptually near-duplicate frames.
3. Creating a source/time-aware annotation manifest without inventing boxes.
4. Tracking annotation status and negative frames.
5. Auditing class balance, sources, bbox size distribution, duplicates, background diversity proxies, and negative ratio.
6. Evaluating predictions against the annotated manifest.

Required reports include:

- per-class precision, recall, F1, AP50;
- small/far-object buckets;
- truck-to-reach-stacker and reach-stacker-to-truck confusion;
- static-container false positives;
- false alerts per minute after zone/event logic;
- end-to-end Area FPS and peak VRAM on the RTX 3050 4 GB;
- threshold sweep results separated into initiation and continuation thresholds.

The existing external dataset may be retained as supplemental positive data, but it cannot be the golden set. A future training set targets 20-30% negative/hard-negative frames and source/time isolation between train, validation, and test.

## 10. Compatibility and Failure Handling

- Gate/LPR detectors and routes are out of scope and must remain behaviorally unchanged.
- Zone event timing remains: one-second confirmation, boundary sustain, three observed outside frames to close, and twelve-second missing-track reconnect grace.
- Clip buffering/encoding and event persistence contracts remain unchanged.
- A capability refresh or custom model failure emits diagnostics and fails closed for affected custom labels while COCO-capable labels continue normally.
- UI/API errors are explicit; no client-side optimistic fallback creates state that the server did not persist.

## 11. Verification Strategy

### Unit and contract tests

- Full capability truth table: COCO, active custom, inactive custom, invalid manifest, ambiguous/static container, sample-count independence.
- Node/Python taxonomy parity using the same fixtures.
- Exact custom 2-of-3 temporal confirmation.
- Initiation versus continuation thresholds.
- Class-aware merge without semantic relabeling.
- Strict registry whitelist in detector, Zone API, and ZoneChecker.
- UI rendering and disable rules for unavailable labels.

### Regression tests

- Existing event open/sustain/close/reconnect behavior.
- Clip generation and browser-compatible encoding.
- Stream rewind and source-speed handling.
- Gate/LPR, label CRUD, zone CRUD, WebSocket, and API contracts.

### Evaluation and performance

- Run the benchmark matrix only with local assets.
- Run golden evaluation once ground-truth annotations exist.
- Classify every acceptance target as `PASS`, `FAIL`, or `BLOCKED/NOT EVALUATED`, with evidence paths.

## 12. Rollout Boundaries

This work changes repository source, tests, generated local evaluation artifacts, and documentation only. It does not commit, push, deploy, activate a model, modify production Neon rows, download a model, install dependencies, or start a new training job without separate authorization.
