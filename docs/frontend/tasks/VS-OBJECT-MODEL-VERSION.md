# VS-OBJECT-MODEL-VERSION Frontend Task — Use new version or return

## Task identity

- Slice ID: VS-OBJECT-MODEL-VERSION
- Task ID: FE-OBJECT-MODEL-VERSION
- Master plan: `docs/plan/plan.md#vs-object-model-version-dung-ban-nhan-dien-moi-hoac-quay-ve-ban-truoc`
- Backend task: `docs/backend/tasks/VS-OBJECT-MODEL-VERSION.md`
- Owner: unassigned
- Branch: none
- Priority: P0
- Size: M
- Status: waiting_backend

## Inputs and dependencies

- Requirement sources: Product AC-11/BR-11; Architecture §11; UI Handoff §4.3.
- Consumed fingerprints: Product `8E25FF46`; Architecture `F9697DAE`; UI handoff `456E4FDD`.
- Foundation dependencies: FDN-FRONTEND-API.
- Slice dependencies: VS-OBJECT-TRAIN-RUN.
- Backend gate: matching backend task backend_verified with current version contract.

## Integration contract

- Route/flow: Settings → Nhãn đối tượng → Bản nhận diện mới.
- UI source and states: `ObjectTrainingPanel.tsx`; evaluated result, use confirmation, active custom augmentation, return confirmation, reload failure and artifact unavailable error.
- API operations: unknown until backend contract checkpoint; no endpoint is inferred from mock UI.
- Auth and permission: none.

## Acceptance criteria

- [ ] Only backend-approved evaluated result offers `Dùng bản nhận diện mới`.
- [ ] Confirmation clearly says people/container/standard vehicles remain detected by base YOLO.
- [ ] Return shows baseline-only status without claiming model deletion.
- [ ] The flow uses the verified real API; no required production path remains mocked.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `frontend/src/components/Settings/ObjectTrainingPanel.tsx` | version list/use/return UI |
| likely | `frontend/src/api/modelVersions*.ts` | version contract client |

## Validation and evidence

- Required evidence kinds: build_output, API_integration_evidence, hybrid_manual_regression.
- Planned command/procedure: evaluate candidate → use → confirm Area detection of person/container/forklift → return.
- Pass criteria: user-visible state equals backend version state; base classes stay detected before and after return.
- Latest evidence: not_run.

## User acceptance and delivery

- Manual acceptance procedure: Inspect result → choose use → verify live Area feed → choose return → verify feed again.
- User acceptance result: not_run.
- Pull request: none.
- Merge evidence: none.
- Post-merge smoke: not_run.

## Execution record

- Changed files: none.
- Blocker: waiting for backend gate.
- Exact next action: replace mock activation/return after backend verification.
