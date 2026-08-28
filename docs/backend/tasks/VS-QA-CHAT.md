# VS-QA-CHAT Backend Task — Hỏi đáp AI: Gemini function calling + clip reference

## Task identity

- Slice ID: VS-QA-CHAT
- Task ID: BE-QA-CHAT
- Master plan: `docs/plan/plan.md#vs-qa-chat`
- Owner: Hữu Thuận
- Branch: feature/vs-qa-chat
- Priority: P1
- Size: M
- Status: backend_verified
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> pending | planned | team1-plan
  - 2026-08-27T19:28:46+07:00 | pending -> blocked | required `GEMINI_API_KEY` is not configured in `backend/.env`; implementation and real-service verification cannot start | team1-slice/team1-backend
  - 2026-08-27T19:33:34+07:00 | blocked -> ready | `GEMINI_API_KEY` and `NEON_DATABASE_URL` are configured; read-only Neon check found 3 gate events and 7 zone violations | team1-backend
  - 2026-08-27T19:33:34+07:00 | ready -> in_progress | environment and saved-event dependency gates passed; backend implementation started | team1-backend
  - 2026-08-27T19:47:28+07:00 | in_progress -> blocked | safe automated/backend contract checks pass, but real 5-question Gemini verification would transmit saved plate/incident data to Google and requires explicit user consent | team1-backend
  - 2026-08-27T19:51:14+07:00 | blocked -> ready | Hữu Thuận explicitly approved sending development/test event payloads to Google Gemini for the required real-data verification | team1-backend
  - 2026-08-27T19:51:14+07:00 | ready -> in_progress | resume AC-07 and 5-question real API verification with test-created chat-row cleanup | team1-backend
  - 2026-08-27T19:55:14+07:00 | in_progress -> backend_verified | 5/5 real-data Gemini questions, correct UTC+07 details, chat persistence, clip range/download, focused tests, build/typecheck and OpenAPI lint passed | team1-backend
  - 2026-08-27T21:30:00+07:00 | backend_verified -> invalidated | approved BAI-KIEM activity-analytics delta adds persisted all-label activity sessions, replay idempotency and lazy activity clips | team1-slice/team1-backend
  - 2026-08-27T21:30:00+07:00 | invalidated -> in_progress | began implementation and real-video verification for the approved delta | team1-backend
  - 2026-08-27T22:14:00+07:00 | in_progress -> backend_verified | real BAI-KIEM vehicle sessions, unchanged local replay, lazy clip generation, Gemini vehicle statistics and automated gates passed | team1-backend

## Inputs and dependencies

- Requirement sources: Product M4 (§3), BR-09, AC-07, Architecture §6.2 Flow 7
- Consumed fingerprints:
  - `docs/product/product.md` → `330AA279`
  - `docs/architecture/architecture.md` → `923894E3`
  - `docs/database/database.md` → `9113CF8E`
- Foundation dependencies: FDN-DB-MIGRATION, FDN-API-CONTRACT
- Slice dependencies: VS-GATE-LIVE (gate_events data), VS-AREA-VIOLATION (zone_violations data)
- Environment dependencies: `NEON_DATABASE_URL`, `GEMINI_API_KEY`

## Contract checkpoint

- API/interface surface:
  - `POST /api/v1/qa/query` — submit question `{ query: string }`, get AI response with optional clip reference
  - `GET /api/v1/chat/history?limit=N` — retrieve chat history
  - `DELETE /api/v1/chat/history` — clear chat history
  - `GET /api/v1/clips/:id/stream` — stream clip video (shared with VS-GATE-LIVE)
  - `GET /api/v1/clips/:id/download` — download clip file
- Auth and permission: None
- Request/response/errors:
  - `POST /api/v1/qa/query` → `200: { id, role: "assistant", text, clip?: { cam, from, to, title, boxLabel, boxColor, tint, downloadUrl } }` | `503: { error: "Gemini API unavailable" }` | `504: { error: "Gemini API timeout" }`
  - `GET /api/v1/chat/history` → `200: { data: ChatMessage[] }`
  - `DELETE /api/v1/chat/history` → `204`
- Contract source/output: `node-api/openapi/qa.yaml` (planned)
- Gate pass condition: User can ask natural language questions, receive accurate answers with clip references from DB data

## Acceptance criteria

