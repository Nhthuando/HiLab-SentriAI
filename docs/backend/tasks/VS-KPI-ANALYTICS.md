# VS-KPI-ANALYTICS Backend Task — KPI Dashboard: thống kê tổng quan

## Task identity

- Slice ID: VS-KPI-ANALYTICS
- Task ID: BE-KPI-ANALYTICS
- Master plan: `docs/plan/plan.md#vs-kpi-analytics`
- Owner: Hữu Thuận
- Branch: none
- Priority: P2
- Size: S
- Status: pending
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> pending | planned | team1-plan

## Inputs and dependencies

- Requirement sources: Product M1/M2 (KPI display on monitoring tabs), UI Design Contract §2.2, §2.3
- Consumed fingerprints:
  - `docs/product/product.md` → `871DEC9C`
  - `docs/database/database.md` → `F514CB6D`
- Foundation dependencies: FDN-DB-MIGRATION, FDN-API-CONTRACT
- Slice dependencies: VS-GATE-LIVE (gate_events data), VS-AREA-VIOLATION (zone_violations data)
- Environment dependencies: `NEON_DATABASE_URL`

## Contract checkpoint

- API/interface surface:
  - `GET /api/v1/analytics/kpis?date=:date` — KPI stats for a given date (default: today)
- Auth and permission: None
- Request/response/errors:
  - `GET /api/v1/analytics/kpis` → `200: { gate: { total_entries, plates_read, plates_unread, avg_confidence }, area: { objects_in_zones, violations_today, active_forklifts, active_zones } }`
- Contract source/output: `node-api/openapi/analytics.yaml` (planned)
- Gate pass condition: KPI endpoint returns accurate aggregated stats from gate_events and zone_violations

## Acceptance criteria

- [ ] `GET /api/v1/analytics/kpis` returns gate KPIs: total vehicle entries today, successful plate reads (confidence > 0), unreadable plates, average confidence
- [ ] `GET /api/v1/analytics/kpis` returns area KPIs: objects detected in zones, violations today, active forklift/container count (from recent zone_violations), active zone count
- [ ] Empty data → returns 0 for all counts
- [ ] OpenAPI and backend handoff describe only verified behavior for this slice.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| likely | `node-api/src/routes/analytics.ts` | KPI aggregation endpoint |

## Quality baseline

- Baseline reason: none — straightforward aggregation
- Risk mitigated: none
- Required verifier: curl API call + manual data comparison

## Validation and evidence

- Required evidence kinds: api_response_sample
- Planned command/procedure: `curl GET /api/v1/analytics/kpis` + compare with DB counts
- Pass criteria: KPI numbers match manual DB queries
- Latest evidence:
  - Evidence ID: none
  - Command/procedure: not_run
  - Context: not_run
  - Exit/result: not_run
  - Fresh: no
  - Summary: not_run

## Execution record

- Changed files: none
- Decisions/assumptions: none
- Blocker: none
- Exact next action: Wait for VS-GATE-LIVE and VS-AREA-VIOLATION to populate event data, then implement KPI aggregation endpoint
