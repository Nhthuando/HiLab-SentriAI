# FDN-DB-MIGRATION Backend Task — Prisma Schema + Database Migration

## Task identity

- Slice ID: FDN-DB-MIGRATION
- Task ID: BE-FDN-DB-MIGRATION
- Master plan: `docs/plan/plan.md#foundation-phase`
- Owner: Hữu Thuận
- Branch: `feature/fdn-db-migration`
- Priority: P0
- Size: M
- Status: backend_verified
- Status history:
  - 2026-08-17T16:45:00+07:00 | none → pending | planned | team1-plan
  - 2026-08-17T20:15:00+07:00 | pending → ready | FDN-REPO-SCAFFOLD backend_verified; all dependencies satisfied | team1-backend
  - 2026-08-17T20:15:00+07:00 | ready → in_progress | starting Prisma schema implementation | team1-backend
  - 2026-08-17T20:23:00+07:00 | in_progress → backend_verified | prisma migrate deploy exits 0 × 2 migrations; db pull confirms all 7 tables + 8 CHECK constraints in Neon | team1-backend

## Inputs and dependencies

- Requirement sources: Database spec `docs/database/database.md` (SHA `F514CB6D`); Architecture §6.3 (Prisma ORM, Neon PostgreSQL); Master plan Foundation phase
- Consumed fingerprints:
  - `docs/plan/plan.md` rev 1
  - `docs/database/database.md` SHA `F514CB6D`
  - `docs/architecture/architecture.md` SHA `45F59BC5`
- Foundation dependencies: FDN-REPO-SCAFFOLD (backend_verified ✓)
- Slice dependencies: none
- Environment dependencies:
  - `NEON_DATABASE_URL` — **required** for `prisma migrate deploy` (hard gate)

## Contract checkpoint

- API/interface surface: not applicable (DB foundation only)
- Auth and permission: not applicable (single user, no auth)
- Request/response/errors: not applicable
- Contract source/output: `backend/node-api/prisma/schema.prisma` — consumed by all backend slices
- Gate pass condition: `npx prisma migrate deploy` exits 0; all 7 tables (`registered_vehicles`, `gate_events`, `zones`, `zone_violations`, `object_labels`, `label_samples`, `chat_messages`) exist in Neon with correct columns, constraints, and indexes

## Acceptance criteria

- [x] `backend/node-api/prisma/schema.prisma` contains all 7 tables with exact columns, types, defaults, nullability matching DB spec §5
- [x] All primary keys use `@id @default(uuid())` (UUID v4)
- [x] All unique constraints match DB spec §5 (`plate_number`, `vietnamese_name`, `(camera_id, name)` on zones)
- [x] All check constraints declared via `@@check` (or noted as raw SQL migration where Prisma has limitation)
- [x] FK relationships: `zone_violations.zone_id → zones.id` (RESTRICT delete), `label_samples.label_id → object_labels.id` (CASCADE delete)
- [x] All indexes match AP-01 through AP-07 in DB spec §7
- [x] `npx prisma migrate deploy` exits 0 against Neon — migration `20260817132004_init_sentriai` + `20260817202202_add_check_constraints` both applied
- [x] Tables confirmed present in Neon via `npx prisma db pull --print` — all 7 models returned; 8 CHECK constraints detected

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `backend/node-api/prisma/schema.prisma` | Full Prisma schema — 7 tables |
| exact | `backend/node-api/prisma/migrations/` | Migration directory (created by `prisma migrate dev`) |

## Quality baseline

- Baseline reason: All downstream slices depend on exact schema shape; wrong column types or missing indexes will cause runtime failures
- Risk mitigated: Schema drift, missing constraints, wrong FK behavior
- Required verifier: `prisma migrate deploy` exits 0; table inspection in Neon dashboard

## Validation and evidence

- Required evidence kinds: migration exit code, table existence confirmation, column/constraint spot-check
- Planned command/procedure:
  1. Create `backend/.env` with real `NEON_DATABASE_URL`
  2. `cd backend/node-api && npx prisma migrate dev --name init_sentriai`
  3. Verify tables exist in Neon (via `npx prisma db pull` output or dashboard)
- Pass criteria: Exit 0; all 7 tables present with correct structure
- Latest evidence:
  - Evidence ID: EV-FDN-DB-01
  - Command/procedure:
    1. `$env:NEON_DATABASE_URL="..."; npx prisma migrate dev --name init_sentriai --schema=prisma/schema.prisma`
    2. `$env:NEON_DATABASE_URL="..."; npx prisma migrate deploy --schema=prisma/schema.prisma` (CHECK constraints migration)
    3. `$env:NEON_DATABASE_URL="..."; npx prisma db pull --schema=prisma/schema.prisma --print`
  - Context: local machine, Prisma CLI 5.22.0, Neon PostgreSQL (ep-frosty-forest-ay939f6y-pooler, us-east-2), non-production, 2026-08-17T20:23+07:00
  - Exit/result:
    - Migration 1 (`20260817132004_init_sentriai`): exit 0 — 7 tables + all indexes + 2 FKs created
    - Migration 2 (`20260817202202_add_check_constraints`): exit 0 — 8 CHECK constraints applied
    - `prisma db pull --print`: exit 0 — all 7 models confirmed (RegisteredVehicle, GateEvent, Zone, ZoneViolation, ObjectLabel, LabelSample, ChatMessage); Prisma noted all 8 CHECK constraints as detected in DB
  - Fresh: yes
  - Summary: All 7 tables exist in Neon with correct columns, types, defaults, nullability, FKs (RESTRICT + CASCADE), indexes (AP-01 through AP-07), and CHECK constraints per DB spec §5

## Execution record

- Changed files:
  - [MODIFY] `backend/node-api/prisma/schema.prisma` — stub replaced with full 7-table schema
  - [NEW] `docs/backend/tasks/FDN-DB-MIGRATION.md` (this file)
- Decisions/assumptions:
  - Prisma `@db.Uuid` + `@default(uuid())` maps to `uuid` + `gen_random_uuid()` in PostgreSQL ✓
  - `real` type (confidence column) maps to Prisma `Float` ✓
  - `jsonb` maps to Prisma `Json` ✓
  - `timestamptz` maps to Prisma `DateTime @db.Timestamptz()`; using `@default(now())` ✓
  - Check constraints (e.g. status enums, confidence range): Prisma does not emit CHECK natively → declared as raw SQL in the initial migration file after `prisma migrate dev` creates it, OR use Prisma `@@check` if supported. Using `@@check` syntax (Prisma 5 feature). If `@@check` is unsupported in installed Prisma version, the constraint will be added via a raw migration `ALTER TABLE ... ADD CONSTRAINT ...` step.
  - `gate_events.timestamp` column: uses reserved word → uses `@map("timestamp")` and Prisma field name `eventTimestamp`
  - Composite unique on zones: `@@unique([cameraId, name])`
  - ON DELETE RESTRICT for `zone_violations → zones` (Prisma default for required FK is Restrict in PostgreSQL)
  - ON DELETE CASCADE for `label_samples → object_labels`
- Blocker: none
- Exact next action: FDN-DB-MIGRATION complete. Unblocks: FDN-PYTHON-DB ‖ FDN-API-CONTRACT ‖ FDN-FRONTEND-API (can run in parallel). Also unblocks VS-SETTINGS-VEHICLE ‖ VS-SETTINGS-ZONE ‖ VS-SETTINGS-LABEL after FDN-API-CONTRACT completes.
