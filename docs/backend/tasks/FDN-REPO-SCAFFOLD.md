# FDN-REPO-SCAFFOLD Backend Task — Repository Scaffold

## Task identity

- Slice ID: FDN-REPO-SCAFFOLD
- Task ID: BE-FDN-REPO-SCAFFOLD
- Master plan: `docs/plan/plan.md#foundation-phase`
- Owner: Hữu Thuận
- Branch: `feature/fdn-repo-scaffold`
- Priority: P0
- Size: M
- Status: backend_verified
- Status history:
  - 2026-08-17T16:45:00+07:00 | none → pending | planned | team1-plan
  - 2026-08-17T19:49:00+07:00 | pending → ready | no dependencies; first ready task | team1-backend
  - 2026-08-17T19:49:00+07:00 | ready → in_progress | starting scaffold implementation | team1-backend
  - 2026-08-17T20:06:00+07:00 | in_progress → backend_verified | all acceptance criteria met; pip + npm install exit 0; import smoke test exit 0 | team1-backend

## Inputs and dependencies

- Requirement sources: Architecture §6.2, §6.3, §7 (directory structure, stack, run instructions); Master plan Foundation phase
- Consumed fingerprints:
  - `docs/plan/plan.md` rev 1
  - `docs/architecture/architecture.md` SHA `45F59BC5`
- Foundation dependencies: none
- Slice dependencies: none
- Environment dependencies: none (only creates `.env.example`; no real secret values needed for this task)

## Contract checkpoint

- API/interface surface: not applicable (scaffold only, no public API)
- Auth and permission: not applicable
- Request/response/errors: not applicable
- Contract source/output: not applicable
- Gate pass condition: `backend/python-worker/` and `backend/node-api/` directories exist with package manifests; `pip install -r backend/python-worker/requirements.txt` succeeds; `cd backend/node-api && npm install` succeeds

## Acceptance criteria

- [x] `backend/python-worker/` exists with `main.py`, `requirements.txt`, subdirs: `stream/`, `detection/`, `zone/`, `buffer/`, `db/` (each with `__init__.py`)
- [x] `backend/node-api/` exists with `package.json`, `tsconfig.json`, `src/` subdirs: `routes/`, `ws/`, `ai/`, `prisma/`; `prisma/schema.prisma` stub exists
- [x] `data/clips/` and `data/crops/` exist (with `.gitkeep`)
- [x] `.env.example` exists with all required variable names documented
- [x] `pip install -r python-worker/requirements.txt` exits 0 (import smoke test also exit 0)
- [x] `cd node-api && npm install` exits 0

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `backend/python-worker/main.py` | Python worker entry point (stub) |
| exact | `backend/python-worker/requirements.txt` | Python dependencies |
| exact | `backend/python-worker/stream/__init__.py` | Stream reader module placeholder |
| exact | `backend/python-worker/detection/__init__.py` | YOLO/OCR detection module placeholder |
| exact | `backend/python-worker/zone/__init__.py` | Zone polygon module placeholder |
| exact | `backend/python-worker/buffer/__init__.py` | Circular buffer module placeholder |
| exact | `backend/python-worker/db/__init__.py` | asyncpg DB module placeholder |
| exact | `backend/node-api/package.json` | Node.js deps (Express, Prisma, TypeScript, ws, Gemini SDK) |
| exact | `backend/node-api/tsconfig.json` | TypeScript config |
| exact | `backend/node-api/src/index.ts` | Express app entry point (stub) |
| exact | `backend/node-api/src/routes/.gitkeep` | Routes directory placeholder |
| exact | `backend/node-api/src/ws/.gitkeep` | WebSocket proxy placeholder |
| exact | `backend/node-api/src/ai/.gitkeep` | Gemini AI module placeholder |
| exact | `backend/node-api/src/prisma/.gitkeep` | Prisma client placeholder |
| exact | `backend/node-api/prisma/schema.prisma` | Prisma schema stub (FDN-DB-MIGRATION will fill) |
| exact | `data/clips/.gitkeep` | Clips storage directory |
| exact | `data/crops/.gitkeep` | Crops storage directory |
| exact | `.env.example` | All env variable names with safe examples |

## Quality baseline

- Baseline reason: Scaffold correctness — all downstream FDN-* tasks require valid manifests and installable dependencies
- Risk mitigated: Broken install would block all FDN-* and VS-* downstream tasks
- Required verifier: `pip install` exits 0; `npm install` exits 0

## Validation and evidence

