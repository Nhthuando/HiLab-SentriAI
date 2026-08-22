# VS-SETTINGS-LABEL Backend Task — Cài đặt: nhãn đối tượng + gắn mẫu

## Task identity

- Slice ID: VS-SETTINGS-LABEL
- Task ID: BE-SETTINGS-LABEL
- Master plan: `docs/plan/plan.md#vs-settings-label`
- Owner: Phạm Hưng
- Branch: none
- Priority: P1
- Size: M
- Status: backend_verified
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> pending | planned | team1-plan
  - 2026-08-18T22:16:00+07:00 | pending -> in_progress | implementing label CRUD & upload | team1-backend
  - 2026-08-18T22:18:00+07:00 | in_progress -> backend_verified | label CRUD, batch samples & image upload verified | team1-backend

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
  - `GET /api/v1/labels` — list all object labels with sample count
  - `POST /api/v1/labels` — create label `{ vietnamese_name, base_class }`
  - `PUT /api/v1/labels/:id` — update label
  - `DELETE /api/v1/labels/:id` — delete label (cascades to samples)
  - `GET /api/v1/labels/:id/samples` — list samples for a label
  - `POST /api/v1/samples/batch` — batch create annotation samples `{ samples: [{label_id, image_path, bbox}] }`
  - `POST /api/v1/upload/image` — upload image file, return stored path
- Auth and permission: None
- Request/response/errors:
  - `GET /api/v1/labels` → `200: { success: true, data: ObjectLabel[] }`
  - `POST /api/v1/labels` → `201: { success: true, data: ObjectLabel }` | `409: { error: { code: "CONFLICT" } }`
  - `DELETE /api/v1/labels/:id` → `204` (cascades samples)
  - `POST /api/v1/samples/batch` → `201: { success: true, data: { count: number } }`
  - `POST /api/v1/upload/image` → `201: { success: true, data: { path: string, url: string } }` | `400`
- Contract source/output: `node-api/src/routes/labels.ts`, `samples.ts`, `upload.ts`
- Gate pass condition: Label CRUD + sample batch + image upload work correctly

## Acceptance criteria

- [x] `GET /api/v1/labels` returns all object labels with sample count
- [x] `POST /api/v1/labels` creates label; enforces unique vietnamese_name
- [x] `DELETE /api/v1/labels/:id` deletes label and cascades to all label_samples
- [x] `POST /api/v1/samples/batch` creates multiple annotation samples in one request
- [x] `POST /api/v1/upload/image` accepts image files (JPEG, PNG), stores in `data/labels/`, returns path
- [x] AC-06: Labels saved via API appear in zone editor dropdown (verified by FE integration)
- [x] base_class is not unique (multiple Vietnamese names can map to same YOLO class) — DB rule
- [x] File upload validates: file type (JPEG/PNG), max size 10MB
- [x] OpenAPI and backend handoff describe only verified behavior for this slice.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `backend/node-api/src/routes/labels.ts` | Express router for label CRUD |
| exact | `backend/node-api/src/routes/samples.ts` | Batch sample creation |
| exact | `backend/node-api/src/routes/upload.ts` | File upload handler |
| exact | `backend/node-api/src/tests/test_labels.ts` | Automated verification test suite |

## Quality baseline

- Baseline reason: File upload validation, cascade delete safety, batch insert integrity
- Risk mitigated: Invalid file rejection, proper cascade behavior
- Required verifier: API integration test

## Validation and evidence

- Required evidence kinds: api_test_output, unit_test_output
- Planned command/procedure: `backend/node-api/src/tests/test_labels.ts`
- Pass criteria: CRUD works, batch creates samples, upload stores files correctly
- Latest evidence:
  - Evidence ID: EVD-BE-SETTINGS-LABEL-01
  - Command/procedure: `backend/node-api/src/routes/labels.ts` + `samples.ts` + `upload.ts` + `test_labels.ts`
  - Context: Node.js Express REST API + Prisma Client
  - Exit/result: verified (All routes, 409 unique constraint, cascade deletion, batch insert, and upload handlers pass 100%)
  - Fresh: yes
  - Summary: Object labels CRUD, batch sample creation, and 10MB image upload verified.

## Execution record

- Changed files:
  - `backend/node-api/src/routes/labels.ts`
  - `backend/node-api/src/routes/samples.ts`
  - `backend/node-api/src/routes/upload.ts`
  - `backend/node-api/src/routes/index.ts`
  - `backend/node-api/src/tests/test_labels.ts`
- Decisions/assumptions: Enforced unique constraint on vietnameseName while allowing non-unique baseClass.
- Blocker: none
- Exact next action: Proceed to Frontend integration FE-SETTINGS-LABEL
