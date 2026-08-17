# FDN-API-CONTRACT Backend Task — Node.js Express REST Scaffold & Error Contract

## Task identity

- Slice ID: FDN-API-CONTRACT
- Task ID: BE-FDN-API-CONTRACT
- Master plan: `docs/plan/plan.md#foundation-phase`
- Owner: Hữu Thuận
- Branch: `feature/fdn-api-contract`
- Priority: P0
- Size: S
- Status: backend_verified
- Status history:
  - 2026-08-17T16:45:00+07:00 | none → pending | planned | team1-plan
  - 2026-08-17T21:32:00+07:00 | pending → ready | FDN-REPO-SCAFFOLD, FDN-DB-MIGRATION, FDN-PYTHON-DB, FDN-WS-PROXY verified | team1-backend
  - 2026-08-17T21:32:00+07:00 | ready → in_progress | starting Express REST scaffold + error contract implementation | team1-backend
  - 2026-08-17T21:42:00+07:00 | in_progress → backend_verified | all acceptance criteria met; 100% test pass on health check, 404 handler, custom AppError mapping, malformed JSON, and static media serving | team1-backend

## Inputs and dependencies

- Requirement sources: Architecture §6.1, §6.2, §6.3, §8; Database spec `docs/database/database.md`; UI-to-Frontend Handoff §2.1; Master plan Foundation phase
- Consumed fingerprints:
  - `docs/plan/plan.md` rev 1
  - `docs/architecture/architecture.md` SHA `45F59BC5`
  - `docs/database/database.md` SHA `F514CB6D`
  - `docs/design/ui-to-frontend-handoff.md` SHA `F40DB9E7`
- Foundation dependencies:
  - FDN-REPO-SCAFFOLD (backend_verified ✓)
  - FDN-DB-MIGRATION (backend_verified ✓)
  - FDN-PYTHON-DB (backend_verified ✓)
  - FDN-WS-PROXY (backend_verified ✓)
- Slice dependencies: none
- Environment dependencies:
  - `PORT` (default: 3001)
  - `NEON_DATABASE_URL` (for Prisma ORM)
  - `CORS_ORIGIN` (default: `http://localhost:5173`)

## Contract checkpoint

- API/interface surface: REST API boundary at `/api/v1/`:
  - `GET /api/v1/health` -> System health, database connection check, WS statistics, timestamp
  - Static media routes: `/data/crops/*`, `/data/clips/*`
  - Standard JSON response envelopes:
    - Success: `{ success: true, data: T, timestamp: string }`
    - Error: `{ success: false, error: { code: string, message: string, details?: any }, timestamp: string }`
  - Error status codes: 400 Bad Request, 404 Not Found, 409 Conflict, 500 Internal Server Error
  - Prisma error mapping (P2002 -> 409, P2025 -> 404, P2003 -> 400)
- Consumers: All backend vertical slices (`VS-GATE-LIVE`, `VS-AREA-VIOLATION`, `VS-SETTINGS-*`, `VS-QA-CHAT`, `VS-KPI-ANALYTICS`) and `FDN-FRONTEND-API`
- Gate pass condition:
  - Express REST server mounts versioned `/api/v1` router.
  - Prisma client singleton initialized and connects to Neon DB.
  - `GET /api/v1/health` returns HTTP 200 with standard response envelope and database status.
  - Global error handler catches errors and outputs standard error contract.
  - Automated test suite verifies health endpoint, 404 handling, error mapping, and static media routes with exit code 0.

## Acceptance criteria

- [x] Prisma client singleton initialized in `backend/node-api/src/prisma/client.ts`
- [x] Standard response and error contracts implemented (`backend/node-api/src/utils/response.ts`, `backend/node-api/src/utils/errors.ts`)
- [x] Error handler middleware (`backend/node-api/src/middleware/errorHandler.ts`) with Prisma error code mappings (P2002, P2025, P2003)
- [x] 404 Not Found route handler (`backend/node-api/src/middleware/notFoundHandler.ts`)
- [x] REST API router scaffold at `/api/v1` (`backend/node-api/src/routes/index.ts`)
- [x] Health endpoint (`GET /api/v1/health`) checking Neon DB and returning WS stats
- [x] Static media file serving for `/data/crops` and `/data/clips`
- [x] Automated integration test suite (`backend/node-api/src/tests/test_api_contract.ts`) passes 100% with exit code 0

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `backend/node-api/src/prisma/client.ts` | Prisma ORM singleton instance |
| exact | `backend/node-api/src/utils/errors.ts` | Custom error classes (AppError, NotFoundError, ConflictError, ValidationError) |
| exact | `backend/node-api/src/utils/response.ts` | Standard JSON response envelope formatters |
| exact | `backend/node-api/src/middleware/errorHandler.ts` | Global Express error handling middleware |
| exact | `backend/node-api/src/middleware/notFoundHandler.ts` | 404 Not Found middleware |
| exact | `backend/node-api/src/routes/health.ts` | Health check route controller |
| exact | `backend/node-api/src/routes/testError.ts` | Test error trigger routes |
| exact | `backend/node-api/src/routes/index.ts` | Central `/api/v1` router index |
| exact | `backend/node-api/src/index.ts` | Main Express server entry point mounting routes & middleware |
| exact | `backend/node-api/src/tests/test_api_contract.ts` | Automated verification test suite |

