# VS-SETTINGS-ZONE Frontend Task — Cài đặt: vẽ zone đa giác

## Task identity

- Slice ID: VS-SETTINGS-ZONE
- Task ID: FE-SETTINGS-ZONE
- Master plan: `docs/plan/plan.md#vs-settings-zone`
- Backend task: `docs/backend/tasks/VS-SETTINGS-ZONE.md`
- Owner: Phạm Hưng
- Branch: none
- Priority: P1
- Size: M
- Status: waiting_backend
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> waiting_backend | planned | team1-plan

## Inputs and dependencies

- Requirement sources: Product M3 (vẽ zone), BR-07, AC-05, UI Design Contract §2.4 item 2, UI Handoff §4.1
- Consumed fingerprints:
  - `docs/design/ui-design-contract.md` → `F5A9D0E4`
  - `docs/design/ui-to-frontend-handoff.md` → `F40DB9E7`
- Foundation dependencies: FDN-FRONTEND-API
- Slice dependencies: none
- Backend gate: matching backend task is `backend_verified` with current OpenAPI/handoff evidence
- Environment dependencies: `VITE_API_URL`

## Integration contract

- Route/flow: Tab `set` → Sub-tab `zone` (Vẽ Zone) — `ZoneEditorTab.tsx`
- UI source and states:
  - Loading: Canvas loading with skeleton panel
  - Empty: Camera snapshot background, no zones, "Vẽ zone mới" prompt
  - Error: Error toast if API/snapshot fails
  - Success: Camera snapshot with zone polygons + zone management panel
- API operations:
  - `GET /api/v1/zones?camera_id=:camId` — load zones for selected camera
  - `POST /api/v1/zones` — create new zone
  - `PUT /api/v1/zones/:id` — update zone polygon/rules/name
  - `DELETE /api/v1/zones/:id` — delete zone
  - `GET /api/v1/cameras/:id/snapshot` — get camera frame for canvas background
- Auth and permission: None
- Expected errors and client behavior:
  - 409 duplicate zone name → toast
  - 409 delete with violations → toast "Không thể xóa zone đang có vi phạm"
  - Camera offline → fallback to static image

## Acceptance criteria

- [ ] AC-05: Vẽ zone mới → zone lưu DB → active ngay trên màn hình giám sát (via Python Worker poll)
- [ ] Camera selector: Bãi Kiểm / Cổng vào → loads zones for selected camera
- [ ] Canvas background: real camera snapshot from API (fallback to static image if offline)
- [ ] Draw mode: click to add vertices → Enter to save zone (>= 3 vertices)
- [ ] Edit mode: click to select zone → drag body/vertices, keyboard shortcuts (Ctrl+Z, Ctrl+Y, Delete)
- [ ] Zone management panel: search, color picker, rename, auto-scroll to selected zone
- [ ] Zone data persisted via real API; reload preserves zones
- [ ] Mock data completely removed
- [ ] The flow uses the verified real API; no required production path remains mocked.
- [ ] Required automated integrated evidence is fresh.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `frontend/src/components/Settings/ZoneEditorTab.tsx` | Replace mock with real API calls |
| likely | `frontend/src/api/zones.ts` | Zone API client |
| likely | `frontend/src/api/cameras.ts` | Camera snapshot API client |

## Quality baseline

- Baseline reason: BR-07 real-time zone update verification
- Risk mitigated: Zone data integrity between canvas and API
- Required verifier: Manual draw + verify on monitoring tab

## Validation and evidence

- Required evidence kinds: browser_screenshot, manual_flow_test
- Planned command/procedure: Draw zone → save → switch to monitoring tab → verify zone overlay appears
- Pass criteria: Zone CRUD works, zones persist, monitoring tab shows new zone
- Latest evidence:
  - Evidence ID: none
  - Command/procedure: not_run
  - Context: not_run
  - Exit/result: not_run
  - Fresh: no
  - Summary: not_run

## User acceptance and delivery

- Manual acceptance procedure: Settings → Vẽ Zone → draw polygon → Enter → check monitoring tab
- User acceptance result: not_run
- Pull request: none
- Merge evidence: none
- Post-merge smoke: not_run

## Execution record

- Changed files: none
- Decisions/assumptions: none
- Blocker: waiting for backend gate
- Exact next action: wait for matching backend task to reach `backend_verified`
