# VS-OBJECT-MODEL-VERSION Backend Task — Use custom model version or return

## Task identity

- Slice ID: VS-OBJECT-MODEL-VERSION
- Task ID: BE-OBJECT-MODEL-VERSION
- Master plan: `docs/plan/plan.md#vs-object-model-version-dung-ban-nhan-dien-moi-hoac-quay-ve-ban-truoc`
- Owner: unassigned
- Branch: none
- Priority: P0
- Size: M
- Status: pending
- Status history: 2026-08-20T16:20:00+07:00 | none -> pending | planned | team1-plan

## Inputs and dependencies

- Requirement sources: Product AC-11/BR-11; Architecture §11 hybrid policy; Database `model_versions`, AP-10/AP-11.
- Consumed fingerprints: Product `8E25FF46`; Architecture `F9697DAE`; Database `780BD9B6`.
- Foundation dependencies: FDN-TRAINING-PERSISTENCE.
- Slice dependencies: VS-OBJECT-TRAIN-RUN, VS-AREA-VIOLATION.
- Environment dependencies: local model artifact storage and Python worker control channel.

## Contract checkpoint

- API/interface surface: version list, explicit use/return and error contract are planned; only evaluated candidate can enter use operation.
- Gate pass: activation atomically selects one custom augmentation; base YOLO remains loaded for person/container/COCO vehicles; return disables custom augmentation without restarting monitoring.

## Acceptance criteria

- [ ] Artifact path/checksum and evaluation state are verified before use.
- [ ] Concurrent use requests cannot enable two custom versions.
- [ ] Reload failure restores previous custom/base inference state and returns recoverable error.
- [ ] Return retains candidate metadata and restores baseline-only behavior.
- [ ] OpenAPI and backend handoff describe only verified behavior for this slice.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| likely | `backend/node-api/src/routes/modelVersions*.ts` | version/list/use/return contract |
| likely | `backend/node-api/src/services/modelVersion*.ts` | transactional state change |
| exact | `backend/python-worker/detection/` | base/custom hybrid load and fusion |
| exact | `backend/python-worker/main.py` | atomic reload signal |

## Quality baseline

- Baseline reason: preserve current recognition when custom model is unsafe.
- Risk mitigated: broken artifact, accidental replacement of base classes, activation race.
- Required verifier: transaction/integration tests and Area video regression with active/returned custom model.

## Validation and evidence

- Required evidence kinds: integration_test_output, artifact_integrity_evidence, hybrid_regression_report, FPS_benchmark.
- Planned command/procedure: candidate use→Area inference→return sequence with corrupted-artifact and race tests.
- Pass criteria: base COCO detection works in every path; only one custom version is active; Area remains >=8 FPS.
- Latest evidence: not_run.

## Execution record

- Changed files: none.
- Blocker: waiting for evaluated candidate evidence.
- Exact next action: author version contract after VS-OBJECT-TRAIN-RUN is backend_verified.
