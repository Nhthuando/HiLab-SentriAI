# VS-SETTINGS-ZONE Backend Task — Cài đặt: vẽ zone đa giác + zone rules

## Task identity

- Slice ID: VS-SETTINGS-ZONE
- Task ID: BE-SETTINGS-ZONE
- Master plan: `docs/plan/plan.md#vs-settings-zone`
- Owner: Hữu Thuận
- Branch: feature/vs-settings-zone
- Priority: P1
- Size: M
- Status: blocked
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> pending | planned | team1-plan
  - 2026-08-18T13:47:20+07:00 | pending -> ready | user explicitly reassigned the slice; FDN-DB-MIGRATION and FDN-API-CONTRACT are already verified | team1-slice
  - 2026-08-18T13:47:20+07:00 | ready -> in_progress | begin BAI-KIEM-only zone CRUD and snapshot implementation | team1-backend
  - 2026-08-18T13:47:20+07:00 | in_progress -> blocked | implementation and basic local checks complete; HTTP/DB integration verification is deferred to user manual acceptance | team1-backend

## Inputs and dependencies

- Requirement sources: Product M3 (§3, vẽ zone), M2, BR-07, AC-05
- Consumed fingerprints:
  - `docs/product/product.md` → `871DEC9C`
  - `docs/database/database.md` → `F514CB6D`
- Foundation dependencies: FDN-DB-MIGRATION, FDN-API-CONTRACT
- Slice dependencies: none
- Environment dependencies: `NEON_DATABASE_URL`

## Contract checkpoint

- API/interface surface:
  - `GET /api/v1/zones?camera_id=:camId` — list zones for a camera
  - `POST /api/v1/zones` — create zone `{ camera_id, name, polygon_points, rule_type, target_labels, is_active? }`
  - `PUT /api/v1/zones/:id` — update zone (polygon, rules, name, active status)
  - `DELETE /api/v1/zones/:id` — delete zone and its linked violations (CASCADE; approved for Area test cleanup)
  - `GET /api/v1/cameras/:id/snapshot` — get current frame snapshot from Python Worker for zone editor canvas background
- Auth and permission: None
- Request/response/errors:
  - `GET /api/v1/zones` → `200: { data: Zone[] }`
  - `POST /api/v1/zones` → `201: Zone` | `409: { error: "Zone name already exists for this camera" }`
  - `PUT /api/v1/zones/:id` → `200: Zone` | `404`
  - `DELETE /api/v1/zones/:id` → `204` | `404`; linked `zone_violations` are deleted in the same database operation
  - `GET /api/v1/cameras/:id/snapshot` → `200: { image: base64_jpeg }` | `503: { error: "Camera offline" }`
- Contract source/output: `node-api/openapi/zones.yaml` (planned)
- Gate pass condition: Zone CRUD works, polygon_points stored as JSONB, camera snapshot available for zone editor

## Acceptance criteria

- [ ] `GET /api/v1/zones?camera_id=BAI-KIEM` returns all zones for the camera
- [ ] `POST /api/v1/zones` creates zone with normalized polygon_points JSONB, enforces unique (camera_id, name)
- [ ] `PUT /api/v1/zones/:id` updates polygon, rules, name, or active status
- [ ] `DELETE /api/v1/zones/:id` returns 204 and cascades deletion to linked zone_violations
- [ ] Zone update triggers notification to Python Worker (via internal WS or DB poll) for real-time effect (BR-07)
- [ ] `GET /api/v1/cameras/:id/snapshot` returns current frame from Python Worker as base64 JPEG
- [ ] Polygon data validation: at least 3 points, coordinates between 0.0 and 1.0
- [ ] rule_type validated: only PROHIBIT_SPECIFIED or ALLOW_SPECIFIED
- [ ] target_labels is JSONB array of strings
- [ ] OpenAPI and backend handoff describe only verified behavior for this slice.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| likely | `node-api/src/routes/zones.ts` | Express router for zone CRUD |
| likely | `node-api/src/routes/cameras.ts` | Snapshot endpoint |
| likely | `node-api/prisma/schema.prisma` | Prisma model for zones (from FDN-DB-MIGRATION) |

## Quality baseline

- Baseline reason: BR-07 real-time update, polygon data integrity, user-approved CASCADE delete for Area test cleanup
- Risk mitigated: Invalid polygon rejection, proper cascade behavior
- Required verifier: API integration test

## Validation and evidence

- Required evidence kinds: api_test_output, curl_samples
- Planned command/procedure: `cd node-api && npm test -- --grep "zones"` + curl CRUD + verify Python Worker picks up new zone
- Pass criteria: CRUD works, polygon stored correctly, deleting a zone cascades to its linked violations
- Latest evidence:
  - Evidence ID: EVD-BE-ZONE-01
  - Command/procedure: `npm run typecheck` and `npx ts-node src/tests/test_zone_validation.ts`
  - Context: `backend/node-api`, local source-only validation; no service or database operation.
  - Exit/result: exit 0; TypeScript check passed and zone validation checks passed.
  - Fresh: yes, but incomplete for the HTTP/DB integration criteria.
  - Summary: Covers BAI-KIEM-only camera scope, polygon bounds/minimum count, rule values, target-label normalization, and empty update rejection.

## Execution record

- Changed files:
  - `backend/node-api/src/routes/zones.ts`
  - `backend/node-api/src/routes/cameras.ts`
  - `backend/node-api/src/routes/index.ts`
  - `backend/node-api/openapi/zones.yaml`
  - `backend/node-api/src/tests/test_zone_validation.ts`
  - `backend/.env.example`
  - `docs/backend/backend.md`
  - `docs/backend/tasks/VS-SETTINGS-ZONE.md`
- Decisions/assumptions: User approved a BAI-KIEM-only editor for Area testing and then approved cascading deletion of linked violations so test zones can be removed cleanly. Relative `PYTHON_WORKER_HTTP_URL` defaults to `http://localhost:8001`.
- Blocker: Required live HTTP/DB verification (CRUD, duplicate name, delete cascade, and Python snapshot) was intentionally deferred for the user's manual browser test.
- Exact next action: User starts the local Python worker, Node API, and frontend, then verifies BAI-KIEM zone CRUD and Area overlay refresh. Record results before changing to `backend_verified`.
