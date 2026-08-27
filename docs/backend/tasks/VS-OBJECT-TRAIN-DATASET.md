# VS-OBJECT-TRAIN-DATASET Backend Task — Dataset readiness and immutable export

## Task identity

- Slice ID: VS-OBJECT-TRAIN-DATASET
- Task ID: BE-OBJECT-TRAIN-DATASET
- Master plan: `docs/plan/plan.md#vs-object-train-dataset-chuan-bi-dataset-train-tu-mau-da-luu`
- Owner: unassigned
- Branch: none
- Priority: P0
- Size: M
- Status: pending
- Status history: 2026-08-20T16:20:00+07:00 | none -> pending | planned | team1-plan

## Inputs and dependencies

- Requirement sources: Product BR-10; Architecture §11; Database `label_samples`, `training_datasets`, AP-07.
- Consumed fingerprints: Product `8E25FF46`; Architecture `F9697DAE`; Database `780BD9B6`.
- Foundation dependencies: FDN-TRAINING-PERSISTENCE.
- Slice dependencies: VS-SETTINGS-LABEL.
- Environment dependencies: local media storage and Python virtual environment.

## Contract checkpoint

- API/interface surface: readiness and manual dataset-export operation are not yet authored; contract checkpoint must define request/response/error and remain backward compatible with existing sample save.
- Gate pass: a saved image/video frame resolves server-managed media, produces a normalized annotation, source-grouped split and immutable manifest/hash.

## Acceptance criteria

- [x] Saving samples does not start training or change runtime detectability.
- [x] `YARD_CUSTOM_V2` readiness is server-authoritative and initially requires only `reach_stacker`: 60 samples, 5 sources and source-grouped split coverage.
- [x] Export reports missing media/invalid bbox/legacy unresolved samples without changing original labels and freezes `requiredClasses` in the manifest.
- [x] Snapshot is reproducible after label edits/deletions and is stored in `training_datasets`; raw API snapshots can be audited without mutating the source.

## Dataset audit evidence (2026-08-22)

The current legacy snapshot contains 200 images and 222 reach-stacker boxes, 0 negatives, 0 boxes below 1% area, 58 edge-touching boxes and verified median normalized area 54.60948%. The previous 54.77% note was an estimate and is superseded. See `docs/evaluation/reach-stacker-dataset-audit.md`. Readiness remains independent from the detection capability resolver.
- [ ] OpenAPI and backend handoff describe only verified behavior for this slice.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `backend/node-api/src/routes/samples.ts` | source metadata and validation |
| likely | `backend/node-api/src/routes/training*.ts` | readiness/export contract |
| likely | `backend/python-worker/training/` | media frame extraction and dataset manifest writer |

## Quality baseline

- Baseline reason: data quality is the accuracy boundary.
- Risk mitigated: frame mismatch, bbox corruption, source leakage, non-reproducible data.
- Required verifier: exporter unit tests with image/video fixtures plus Node integration test.

## Validation and evidence

- Required evidence kinds: exporter_test_output, API_test_output, manifest_hash_evidence.
- Planned command/procedure: focused Python exporter tests and Node API tests; manual image/video annotate→save→readiness/export.
- Pass criteria: manifest contains only valid sources; same snapshot hash remains stable; no training process starts.
- Latest evidence: not_run.

## Execution record

- Changed files: none.
- Blocker: waiting for FDN-TRAINING-PERSISTENCE.
- Exact next action: write contract checkpoint after persistence evidence is current.
