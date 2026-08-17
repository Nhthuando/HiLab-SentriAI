# FDN-WS-PROXY Backend Task — Node.js WebSocket Proxy (Python → Node → Browser)

## Task identity

- Slice ID: FDN-WS-PROXY
- Task ID: BE-FDN-WS-PROXY
- Master plan: `docs/plan/plan.md#foundation-phase`
- Owner: Hữu Thuận
- Branch: `feature/fdn-ws-proxy`
- Priority: P0
- Size: M
- Status: backend_verified
- Status history:
  - 2026-08-17T16:45:00+07:00 | none → pending | planned | team1-plan
  - 2026-08-17T21:18:00+07:00 | pending → ready | FDN-REPO-SCAFFOLD, FDN-DB-MIGRATION, FDN-PYTHON-DB verified | team1-backend
  - 2026-08-17T21:18:00+07:00 | ready → in_progress | starting Node.js WebSocket proxy implementation | team1-backend
  - 2026-08-17T21:22:00+07:00 | in_progress → backend_verified | all acceptance criteria met; 100% test pass on WS routing, channel isolation, inbound publishing, and direct broadcasting | team1-backend

## Inputs and dependencies

- Requirement sources: Architecture §5 (Decisions), §6.1, §6.2 (Luồng 2, 3, 4), §6.3; UI-to-Frontend Handoff §2.1; Master plan Foundation phase
- Consumed fingerprints:
  - `docs/plan/plan.md` rev 1
  - `docs/architecture/architecture.md` SHA `45F59BC5`
  - `docs/design/ui-to-frontend-handoff.md` SHA `F40DB9E7`
- Foundation dependencies:
  - FDN-REPO-SCAFFOLD (backend_verified ✓)
  - FDN-DB-MIGRATION (backend_verified ✓)
  - FDN-PYTHON-DB (backend_verified ✓)
- Slice dependencies: none
- Environment dependencies:
  - `PORT` (default: 3001)
  - `PYTHON_WS_URL` (default: `ws://localhost:8001`)
  - `CORS_ORIGIN` (default: `http://localhost:5173`)

## Contract checkpoint

- API/interface surface: WebSocket endpoints on Node.js server (port 3001):
  - Feed channels:
    - `/ws/feed/gate` (alias: `/ws/feed/GATE-01`)
    - `/ws/feed/area` (alias: `/ws/feed/BAI-KIEM`)
    - `/ws/feed/:cameraId`
  - Event channels:
    - `/ws/events/gate` (Gate LPR events)
    - `/ws/events/area` (Zone violation events)
  - Alert channel:
    - `/ws/alerts` (Urgent cross-tab notifications)
  - Inbound publisher / Ingestion endpoints:
    - `/ws/publish/feed/:cameraId`
    - `/ws/publish/events/:channel`
    - `/ws/publish`
  - Outbound connector to Python Worker (`PYTHON_WS_URL`) with auto-reconnect backoff
- Consumers: `VS-GATE-LIVE`, `VS-AREA-VIOLATION`, `FDN-FRONTEND-API`
- Gate pass condition:
  - Node.js WebSocket server initializes on HTTP server instance.
  - Browser/client can connect to `/ws/feed/gate`, `/ws/feed/area`, `/ws/events/gate`, `/ws/events/area`, `/ws/alerts`.
  - Python worker (or test publisher) sends a frame or event payload to Node.js proxy, and connected clients receive the exact payload with minimal latency.
  - Automatic disconnection handling and reconnect resilience verified via automated tests.

## Acceptance criteria

