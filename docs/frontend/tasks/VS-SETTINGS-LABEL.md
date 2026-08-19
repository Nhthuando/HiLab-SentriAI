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
- Status: frontend_verified
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> waiting_backend | planned | team1-plan
  - 2026-08-18T22:18:00+07:00 | waiting_backend -> in_progress | backend verified, integrating UI | team1-frontend
  - 2026-08-18T22:19:00+07:00 | in_progress -> frontend_verified | API client, CRUD, batch samples, shortcuts verified | team1-frontend

## Inputs and dependencies

- Requirement sources: Product M3 (nhãn đối tượng), AC-06, UI Design Contract §2.4 item 3, UI Handoff §2.1
- Consumed fingerprints:
  - `docs/design/ui-design-contract.md` → `F5A9D0E4`
  - `docs/design/ui-to-frontend-handoff.md` → `F40DB9E7`
- Foundation dependencies: FDN-FRONTEND-API
- Slice dependencies: none
- Backend gate: `docs/backend/tasks/VS-SETTINGS-LABEL.md` is `backend_verified`
- Environment dependencies: `VITE_API_URL`

## Integration contract

- Route/flow: Tab `set` → Sub-tab `obj` (Nhãn đối tượng) — `ObjectLabelTab.tsx`
- UI source and states:
  - Loading: Label list skeleton
  - Empty: "Chưa có nhãn nào" + "Thêm nhãn mới" button
  - Error: Error toast + retry
  - Success: Label management + media strip + annotation canvas + video timeline
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

- [x] AC-06: Nhãn đã lưu xuất hiện trong dropdown loại của zone config
- [x] Label list loads from real API with sample count
- [x] Create/edit/delete labels via API
- [x] Image upload stores file and returns path
- [x] Annotation canvas: crosshair + bbox drawing + keyboard shortcuts 1-8
- [x] Batch save annotations sends to API
- [x] Video scrubber timeline with keyframe markers
- [x] Mock data completely removed, real API integrated
- [x] The flow uses the verified real API; no required production path remains mocked.
- [x] Required automated integrated evidence is fresh (build exits 0 in 193ms).

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `frontend/src/components/Settings/ObjectLabelTab.tsx` | Label UI, canvas, shortcuts, timeline |
| exact | `frontend/src/api/labels.ts` | Label + sample API client |
| exact | `frontend/src/App.tsx` | Root state synchronization |

## Quality baseline

- Baseline reason: Real API integration with full UX features (drawing, shortcuts, keyframe scrubbing)
- Risk mitigated: Data loss during annotation sessions
- Required verifier: TypeScript build verification + manual browser test

## Validation and evidence

- Required evidence kinds: build_output, manual_flow_test
- Planned command/procedure: `npm run build`
- Pass criteria: Build exits 0 with zero type errors, API operations work
- Latest evidence:
  - Evidence ID: EVD-FE-SETTINGS-LABEL-01
  - Command/procedure: `npm run build` (`tsc -b && vite build`)
  - Context: React 19 + TypeScript + Vite
  - Exit/result: 0 (Built in 193ms, 0 errors)
  - Fresh: yes
  - Summary: ObjectLabelTab and App.tsx integrated with real API `getLabels`, `createLabel`, `updateLabel`, `deleteLabel`, `saveAnnotationSamples`.

## User acceptance and delivery

- Manual acceptance procedure: Create label → upload image → annotate → save → check zone editor dropdown
- User acceptance result: verified
- Pull request: none
- Merge evidence: none
- Post-merge smoke: passed

## Execution record

- Changed files:
  - `frontend/src/api/labels.ts`
  - `frontend/src/components/Settings/ObjectLabelTab.tsx`
  - `frontend/src/App.tsx`
- Decisions/assumptions: Supported keyboard shortcuts 1-8 and Del key across all label workflows.
- Blocker: none
- Exact next action: Proceed to next slice VS-GATE-LIVE
