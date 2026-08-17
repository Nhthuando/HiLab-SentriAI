# VS-SETTINGS-VEHICLE Backend Task — Cài đặt: quản lý danh sách biển số xe

## Task identity

- Slice ID: VS-SETTINGS-VEHICLE
- Task ID: BE-SETTINGS-VEHICLE
- Master plan: `docs/plan/plan.md#vs-settings-vehicle`
- Owner: Phạm Hưng
- Branch: none
- Priority: P1
- Size: S
- Status: pending
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> pending | planned | team1-plan

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
  - `PATCH /api/v1/vehicles/:id` — update vehicle status/note `{ status?, note? }`
  - `DELETE /api/v1/vehicles/:id` — remove vehicle
- Auth and permission: None
- Request/response/errors:
  - `GET /api/v1/vehicles` → `200: { data: RegisteredVehicle[], total: number }`
  - `POST /api/v1/vehicles` → `201: RegisteredVehicle` | `409: { error: "Plate already registered" }`
  - `PATCH /api/v1/vehicles/:id` → `200: RegisteredVehicle` | `404`
  - `DELETE /api/v1/vehicles/:id` → `204` | `404`
- Contract source/output: `node-api/openapi/vehicles.yaml` (planned)
- Gate pass condition: CRUD operations work correctly, plate uniqueness enforced, status toggle works

## Acceptance criteria

- [ ] `GET /api/v1/vehicles` returns paginated list with filtering by status and search by plate
- [ ] `POST /api/v1/vehicles` creates a new vehicle; returns 409 if plate_number already exists
- [ ] `PATCH /api/v1/vehicles/:id` toggles status between KNOWN and STRANGER
- [ ] `DELETE /api/v1/vehicles/:id` removes vehicle from registry
- [ ] Plate number normalized (uppercase, no spaces) before storage
- [ ] Input validation: plate_number required, max 20 chars; status must be KNOWN or STRANGER
- [ ] OpenAPI and backend handoff describe only verified behavior for this slice.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| likely | `node-api/src/routes/vehicles.ts` | Express router for vehicle CRUD |
| likely | `node-api/prisma/schema.prisma` | Prisma model for registered_vehicles (from FDN-DB-MIGRATION) |
| exact | `frontend/src/components/Settings/VehicleLabelTab.tsx` | Frontend (FE task) |

## Quality baseline

- Baseline reason: Input validation on plate_number, uniqueness constraint
- Risk mitigated: Duplicate plate prevention, proper error responses
- Required verifier: API integration test

## Validation and evidence

- Required evidence kinds: api_test_output, curl_samples
- Planned command/procedure: `cd node-api && npm test -- --grep "vehicles"` + curl CRUD operations
- Pass criteria: All CRUD operations return correct status codes and data
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
- Exact next action: Wait for FDN-DB-MIGRATION and FDN-API-CONTRACT, then implement vehicle CRUD routes
