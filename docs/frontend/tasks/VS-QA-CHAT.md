# VS-QA-CHAT Frontend Task — Hỏi đáp AI: chat + clip player

## Task identity

- Slice ID: VS-QA-CHAT
- Task ID: FE-QA-CHAT
- Master plan: `docs/plan/plan.md#vs-qa-chat`
- Backend task: `docs/backend/tasks/VS-QA-CHAT.md`
- Owner: Hữu Thuận
- Branch: feature/vs-qa-chat
- Priority: P1
- Size: M
- Status: ready_for_user_test
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> waiting_backend | planned | team1-plan
  - 2026-08-27T19:58:23+07:00 | waiting_backend -> ready | matching backend task is backend_verified; OpenAPI/handoff and controlling fingerprints reconciled | team1-frontend
  - 2026-08-27T19:58:23+07:00 | ready -> in_progress | began approved real-API frontend integration on feature/vs-qa-chat | team1-frontend
  - 2026-08-27T20:27:40+07:00 | in_progress -> frontend_verified | build/lint passed; 5/5 real Gemini browser questions, persistence, copy, real clip playback/download URLs, loading/no-clip, 503/504 states and screenshots verified | team1-frontend
  - 2026-08-27T20:27:40+07:00 | frontend_verified -> ready_for_user_test | frontend and backend gates current; handed back for Hữu Thuận browser acceptance | team1-slice
  - 2026-08-27T21:30:00+07:00 | ready_for_user_test -> invalidated | approved activity-analytics delta changes Q&A evidence and lazy activity-clip behavior | team1-slice/team1-frontend
  - 2026-08-27T21:30:00+07:00 | invalidated -> in_progress | integrated persisted activity evidence and request-on-view clip states | team1-frontend
  - 2026-08-27T22:14:00+07:00 | in_progress -> frontend_verified | real browser Q&A, activity evidence, explicit clip request/poll/playback and production gates passed | team1-frontend
  - 2026-08-27T22:14:00+07:00 | frontend_verified -> ready_for_user_test | activity delta handed back for Hữu Thuận acceptance | team1-slice

## Inputs and dependencies

- Requirement sources: Product M4, BR-09, AC-07, UI Design Contract §2.5, UI Handoff §2.1
- Consumed fingerprints:
  - `docs/design/ui-design-contract.md` → `3198A3D7`
  - `docs/design/ui-to-frontend-handoff.md` → `70CBF2AE`
- Foundation dependencies: FDN-FRONTEND-API
- Slice dependencies: VS-GATE-LIVE (event data), VS-AREA-VIOLATION (violation data)
- Backend gate: matching backend task is `backend_verified` with current OpenAPI/handoff evidence
- Environment dependencies: `VITE_API_URL`

## Integration contract

- Route/flow: Tab `qa` (Hỏi đáp AI) — `AIQAChat.tsx`
- UI source and states:
  - Loading: Chat loading spinner while waiting for Gemini response
  - Empty: Welcome message + suggestion chips
  - Error: Error message for Gemini timeout/unavailable
  - Success: Chat messages with AI response + optional video clip player
- API operations:
  - `POST /api/v1/qa/query` — submit question
  - `GET /api/v1/chat/history` — load chat history
  - `DELETE /api/v1/chat/history` — clear history
  - `GET /api/v1/clips/:id/stream` — stream clip video
  - `GET /api/v1/clips/:id/download` — download clip
- Auth and permission: None
- Expected errors and client behavior:
  - 503 Gemini unavailable → "AI đang không khả dụng, vui lòng thử lại"
  - 504 Gemini timeout → "AI phản hồi quá chậm, vui lòng thử lại"
  - No clip → "Không có clip" message

## Acceptance criteria

- [x] AC-07: "Hôm nay có bao nhiêu xe lạ vào?" → correct count + details + clip reference + download button
- [x] Chat messages load from API history on mount (persistent across sessions)
- [x] User sends question → loading state → AI response appears
- [x] AI response with clip → video player with timeline markers, play/pause, "Tải clip 10s" button
- [x] Suggestion chips trigger pre-defined questions
- [x] "Xóa lịch sử chat" button clears all messages via API
- [x] "Sao chép" button copies AI response text
- [x] Gemini timeout → clear error message (no crash)
- [x] Mock QA_KNOWLEDGE_BASE removed, real Gemini responses used
- [x] The flow uses the verified real API; no required production path remains mocked.
- [x] Required automated integrated evidence is fresh.
- [x] Vehicle activity answers display verified counts/status/duration plus one or more persisted activity evidence references.
- [x] An activity without a generated clip displays `Xem video`; only that action requests generation, polls status and mounts the playable media when ready.
- [x] Existing Gate/Area Q&A, copy, history, errors and unrelated screens remain intact.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `frontend/src/components/AIQAChat.tsx` | Replace mock with real API calls |
| likely | `frontend/src/api/qa.ts` | Q&A API client |
| likely | `frontend/src/api/chat.ts` | Chat history API client |
| exact | `frontend/src/mockData.ts` | Remove QA_KNOWLEDGE_BASE mock |

## Quality baseline

