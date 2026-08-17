# VS-GATE-LIVE Frontend Task — Giám sát cổng real-time: LPR + live feed + alert

## Task identity

- Slice ID: VS-GATE-LIVE
- Task ID: FE-GATE-LIVE
- Master plan: `docs/plan/plan.md#vs-gate-live`
- Backend task: `docs/backend/tasks/VS-GATE-LIVE.md`
- Owner: Phạm Hưng
- Branch: none
- Priority: P0
- Size: L
- Status: waiting_backend
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> waiting_backend | planned | team1-plan

## Inputs and dependencies

- Requirement sources: Product M1, BR-01, BR-02, AC-01, AC-02, AC-09, UI Design Contract §2.2, UI Handoff §2.1
- Consumed fingerprints:
  - `docs/product/product.md` → `871DEC9C`
  - `docs/design/ui-design-contract.md` → `F5A9D0E4`
  - `docs/design/ui-to-frontend-handoff.md` → `F40DB9E7`
- Foundation dependencies: FDN-FRONTEND-API
- Slice dependencies: none
- Backend gate: matching backend task is `backend_verified` with current OpenAPI/handoff evidence
- Environment dependencies: `VITE_API_URL` (Node.js API base), `VITE_WS_URL` (WebSocket base)

## Integration contract

- Route/flow: Tab `mon` (Giám sát cổng) — `GateMonitor.tsx`
- UI source and states:
  - Loading: Skeleton feed + "Đang kết nối camera..."
  - Empty: Feed active but no events yet, empty alert panel
  - Error: "Mất kết nối" overlay on feed (AC-09), error toast
  - Success: Live feed with bbox overlays + alert panel with real-time events
- API operations:
  - `GET /api/v1/events/gate` — initial event list load
  - `WS /ws/feed/gate` — real-time JPEG frames + bbox metadata
  - `WS /ws/events/gate` — real-time event push
- Auth and permission: None
- Expected errors and client behavior:
  - WS disconnect → show "Mất kết nối" overlay, auto-reconnect with backoff
  - API 500 → show error toast, retry button

## Acceptance criteria

- [ ] AC-01: Xe vào làn IN → bbox + biển số + badge quen/lạ xuất hiện trên feed trong <= 500ms
- [ ] Live JPEG frames render on Canvas element with bbox overlay from WS metadata
- [ ] Bounding box styling: cyan glow for LPR (Design Contract §1.2 `--cyan`), green badge XE QUEN (`--ok`), yellow badge XE LẠ (`--p1`)
- [ ] Alert panel shows real-time events: timestamp (mono font), plate number, lane, status badge, confidence dot
- [ ] Tab filters: Tất cả | ⚠ Xe lạ | ✓ Xe quen + instant search box
- [ ] Hover synchronization: hover event row → highlight bbox on feed, hover off → reset (BR-09, UI Handoff §4.2)
- [ ] Stream disconnect → "Mất kết nối" overlay on feed, app does not crash (AC-09)
- [ ] Mock data replaced with real API data from verified backend
- [ ] The flow uses the verified real API; no required production path remains mocked.
- [ ] Required automated integrated evidence is fresh.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `frontend/src/components/GateMonitor.tsx` | Main gate monitoring component — replace mock data with real API/WS |
| likely | `frontend/src/hooks/useWebSocket.ts` | WebSocket connection hook (from FDN-FRONTEND-API) |
| likely | `frontend/src/api/events.ts` | Gate events API client |
| exact | `frontend/src/types.ts` | GateEvent type — align with backend response schema |
| exact | `frontend/src/mockData.ts` | Remove gate mock data |

## Quality baseline

- Baseline reason: Real-time rendering performance, WS reconnection reliability
- Risk mitigated: Canvas rendering at >= 5 FPS without memory leak
- Required verifier: Manual browser test with live backend

## Validation and evidence

- Required evidence kinds: browser_screenshot, manual_flow_test
- Planned command/procedure: Open http://localhost:5173/ → Tab "Giám sát cổng" → verify live feed + events + hover sync
- Pass criteria: Live feed renders, events appear in alert panel, hover sync works, disconnect handled
- Latest evidence:
  - Evidence ID: none
  - Command/procedure: not_run
  - Context: not_run
  - Exit/result: not_run
  - Fresh: no
  - Summary: not_run

## User acceptance and delivery

- Manual acceptance procedure: Open app → Tab Giám sát cổng → Play GATE-01 video → verify bbox + badge + alert panel + clip
- User acceptance result: not_run
- Pull request: none
- Merge evidence: none
- Post-merge smoke: not_run

## Execution record

- Changed files: none
- Decisions/assumptions: none
- Blocker: waiting for backend gate
- Exact next action: wait for matching backend task to reach `backend_verified`