- Required evidence kinds: directory-existence check, dependency install success (pip + npm), import smoke test
- Planned command/procedure:
  1. `Test-Path` all required paths (PowerShell)
  2. `cd python-worker && pip install -r requirements.txt`
  3. `cd node-api && npm install`
  4. `python -c "import fastapi, uvicorn, websockets, cv2, ultralytics, easyocr, shapely, asyncpg, dotenv, aiofiles, numpy; print('ALL OK')"`
- Pass criteria: All paths exist; both installs exit 0; import smoke test exits 0
- Latest evidence:
  - Evidence ID: EV-FDN-REPO-01
  - Command/procedure:
    1. PowerShell `Test-Path` on 17 scaffold paths
    2. `pip install -r requirements.txt` (backend/python-worker/)
    3. `npm install` (backend/node-api/)
    4. `python -c "import fastapi, uvicorn, websockets, cv2, ultralytics, easyocr, shapely, asyncpg, dotenv, aiofiles, numpy; print('ALL OK')"`
  - Context: local machine, Python 3.14.4 (Win AMD64), non-production, 2026-08-17T20:06+07:00
  - Exit/result:
    - Path check: exit 0 — all 17 paths confirmed present
    - pip install: exit 0 (after fixing numpy→2.5.2, asyncpg→0.31.0, websockets→>=13.0 for Python 3.14 cp314 wheel compatibility)
    - npm install: exit 0 — 161 packages, 0 vulnerabilities
    - import smoke test: exit 0 — ALL OK; numpy 2.5.2, asyncpg 0.31.0, websockets 16.1.1, ultralytics 8.4.120
  - Fresh: yes
  - Summary: All scaffold directories and files exist; pip install and npm install succeed; all Python packages import correctly on Python 3.14.4

## Execution record

- Changed files:
  - [NEW] `backend/python-worker/main.py`
  - [NEW] `backend/python-worker/requirements.txt`
  - [NEW] `backend/python-worker/stream/__init__.py`
  - [NEW] `backend/python-worker/detection/__init__.py`
  - [NEW] `backend/python-worker/zone/__init__.py`
  - [NEW] `backend/python-worker/buffer/__init__.py`
  - [NEW] `backend/python-worker/db/__init__.py`
  - [NEW] `backend/node-api/package.json`
  - [NEW] `backend/node-api/tsconfig.json`
  - [NEW] `backend/node-api/src/index.ts`
  - [NEW] `backend/node-api/src/routes/.gitkeep`
  - [NEW] `backend/node-api/src/ws/.gitkeep`
  - [NEW] `backend/node-api/src/ai/.gitkeep`
  - [NEW] `backend/node-api/src/prisma/.gitkeep`
  - [NEW] `backend/node-api/prisma/schema.prisma`
  - [NEW] `data/clips/.gitkeep`
  - [NEW] `data/crops/.gitkeep`
  - [NEW] `.env.example`
  - [NEW] `.gitignore`
  - [NEW] `docs/backend/tasks/FDN-REPO-SCAFFOLD.md` (this file)
- Decisions/assumptions:
  - FastAPI + uvicorn for Python AI Worker (Architecture §6.3, AI process server)
  - Express 4 + TypeScript 5 for Node.js API (Architecture §6.3)
  - asyncpg≥0.31.0 (0.31.0 is first version with Python 3.14 cp314 wheel; 0.29.0 original plan requires C++ Build Tools on Python 3.14)
  - ultralytics≥8.2.100 resolved to 8.4.120 (latest stable with Python 3.14 support)
  - PaddleOCR as primary OCR; EasyOCR 1.7.2 installed (PaddleOCR install deferred to FDN-PYTHON-STREAM — requires separate paddlepaddle install)
  - Shapely≥2.0.6 resolved to 2.1.2 (has Python 3.14 cp314 wheel)
  - numpy==2.5.2 (original 1.26.4 has no cp314 wheel and no C compiler available)
  - websockets≥13.0,<17.0 resolved to 16.1.1 (12.0 conflicts with system google-genai)
  - opencv-python≥4.10 resolved to 5.0.0.93 (cp314 wheel available)
  - Prisma as Node.js ORM (Architecture §6.3)
  - @google/generative-ai SDK for Gemini function calling
  - ws library for Node.js WebSocket
  - data/ directory gitignored for large files; .gitkeep commits empty dirs
- Blocker: none
- Exact next action: FDN-REPO-SCAFFOLD complete. Next task per critical path: FDN-DB-MIGRATION (Prisma schema + 7 tables).
