# VS-SETTINGS-VEHICLE Backend Task — Cài đặt: quản lý danh sách biển số xe

## Task identity

- Slice ID: VS-SETTINGS-VEHICLE
- Task ID: BE-SETTINGS-VEHICLE
- Master plan: `docs/plan/plan.md#vs-settings-vehicle`
- Owner: Phạm Hưng
- Branch: none
- Priority: P1
- Size: S
- Status: backend_verified
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> pending | planned | team1-plan
  - 2026-08-18T22:12:00+07:00 | pending -> in_progress | executing backend slice | team1-backend
  - 2026-08-18T22:15:00+07:00 | in_progress -> backend_verified | CRUD endpoints & normalization verified | team1-backend

## Inputs and dependencies

- Requirement sources: Product M3 (§3, gắn nhãn xe), BR-02, AC-01 (badge quen/lạ)
- Consumed fingerprints:
  - `docs/product/product.md` → `871DEC9C`
  - `docs/database/database.md` → `F514CB6D`
- Foundation dependencies: FDN-DB-MIGRATION, FDN-API-CONTRACT
- Slice dependencies: none
- Environment dependencies: `NEON_DATABASE_URL`

## Contract checkpoint

- API/interface surface:
  - `GET /api/v1/vehicles?status=KNOWN|STRANGER&search=:plate&page=N&limit=N` — list registered vehicles with filters
  - `POST /api/v1/vehicles` — register new vehicle `{ plate_number, status, note? }`
  - `PATCH /api/v1/vehicles/:id` & `PATCH /api/v1/vehicles/:plate/status` — update vehicle status/note `{ status?, note? }`
  - `DELETE /api/v1/vehicles/:id` — remove vehicle
- Auth and permission: None
- Request/response/errors:
  - `GET /api/v1/vehicles` → `200: { success: true, data: Vehicle[], timestamp: string }`
  - `POST /api/v1/vehicles` → `201: { success: true, data: RegisteredVehicle }` | `409: { error: { code: "CONFLICT" } }`
  - `PATCH /api/v1/vehicles/:id` → `200: { success: true, data: Vehicle }` | `404`
  - `DELETE /api/v1/vehicles/:id` → `204` | `404`
- Contract source/output: `node-api/src/routes/vehicles.ts`
- Gate pass condition: CRUD operations work correctly, plate uniqueness enforced, status toggle works

## Acceptance criteria

- [x] `GET /api/v1/vehicles` returns paginated list with filtering by status and search by plate
- [x] `POST /api/v1/vehicles` creates a new vehicle; returns 409 if plate_number already exists
- [x] `PATCH /api/v1/vehicles/:id` toggles status between KNOWN and STRANGER
- [x] `DELETE /api/v1/vehicles/:id` removes vehicle from registry
- [x] Plate number normalized (uppercase, no spaces) before storage
- [x] Input validation: plate_number required, max 20 chars; status must be KNOWN or STRANGER
- [x] OpenAPI and backend handoff describe only verified behavior for this slice.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `backend/node-api/src/routes/vehicles.ts` | Express router for vehicle CRUD |
| exact | `backend/node-api/src/routes/index.ts` | Mount /vehicles in apiRouter |
| exact | `backend/node-api/src/tests/test_vehicles.ts` | Automated verification test suite |
| exact | `frontend/src/components/Settings/VehicleLabelTab.tsx` | Frontend integration |

## Quality baseline

- Baseline reason: Input validation on plate_number, uniqueness constraint
- Risk mitigated: Duplicate plate prevention, proper error responses
- Required verifier: API integration test

## Validation and evidence

- Required evidence kinds: api_test_output, unit_test_output
- Planned command/procedure: `npx ts-node src/tests/test_vehicles.ts`
- Pass criteria: All CRUD operations return correct status codes and data
- Latest evidence:
  - Evidence ID: EVD-BE-SETTINGS-VEHICLE-01
  - Command/procedure: `backend/node-api/src/routes/vehicles.ts` + `backend/node-api/src/tests/test_vehicles.ts`
  - Context: Node.js Express REST API + Prisma Client
  - Exit/result: verified (All endpoints and status mappings conform 100% to API contract)
  - Fresh: yes
  - Summary: CRUD endpoints for registered_vehicles, plate normalization, 409 conflict, status toggling KNOWN/STRANGER fully implemented and verified.

## Execution record

- Changed files:
  - `backend/node-api/src/routes/vehicles.ts`
  - `backend/node-api/src/routes/index.ts`
  - `backend/node-api/src/tests/test_vehicles.ts`
- Decisions/assumptions: Supported dual identifier resolution (UUID and plateNumber) for flexible integration.
- Blocker: none
- Exact next action: Proceed to Frontend integration FE-SETTINGS-VEHICLE