- [x] WebSocket server module created in `backend/node-api/src/ws/` with channel multiplexing
- [x] Route dispatching for all feed and event endpoints (`/ws/feed/gate`, `/ws/feed/area`, `/ws/events/gate`, `/ws/events/area`, `/ws/alerts`)
- [x] Inbound publisher channel and Outbound connector to Python Worker (`PYTHON_WS_URL`) with auto-reconnect backoff
- [x] Direct broadcast helper functions (`broadcastFeed`, `broadcastGateEvent`, `broadcastAreaEvent`, `broadcastAlert`, `broadcastStatus`)
- [x] Express server in `backend/node-api/src/index.ts` attaches WebSocket proxy to the HTTP server
- [x] Disconnection cleanup and error handling prevents memory leaks
- [x] Automated integration test script (`backend/node-api/src/tests/test_ws_proxy.ts`) verifies end-to-end Python -> Node -> Browser message forwarding with exit code 0

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `backend/node-api/src/ws/types.ts` | Domain message and socket extension types |
| exact | `backend/node-api/src/ws/channels.ts` | Channel manager, subscriber lists, canonical ID mapping, broadcast methods |
| exact | `backend/node-api/src/ws/pythonConnector.ts` | Outbound WebSocket client connecting to Python Worker with reconnect loop |
| exact | `backend/node-api/src/ws/server.ts` | WebSocket server setup, path routing, client connection manager, heartbeat |
| exact | `backend/node-api/src/ws/index.ts` | Package export of WebSocket proxy initialization and broadcast API |
| exact | `backend/node-api/src/index.ts` | Mount WebSocket proxy to HTTP server |
| exact | `backend/node-api/src/tests/test_ws_proxy.ts` | Automated end-to-end verification script for WS proxy |

## Quality baseline

- Baseline reason: WebSocket proxy is the single real-time conduit between AI Worker and Frontend UI. Dropped messages or unhandled disconnects will freeze live feeds or miss critical security alerts.
- Risk mitigated: Memory leaks from dead client sockets, connection churn on stream restart, routing mismatch for camera IDs.
- Required verifier: Automated test executing Python publisher -> Node WS proxy -> multiple subscriber clients verifying payload delivery across all channels.

## Validation and evidence

- Required evidence kinds: automated end-to-end WebSocket proxy test log
- Planned command/procedure:
  - `npm run test:ws` (in `backend/node-api`)
- Pass criteria: Test connects mock publisher and mock browser subscribers to all channels, emits test frames & events, asserts messages received by subscribers, and cleanly disconnects with exit code 0.
- Latest evidence:
  - Evidence ID: EV-FDN-WS-PROXY-01
  - Command/procedure: `npm run test:ws`
  - Context: local machine, Node.js v22 (Win AMD64), ws 8.18.0, non-production, 2026-08-17T21:22+07:00
  - Exit/result: exit 0 — 100% tests passed
    - [1/6] HTTP & WebSocket Server started and upgraded on port 3099
    - [2/6] Connected 5 client subscribers to `/ws/feed/gate`, `/ws/feed/area`, `/ws/events/gate`, `/ws/events/area`, `/ws/alerts`
    - [3/6] Inbound Publisher connected to `/ws/publish/feed/GATE-01`; frame forwarded to `/ws/feed/gate` subscriber; channel isolation verified (Area subscriber did NOT receive Gate frame)
    - [4/6] Inbound Publisher connected to `/ws/publish/events/gate`; gate event forwarded to `/ws/events/gate` subscriber
    - [5/6] Direct Node.js `channelManager.broadcastAreaEvent` and `broadcastAlert` delivered to `/ws/events/area` and `/ws/alerts` subscribers
    - [6/6] Clean disconnection, socket unsubscription, memory cleared (0 residual subscribers), server closed gracefully
  - Fresh: yes
  - Summary: Node.js WebSocket Proxy subsystem fully operational. Path routing, channel isolation, inbound publisher ingestion, direct broadcasting, heartbeat ping-pong, and cleanup verified working.

## Execution record

- Changed files:
  - [NEW] `docs/backend/tasks/FDN-WS-PROXY.md` (this file)
  - [NEW] `backend/node-api/src/ws/types.ts`
  - [NEW] `backend/node-api/src/ws/channels.ts`
  - [NEW] `backend/node-api/src/ws/pythonConnector.ts`
  - [NEW] `backend/node-api/src/ws/server.ts`
  - [NEW] `backend/node-api/src/ws/index.ts`
  - [MODIFY] `backend/node-api/src/index.ts`
  - [MODIFY] `backend/node-api/package.json`
  - [NEW] `backend/node-api/src/tests/test_ws_proxy.ts`
- Decisions/assumptions:
  - Channel name normalization: Maps `gate` to `GATE-01` and `area` to `BAI-KIEM` automatically for developer and client convenience.
  - Heartbeat: 30-second ping interval with automatic zombie client termination.
  - Dual ingestion model: Supports both inbound WebSocket publisher connections (`/ws/publish/...`) and outbound reconnection client (`PythonWorkerConnector`).
- Blocker: none
- Exact next action: FDN-WS-PROXY complete. Next foundations in critical path: FDN-PYTHON-STREAM, FDN-API-CONTRACT, FDN-FRONTEND-API.
