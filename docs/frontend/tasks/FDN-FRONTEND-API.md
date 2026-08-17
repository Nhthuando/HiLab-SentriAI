# FDN-FRONTEND-API Frontend Task — API Client & WebSocket Custom Hooks

## Task identity

- Slice ID: FDN-FRONTEND-API
- Task ID: FE-FDN-FRONTEND-API
- Master plan: `docs/plan/plan.md#foundation-phase`
- Owner: Hữu Thuận
- Branch: `feature/fdn-frontend-api`
- Priority: P0
- Size: S
- Status: frontend_verified
- Status history:
  - 2026-08-17T16:45:00+07:00 | none → pending | planned | team1-plan
  - 2026-08-17T21:45:00+07:00 | pending → ready | FDN-DB-MIGRATION, FDN-WS-PROXY, FDN-API-CONTRACT verified | team1-frontend
  - 2026-08-17T21:45:00+07:00 | ready → in_progress | starting API client and WebSocket custom hooks implementation | team1-frontend
  - 2026-08-17T21:48:00+07:00 | in_progress → frontend_verified | all acceptance criteria met; 100% build & typecheck pass with clean API services and custom hooks | team1-frontend

## Inputs and dependencies

- Requirement sources: Architecture §6.1, §6.2 (Luồng 2, 5), §6.3; UI-to-Frontend Handoff §2.1; Master plan Foundation phase
- Consumed fingerprints:
  - `docs/plan/plan.md` rev 1
  - `docs/architecture/architecture.md` SHA `45F59BC5`
  - `docs/design/ui-to-frontend-handoff.md` SHA `F40DB9E7`
- Foundation dependencies:
  - FDN-REPO-SCAFFOLD (backend_verified ✓)
  - FDN-DB-MIGRATION (backend_verified ✓)
  - FDN-WS-PROXY (backend_verified ✓)
  - FDN-API-CONTRACT (backend_verified ✓)
- Slice dependencies: none
- Environment dependencies:
  - `VITE_API_URL` (default: `http://localhost:3001/api/v1`)
  - `VITE_WS_URL` (default: `ws://localhost:3001`)

## Contract checkpoint

- API/interface surface:
  - REST client in `frontend/src/api/`:
    - Base client wrapper `apiClient` with automatic standard envelope unwrapping
    - Domain API modules: `health`, `vehicles`, `zones`, `labels`, `events`, `qa`, `analytics`
  - Custom React hooks in `frontend/src/hooks/`:
    - `useWebSocket`: generic WebSocket connection manager with reconnect backoff and typing
    - `useCameraFeed`: specialized camera feed subscriber hook (frame image base64, detections, fps, status)
    - `useBroadcastChannel`: cross-tab notification hook via BroadcastChannel API (BR-08)
- Consumers: All frontend vertical slices (`VS-GATE-LIVE`, `VS-AREA-VIOLATION`, `VS-SETTINGS-*`, `VS-QA-CHAT`, `VS-KPI-ANALYTICS`)
- Gate pass condition:
  - `frontend/src/api/` modules compile with clean TypeScript types matching backend contracts.
  - `useWebSocket` and `useBroadcastChannel` hooks manage lifecycles, reconnects, and message dispatching cleanly.
  - Frontend typecheck (`tsc -b`) and build pass with 0 errors.

## Acceptance criteria

