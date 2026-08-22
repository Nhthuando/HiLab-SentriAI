# FDN-TRAINING-PERSISTENCE Backend Task — Training persistence migration

## Task identity

- Slice ID: FDN-TRAINING-PERSISTENCE
- Task ID: BE-TRAINING-PERSISTENCE
- Master plan: `docs/plan/plan.md#fdn-training-persistence-training-persistence-migration`
- Owner: unassigned
- Branch: none
- Priority: P0
- Size: M
- Status: backend_verified
- Status history:
  - 2026-08-20T16:20:00+07:00 | none -> pending | planned | team1-plan
  - 2026-08-20T16:30:00+07:00 | pending -> ready | user assigned this first foundation directly on current main merge | Codex
  - 2026-08-20T16:35:00+07:00 | ready -> in_progress | backend environment variable exists at backend scope; migration will not be executed against ambiguous Neon environment | Codex
  - 2026-08-20T16:35:00+07:00 | in_progress -> backend_verified | migration, provenance round-trip integration fixture, TypeScript build and REST contract tests passed against confirmed Neon dev/test | Codex

## Inputs and dependencies

- Requirement sources: Product BR-10/BR-11, Architecture §11, Database §§5–9.
- Consumed fingerprints: Product `8E25FF46`; Architecture `F9697DAE`; Database `780BD9B6`.
- Foundation dependencies: FDN-DB-MIGRATION.
- Slice dependencies: none.
- Environment dependencies: `NEON_DATABASE_URL`.

## Contract checkpoint

- API/interface surface: Prisma persistence only; no public API is introduced in this foundation.
- Gate pass: schema/migration implements `label_samples` provenance and `training_datasets`, `training_jobs`, `model_versions` exactly as Database §5, including one-active-custom partial uniqueness.

## Acceptance criteria

- [x] Existing label samples retain data; unresolved legacy source refs remain non-trainable and are never guessed.
- [x] Database constraints/indexes and referential actions match the canonical spec, including one-active-custom partial uniqueness and integrity guards.
- [x] No new public endpoint belongs to this persistence foundation; the backend handoff documents only verified provenance behavior.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `backend/node-api/prisma/schema.prisma` | Prisma models and relations |
| likely | `backend/node-api/prisma/migrations/` | New migration lineage |
| exact | `backend/node-api/src/routes/samples.ts` | Persist media/frame provenance on new samples |

## Quality baseline

- Baseline reason: migration safety and model provenance.
- Risk mitigated: corrupt existing samples, two active custom models, unsafe media paths.
- Required verifier: Prisma migration against development database plus route integration test.

## Validation and evidence

- Required evidence kinds: migration_output, integration_test_output, schema_diff.
- Planned command/procedure: `npx prisma migrate dev` in `backend/node-api/` and focused sample route test.
- Pass criteria: migration applies, prior label CRUD remains functional, constraints reject invalid state.
- Latest evidence: 2026-08-20, all required checks passed in the confirmed Neon development/test environment.

## Execution record

- Changed files: `backend/node-api/prisma/schema.prisma`; `backend/node-api/prisma/migrations/20260820163500_training_persistence/migration.sql`; `backend/node-api/prisma/migrations/20260820171000_training_persistence_constraints/migration.sql`; `backend/node-api/src/routes/samples.ts`; `docs/backend/backend.md`.
- Blocker: none.
- Evidence:
  - 2026-08-20: `npx prisma validate` and `npx prisma migrate deploy` from `backend/node-api/`: pass; migration `20260820171000_training_persistence_constraints` applied to the user-confirmed Neon dev/test database.
  - 2026-08-20: `npm.cmd run build` from `backend/node-api/`: pass.
  - 2026-08-20: `NODE_ENV=test npm.cmd run test:api` from `backend/node-api/`: pass; health/database, error-envelope and static-media regression checks pass.
  - 2026-08-20: temporary integration fixture using an existing uploaded video: create label -> save frame sample -> read it back in canvas percentages -> readiness accepts it -> delete sample and label: pass. No user sample, label or media was changed.
  - 2026-08-20: Python `py_compile` for `training/dataset_exporter.py` and `training/runner.py`: pass.
- Superseding next action: this backend foundation is complete; `VS-OBJECT-TRAIN-DATASET` can use server-verified sample provenance.
- Exact next action: none for this foundation. Continue with real labelled samples, then run the dataset/export/job runtime flow.
