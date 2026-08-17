# VS-SETTINGS-LABEL Backend Task — Cài đặt: nhãn đối tượng + gắn mẫu

## Task identity

- Slice ID: VS-SETTINGS-LABEL
- Task ID: BE-SETTINGS-LABEL
- Master plan: `docs/plan/plan.md#vs-settings-label`
- Owner: Phạm Hưng
- Branch: none
- Priority: P1
- Size: M
- Status: pending
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> pending | planned | team1-plan

## Inputs and dependencies

- Requirement sources: Product M3 (§3, nhãn đối tượng), AC-06, Q2
- Consumed fingerprints:
  - `docs/product/product.md` → `871DEC9C`
  - `docs/database/database.md` → `F514CB6D`
- Foundation dependencies: FDN-DB-MIGRATION, FDN-API-CONTRACT
- Slice dependencies: none
- Environment dependencies: `NEON_DATABASE_URL`

## Contract checkpoint

- API/interface surface:
  - `GET /api/v1/labels` — list all object labels
  - `POST /api/v1/labels` — create label `{ vietnamese_name, base_class }`
  - `PUT /api/v1/labels/:id` — update label
  - `DELETE /api/v1/labels/:id` — delete label (cascades to samples)
  - `GET /api/v1/labels/:id/samples` — list samples for a label
  - `POST /api/v1/samples/batch` — batch create annotation samples `{ samples: [{label_id, image_path, bbox}] }`
  - `POST /api/v1/upload/image` — upload image file, return stored path
- Auth and permission: None
- Request/response/errors:
  - `GET /api/v1/labels` → `200: { data: ObjectLabel[] }`
  - `POST /api/v1/labels` → `201: ObjectLabel` | `409: { error: "Label vietnamese_name already exists" }`
  - `DELETE /api/v1/labels/:id` → `204` (cascades samples)
  - `POST /api/v1/samples/batch` → `201: { created: number }`
  - `POST /api/v1/upload/image` → `201: { path: string }` | `400: { error: "Invalid file type" }`
- Contract source/output: `node-api/openapi/labels.yaml` (planned)
- Gate pass condition: Label CRUD + sample batch + image upload work correctly

## Acceptance criteria

- [ ] `GET /api/v1/labels` returns all object labels with sample count
- [ ] `POST /api/v1/labels` creates label; enforces unique vietnamese_name
- [ ] `DELETE /api/v1/labels/:id` deletes label and cascades to all label_samples
- [ ] `POST /api/v1/samples/batch` creates multiple annotation samples in one request
- [ ] `POST /api/v1/upload/image` accepts image files (JPEG, PNG), stores in `data/labels/`, returns path
- [ ] AC-06: Labels saved via API appear in zone editor dropdown (verified by FE integration)
- [ ] base_class is not unique (multiple Vietnamese names can map to same YOLO class) — DB rule
- [ ] File upload validates: file type (JPEG/PNG), max size 10MB
- [ ] OpenAPI and backend handoff describe only verified behavior for this slice.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| likely | `node-api/src/routes/labels.ts` | Express router for label CRUD |
| likely | `node-api/src/routes/samples.ts` | Batch sample creation |
| likely | `node-api/src/routes/upload.ts` | File upload handler |
| likely | `node-api/prisma/schema.prisma` | Prisma models for object_labels + label_samples (FDN) |

## Quality baseline

- Baseline reason: File upload validation, cascade delete safety, batch insert integrity
- Risk mitigated: Invalid file rejection, proper cascade behavior
- Required verifier: API integration test

## Validation and evidence

- Required evidence kinds: api_test_output, curl_samples
- Planned command/procedure: `cd node-api && npm test -- --grep "labels"` + curl CRUD + image upload test
- Pass criteria: CRUD works, batch creates samples, upload stores files correctly
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
- Exact next action: Wait for FDN-DB-MIGRATION and FDN-API-CONTRACT, then implement label CRUD + upload routes
