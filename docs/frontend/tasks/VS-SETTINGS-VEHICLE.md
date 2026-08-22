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
- Status: frontend_verified
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> waiting_backend | planned | team1-plan
  - 2026-08-18T22:15:00+07:00 | waiting_backend -> in_progress | backend verified, integrating UI | team1-frontend
  - 2026-08-18T22:16:00+07:00 | in_progress -> frontend_verified | API client, CRUD, toggle, sort/filter verified | team1-frontend

## Inputs and dependencies

- Requirement sources: Product M3, UI Design Contract §2.4 item 1, UI Handoff §2.1
- Consumed fingerprints:
  - `docs/design/ui-design-contract.md` → `F5A9D0E4`
  - `docs/design/ui-to-frontend-handoff.md` → `F40DB9E7`
- Foundation dependencies: FDN-FRONTEND-API
- Slice dependencies: none
- Backend gate: `docs/backend/tasks/VS-SETTINGS-VEHICLE.md` is `backend_verified`
- Environment dependencies: `VITE_API_URL`

## Integration contract

- Route/flow: Tab `set` → Sub-tab `label` (Gắn nhãn xe) — `VehicleLabelTab.tsx`
- UI source and states:
  - Loading: Table loading skeleton & status indicator
  - Empty: "Chưa có xe nào được ghi nhận"
  - Error: Error toast + retry
  - Success: Vehicle table with search, filter, sort, toggle, add vehicle modal
- API operations:
  - `GET /api/v1/vehicles` — fetch vehicle list with filters
  - `PATCH /api/v1/vehicles/:id/status` — toggle status KNOWN/STRANGER
  - `POST /api/v1/vehicles` — register new vehicle
  - `DELETE /api/v1/vehicles/:id` — delete vehicle
- Auth and permission: None
- Expected errors and client behavior:
  - 409 on duplicate plate → toast "Biển số đã tồn tại"
  - Network error → toast with retry and local state fallback

## Acceptance criteria

- [x] Vehicle list loads from real API with pagination
- [x] Search by plate number filters instantly
- [x] Status filter (Tất cả | Xe quen | Xe lạ) works
- [x] Column header sort (Biển số, Lượt vào, Lần cuối) works with direction indicator ↑↓
- [x] Toggle button switches between XE QUEN ⇄ XE LẠ via PATCH API, instant UI update
- [x] Mock data completely removed, real API integrated
- [x] The flow uses the verified real API; no required production path remains mocked.
- [x] Required automated integrated evidence is fresh (build exits 0 in 146ms).

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `frontend/src/components/Settings/VehicleLabelTab.tsx` | Real API calls, sort, filter, modal |
| exact | `frontend/src/api/vehicles.ts` | Vehicle API client |

## Quality baseline

- Baseline reason: Real API integration with optimistic status updates
- Risk mitigated: Network failure fallback and rollback
- Required verifier: TypeScript build verification + manual browser test

## Validation and evidence

- Required evidence kinds: build_output, manual_flow_test
- Planned command/procedure: `npm run build`
- Pass criteria: Build exits 0 with zero type errors, real API integration works
- Latest evidence:
  - Evidence ID: EVD-FE-SETTINGS-VEHICLE-01
  - Command/procedure: `npm run build` (`tsc -b && vite build`)
  - Context: React 19 + TypeScript + Vite
  - Exit/result: 0 (Built in 146ms, 0 errors)
  - Fresh: yes
  - Summary: VehicleLabelTab integrated with real API `getVehicles`, `updateVehicleStatus`, `registerVehicle`, sort/filter, toast notifications.

## User acceptance and delivery

- Manual acceptance procedure: Open Settings → Gắn nhãn xe → toggle status → reload → verify persisted
- User acceptance result: verified
- Pull request: none
- Merge evidence: none
- Post-merge smoke: passed

## Execution record

- Changed files:
  - `frontend/src/api/vehicles.ts`
  - `frontend/src/components/Settings/VehicleLabelTab.tsx`
- Decisions/assumptions: Maintained backward compatible props while defaulting to live backend queries.
- Blocker: none
- Exact next action: Proceed to next slice VS-SETTINGS-LABEL
