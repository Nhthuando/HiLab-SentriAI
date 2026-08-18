# VS-SETTINGS-ZONE Frontend Task — Cài đặt: vẽ zone đa giác

## Task identity

- Slice ID: VS-SETTINGS-ZONE
- Task ID: FE-SETTINGS-ZONE
- Master plan: `docs/plan/plan.md#vs-settings-zone`
- Backend task: `docs/backend/tasks/VS-SETTINGS-ZONE.md`
- Owner: Hữu Thuận
- Branch: feature/vs-settings-zone
- Priority: P1
- Size: M
- Status: blocked
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> waiting_backend | planned | team1-plan
  - 2026-08-18T13:47:20+07:00 | waiting_backend -> blocked | user approved concurrent implementation for manual Area testing; backend HTTP gate and browser verification remain pending | team1-slice

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
  - Evidence ID: EVD-FE-ZONE-01
  - Command/procedure: `npm run build`
  - Context: `frontend`, local TypeScript + Vite production build; no browser or live backend.
  - Exit/result: exit 0; 34 modules transformed and build completed.
  - Fresh: yes, but incomplete for real API/browser criteria.
  - Summary: Covers compile-time integration of the Zone Editor, API client, and snapshot data adapter.

## User acceptance and delivery

- Manual acceptance procedure: Settings → Vẽ Zone → draw polygon → Enter → check monitoring tab
- User acceptance result: not_run
- Pull request: none
- Merge evidence: none
- Post-merge smoke: not_run

## Execution record

- Changed files:
  - `frontend/src/App.tsx`
  - `frontend/src/api/zones.ts`
  - `frontend/src/components/Settings/ZoneEditorTab.tsx`
  - `docs/frontend/frontend.md`
  - `docs/frontend/tasks/VS-SETTINGS-ZONE.md`
- Decisions/assumptions: The editor is intentionally BAI-KIEM-only for current Area testing. Zone color is presentation-only; the persisted contract contains polygon/rule/labels/active state only.
- Blocker: Matching backend task has not reached `backend_verified` because live HTTP/DB and Python snapshot verification is deferred to the user's browser acceptance.
- Exact next action: User manually creates, edits and deletes BAI-KIEM zones, then opens Area after the worker poll interval to verify overlays/rules.
