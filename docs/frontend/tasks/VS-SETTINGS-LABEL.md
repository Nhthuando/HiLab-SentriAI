# VS-SETTINGS-LABEL Frontend Task — Cài đặt: nhãn đối tượng + gắn mẫu

## Task identity

- Slice ID: VS-SETTINGS-LABEL
- Task ID: FE-SETTINGS-LABEL
- Master plan: `docs/plan/plan.md#vs-settings-label`
- Backend task: `docs/backend/tasks/VS-SETTINGS-LABEL.md`
- Owner: Phạm Hưng
- Branch: none
- Priority: P1
- Size: M
- Status: waiting_backend
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> waiting_backend | planned | team1-plan

## Inputs and dependencies

- Requirement sources: Product M3 (nhãn đối tượng), AC-06, UI Design Contract §2.4 item 3, UI Handoff §2.1
- Consumed fingerprints:
  - `docs/design/ui-design-contract.md` → `F5A9D0E4`
  - `docs/design/ui-to-frontend-handoff.md` → `F40DB9E7`
- Foundation dependencies: FDN-FRONTEND-API
- Slice dependencies: none
- Backend gate: matching backend task is `backend_verified` with current OpenAPI/handoff evidence
- Environment dependencies: `VITE_API_URL`

## Integration contract

- Route/flow: Tab `set` → Sub-tab `obj` (Nhãn đối tượng) — `ObjectLabelTab.tsx`
- UI source and states:
  - Loading: Label list skeleton
  - Empty: "Chưa có nhãn nào" + "Thêm nhãn mới" button
  - Error: Error toast + retry
  - Success: Label management + media strip + annotation canvas
- API operations:
  - `GET /api/v1/labels` — load labels with sample counts
  - `POST /api/v1/labels` — create new label
  - `PUT /api/v1/labels/:id` — update label
  - `DELETE /api/v1/labels/:id` — delete label (cascades samples)
  - `POST /api/v1/samples/batch` — save batch annotations
  - `POST /api/v1/upload/image` — upload source image
- Auth and permission: None
- Expected errors and client behavior:
  - 409 duplicate name → toast "Tên nhãn đã tồn tại"
  - Upload too large → toast "File quá lớn (tối đa 10MB)"

## Acceptance criteria

- [ ] AC-06: Nhãn đã lưu xuất hiện trong dropdown loại của zone config
- [ ] Label list loads from real API with sample count
- [ ] Create/edit/delete labels via API
- [ ] Image upload stores file and returns path
- [ ] Annotation canvas: crosshair + bbox drawing + keyboard shortcuts 1-8
- [ ] Batch save annotations sends to API
- [ ] Video scrubber timeline with keyframe markers
- [ ] Mock data completely removed
- [ ] The flow uses the verified real API; no required production path remains mocked.
- [ ] Required automated integrated evidence is fresh.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `frontend/src/components/Settings/ObjectLabelTab.tsx` | Replace mock with real API calls |
| likely | `frontend/src/api/labels.ts` | Label + sample API client |
| likely | `frontend/src/api/upload.ts` | Image upload API client |

## Quality baseline

- Baseline reason: File upload validation, batch annotation integrity
- Risk mitigated: Large file rejection, annotation data consistency
- Required verifier: Manual browser test

## Validation and evidence

- Required evidence kinds: browser_screenshot, manual_flow_test
- Planned command/procedure: Open Settings → Nhãn đối tượng → create label → upload image → draw bbox → save batch
- Pass criteria: Labels persist, annotations saved, zone dropdown shows labels
- Latest evidence:
  - Evidence ID: none
  - Command/procedure: not_run
  - Context: not_run
  - Exit/result: not_run
  - Fresh: no
  - Summary: not_run

## User acceptance and delivery

- Manual acceptance procedure: Create label → upload image → annotate → save → check zone editor dropdown
- User acceptance result: not_run
- Pull request: none
- Merge evidence: none
- Post-merge smoke: not_run

## Execution record

- Changed files: none
- Decisions/assumptions: none
- Blocker: waiting for backend gate
- Exact next action: wait for matching backend task to reach `backend_verified`
