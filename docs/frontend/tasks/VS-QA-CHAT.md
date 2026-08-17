# VS-QA-CHAT Frontend Task — Hỏi đáp AI: chat + clip player

## Task identity

- Slice ID: VS-QA-CHAT
- Task ID: FE-QA-CHAT
- Master plan: `docs/plan/plan.md#vs-qa-chat`
- Backend task: `docs/backend/tasks/VS-QA-CHAT.md`
- Owner: Hữu Thuận
- Branch: none
- Priority: P1
- Size: M
- Status: waiting_backend
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> waiting_backend | planned | team1-plan

## Inputs and dependencies

- Requirement sources: Product M4, BR-09, AC-07, UI Design Contract §2.5, UI Handoff §2.1
- Consumed fingerprints:
  - `docs/design/ui-design-contract.md` → `F5A9D0E4`
  - `docs/design/ui-to-frontend-handoff.md` → `F40DB9E7`
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

- [ ] AC-07: "Hôm nay có bao nhiêu xe lạ vào?" → correct count + details + clip reference + download button
- [ ] Chat messages load from API history on mount (persistent across sessions)
- [ ] User sends question → loading state → AI response appears
- [ ] AI response with clip → video player with timeline markers, play/pause, "Tải clip 10s" button
- [ ] Suggestion chips trigger pre-defined questions
- [ ] "Xóa lịch sử chat" button clears all messages via API
- [ ] "Sao chép" button copies AI response text
- [ ] Gemini timeout → clear error message (no crash)
- [ ] Mock QA_KNOWLEDGE_BASE removed, real Gemini responses used
- [ ] The flow uses the verified real API; no required production path remains mocked.
- [ ] Required automated integrated evidence is fresh.

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
  - Evidence ID: none
  - Command/procedure: not_run
  - Context: not_run
  - Exit/result: not_run
  - Fresh: no
  - Summary: not_run

## User acceptance and delivery

- Manual acceptance procedure: Q&A tab → ask "Hôm nay có bao nhiêu xe lạ vào?" → verify correct answer + clip
- User acceptance result: not_run
- Pull request: none
- Merge evidence: none
- Post-merge smoke: not_run

## Execution record

- Changed files: none
- Decisions/assumptions: none
- Blocker: waiting for backend gate
- Exact next action: wait for matching backend task to reach `backend_verified`