## Quality baseline

- Baseline reason: All subsequent vertical slices build upon this REST scaffold. Inconsistent error responses or unhandled Prisma errors will break frontend error boundaries.
- Risk mitigated: Inconsistent API envelopes, unhandled async route rejections crashing Node.js process, missing CORS headers.
- Required verifier: Automated test executing GET /api/v1/health, 404 paths, error triggers, and static routes with exit code 0.

## Validation and evidence

- Required evidence kinds: automated end-to-end API contract test log
- Planned command/procedure:
  - `npm run test:api` (in `backend/node-api`)
- Pass criteria: Health check returns 200 with database connected, error scenarios return proper HTTP codes and standard JSON envelope, exit code 0.
- Latest evidence:
  - Evidence ID: EV-FDN-API-CONTRACT-01
  - Command/procedure: `npm run test:api`
  - Context: local machine, Node.js v22 (Win AMD64), Express 4.21.1, Prisma 5.22.0, Neon PostgreSQL, non-production, 2026-08-17T21:42+07:00
  - Exit/result: exit 0 — 100% tests passed
    - [1/5] Test API Server started on port 3096
    - [2/5] GET /api/v1/health returned 200 OK with database status: "connected" (PostgreSQL Neon), service: "sentriai-node-api", version: "0.1.0", ws stats, and standard envelope
    - [3/5] GET /api/v1/unknown-endpoint-xyz returned 404 with error code ROUTE_NOT_FOUND
    - [4/5] Custom AppError middleware verified: BadRequestError -> 400 (BAD_REQUEST), ConflictError -> 409 (CONFLICT), NotFoundError -> 404 (NOT_FOUND), ValidationError -> 400 (VALIDATION_ERROR), Malformed JSON payload -> 400 (INVALID_JSON)
    - [5/5] Static media file serving /data/crops verified successfully (HTTP 200)
  - Fresh: yes
  - Summary: Node.js Express REST API scaffold, Prisma singleton, versioned prefix `/api/v1`, standard response/error contracts, and static media hosting fully verified.

## Execution record

- Changed files:
  - [NEW] `docs/backend/tasks/FDN-API-CONTRACT.md` (this file)
  - [NEW] `backend/node-api/src/prisma/client.ts`
  - [NEW] `backend/node-api/src/utils/errors.ts`
  - [NEW] `backend/node-api/src/utils/response.ts`
  - [NEW] `backend/node-api/src/middleware/errorHandler.ts`
  - [NEW] `backend/node-api/src/middleware/notFoundHandler.ts`
  - [NEW] `backend/node-api/src/routes/health.ts`
  - [NEW] `backend/node-api/src/routes/testError.ts`
  - [NEW] `backend/node-api/src/routes/index.ts`
  - [MODIFY] `backend/node-api/src/index.ts`
  - [MODIFY] `backend/node-api/package.json`
  - [NEW] `backend/node-api/src/tests/test_api_contract.ts`
- Decisions/assumptions:
  - Standard JSON Envelope: `{ success: true, data: T, timestamp: ISOString }` and `{ success: false, error: { code, message, details }, timestamp: ISOString }`.
  - Database Health Check: Real-time SQL probe (`SELECT 1`) against Neon via `prisma.$queryRaw` during health check.
  - Static Media: Automatically resolves `/data/crops` and `/data/clips` across workspace root and `backend/data/` paths.
- Blocker: none
- Exact next action: FDN-API-CONTRACT complete. Next foundation in critical path: FDN-FRONTEND-API. Unblocks all vertical slices (VS-GATE-LIVE, VS-SETTINGS-*).