- [x] Gemini 3.5 Flash Lite configured with system prompt describing DB schema and available tool functions (Architecture §6.2 Flow 7)
- [x] Tool functions defined for: `get_stranger_vehicles_today`, `get_known_vehicles_today`, `get_gate_events_by_plate`, `get_violations_by_zone`, `get_violations_today`, `get_clip_reference` (Architecture §6.2 Flow 7)
- [x] Each tool function queries DB via Prisma, returns structured data to LLM
- [x] LLM synthesizes answer including clip reference when relevant
- [x] AC-07: "Hôm nay có bao nhiêu xe lạ vào?" → returns correct count + details + clip references
- [x] At least 5 sample questions answered correctly with clip references (Product §8)
- [x] Chat history saved to `chat_messages` table (role, content, clip_reference, created_at)
- [x] `GET /api/v1/chat/history` returns messages ordered by created_at ASC
- [x] `DELETE /api/v1/chat/history` clears all chat_messages
- [x] Gemini API timeout (15s) → return 504 with clear error (Architecture §8)
- [x] Question outside tool scope → LLM responds "không tìm thấy thông tin"
- [x] BR-09: Only queries saved data, no real-time stream analysis
- [x] OpenAPI and backend handoff describe only verified behavior for this slice.
- [x] Every detectable registered label, including people, can create one persisted activity session per tracked object entering and then leaving one zone.
- [x] Activity summaries separate `ALLOWED` and `VIOLATION`, include counts/duration/timestamps/evidence, and treat `forklift` questions as the `forklift + reach_stacker` business group.
- [x] Replaying the same local-video segment does not insert a duplicate or recalculate an existing session's count, duration, timestamps or `updatedAt`.
- [x] Activity clips remain `NOT_REQUESTED` until an explicit user request; processing is queued only after clicking `Xem video` or calling the activity clip endpoint.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| likely | `node-api/src/ai/gemini.ts` | Gemini SDK client + function calling setup |
| likely | `node-api/src/ai/tools.ts` | Tool function definitions and implementations |
| likely | `node-api/src/ai/prompts.ts` | System prompt with DB schema description |
| likely | `node-api/src/routes/qa.ts` | POST /api/v1/qa/query endpoint |
| likely | `node-api/src/routes/chat.ts` | Chat history CRUD |
| likely | `node-api/src/routes/clips.ts` | Clip stream/download endpoints |

## Quality baseline

- Baseline reason: LLM query safety (function calling prevents raw SQL), Gemini API timeout
- Risk mitigated: Function calling isolates DB access, timeout prevents hang
- Required verifier: Manual Q&A test with 5 sample questions

## Validation and evidence

