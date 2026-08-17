# FDN-PYTHON-DB Backend Task — Python asyncpg Client + Connection Pool for Neon

## Task identity

- Slice ID: FDN-PYTHON-DB
- Task ID: BE-FDN-PYTHON-DB
- Master plan: `docs/plan/plan.md#foundation-phase`
- Owner: Hữu Thuận
- Branch: `feature/fdn-python-db`
- Priority: P0
- Size: S
- Status: backend_verified
- Status history:
  - 2026-08-17T16:45:00+07:00 | none → pending | planned | team1-plan
  - 2026-08-17T20:25:00+07:00 | pending → ready | FDN-REPO-SCAFFOLD and FDN-DB-MIGRATION backend_verified | team1-backend
  - 2026-08-17T21:14:00+07:00 | ready → in_progress | starting asyncpg pool and CRUD helpers implementation | team1-backend
  - 2026-08-17T21:16:00+07:00 | in_progress → backend_verified | all acceptance criteria met; 100% test pass against Neon PostgreSQL | team1-backend

## Inputs and dependencies

- Requirement sources: Database spec `docs/database/database.md` (SHA `F514CB6D`); Architecture §6.2, §6.3 (Python asyncpg, connection pooling, AP-01 to AP-07); Master plan Foundation phase
- Consumed fingerprints:
  - `docs/plan/plan.md` rev 1
  - `docs/database/database.md` SHA `F514CB6D`
  - `docs/architecture/architecture.md` SHA `45F59BC5`
- Foundation dependencies:
  - FDN-REPO-SCAFFOLD (backend_verified ✓)
  - FDN-DB-MIGRATION (backend_verified ✓)
- Slice dependencies: none
- Environment dependencies:
  - `NEON_DATABASE_URL` — required for connecting to Neon PostgreSQL

## Contract checkpoint

- API/interface surface: Python internal module `backend/python-worker/db/`
- Consumers: `VS-GATE-LIVE`, `VS-AREA-VIOLATION`
- Contract output:
  - `init_db_pool(dsn=None, min_size=1, max_size=10)` / `close_db_pool()` / `get_db_pool()`
  - CRUD & query helpers for `registered_vehicles`, `gate_events`, `zones`, `zone_violations`, `object_labels`
- Gate pass condition: Python asyncpg connects to Neon, executes queries across the 5 relevant tables, inserts and reads records cleanly, and gracefully closes the pool.

## Acceptance criteria

- [x] Connection pool management (`init_db_pool`, `close_db_pool`, `get_db_pool`, context manager) supporting `NEON_DATABASE_URL` with SSL
- [x] Vehicle query helpers (AP-01: lookup status by plate number; get all registered plates dictionary)
- [x] Gate event CRUD helpers (create gate event with auto-generated UUID, fetch recent events, lookup by plate, count strangers)
- [x] Zone query helpers (AP-05: get active zones by camera, get all active zones, create zone)
- [x] Zone violation CRUD helpers (create OPEN violation, close violation with exited_at/duration_seconds/clip_path, query open violations, query recent violations)
- [x] Object label query helpers (get all active labels with vietnamese_name and base_class, create label)
- [x] Automated verification script / tests run and exit 0 with fresh evidence against Neon DB

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `backend/python-worker/db/connection.py` | asyncpg pool lifecycle, connection acquisition, env loading, jsonb codecs |
| exact | `backend/python-worker/db/repositories.py` | CRUD and query functions for vehicles, events, zones, violations, labels |
| exact | `backend/python-worker/db/__init__.py` | Package export of pool functions and repository helpers |
| exact | `backend/python-worker/tests/test_db.py` | Test suite / verification script for asyncpg DB module |

## Quality baseline

- Baseline reason: Python AI Worker must handle high-throughput frame processing without database connection leaks, slow blocking queries, or unhandled reconnection errors.
- Risk mitigated: Neon SSL connection dropping, pool exhaustion, JSON serialization/deserialization errors for `polygon_points`/`target_labels`.
- Required verifier: Automated test script executing all CRUD operations against Neon exiting with code 0.

## Validation and evidence

- Required evidence kinds: automated execution log of test suite covering pool lifecycle and all 5 table operations
- Planned command/procedure:
  - `python backend/python-worker/tests/test_db.py`
- Pass criteria: All CRUD operations pass, assert statements succeed, pool initializes and terminates cleanly without errors.
- Latest evidence:
  - Evidence ID: EV-FDN-PYTHON-DB-01
  - Command/procedure: `python backend/python-worker/tests/test_db.py`
  - Context: local machine, Python 3.14.4 (Win AMD64), asyncpg 0.31.0, Neon PostgreSQL (ep-frosty-forest-ay939f6y-pooler, us-east-2), non-production, 2026-08-17T21:15+07:00
  - Exit/result: exit 0 — 100% tests passed
    - [1/7] Pool initialization + check_db_health() == True
    - [2/7] registered_vehicles (AP-01 get_vehicle_status_by_plate, register_vehicle, get_all_registered_plates)
    - [3/7] gate_events (AP-02 get_recent_gate_events, AP-03 get_gate_events_by_plate, AP-04 count_stranger_vehicles)
    - [4/7] object_labels (create_object_label, get_all_object_labels)
    - [5/7] zones (AP-05 get_active_zones_by_camera, get_all_active_zones, jsonb deserialization)
    - [6/7] zone_violations (AP-02, AP-06, BR-06 create OPEN, get_open_violations, close_zone_violation with duration calculation)
    - [7/7] Teardown & clean up of test records, graceful pool shutdown
  - Fresh: yes
  - Summary: Python asyncpg client and connection pool fully operational with Neon cloud PostgreSQL; all CRUD and query patterns AP-01 through AP-06 verified working.

## Execution record

- Changed files:
  - [NEW] `docs/backend/tasks/FDN-PYTHON-DB.md` (this file)
  - [MODIFY] `backend/python-worker/db/__init__.py`
  - [NEW] `backend/python-worker/db/connection.py`
  - [NEW] `backend/python-worker/db/repositories.py`
  - [NEW] `backend/python-worker/tests/test_db.py`
- Decisions/assumptions:
  - JSONB codecs: Registered on connection initialization via `conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")` for seamless handling of polygon coordinates and label lists.
  - UUIDs: Python `uuid.uuid4()` automatically mapped and converted to string in dictionary outputs for clean JSON serialization.
  - Case-insensitivity: License plates are automatically stripped and uppercased in both query and insertion helpers.
  - Duration calculation: `close_zone_violation` calculates elapsed duration in seconds automatically from `entered_at` if not provided.
- Blocker: none
- Exact next action: FDN-PYTHON-DB complete. Next foundations in critical path: FDN-WS-PROXY, FDN-PYTHON-STREAM, FDN-API-CONTRACT, FDN-FRONTEND-API.
