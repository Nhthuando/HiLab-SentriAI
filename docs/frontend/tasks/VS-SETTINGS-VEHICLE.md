# VS-SETTINGS-VEHICLE Frontend Task — Cài đặt: quản lý danh sách biển số

## Task identity

- Slice ID: VS-SETTINGS-VEHICLE
- Task ID: FE-SETTINGS-VEHICLE
- Master plan: `docs/plan/plan.md#vs-settings-vehicle`
- Backend task: `docs/backend/tasks/VS-SETTINGS-VEHICLE.md`
- Owner: Phạm Hưng
- Branch: none
- Priority: P1
- Size: S
- Status: waiting_backend
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> waiting_backend | planned | team1-plan

## Inputs and dependencies

- Requirement sources: Product M3, UI Design Contract §2.4 item 1, UI Handoff §2.1
- Consumed fingerprints:
  - `docs/design/ui-design-contract.md` → `F5A9D0E4`
  - `docs/design/ui-to-frontend-handoff.md` → `F40DB9E7`
- Foundation dependencies: FDN-FRONTEND-API
- Slice dependencies: none
- Backend gate: matching backend task is `backend_verified` with current OpenAPI/handoff evidence
- Environment dependencies: `VITE_API_URL`

## Integration contract

- Route/flow: Tab `set` → Sub-tab `label` (Gắn nhãn xe) — `VehicleLabelTab.tsx`
- UI source and states:
  - Loading: Table skeleton
  - Empty: "Chưa có xe nào được ghi nhận"
  - Error: Error toast + retry
  - Success: Vehicle table with search, filter, sort, toggle
- API operations:
  - `GET /api/v1/vehicles` — fetch vehicle list with filters
  - `PATCH /api/v1/vehicles/:id` — toggle status KNOWN/STRANGER
- Auth and permission: None
- Expected errors and client behavior:
  - 409 on duplicate plate → toast "Biển số đã tồn tại"
  - Network error → toast with retry

## Acceptance criteria

- [ ] Vehicle list loads from real API with pagination
- [ ] Search by plate number filters instantly
- [ ] Status filter (Tất cả | Xe quen | Xe lạ) works
- [ ] Column header sort (Biển số, Lượt vào, Lần cuối) works with direction indicator ↑↓
- [ ] Toggle button switches between XE QUEN ⇄ XE LẠ via PATCH API, instant UI update
- [ ] Mock data completely removed
- [ ] The flow uses the verified real API; no required production path remains mocked.
- [ ] Required automated integrated evidence is fresh.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `frontend/src/components/Settings/VehicleLabelTab.tsx` | Replace mock with real API calls |
| likely | `frontend/src/api/vehicles.ts` | Vehicle API client |

## Quality baseline

- Baseline reason: none — straightforward CRUD integration
- Risk mitigated: none
- Required verifier: Manual browser test

## Validation and evidence

- Required evidence kinds: browser_screenshot, manual_flow_test
- Planned command/procedure: Open Settings → Gắn nhãn xe → verify CRUD operations
- Pass criteria: Toggle works, search/filter works, data persists across reload
- Latest evidence:
  - Evidence ID: none
  - Command/procedure: not_run
  - Context: not_run
  - Exit/result: not_run
  - Fresh: no
  - Summary: not_run

## User acceptance and delivery

- Manual acceptance procedure: Open Settings → Gắn nhãn xe → toggle status → reload → verify persisted
- User acceptance result: not_run
- Pull request: none
- Merge evidence: none
- Post-merge smoke: not_run

## Execution record

- Changed files: none
- Decisions/assumptions: none
- Blocker: waiting for backend gate
- Exact next action: wait for matching backend task to reach `backend_verified`
