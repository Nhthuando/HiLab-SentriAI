# VS-OBJECT-TRAIN-DATASET Frontend Task — Dataset readiness

## Task identity

- Slice ID: VS-OBJECT-TRAIN-DATASET
- Task ID: FE-OBJECT-TRAIN-DATASET
- Master plan: `docs/plan/plan.md#vs-object-train-dataset-chuan-bi-dataset-train-tu-mau-da-luu`
- Backend task: `docs/backend/tasks/VS-OBJECT-TRAIN-DATASET.md`
- Owner: unassigned
- Branch: none
- Priority: P0
- Size: M
- Status: waiting_backend

## Inputs and dependencies

- Requirement sources: Product BR-10; UI Handoff §4.3; Database sample provenance.
- Consumed fingerprints: Product `8E25FF46`; UI handoff `456E4FDD`; Database `780BD9B6`.
- Foundation dependencies: FDN-FRONTEND-API.
- Slice dependencies: FDN-TRAINING-PERSISTENCE, VS-SETTINGS-LABEL.
- Backend gate: `VS-OBJECT-TRAIN-DATASET` backend_verified with current contract evidence.

## Integration contract

- Route/flow: Settings → Nhãn đối tượng → Cải thiện nhận diện.
- UI source and states: `ObjectTrainingPanel.tsx`, `ObjectLabelTab.tsx`; loading, insufficient data, ready, invalid/excluded sample explanation and recoverable error.
- API operations: unknown until backend contract checkpoint; do not infer paths or payloads.
- Auth and permission: none.

## Acceptance criteria

- [ ] Readiness uses server-validated saved data, not mock counts.
- [ ] Saving sample refreshes readiness but never starts training.
- [ ] Missing/invalid sample message is plain-language and points to the next action.
- [ ] The flow uses the verified real API; no required production path remains mocked.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `frontend/src/components/Settings/ObjectTrainingPanel.tsx` | real readiness states |
| exact | `frontend/src/components/Settings/ObjectLabelTab.tsx` | save/readiness refresh integration |
| likely | `frontend/src/api/training*.ts` | contract client |

## Validation and evidence

- Required evidence kinds: build_output, API_integration_evidence, manual_flow_test.
- Planned command/procedure: Vite build; save image/video annotation then check real readiness/error states.
- Pass criteria: no auto-train and status matches backend validation.
- Latest evidence: not_run.

## Execution record

- Changed files: none.
- Blocker: waiting for backend gate.
- Exact next action: replace mock readiness only after contract evidence exists.
