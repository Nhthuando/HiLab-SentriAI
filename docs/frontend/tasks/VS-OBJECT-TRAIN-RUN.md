# VS-OBJECT-TRAIN-RUN Frontend Task — Manual training progress

## Task identity

- Slice ID: VS-OBJECT-TRAIN-RUN
- Task ID: FE-OBJECT-TRAIN-RUN
- Master plan: `docs/plan/plan.md#vs-object-train-run-train-thu-cong-bao-ve-camera-va-evaluation`
- Backend task: `docs/backend/tasks/VS-OBJECT-TRAIN-RUN.md`
- Owner: unassigned
- Branch: none
- Priority: P0
- Size: L
- Status: waiting_backend

## Inputs and dependencies

- Requirement sources: Product AC-10/BR-11; UI Handoff §4.3; Architecture §11.
- Consumed fingerprints: Product `8E25FF46`; Architecture `F9697DAE`; UI handoff `456E4FDD`.
- Foundation dependencies: FDN-FRONTEND-API.
- Slice dependencies: VS-OBJECT-TRAIN-DATASET.
- Backend gate: matching backend task backend_verified with current job contract.

## Integration contract

- Route/flow: Settings → Nhãn đối tượng → Bắt đầu cải thiện nhận diện.
- UI source and states: `ObjectTrainingPanel.tsx`; start confirmation, preparing, improving, protecting camera, checking result, failed/retry and ready-result states.
- API operations: unknown until backend contract checkpoint; frontend waits for verified contract.
- Auth and permission: none.

## Acceptance criteria

- [ ] Start is an explicit user action and has clear disabled/error states.
- [ ] `PAUSED_GPU` is rendered as camera protection in plain language, never as generic failure.
- [ ] Progress and result update from real job state; browser reload reconciles current backend state.
- [ ] The flow uses the verified real API; no required production path remains mocked.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `frontend/src/components/Settings/ObjectTrainingPanel.tsx` | job/progress/error UI |
| likely | `frontend/src/api/training*.ts` | job client |

## Validation and evidence

- Required evidence kinds: build_output, API_integration_evidence, monitored_manual_test.
- Planned command/procedure: start job with fixture dataset while Area Monitor runs; inspect pause/result/reload states.
- Pass criteria: UI reflects job state and monitoring stays responsive.
- Latest evidence: not_run.

## Execution record

- Changed files: none.
- Blocker: waiting for backend gate.
- Exact next action: replace mock state machine after verified job contract.