- [x] Base API client with typed request methods (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`) and error unwrapping
- [x] Domain API service functions created for all 7 submodules (health, vehicles, zones, labels, events, qa, analytics)
- [x] `useWebSocket` custom hook implemented with auto-reconnect, connection state, and cleanup
- [x] `useCameraFeed` custom hook implemented for subscribing to `/ws/feed/gate` and `/ws/feed/area`
- [x] `useBroadcastChannel` custom hook implemented for cross-tab alert synchronization (BR-08)
- [x] Package exports provided in `frontend/src/api/index.ts` and `frontend/src/hooks/index.ts`
- [x] Frontend build and typecheck pass 100% (`npm run build` exits 0)

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `frontend/src/api/client.ts` | Base HTTP client with envelope unwrapping and error throwing |
| exact | `frontend/src/api/health.ts` | Health check API caller |
| exact | `frontend/src/api/vehicles.ts` | Registered vehicle API callers |
| exact | `frontend/src/api/zones.ts` | Zone CRUD API callers |
| exact | `frontend/src/api/labels.ts` | Object labels and annotation samples API callers |
| exact | `frontend/src/api/events.ts` | Gate and Area events API callers |
| exact | `frontend/src/api/qa.ts` | AI QA chat API caller |
| exact | `frontend/src/api/analytics.ts` | KPI Analytics API caller |
| exact | `frontend/src/api/index.ts` | Central API package export |
| exact | `frontend/src/hooks/useWebSocket.ts` | Generic WebSocket hook with reconnect |
| exact | `frontend/src/hooks/useCameraFeed.ts` | Dedicated live camera feed hook |
| exact | `frontend/src/hooks/useBroadcastChannel.ts` | Cross-tab broadcast channel hook |
| exact | `frontend/src/hooks/index.ts` | Central hooks package export |

## Quality baseline

- Baseline reason: All UI components depend on these hooks and API functions for live data and CRUD operations.
- Risk mitigated: Unhandled WebSocket memory leaks, broken reconnect loops, inconsistent API type definitions.
- Required verifier: TypeScript typecheck and build pass with 0 errors.

## Validation and evidence

- Required evidence kinds: build log, typecheck log
- Planned command/procedure:
  - `npm run build` (in `frontend/`)
- Pass criteria: TypeScript typecheck `tsc -b` and Vite build complete with exit code 0.
- Latest evidence:
  - Evidence ID: EV-FDN-FRONTEND-API-01
  - Command/procedure: `npm run build`
  - Context: local machine, Node.js v22, React 19.2.8, Vite 8.2.1, non-production, 2026-08-17T21:47+07:00
  - Exit/result: exit 0 — 100% build pass in 322ms
    - `tsc -b` completed with 0 errors
    - `dist/index.html` (1.02 kB), `dist/assets/index.css` (6.20 kB), `dist/assets/index.js` (318.76 kB)
    - All 7 API service modules (`health`, `vehicles`, `zones`, `labels`, `events`, `qa`, `analytics`) and 3 custom hooks (`useWebSocket`, `useCameraFeed`, `useBroadcastChannel`) verified type-safe
  - Fresh: yes
  - Summary: Frontend API integration foundation is fully established and ready for vertical slice feature integration.

## Execution record

- Changed files:
  - [NEW] `docs/frontend/tasks/FDN-FRONTEND-API.md` (this file)
  - [NEW] `frontend/src/api/client.ts`
  - [NEW] `frontend/src/api/health.ts`
  - [NEW] `frontend/src/api/vehicles.ts`
  - [NEW] `frontend/src/api/zones.ts`
  - [NEW] `frontend/src/api/labels.ts`
  - [NEW] `frontend/src/api/events.ts`
  - [NEW] `frontend/src/api/qa.ts`
  - [NEW] `frontend/src/api/analytics.ts`
  - [NEW] `frontend/src/api/index.ts`
  - [NEW] `frontend/src/hooks/useWebSocket.ts`
  - [NEW] `frontend/src/hooks/useCameraFeed.ts`
  - [NEW] `frontend/src/hooks/useBroadcastChannel.ts`
  - [NEW] `frontend/src/hooks/index.ts`
  - [NEW] `frontend/.env.example`
- Decisions/assumptions:
  - Base URL fallback: Uses `import.meta.env.VITE_API_URL || 'http://localhost:3001/api/v1'`.
  - WS URL fallback: Uses `import.meta.env.VITE_WS_URL || 'ws://localhost:3001'`.
  - Offline label: Displays "Mất kết nối" per AC-09 Vietnamese error contract when camera stream drops.
- Blocker: none
- Exact next action: All Foundation tasks (FDN-*) are completed and verified! Next step is starting Vertical Slices (VS-GATE-LIVE, VS-SETTINGS-*, VS-AREA-VIOLATION).
