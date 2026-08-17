# VS-QA-CHAT Backend Task — Hỏi đáp AI: Gemini function calling + clip reference

## Task identity

- Slice ID: VS-QA-CHAT
- Task ID: BE-QA-CHAT
- Master plan: `docs/plan/plan.md#vs-qa-chat`
- Owner: Hữu Thuận
- Branch: none
- Priority: P1
- Size: M
- Status: pending
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> pending | planned | team1-plan

## Inputs and dependencies

- Requirement sources: Product M4 (§3), BR-09, AC-07, Architecture §6.2 Flow 7
- Consumed fingerprints:
  - `docs/product/product.md` → `871DEC9C`
  - `docs/architecture/architecture.md` → `45F59BC5`
  - `docs/database/database.md` → `F514CB6D`
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

- [ ] Gemini 3.5 Flash Lite configured with system prompt describing DB schema and available tool functions (Architecture §6.2 Flow 7)
- [ ] Tool functions defined for: `get_stranger_vehicles_today`, `get_known_vehicles_today`, `get_gate_events_by_plate`, `get_violations_by_zone`, `get_violations_today`, `get_clip_reference` (Architecture §6.2 Flow 7)
- [ ] Each tool function queries DB via Prisma, returns structured data to LLM
- [ ] LLM synthesizes answer including clip reference when relevant
- [ ] AC-07: "Hôm nay có bao nhiêu xe lạ vào?" → returns correct count + details + clip references
- [ ] At least 5 sample questions answered correctly with clip references (Product §8)
- [ ] Chat history saved to `chat_messages` table (role, content, clip_reference, created_at)
- [ ] `GET /api/v1/chat/history` returns messages ordered by created_at ASC
- [ ] `DELETE /api/v1/chat/history` clears all chat_messages
- [ ] Gemini API timeout (15s) → return 504 with clear error (Architecture §8)
- [ ] Question outside tool scope → LLM responds "không tìm thấy thông tin"
- [ ] BR-09: Only queries saved data, no real-time stream analysis
- [ ] OpenAPI and backend handoff describe only verified behavior for this slice.

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
- Exact next action: Wait for FDN-DB-MIGRATION and event data from VS-GATE-LIVE + VS-AREA-VIOLATION, then implement Gemini function calling
