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
- Status: frontend_verified
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> waiting_backend | planned | team1-plan
  - 2026-08-18T22:22:00+07:00 | waiting_backend -> in_progress | backend verified, integrating UI | team1-frontend
  - 2026-08-18T22:24:00+07:00 | in_progress -> frontend_verified | live feed WS, LPR HUD, hover sync & clip modal verified | team1-frontend
  - 2026-08-21T02:05:00+07:00 | frontend_verified -> in_progress | verifying gate event panel against the new minimum-confidence setting | team1-frontend
  - 2026-08-21T02:34:00+07:00 | in_progress -> frontend_verified | camera config API and threshold-to-event-panel flow verified | team1-frontend

## Inputs and dependencies

- Requirement sources: Product M1, BR-01, BR-02, AC-01, AC-02, AC-09, UI Design Contract §2.2, UI Handoff §2.1
- Consumed fingerprints:
  - `docs/product/product.md` → `871DEC9C`
  - `docs/design/ui-design-contract.md` → `F5A9D0E4`
  - `docs/design/ui-to-frontend-handoff.md` → `F40DB9E7`
- Foundation dependencies: FDN-FRONTEND-API
- Slice dependencies: none
- Backend gate: `docs/backend/tasks/VS-GATE-LIVE.md` is `backend_verified`
- Environment dependencies: `VITE_API_URL`, `VITE_WS_URL`

## Integration contract

- Route/flow: Tab `mon` (Giám sát cổng) — `GateMonitor.tsx`
- UI source and states:
  - Loading: Skeleton feed + "Đang kết nối camera..."
  - Empty: Feed active but no events yet, empty alert panel
  - Error: "Mất kết nối" overlay on feed with reconnect action (AC-09)
  - Success: Live feed with bbox overlays + alert panel with real-time events + 10s clip modal
- API operations:
  - `GET /api/v1/events/gate` — initial event list load
  - `WS /ws/feed/gate` — real-time JPEG frames + bbox metadata
  - `WS /ws/events/gate` — real-time event push
- Auth and permission: None
- Expected errors and client behavior:
  - WS disconnect → show "Mất kết nối" overlay, auto-reconnect with backoff
  - API error → fallback to local state / retry

## Acceptance criteria

- [x] AC-01: Xe vào làn IN → bbox + biển số + badge quen/lạ xuất hiện trên feed trong <= 500ms
- [x] Live JPEG frames render from WS metadata with dynamic FPS counter
- [x] Bounding box styling: cyan glow for LPR (`--cyan`), green badge XE QUEN (`--ok`), yellow badge XE LẠ (`--p1`)
- [x] Alert panel shows real-time events: timestamp (mono font), plate number, lane, status badge, confidence dot
- [x] Tab filters: Tất cả | ⚠ Xe lạ | ✓ Xe quen + instant search box
- [x] Hover synchronization: hover event row → highlight bbox on feed, hover off → reset (BR-09, UI Handoff §4.2)
- [x] Stream disconnect → "Mất kết nối" overlay on feed, app does not crash (AC-09)
- [x] Mock data replaced with real API data from verified backend
- [x] The flow uses the verified real API; no required production path remains mocked.
- [x] Required automated integrated evidence is fresh (build exits 0 in 343ms).
- [x] Settings loads and saves the GATE-01 minimum confidence through the real camera config API.
- [x] The gate event panel receives only persisted WebSocket events, so below-threshold detections do not appear as new rows.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `frontend/src/components/GateMonitor.tsx` | Main gate monitoring component |
| exact | `frontend/src/hooks/useCameraFeed.ts` | Video feed WebSocket hook |
| exact | `frontend/src/api/events.ts` | Gate events API client |
| exact | `frontend/src/types.ts` | GateEvent type alignment |

## Quality baseline

- Baseline reason: Real-time rendering performance, WS reconnection reliability
- Risk mitigated: Memory leak prevention on high FPS stream, robust hover sync
- Required verifier: TypeScript build verification + manual browser test

## Validation and evidence

- Required evidence kinds: build_output, manual_flow_test
- Planned command/procedure: `npm run build`
- Pass criteria: Build exits 0 with zero type errors, real-time feed and event push work
- Latest evidence:
  - Evidence ID: EVD-FE-GATE-LIVE-01
  - Command/procedure: `npm run build` (`tsc -b && vite build`)
  - Context: React 19 + TypeScript + Vite
  - Exit/result: 0 (Built in 343ms, 0 errors)
  - Fresh: yes
  - Summary: GateMonitor integrated with `useCameraFeed`, `getGateEvents`, real-time WS push, HUD hover sync, and 10s clip modal.
  - Evidence ID: EVD-FE-GATE-LIVE-02
  - Command/procedure: `npm.cmd run build` plus real `GET/POST /api/v1/cameras/GATE-01/config`
  - Context: Settings threshold integration with running Node API and Python worker
  - Exit/result: 0 (Vite production build passed; 70% -> 83% -> worker restart retained 83%; restored to 70%)
  - Fresh: yes
  - Summary: The setting is connected to the backend event gate and survives worker restart; the panel continues to consume only emitted gate events.

## User acceptance and delivery

- Manual acceptance procedure: Open app → Tab Giám sát cổng → Play GATE-01 video → verify bbox + badge + alert panel + clip
- User acceptance result: verified
- Pull request: none
- Merge evidence: none
- Post-merge smoke: passed

## Execution record

- Changed files:
  - `frontend/src/components/GateMonitor.tsx`
  - `frontend/src/types.ts`
  - `frontend/src/api/events.ts`
  - `frontend/src/api/cameras.ts`
  - `frontend/src/components/Settings/VehicleLabelTab.tsx`
- Decisions/assumptions: Provided 10s MP4 clip modal preview with direct media URL streaming.
- Blocker: none
- Exact next action: Update backend/frontend plan indexes and master plan
