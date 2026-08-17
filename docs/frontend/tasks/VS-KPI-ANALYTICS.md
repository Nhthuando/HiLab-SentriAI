# VS-KPI-ANALYTICS Frontend Task — KPI Dashboard cards

## Task identity

- Slice ID: VS-KPI-ANALYTICS
- Task ID: FE-KPI-ANALYTICS
- Master plan: `docs/plan/plan.md#vs-kpi-analytics`
- Backend task: `docs/backend/tasks/VS-KPI-ANALYTICS.md`
- Owner: Hữu Thuận
- Branch: none
- Priority: P2
- Size: S
- Status: waiting_backend
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> waiting_backend | planned | team1-plan

## Inputs and dependencies

- Requirement sources: UI Design Contract §2.2 (Gate KPI), §2.3 (Area KPI)
- Consumed fingerprints:
  - `docs/design/ui-design-contract.md` → `F5A9D0E4`
  - `docs/design/ui-to-frontend-handoff.md` → `F40DB9E7`
- Foundation dependencies: FDN-FRONTEND-API
- Slice dependencies: VS-GATE-LIVE, VS-AREA-VIOLATION
- Backend gate: matching backend task is `backend_verified` with current OpenAPI/handoff evidence
- Environment dependencies: `VITE_API_URL`

## Integration contract

- Route/flow: GateMonitor KPI cards + AreaMonitor KPI cards
- UI source and states:
  - Loading: KPI card skeletons with shimmer
  - Empty: All values show 0
  - Success: Animated KPI values from real data
- API operations:
  - `GET /api/v1/analytics/kpis` — fetch KPI stats
- Auth and permission: None
- Expected errors and client behavior:
  - API error → show stale data or 0s with subtle error indicator

## Acceptance criteria

- [ ] Gate KPI cards: Lượt xe qua cổng, Biển số đọc thành công, Không đọc được, Độ tin cậy TB — from real API
- [ ] Area KPI cards: Đối tượng trong khu, Vi phạm hôm nay, Xe nâng hoạt động, Zone giám sát — from real API
- [ ] KPI values refresh on tab switch or periodic polling
- [ ] No data → show 0 for all values
- [ ] Mock KPI data removed
- [ ] The flow uses the verified real API; no required production path remains mocked.
- [ ] Required automated integrated evidence is fresh.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `frontend/src/components/GateMonitor.tsx` | KPI card section — replace mock values |
| exact | `frontend/src/components/AreaMonitor.tsx` | KPI card section — replace mock values |
| likely | `frontend/src/api/analytics.ts` | KPI API client |

## Quality baseline

- Baseline reason: none
- Risk mitigated: none
- Required verifier: Manual data comparison

## Validation and evidence

- Required evidence kinds: browser_screenshot
- Planned command/procedure: Compare KPI values on screen with DB aggregate queries
- Pass criteria: KPI numbers match DB data
- Latest evidence:
  - Evidence ID: none
  - Command/procedure: not_run
  - Context: not_run
  - Exit/result: not_run
  - Fresh: no
  - Summary: not_run

## User acceptance and delivery

- Manual acceptance procedure: Open monitoring tabs → verify KPI cards show correct data from DB
- User acceptance result: not_run
- Pull request: none
- Merge evidence: none
- Post-merge smoke: not_run

## Execution record

- Changed files: none
- Decisions/assumptions: none
- Blocker: waiting for backend gate
- Exact next action: wait for matching backend task to reach `backend_verified`
