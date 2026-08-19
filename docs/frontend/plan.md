# Frontend Worker Plan Index

> Generated and reconciled by `team1-plan`. Frontend workers update only the assigned files under `docs/frontend/tasks/`.

## Index identity

- Master plan: `docs/plan/plan.md`
- Frontend workspace: `frontend/` (React 19 + Vite + TypeScript)
- Plan revision: 1.3
- Last reconciled: 2026-08-18T09:21:08+07:00

## Inputs

| Source | Path | SHA-256/revision |
|---|---|---|
| Master plan | `docs/plan/plan.md` | rev 1.3 |
| Product | `docs/product/product.md` | `9C2C05C7` |
| Architecture | `docs/architecture/architecture.md` | `45F59BC5` |
| Design Contract | `docs/design/ui-design-contract.md` | `3198A3D7` |
| UI handoff | `docs/design/ui-to-frontend-handoff.md` | `DF5C18AD` |

## Task index

| Slice | Frontend task | Owner | Status | Backend gate | Next action |
|---|---|---|---|---|---|
| FDN-FRONTEND-API | `docs/frontend/tasks/FDN-FRONTEND-API.md` | Hữu Thuận | frontend_verified | `docs/backend/tasks/FDN-API-CONTRACT.md` (verified) | complete — API client & custom WebSocket hooks verified |
| VS-GATE-LIVE | `docs/frontend/tasks/VS-GATE-LIVE.md` | Hữu Thuận | frontend_verified | `docs/backend/tasks/VS-GATE-LIVE.md` (verified) | complete — live video feed, in-zone LPR bounding boxes & gate events verified |
| VS-AREA-VIOLATION | `docs/frontend/tasks/VS-AREA-VIOLATION.md` | Hữu Thuận | frontend_verified | `docs/backend/tasks/VS-AREA-VIOLATION.md` (verified) | complete — camera-specific Area pipeline, WebSocket stream & zone violations verified |
| VS-SETTINGS-VEHICLE | `docs/frontend/tasks/VS-SETTINGS-VEHICLE.md` | Hữu Thuận | frontend_verified | `docs/backend/tasks/VS-SETTINGS-VEHICLE.md` (verified) | complete — VehicleLabelTab real API CRUD & sort/filter verified |
| VS-SETTINGS-ZONE | `docs/frontend/tasks/VS-SETTINGS-ZONE.md` | Hữu Thuận | frontend_verified | `docs/backend/tasks/VS-SETTINGS-ZONE.md` (verified) | complete — ZoneEditorTab multi-camera switcher, CRUD & interactive drag verified |
| VS-SETTINGS-LABEL | `docs/frontend/tasks/VS-SETTINGS-LABEL.md` | Hữu Thuận | frontend_verified | `docs/backend/tasks/VS-SETTINGS-LABEL.md` (verified) | complete — ObjectLabelTab real API CRUD, shortcuts & batch samples verified |
| VS-QA-CHAT | `docs/frontend/tasks/VS-QA-CHAT.md` | Hữu Thuận | waiting_backend | `docs/backend/tasks/VS-QA-CHAT.md` | wait for backend gate |
| VS-KPI-ANALYTICS | `docs/frontend/tasks/VS-KPI-ANALYTICS.md` | Hữu Thuận | waiting_backend | `docs/backend/tasks/VS-KPI-ANALYTICS.md` | wait for backend gate |

## Index rules

- This is the only frontend `plan.md` and it is a compact index, not the execution body. `docs/plan/plan.md` is the cross-project master; the execution authority for this slice is `docs/frontend/tasks/VS-AREA-VIOLATION.md`.
- Master plan owns scope and topology.
- Per-slice task files own frontend and post-backend execution evidence.
- Do not place full task bodies in this index.
- Do not infer completion from this summary; read the task file.
