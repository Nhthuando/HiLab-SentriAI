# VS-OBJECT-TRAIN-RUN Backend Task — Manual training, GPU guard and evaluation

## Task identity

- Slice ID: VS-OBJECT-TRAIN-RUN
- Task ID: BE-OBJECT-TRAIN-RUN
- Master plan: `docs/plan/plan.md#vs-object-train-run-train-thu-cong-bao-ve-camera-va-evaluation`
- Owner: unassigned
- Branch: none
- Priority: P0
- Size: L
- Status: pending
- Status history: 2026-08-20T16:20:00+07:00 | none -> pending | planned | team1-plan

## Inputs and dependencies

- Requirement sources: Product AC-10/BR-11; Architecture §11; Database `training_jobs`/`model_versions`.
- Consumed fingerprints: Product `8E25FF46`; Architecture `F9697DAE`; Database `780BD9B6`.
- Foundation dependencies: FDN-TRAINING-PERSISTENCE.
- Slice dependencies: VS-OBJECT-TRAIN-DATASET, VS-AREA-VIOLATION.
- Environment dependencies: CUDA Python environment and local artifact storage.

## Contract checkpoint

- API/interface surface: manual start/job-status contract is planned and must specify terminal, `PAUSED_GPU`, validation and failure states before frontend work.
- Gate pass: job uses a completed immutable dataset; runner is independent from active inference; evaluation reports held-out-by-source accuracy, person/vehicle base regression, forklift metric and Area FPS.

## Acceptance criteria

- [ ] No sample save starts a job; user action is required.
- [ ] Governor pauses/throttles train before Area FPS drops below 8 and resumes only after stable telemetry.
- [ ] OOM/runner failure/dataset error leaves base and current custom inference unchanged.
- [ ] Job becomes candidate-ready only after evaluation; failing regression or FPS cannot proceed to version activation.
- [ ] OpenAPI and backend handoff describe only verified behavior for this slice.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| likely | `backend/node-api/src/routes/training*.ts` | job lifecycle API |
| likely | `backend/node-api/src/services/training*.ts` | process supervision and state transitions |
| likely | `backend/python-worker/training/runner.py` | Ultralytics train/evaluate runner |
| exact | `backend/python-worker/main.py` | Area FPS telemetry consumer only |

## Quality baseline

- Baseline reason: continuous monitoring and accuracy regression safety.
- Risk mitigated: GPU starvation, catastrophic forgetting, silent failed job.
- Required verifier: job-state tests, source-held-out evaluation, GPU monitored Area video benchmark.

## Validation and evidence

- Required evidence kinds: unit_test_output, runner_log_sanitized, evaluation_report, FPS_benchmark.
- Planned command/procedure: fixture dataset training/evaluation plus concurrent Area Monitor benchmark.
- Pass criteria: Area stays >=8 FPS, candidate report contains regression and forklift results, failed paths preserve active inference.
- Latest evidence: not_run.

## Execution record

- Changed files: none.
- Blocker: waiting for dataset export evidence.
- Exact next action: approve exact job API contract after dataset slice backend verification.
