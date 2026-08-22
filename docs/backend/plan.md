# Backend Worker Plan Index

> Generated and reconciled by `team1-plan`. Backend workers update only the assigned files under `docs/backend/tasks/`.

## Index identity

- Master plan: `docs/plan/plan.md`
- Backend root: `backend/node-api/` (Node.js/Express/Prisma) + `backend/python-worker/` (Python AI pipeline)
- Plan revision: 1.4
- Last reconciled: 2026-08-20T16:20:00+07:00

## Inputs

| Source | Path | SHA-256/revision |
|---|---|---|
| Master plan | `docs/plan/plan.md` | rev 1.4 |
| Product | `docs/product/product.md` | `8E25FF46` |
| Architecture | `docs/architecture/architecture.md` | `F9697DAE` |
| Database | `docs/database/database.md` | `780BD9B6` |

## Task index

| Slice | Backend task | Owner | Status | Dependencies | Next action |
|---|---|---|---|---|---|
| FDN-REPO-SCAFFOLD | `docs/backend/tasks/FDN-REPO-SCAFFOLD.md` | Hữu Thuận | backend_verified | none | complete — unblocked FDN-DB-MIGRATION and others |
| FDN-DB-MIGRATION | `docs/backend/tasks/FDN-DB-MIGRATION.md` | Hữu Thuận | backend_verified | FDN-REPO-SCAFFOLD | complete — unblocks FDN-PYTHON-DB, FDN-API-CONTRACT, FDN-FRONTEND-API (parallel); VS-SETTINGS-* after FDN-API-CONTRACT |
| FDN-PYTHON-DB | `docs/backend/tasks/FDN-PYTHON-DB.md` | Hữu Thuận | backend_verified | FDN-DB-MIGRATION | complete — asyncpg connection pool + CRUD helpers verified against Neon |
| FDN-WS-PROXY | `docs/backend/tasks/FDN-WS-PROXY.md` | Hữu Thuận | backend_verified | FDN-REPO-SCAFFOLD, FDN-DB-MIGRATION | complete — Node.js WebSocket proxy (Python -> Node -> Browser) verified |
| FDN-PYTHON-STREAM | `docs/backend/tasks/FDN-PYTHON-STREAM.md` | Hữu Thuận | backend_verified | FDN-REPO-SCAFFOLD, FDN-WS-PROXY | complete — OpenCV stream reader + YOLO detection pipeline verified |
| FDN-API-CONTRACT | `docs/backend/tasks/FDN-API-CONTRACT.md` | Hữu Thuận | backend_verified | FDN-DB-MIGRATION, FDN-WS-PROXY | complete — Express REST scaffold, error contract, and health checks verified |
| VS-GATE-LIVE | `docs/backend/tasks/VS-GATE-LIVE.md` | Hữu Thuận | backend_verified | FDN-REPO-SCAFFOLD, FDN-DB-MIGRATION, FDN-PYTHON-DB, FDN-WS-PROXY, FDN-PYTHON-STREAM, FDN-API-CONTRACT | complete — GPU-accelerated LPR, in-zone tracking, gate events verified |
| VS-AREA-VIOLATION | `docs/backend/tasks/VS-AREA-VIOLATION.md` | Hữu Thuận | backend_verified | FDN-REPO-SCAFFOLD, FDN-DB-MIGRATION, FDN-PYTHON-DB, FDN-WS-PROXY, FDN-PYTHON-STREAM, FDN-API-CONTRACT | complete — camera-specific Area pipeline, REST/WS contracts, and unit/integration tests verified |
| VS-SETTINGS-VEHICLE | `docs/backend/tasks/VS-SETTINGS-VEHICLE.md` | Hữu Thuận | backend_verified | FDN-DB-MIGRATION, FDN-API-CONTRACT | complete — vehicle CRUD + plate normalization verified |
| VS-SETTINGS-ZONE | `docs/backend/tasks/VS-SETTINGS-ZONE.md` | Hữu Thuận | backend_verified | FDN-DB-MIGRATION, FDN-API-CONTRACT | complete — zone CRUD and multi-camera snapshots verified |
| VS-SETTINGS-LABEL | `docs/backend/tasks/VS-SETTINGS-LABEL.md` | Hữu Thuận | backend_verified | FDN-DB-MIGRATION, FDN-API-CONTRACT | complete — label CRUD, batch samples & image upload verified |
| VS-QA-CHAT | `docs/backend/tasks/VS-QA-CHAT.md` | Hữu Thuận | pending | FDN-DB-MIGRATION, FDN-API-CONTRACT, VS-GATE-LIVE, VS-AREA-VIOLATION | wait for event data |
| VS-KPI-ANALYTICS | `docs/backend/tasks/VS-KPI-ANALYTICS.md` | Hữu Thuận | pending | VS-GATE-LIVE, VS-AREA-VIOLATION | wait for event tables populated |
| FDN-TRAINING-PERSISTENCE | `docs/backend/tasks/FDN-TRAINING-PERSISTENCE.md` | unassigned | pending | FDN-DB-MIGRATION | assign owner; implement training persistence migration |
| VS-OBJECT-TRAIN-DATASET | `docs/backend/tasks/VS-OBJECT-TRAIN-DATASET.md` | unassigned | pending | FDN-TRAINING-PERSISTENCE, VS-SETTINGS-LABEL | wait for persistence gate |
| VS-OBJECT-TRAIN-RUN | `docs/backend/tasks/VS-OBJECT-TRAIN-RUN.md` | unassigned | pending | VS-OBJECT-TRAIN-DATASET, VS-AREA-VIOLATION | wait for dataset export evidence |
| VS-OBJECT-MODEL-VERSION | `docs/backend/tasks/VS-OBJECT-MODEL-VERSION.md` | unassigned | pending | VS-OBJECT-TRAIN-RUN, VS-AREA-VIOLATION | wait for evaluated candidate evidence |

## Index rules

- This file is a compact backend index, not an implementation plan. The execution authority for this slice is `docs/backend/tasks/VS-AREA-VIOLATION.md`.
- Master plan owns scope and topology.
- Per-slice task files own backend execution evidence.
- Do not place full task bodies in this index.
- Do not infer completion from this summary; read the task file.
