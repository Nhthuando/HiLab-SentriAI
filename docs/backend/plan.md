# Backend Worker Plan Index

> Generated and reconciled by `team1-plan`. Backend workers update only the assigned files under `docs/backend/tasks/`.

## Index identity

- Master plan: `docs/plan/plan.md`
- Backend root: `node-api/` (Node.js/Express/Prisma) + `python-worker/` (Python AI pipeline)
- Plan revision: 1
- Last reconciled: 2026-08-17T16:45:00+07:00

## Inputs

| Source | Path | SHA-256/revision |
|---|---|---|
| Master plan | `docs/plan/plan.md` | rev 1 |
| Product | `docs/product/product.md` | `871DEC9C` |
| Architecture | `docs/architecture/architecture.md` | `45F59BC5` |
| Database | `docs/database/database.md` | `F514CB6D` |

## Task index

| Slice | Backend task | Owner | Status | Dependencies | Next action |
|---|---|---|---|---|---|
| VS-GATE-LIVE | `docs/backend/tasks/VS-GATE-LIVE.md` | Phạm Hưng | pending | FDN-REPO-SCAFFOLD, FDN-DB-MIGRATION, FDN-PYTHON-DB, FDN-WS-PROXY, FDN-PYTHON-STREAM, FDN-API-CONTRACT | wait for all foundations |
| VS-AREA-VIOLATION | `docs/backend/tasks/VS-AREA-VIOLATION.md` | Hữu Thuận | pending | FDN-*, VS-GATE-LIVE | wait for VS-GATE-LIVE backend |
| VS-SETTINGS-VEHICLE | `docs/backend/tasks/VS-SETTINGS-VEHICLE.md` | Phạm Hưng | pending | FDN-DB-MIGRATION, FDN-API-CONTRACT | wait for FDN-DB-MIGRATION |
| VS-SETTINGS-ZONE | `docs/backend/tasks/VS-SETTINGS-ZONE.md` | Phạm Hưng | pending | FDN-DB-MIGRATION, FDN-API-CONTRACT | wait for FDN-DB-MIGRATION |
| VS-SETTINGS-LABEL | `docs/backend/tasks/VS-SETTINGS-LABEL.md` | Phạm Hưng | pending | FDN-DB-MIGRATION, FDN-API-CONTRACT | wait for FDN-DB-MIGRATION |
| VS-QA-CHAT | `docs/backend/tasks/VS-QA-CHAT.md` | Hữu Thuận | pending | FDN-DB-MIGRATION, FDN-API-CONTRACT, VS-GATE-LIVE, VS-AREA-VIOLATION | wait for event data |
| VS-KPI-ANALYTICS | `docs/backend/tasks/VS-KPI-ANALYTICS.md` | Hữu Thuận | pending | VS-GATE-LIVE, VS-AREA-VIOLATION | wait for event tables populated |

## Index rules

- Master plan owns scope and topology.
- Per-slice task files own backend execution evidence.
- Do not place full task bodies in this index.
- Do not infer completion from this summary; read the task file.
