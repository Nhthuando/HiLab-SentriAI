# VS-SETTINGS-ZONE Backend Task — Cài đặt: vẽ zone đa giác + zone rules

## Task identity

- Slice ID: VS-SETTINGS-ZONE
- Task ID: BE-SETTINGS-ZONE
- Master plan: `docs/plan/plan.md#vs-settings-zone`
- Owner: Phạm Hưng
- Branch: none
- Priority: P1
- Size: M
- Status: pending
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> pending | planned | team1-plan

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
  - `DELETE /api/v1/zones/:id` — delete zone (RESTRICT if violations exist)
  - `GET /api/v1/cameras/:id/snapshot` — get current frame snapshot from Python Worker for zone editor canvas background
- Auth and permission: None
- Request/response/errors:
  - `GET /api/v1/zones` → `200: { data: Zone[] }`
  - `POST /api/v1/zones` → `201: Zone` | `409: { error: "Zone name already exists for this camera" }`
  - `PUT /api/v1/zones/:id` → `200: Zone` | `404`
  - `DELETE /api/v1/zones/:id` → `204` | `409: { error: "Cannot delete zone with existing violations" }` | `404`
  - `GET /api/v1/cameras/:id/snapshot` → `200: { image: base64_jpeg }` | `503: { error: "Camera offline" }`
- Contract source/output: `node-api/openapi/zones.yaml` (planned)
- Gate pass condition: Zone CRUD works, polygon_points stored as JSONB, camera snapshot available for zone editor

## Acceptance criteria

- [ ] `GET /api/v1/zones?camera_id=BAI-KIEM` returns all zones for the camera
- [ ] `POST /api/v1/zones` creates zone with normalized polygon_points JSONB, enforces unique (camera_id, name)
- [ ] `PUT /api/v1/zones/:id` updates polygon, rules, name, or active status
- [ ] `DELETE /api/v1/zones/:id` returns 409 if zone has zone_violations (ON DELETE RESTRICT)
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

- Baseline reason: BR-07 real-time update, polygon data integrity, RESTRICT on delete
- Risk mitigated: Invalid polygon rejection, proper cascade behavior
- Required verifier: API integration test

## Validation and evidence

- Required evidence kinds: api_test_output, curl_samples
- Planned command/procedure: `cd node-api && npm test -- --grep "zones"` + curl CRUD + verify Python Worker picks up new zone
- Pass criteria: CRUD works, polygon stored correctly, delete with violations returns 409
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
- Exact next action: Wait for FDN-DB-MIGRATION and FDN-API-CONTRACT, then implement zone CRUD routes