- Baseline reason: Gemini timeout handling, clip player reliability
- Risk mitigated: API error handling prevents UI hang
- Required verifier: Manual Q&A test with 5 sample questions

## Validation and evidence

- Required evidence kinds: browser_screenshot, manual_flow_test
- Planned command/procedure: Open Q&A tab → ask 5 sample questions → verify answers + clip players + history persistence
- Pass criteria: 5/5 questions answered correctly, clips playable, history persists
- Latest evidence:
  - Evidence ID: FE-QA-BUILD-20260827
  - Command/procedure: `npm.cmd run build`; `npm.cmd run lint`; `git diff --check`
  - Context: `frontend/` and repository root on `feature/vs-qa-chat`, 2026-08-27
  - Exit/result: pass / pass / pass
  - Fresh: yes
  - Summary: TypeScript/Vite production build and oxlint passed; only the pre-existing Vite ineffective dynamic import warning for `api/labels.ts` was reported.
  - Evidence ID: FE-QA-BROWSER-20260827
  - Command/procedure: isolated `agent-browser` session at `http://localhost:5173/` against `http://localhost:3001/api/v1`; submit 5 real-data questions, reload, play clip, inspect media/network/errors, copy response, and exercise delayed/504 dev-only response injection.
  - Context: development/test Neon data and configured Gemini key; user consent recorded; browser origin matched configured CORS.
  - Exit/result: pass — 5/5 successful real answers; one transient real 503 was surfaced correctly and retry passed; no unhandled page errors.
  - Fresh: yes
  - Summary: AC-07 returned 3 strangers with all expected plates and UTC+07 times; five persistent assistant responses hydrated five players/download links after reload; selected real MP4 reached readyState 4 and played with `206`; copy changed to `Đã chép`; loading, no-clip, 503 and 504 copy matched the contract. Screenshots: `docs/frontend/evidence/vs-qa-chat-empty.png`, `vs-qa-chat-loading.png`, `vs-qa-chat-timeout.png`, `vs-qa-chat-success.png`.
  - Evidence ID: FE-QA-CLEAR-CONTRACT-20260827
  - Command/procedure: verified `clearChatHistory()` → `DELETE /chat/history` → state reset only after success; matching backend endpoint previously returned 204 in fresh QA verification.
  - Context: integrated client/backend contract; destructive browser click deferred to user acceptance because it clears the entire single-user history.
  - Exit/result: pass at client/contract level; browser acceptance action intentionally pending.
  - Fresh: yes
  - Summary: Current history contains 11 rows (6 user, 5 assistant), all created after the confirmed zero-row browser baseline and retained for user review/clear acceptance.
  - Evidence ID: `FE-QA-ACTIVITY-BROWSER-20260827`
  - Command/procedure: isolated real browser session; ask “Hôm nay có bao nhiêu xe tải ra vào và làm việc ra sao?”, inspect the answer/evidence, click `Xem video`, observe request/polling, and inspect the native player/media request.
  - Context: local frontend `5173`, API `3001`, worker `8001`, real BAI-KIEM/Neon data and user-approved Gemini transmission.
  - Exit/result: pass
  - Fresh: yes
  - Summary: Q&A POST 200; returned one ALLOWED truck session lasting 29 seconds; clip request returned 202 and polling 200 until ready; media returned 206; player reached readyState 4 with duration 10.048 and no media error. Screenshots `vs-qa-chat-activity.png`, `vs-qa-chat-activity-answer.png`, and `vs-qa-chat-activity-final.png`; six failed/interrupted test chat rows were removed by exact ID, preserving all 15 prior rows and six correct forklift/truck rows (21 total).

## User acceptance and delivery

- Manual acceptance procedure: Open `http://localhost:5173/` → Hỏi đáp AI; review the retained correct forklift/truck statistics, ask “Hôm nay xe con hoạt động thế nào?”, verify count/status/duration/evidence, click `Xem video`, wait for playback, then reload to confirm persistence. Clear the whole history only if you intentionally want to remove all 21 retained rows.
- User acceptance result: ready_for_user_test — pending Hữu Thuận
- Pull request: none
- Merge evidence: none
- Post-merge smoke: pending until a merge exists

## Execution record

- Changed files: `frontend/src/App.tsx`, `frontend/src/components/AIQAChat.tsx`, `frontend/src/api/qa.ts`, `frontend/src/api/chat.ts`, `frontend/src/api/index.ts`, `frontend/src/types.ts`, `frontend/src/mockData.ts`, `frontend/src/index.css`, `docs/frontend/frontend.md`, `docs/frontend/tasks/VS-QA-CHAT.md`, and `docs/frontend/evidence/vs-qa-chat-*.png`.
- Decisions/assumptions: The approved visual layout is preserved. Production Q&A/history/clip paths are real; browser-only delayed/504 response injection was used solely to make transient UI states deterministic. Native video controls use `preload="none"`. Activity clips are requested only through the explicit `Xem video` action. Current history has 21 rows: 15 pre-existing rows plus six correct forklift/truck test rows; failed test noise was removed without clearing history.
- Blocker: none
- Exact next action: Hữu Thuận runs the activity-focused manual acceptance procedure and reports pass/fail; on pass, advance to `ready_for_pr` without commit/push/PR in this workflow.
