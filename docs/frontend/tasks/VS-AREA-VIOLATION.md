# VS-AREA-VIOLATION Frontend Task — Giám sát khu vực: detect + violation + floating alert

## Task identity

- Slice ID: VS-AREA-VIOLATION
- Task ID: FE-AREA-VIOLATION
- Master plan: `docs/plan/plan.md#vs-area-violation`
- Backend task: `docs/backend/tasks/VS-AREA-VIOLATION.md`
- Owner: Hữu Thuận
- Branch: none
- Priority: P0
- Size: L
- Status: waiting_backend
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> waiting_backend | planned | team1-plan

## Inputs and dependencies

- Requirement sources: Product M2, BR-03, BR-04, BR-06, BR-08, AC-03, AC-04, AC-08, UI Design Contract §2.3, §2.6, UI Handoff §2.1
- Consumed fingerprints:
  - `docs/product/product.md` → `871DEC9C`
  - `docs/design/ui-design-contract.md` → `F5A9D0E4`
  - `docs/design/ui-to-frontend-handoff.md` → `F40DB9E7`
- Foundation dependencies: FDN-FRONTEND-API
- Slice dependencies: VS-GATE-LIVE (frontend WS infrastructure)
- Backend gate: matching backend task is `backend_verified` with current OpenAPI/handoff evidence
- Environment dependencies: `VITE_API_URL`, `VITE_WS_URL`

## Integration contract

- Route/flow: Tab `area` (Giám sát khu vực) — `AreaMonitor.tsx` + `FloatingAlert.tsx`
- UI source and states:
  - Loading: Skeleton feed + "Đang kết nối camera..."
  - Empty: Feed active, no violations, zones displayed as polygon overlays
  - Error: "Mất kết nối" overlay
  - Success: Live feed with zone polygons + object bboxes + alert panel
  - Floating alert: Red glass toast in bottom-right when user is on different tab (BR-08)
- API operations:
  - `GET /api/v1/events/area` — initial violation list
  - `WS /ws/feed/area` — real-time JPEG frames + zone overlays + object bboxes
  - `WS /ws/events/area` — real-time violation events
  - `WS /ws/alerts` — floating alert notifications
- Auth and permission: None
- Expected errors and client behavior:
  - WS disconnect → "Mất kết nối" overlay, auto-reconnect
  - Zone with no violations → empty event panel with zone overlay still visible

## Acceptance criteria

- [ ] AC-03: Đối tượng bị cấm vào zone → bbox đỏ + alert panel item + floating mini-alert (khi ở tab khác)
- [ ] Live JPEG frames render with zone polygon overlays (SVG on Canvas)
- [ ] Object bboxes colored: green `--ok` for allowed, red `--p0` for violation (Design Contract §2.3)
- [ ] Zone rule chips displayed: ✓ for allowed types, ✕ for prohibited types
- [ ] Alert panel with tab filters: Tất cả | ⚠ Vi phạm | ✓ Được phép + search
- [ ] Hover synchronization: hover event → highlight object/zone on feed (UI Handoff §4.2)
- [ ] AC-08: Unknown object → "CHƯA XÁC ĐỊNH" label displayed, zone rule still applied
- [ ] Floating mini-alert (FloatingAlert.tsx): appears bottom-right when document.hidden=true and violation occurs via BroadcastChannel (BR-08)
- [ ] Floating alert has "Xem camera ngay →" button → navigates to area tab (Design Contract §2.6)
- [ ] When user returns to area tab, floating alert dismissed (BR-08)
- [ ] Mock data replaced with real API data
- [ ] The flow uses the verified real API; no required production path remains mocked.
- [ ] Required automated integrated evidence is fresh.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `frontend/src/components/AreaMonitor.tsx` | Main area monitoring — replace mock with real API/WS |
| exact | `frontend/src/components/FloatingAlert.tsx` | Floating alert — connect to real WS alerts |
| likely | `frontend/src/hooks/useBroadcastChannel.ts` | BroadcastChannel hook for cross-tab alerts (FDN) |
| likely | `frontend/src/api/events.ts` | Area events API client |
| exact | `frontend/src/types.ts` | AreaEvent type — align with backend schema |
| exact | `frontend/src/App.tsx` | Floating alert state management — connect to real WS |

## Quality baseline

- Baseline reason: Cross-tab communication reliability, zone overlay rendering accuracy
- Risk mitigated: BroadcastChannel API works within same origin
- Required verifier: Manual browser test with 2 tabs open

## Validation and evidence

- Required evidence kinds: browser_screenshot, manual_flow_test
- Planned command/procedure: Open 2 browser tabs → Tab 1 on Settings, Tab 2 on Area → trigger violation → verify floating alert on Tab 1
- Pass criteria: Live feed with zones, violations appear, floating alert works cross-tab
- Latest evidence:
  - Evidence ID: none
  - Command/procedure: not_run
  - Context: not_run
  - Exit/result: not_run
  - Fresh: no
  - Summary: not_run

## User acceptance and delivery

- Manual acceptance procedure: Open app → Tab Giám sát khu vực → Play BAI-KIEM video → verify zone overlay + violation + floating alert on other tab
- User acceptance result: not_run
- Pull request: none
- Merge evidence: none
- Post-merge smoke: not_run

## Execution record

- Changed files: none
- Decisions/assumptions: none
- Blocker: waiting for backend gate
- Exact next action: wait for matching backend task to reach `backend_verified`