- Required evidence kinds: manual_qa_test, api_response_sample
- Planned command/procedure: Manual test with 5 questions from Product §3 M4 examples + curl API calls
- Pass criteria: 5/5 sample questions return correct data with clip references where applicable
- Latest evidence:
  - Evidence ID: `BE-QA-CHAT-20260827-SAFE-GATE`
  - Command/procedure: `npm.cmd run typecheck`; `npm.cmd run build`; `npm.cmd run test:qa`; synthetic-data Gemini function-call smoke; synthetic outside-scope smoke; sequential read-only execution of all 6 tools against Neon; HTTP checks for history, validation, clip range and clear-history.
  - Context: local Node 24.12.0; `@google/genai` 2.19.0; user-confirmed Gemini key; approved Neon development/test DB; Google calls used only `TEST-01`/`TEST-02` synthetic rows and an out-of-scope weather question.
  - Exit/result: typecheck 0; build 0; focused tests 0; synthetic Gemini function call returned count 2; outside-scope returned `Không tìm thấy thông tin`; real tools returned counts stranger=3, known=0, plate=1, zone=7, today=7 and clip found; clip stream 206/32-byte range; history GET 200; invalid query 400; clear empty history 204.
  - Fresh: yes for implemented code; real-event Gemini synthesis was pending consent at this historical gate and was completed by the later real-data gate.
  - Summary: Safe backend surfaces pass. `npm run lint` is unavailable because the repository has no installed ESLint binary. The legacy REST suite completed every assertion, then exited 1 in the pre-existing PythonConnector teardown (`UV_HANDLE_CLOSING`); no Q&A assertion failed.
  - Evidence ID: `BE-QA-CHAT-20260827-REAL-GATE`
  - Command/procedure: User-approved 5-question HTTP smoke through `POST /api/v1/qa/query`; assert expected database facts and UTC+07 times; assert tool sources and exact event clip IDs; range-fetch stream/download; load chronological history; delete only test-created chat IDs; `npx.cmd --yes @redocly/cli lint openapi/qa.yaml`.
  - Context: running local API on port 3001, Gemini `gemini-3.5-flash-lite`, approved Neon development/test data, explicit Hữu Thuận consent to transmit saved event payloads for verification.
  - Exit/result: 5/5 passed; AC-07 returned 3 stranger vehicles with all three plates and correct 19:04:40/19:02:10/19:01:10 UTC+07 times; all five responses included expected tool source and clip; stream/download returned 206; history persisted 10 chronological messages; exactly 10 test-created rows cleaned; OpenAPI valid with 0 errors (3 non-blocking style warnings for local-only server/license/delete-4xx convention).
  - Fresh: yes
  - Summary: Backend contract gate passed after fixing ambiguous UTC timestamps to explicit Asia/Bangkok tool fields. No Gate/Area event, clip, zone, camera, training or pre-existing chat record was modified.
  - Evidence ID: `BE-QA-ACTIVITY-20260827-REAL`
  - Command/procedure: run the real `KiemHoa-LM06_fastseek.mp4` segment through the current Area worker, query persisted activity sessions, and ask Gemini the approved forklift/truck activity questions through the HTTP API.
  - Context: user-approved real development data; BAI-KIEM custom detector classes `car`, `forklift`, `person`, `reach_stacker`, `truck`; local API/worker connected to Neon.
  - Exit/result: pass — 13 total sessions remained after cleanup; a CLOSED `reach_stacker` ALLOWED session lasted 38 seconds and a CLOSED `truck` ALLOWED session lasted 29 seconds; the forklift answer correctly grouped reach stacker and both vehicle questions returned counts, status, duration and evidence.
  - Fresh: yes
  - Evidence ID: `BE-QA-ACTIVITY-REPLAY-20260827`
  - Command/procedure: replay the same local-video 210–235 second segment after enabling fuzzy source-position/entry-point idempotency; compare every persisted row before and after.
  - Exit/result: pass — total stayed 13 → 13 and the changed-row set was empty; no count, duration, timestamp or update time was recalculated.
  - Fresh: yes
  - Evidence ID: `BE-QA-ACTIVITY-CLIP-20260827`
  - Command/procedure: inspect `NOT_REQUESTED`, explicitly request the reach-stacker/truck activity clips, poll until ready, then range-fetch stream/download.
  - Exit/result: pass — clips transitioned `NOT_REQUESTED → QUEUED → READY` only after request; both stream and download returned `206`; produced media duration was 10.048 seconds.
  - Fresh: yes
  - Evidence ID: `BE-QA-ACTIVITY-AUTO-20260827`
  - Command/procedure: focused Python activity/tracker/repository suites; focused Node QA/activity-clip tests; Node typecheck/build; frontend lint/build; `git diff --check`.
  - Exit/result: pass
  - Fresh: yes
  - Summary: Python 70/70; all focused Node tests passed; typecheck/build/lint and whitespace gates passed.

## Execution record

- Changed files: original VS-QA-CHAT files plus `backend/python-worker/zone/activity_tracker.py`, `backend/python-worker/detection/area_pipeline.py`, `backend/python-worker/db/repositories.py`, their focused tests, the Area activity persistence/migration/API/clip service files, `backend/node-api/src/ai/{prompts,tools,gemini}.ts`, `backend/node-api/src/tests/test_qa_chat.ts`, approved spec/plan documents, handoffs and browser evidence.
- Decisions/assumptions: Work resumes only on `feature/vs-qa-chat`; no secret value is recorded in task evidence. Current Product/Architecture/Database fingerprints supersede the 2026-08-17 task fingerprints; later changes concern training/detection and preserve M4/BR-09/AC-07. The user-configured Neon database is the approved development/test database recorded by the backend handoff. Saved-event dependency is satisfied by a read-only count of 3 gate events and 7 zone violations. Use the maintained `@google/genai` SDK with the architecture-approved `gemini-3.5-flash-lite` model. Clip route `:id` is the existing GateEvent/ZoneViolation UUID because the approved schema has no Clip entity; the server resolves the path and never accepts a client filesystem path.
- Blocker: none
- Exact next action: Hữu Thuận manually accepts the retained forklift/truck answers and requests one still-unrequested activity clip from the Q&A UI; no backend implementation blocker remains.
