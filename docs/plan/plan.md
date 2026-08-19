# Team1 MVP Delivery Plan

> Planning authority: team lead. Implementers read this file and update only their assigned worker task files.

## Plan identity

- Goal: Deliver SentriAI MVP — hệ thống giám sát camera AI với 4 module (Cổng, Bãi Kiểm, Cài đặt, Q&A) chạy local, single user, demo 2 tuần
- State: planning
- Revision: 1
- Last updated: 2026-08-17T16:45:00+07:00 — team1-plan
- Change authority: team lead through `team1-plan`

## Controlling inputs

| Owner | Path | Approval/revision | SHA-256 | Consumed scope | Last checked |
|---|---|---|---|---|---|
| Product | `docs/product/product.md` | Đã duyệt, HuuThuan, 2026-08-17T14:43:00+07:00 | `871DEC9C` | M1–M4, BR-01–BR-09, AC-01–AC-09 | 2026-08-17T16:45:00+07:00 |
| Architecture | `docs/architecture/architecture.md` | Đã duyệt, 2026-08-17 | `45F59BC5` | §3–§8, stack, flows, risks | 2026-08-17T16:45:00+07:00 |
| Database | `docs/database/database.md` | Đã duyệt, 2026-08-17 | `F514CB6D` | 7 tables, AP-01–AP-07, data rules | 2026-08-17T16:45:00+07:00 |
| Design Contract | `docs/design/ui-design-contract.md` | Approved | `F5A9D0E4` | §1–§3, tokens, components, responsive | 2026-08-17T16:45:00+07:00 |
| UI handoff | `docs/design/ui-to-frontend-handoff.md` | Approved & Ready for Integration | `F40DB9E7` | §1–§5, API mapping, BR mapping, state machine | 2026-08-17T16:45:00+07:00 |

## MVP boundaries

- In scope: M1 (Giám sát cổng GATE-01, 2 làn IN), M2 (Giám sát khu vực BAI-KIEM), M3 (Cài đặt: gắn nhãn xe, vẽ zone, nhãn đối tượng), M4 (Hỏi đáp AI), BR-01–BR-09, AC-01–AC-09
- Out of scope: Fine-tune/re-train model, Docker production, OUT lane, Push notification ngoài app, Phân quyền Admin/Bảo vệ/Viewer, Đa site/đa tổ chức, Âm thanh cảnh báo
- Quality baseline: Input validation, error contract, auth negative paths không cần (single user no auth), migration safety, contract checks (OpenAPI), proportionate unit/integration tests
- Accepted assumptions: 2 camera cố định (GATE-01, BAI-KIEM); COCO class bao phủ hầu hết loại xe; single user no auth; local deployment; demo cần Internet (Neon + Gemini)

## Requirement traceability

| Requirement | Source | Architecture/DB/UI/API impact | Current state | Owning slice | Disposition |
|---|---|---|---|---|---|
| M1-LPR: Nhận diện biển số xe vào làn IN | Product §3 M1, BR-01 | Python AI Worker YOLO+OCR, `gate_events` table, GateMonitor UI, WS `/ws/events/gate` | absent | VS-GATE-LIVE | planned |
| M1-FEED: Live feed cổng với bbox overlay | Product §3 M1 | Python frame→WS→Node proxy→Browser Canvas, GateMonitor UI | absent | VS-GATE-LIVE | planned |
| M1-ALERT: Alert panel real-time sự kiện cổng | Product §3 M1, AC-01, AC-02 | WS events, GateMonitor alert panel | UI mock present | VS-GATE-LIVE | planned |
| M1-CLIP: Clip 10s pre-saved khi event | Product §3 M1, BR-05 | Python circular buffer→MP4, `gate_events.clip_path` | absent | VS-GATE-LIVE | planned |
| M1-QUEN-LA: Phân loại xe quen/lạ | Product §3 M1, BR-02 | `registered_vehicles` lookup, badge UI | absent | VS-GATE-LIVE | planned |
| M2-DETECT: Phát hiện đối tượng trong zone đa giác | Product §3 M2, BR-03, BR-04 | Python YOLO+point-in-polygon, `zone_violations` | absent | VS-AREA-VIOLATION | planned |
| M2-VIOLATION: Sự kiện vi phạm vào/ra zone | Product §3 M2, BR-06, AC-03, AC-04 | Python open/close event, `zone_violations` OPEN→CLOSED | absent | VS-AREA-VIOLATION | planned |
| M2-FEED: Live feed bãi kiểm với zone overlay | Product §3 M2 | Python frame→WS→Node proxy→Browser Canvas, AreaMonitor UI | absent | VS-AREA-VIOLATION | planned |
| M2-FLOAT: Floating mini-alert cross-tab | Product §3 M2, BR-08 | BroadcastChannel API, FloatingAlert component | UI mock present | VS-AREA-VIOLATION | planned |
| M3-VEHICLE: Gắn nhãn biển số quen/lạ | Product §3 M3 | REST CRUD `registered_vehicles`, VehicleLabelTab UI | UI mock present | VS-SETTINGS-VEHICLE | planned |
| M3-ZONE: Vẽ zone đa giác trên khung hình | Product §3 M3, BR-07, AC-05 | REST CRUD `zones`, ZoneEditorTab UI, Python poll zone | UI mock present | VS-SETTINGS-ZONE | planned |
| M3-LABEL: Nhãn đối tượng + gắn mẫu | Product §3 M3, AC-06 | REST CRUD `object_labels` + `label_samples`, ObjectLabelTab UI | UI mock present | VS-SETTINGS-LABEL | planned |
| M4-QA: Chat hỏi đáp AI sự kiện | Product §3 M4, BR-09, AC-07 | Gemini function calling, `chat_messages`, AIQAChat UI | UI mock present | VS-QA-CHAT | planned |
| M4-CLIP-REF: Clip reference trong câu trả lời Q&A | Product §3 M4 | Gemini tool response + clip URL, video player UI | UI mock present | VS-QA-CHAT | planned |
| EXCEPTION: Stream ngắt hiển thị "Mất kết nối" | Product §7, AC-09 | Python reconnect loop, WS disconnect event, UI state | absent | VS-GATE-LIVE | planned |
| EXCEPTION: Clip ghi fail → clip=null | Product §7, BR-05 | Python try/except clip writer | absent | VS-GATE-LIVE | planned |

## Foundation phase

| ID | Foundation | Current evidence | Missing outcome | Consumers | Size | Owner | Status | Evidence gate |
|---|---|---|---|---|---|---|---|---|
| FDN-REPO-SCAFFOLD | Repository scaffold: python-worker, node-api, .env.example, scripts | None — only `frontend/` and `docs/` exist | `python-worker/`, `node-api/` directories with package manifests, `.env.example`, `data/clips/`, `data/crops/` | All slices | M | Hữu Thuận | completed | directories exist, `pip install` + `npm install` succeed |
| FDN-DB-MIGRATION | Prisma schema + migration cho 7 tables | `backend/node-api/prisma/schema.prisma` with all tables, `npx prisma migrate deploy` succeeds against Neon | All slices except VS-QA-CHAT (indirectly) | M | Hữu Thuận | completed | `npx prisma migrate deploy` exits 0 (2 migrations applied); all 7 tables + 8 CHECK constraints confirmed in Neon via `db pull` |
| FDN-PYTHON-DB | Python asyncpg client + connection pool for Neon | `backend/python-worker/db/` module with connection pool, basic CRUD helpers | VS-GATE-LIVE, VS-AREA-VIOLATION | S | Hữu Thuận | completed | Python connects, executes AP-01 to AP-06 CRUD, verifies jsonb codecs, exits 0 on full test suite |
| FDN-WS-PROXY | Node.js WebSocket proxy: Python→Node→Browser | `node-api/src/ws/` WebSocket proxy with path routing, channel isolation & broadcast helpers | VS-GATE-LIVE, VS-AREA-VIOLATION | M | Hữu Thuận | completed | Browser receives test frame via WS chain, channel isolation + publishing verified on full test suite |
| FDN-PYTHON-STREAM | Python AI Worker: OpenCV stream reader + YOLO inference pipeline | `python-worker/stream/`, `detection/`, `buffer/` modules with 640x480 resize, YOLOv8n, clip buffer, WS emitter | VS-GATE-LIVE, VS-AREA-VIOLATION | M | Hữu Thuận | completed | Python reads video stream, runs YOLO, extracts MP4 clip from buffer, emits annotated frames via WS |
| FDN-API-CONTRACT | Node.js Express REST scaffold + API versioning + error contract | `node-api/src/routes/` with health check, Prisma client, error middleware, standard envelope, static media routes | All backend slices | S | Hữu Thuận | completed | `GET /api/v1/health` returns 200 with database connected, error contract & static media verified |
| FDN-FRONTEND-API | Frontend API client + WebSocket hooks | `frontend/src/api/` + `frontend/src/hooks/useWebSocket.ts`, `useCameraFeed.ts`, `useBroadcastChannel.ts` | All frontend slices | S | Hữu Thuận | completed | `npm run build` exits 0 (322ms), all 7 API modules + 3 hooks type-safe |

## Vertical slices

### VS-GATE-LIVE — Giám sát cổng real-time: LPR + live feed + alert + clip

- Priority: P0
- Size: L
- Owner: Phạm Hưng
- Status: verified
- Requirements: M1-LPR, M1-FEED, M1-ALERT, M1-CLIP, M1-QUEN-LA, EXCEPTION-STREAM, EXCEPTION-CLIP
- Dependencies: FDN-REPO-SCAFFOLD, FDN-DB-MIGRATION, FDN-PYTHON-DB, FDN-WS-PROXY, FDN-PYTHON-STREAM, FDN-API-CONTRACT, FDN-FRONTEND-API
- Contract checkpoint: `GET /api/v1/events/gate`, `WS /ws/feed/gate`, `WS /ws/events/gate`
- Backend task: `docs/backend/tasks/VS-GATE-LIVE.md`
- Frontend task: `docs/frontend/tasks/VS-GATE-LIVE.md`
- Acceptance summary:
  - AC-01: Xe vào làn IN → bbox + biển số + badge quen/lạ trên feed trong <= 500ms
  - AC-02: Sự kiện cổng ghi đủ: timestamp, biển số, làn, trạng thái, ảnh cắt, clip 10s
  - AC-09: Stream ngắt → app hiện "Mất kết nối", không crash
- Critical negative paths:
  - Biển số confidence thấp → vẫn ghi event (BR-04)
  - Clip ghi fail → clip_path = null, event vẫn ghi (BR-05)
  - Stream ngắt → reconnect + UI "Mất kết nối" (AC-09)
- Quality baseline:
  - Reason/risk: R1 Performance (2 stream YOLO), R3 Clip storage, R4 OCR accuracy
  - Verifier: Python unit test cho LPR pipeline + manual video test
- Conflict zones: `python-worker/detection/`, `node-api/src/ws/`, `frontend/src/components/GateMonitor.tsx`
- Ready when: All FDN-* foundations are completed
- Done when: backend verified, real API frontend verified, automated integrated checks pass, user acceptance passes, peer review and merge complete, post-merge smoke passes

### VS-AREA-VIOLATION — Giám sát khu vực: detect + violation event + floating alert

- Priority: P0
- Size: L
- Owner: Hữu Thuận
- Status: planned
- Requirements: M2-DETECT, M2-VIOLATION, M2-FEED, M2-FLOAT
- Dependencies: FDN-REPO-SCAFFOLD, FDN-DB-MIGRATION, FDN-PYTHON-DB, FDN-WS-PROXY, FDN-PYTHON-STREAM, FDN-API-CONTRACT, FDN-FRONTEND-API, VS-GATE-LIVE (shared Python stream infrastructure)
- Contract checkpoint: `GET /api/v1/events/area`, `WS /ws/feed/area`, `WS /ws/events/area`, `WS /ws/alerts`
- Backend task: `docs/backend/tasks/VS-AREA-VIOLATION.md`
- Frontend task: `docs/frontend/tasks/VS-AREA-VIOLATION.md`
- Acceptance summary:
  - AC-03: Đối tượng cấm vào zone → bbox đỏ + alert panel + floating mini-alert
  - AC-04: Vi phạm có: thời gian vào/ra, duration, clip 10s từ lúc vào
- Critical negative paths:
  - Đối tượng không khớp class → "CHƯA XÁC ĐỊNH" + vẫn check zone rule (BR-03, BR-04, AC-08)
  - Đối tượng vào/ra < 1s → vẫn sinh event (Product §7)
  - Vi phạm kéo dài → 1 event, không spam alert (BR-06)
- Quality baseline:
  - Reason/risk: R1 Performance, point-in-polygon accuracy
  - Verifier: Python unit test cho zone check + manual video test
- Conflict zones: `python-worker/zone/`, `python-worker/detection/`, `frontend/src/components/AreaMonitor.tsx`, `frontend/src/components/FloatingAlert.tsx`
- Ready when: FDN-* completed, VS-GATE-LIVE stream infrastructure merged (shared Python stream reader)
- Done when: backend verified, real API frontend verified, automated integrated checks pass, user acceptance passes, peer review and merge complete, post-merge smoke passes

### VS-SETTINGS-VEHICLE — Cài đặt: quản lý danh sách biển số xe

- Priority: P1
- Size: S
- Owner: Phạm Hưng
- Status: verified
- Requirements: M3-VEHICLE
- Dependencies: FDN-DB-MIGRATION, FDN-API-CONTRACT, FDN-FRONTEND-API
- Contract checkpoint: `GET /api/v1/vehicles`, `POST /api/v1/vehicles`, `PATCH /api/v1/vehicles/:id`, `DELETE /api/v1/vehicles/:id`
- Backend task: `docs/backend/tasks/VS-SETTINGS-VEHICLE.md`
- Frontend task: `docs/frontend/tasks/VS-SETTINGS-VEHICLE.md`
- Acceptance summary:
  - CRUD biển số xe hoạt động đầy đủ
  - Toggle quen/lạ cập nhật DB ngay, Python Worker lookup biển chính xác
- Critical negative paths:
  - Biển số trùng → API trả 409 Conflict
- Quality baseline:
  - Reason/risk: Input validation biển số
  - Verifier: API unit test
- Conflict zones: `node-api/src/routes/vehicles.ts`, `frontend/src/components/Settings/VehicleLabelTab.tsx`
- Ready when: FDN-DB-MIGRATION, FDN-API-CONTRACT completed
- Done when: backend verified, real API frontend verified, automated integrated checks pass, user acceptance passes, peer review and merge complete, post-merge smoke passes

### VS-SETTINGS-ZONE — Cài đặt: vẽ zone đa giác + zone rules

- Priority: P1
- Size: M
- Owner: Phạm Hưng
- Status: planned
- Requirements: M3-ZONE
- Dependencies: FDN-DB-MIGRATION, FDN-API-CONTRACT, FDN-FRONTEND-API
- Contract checkpoint: `GET /api/v1/zones`, `POST /api/v1/zones`, `PUT /api/v1/zones/:id`, `DELETE /api/v1/zones/:id`, `GET /api/v1/cameras/:id/snapshot`
- Backend task: `docs/backend/tasks/VS-SETTINGS-ZONE.md`
- Frontend task: `docs/frontend/tasks/VS-SETTINGS-ZONE.md`
- Acceptance summary:
  - AC-05: Vẽ zone mới → zone active ngay trên màn hình giám sát
  - Zone CRUD lưu/đọc tọa độ polygon chính xác
  - Python Worker poll zone mỗi 5s, zone mới có hiệu lực
- Critical negative paths:
  - Zone trùng tên trên cùng camera → API trả 409
  - Xóa zone đang có violation → RESTRICT (DB rule)
- Quality baseline:
  - Reason/risk: BR-07 real-time update, polygon data integrity
  - Verifier: API test + manual zone create→verify on monitoring
- Conflict zones: `node-api/src/routes/zones.ts`, `frontend/src/components/Settings/ZoneEditorTab.tsx`
- Ready when: FDN-DB-MIGRATION, FDN-API-CONTRACT completed
- Done when: backend verified, real API frontend verified, automated integrated checks pass, user acceptance passes, peer review and merge complete, post-merge smoke passes

### VS-SETTINGS-LABEL — Cài đặt: nhãn đối tượng + gắn mẫu

- Priority: P1
- Size: M
- Owner: Phạm Hưng
- Status: verified
- Requirements: M3-LABEL
- Dependencies: FDN-DB-MIGRATION, FDN-API-CONTRACT, FDN-FRONTEND-API
- Contract checkpoint: `GET /api/v1/labels`, `POST /api/v1/labels`, `PUT /api/v1/labels/:id`, `DELETE /api/v1/labels/:id`, `POST /api/v1/samples/batch`, `POST /api/v1/upload/image`
- Backend task: `docs/backend/tasks/VS-SETTINGS-LABEL.md`
- Frontend task: `docs/frontend/tasks/VS-SETTINGS-LABEL.md`
- Acceptance summary:
  - AC-06: Nhãn đã lưu → xuất hiện trong dropdown loại của zone config
  - Upload ảnh/video + vẽ bbox + lưu batch thành công
  - >= 5 loại nhãn, >= 20 mẫu/loại (success metrics)
- Critical negative paths:
  - Nhãn trùng vietnamese_name → 409
  - Xóa nhãn → cascade xóa label_samples
- Quality baseline:
  - Reason/risk: File upload validation, bbox data integrity
  - Verifier: API test + manual label workflow
- Conflict zones: `node-api/src/routes/labels.ts`, `frontend/src/components/Settings/ObjectLabelTab.tsx`
- Ready when: FDN-DB-MIGRATION, FDN-API-CONTRACT completed
- Done when: backend verified, real API frontend verified, automated integrated checks pass, user acceptance passes, peer review and merge complete, post-merge smoke passes

### VS-QA-CHAT — Hỏi đáp AI: Gemini function calling + clip reference

- Priority: P1
- Size: M
- Owner: Hữu Thuận
- Status: planned
- Requirements: M4-QA, M4-CLIP-REF
- Dependencies: FDN-DB-MIGRATION, FDN-API-CONTRACT, FDN-FRONTEND-API, VS-GATE-LIVE (events data for querying), VS-AREA-VIOLATION (violations data for querying)
- Contract checkpoint: `POST /api/v1/qa/query`, `GET /api/v1/clips/:id/stream`, `GET /api/v1/clips/:id/download`, `GET /api/v1/chat/history`, `DELETE /api/v1/chat/history`
- Backend task: `docs/backend/tasks/VS-QA-CHAT.md`
- Frontend task: `docs/frontend/tasks/VS-QA-CHAT.md`
- Acceptance summary:
  - AC-07: Query "Hôm nay có bao nhiêu xe lạ vào?" → số đúng + chi tiết + clip reference + nút tải
  - >= 5 câu hỏi mẫu cơ bản có kèm clip tham chiếu (success metrics)
  - Lịch sử chat persistent qua reload
- Critical negative paths:
  - Gemini timeout → trả lỗi rõ ràng (Architecture §8: 15s timeout)
  - Câu hỏi ngoài scope → LLM trả "không tìm thấy thông tin"
  - Clip không tồn tại → hiển thị "không có clip"
- Quality baseline:
  - Reason/risk: LLM query an toàn (function calling), Gemini API timeout
  - Verifier: Manual Q&A test with 5 sample questions
- Conflict zones: `node-api/src/ai/`, `node-api/src/routes/qa.ts`, `frontend/src/components/AIQAChat.tsx`
- Ready when: FDN-DB-MIGRATION, FDN-API-CONTRACT completed; event data exists from VS-GATE-LIVE and VS-AREA-VIOLATION
- Done when: backend verified, real API frontend verified, automated integrated checks pass, user acceptance passes, peer review and merge complete, post-merge smoke passes

### VS-KPI-ANALYTICS — KPI Dashboard: thống kê tổng quan

- Priority: P2
- Size: S
- Owner: Hữu Thuận
- Status: planned
- Requirements: KPI display on GateMonitor (4 KPI cards), AreaMonitor (4 KPI cards)
- Dependencies: FDN-DB-MIGRATION, FDN-API-CONTRACT, FDN-FRONTEND-API, VS-GATE-LIVE, VS-AREA-VIOLATION
- Contract checkpoint: `GET /api/v1/analytics/kpis`
- Backend task: `docs/backend/tasks/VS-KPI-ANALYTICS.md`
- Frontend task: `docs/frontend/tasks/VS-KPI-ANALYTICS.md`
- Acceptance summary:
  - KPI cards hiển thị dữ liệu chính xác từ DB (tổng lượt xe, biển đọc thành công, vi phạm hôm nay, etc.)
- Critical negative paths:
  - Không có data → hiển thị 0
- Quality baseline:
  - Reason/risk: none
  - Verifier: Manual data comparison
- Conflict zones: `frontend/src/components/GateMonitor.tsx`, `frontend/src/components/AreaMonitor.tsx`
- Ready when: VS-GATE-LIVE and VS-AREA-VIOLATION backend_verified
- Done when: backend verified, real API frontend verified, automated integrated checks pass, user acceptance passes, peer review and merge complete, post-merge smoke passes

## Dependency and parallelization map

- Critical path: FDN-REPO-SCAFFOLD → FDN-DB-MIGRATION → FDN-PYTHON-DB + FDN-API-CONTRACT → FDN-WS-PROXY + FDN-PYTHON-STREAM → VS-GATE-LIVE → VS-AREA-VIOLATION → VS-QA-CHAT → VS-KPI-ANALYTICS
- Safe parallel slices:
  - After FDN-DB-MIGRATION + FDN-API-CONTRACT: VS-SETTINGS-VEHICLE ‖ VS-SETTINGS-ZONE ‖ VS-SETTINGS-LABEL (tất cả 3 slice cài đặt có thể chạy song song)
  - FDN-PYTHON-DB ‖ FDN-API-CONTRACT ‖ FDN-FRONTEND-API (3 foundation song song sau FDN-DB-MIGRATION)
- Sequential gates:
  - VS-AREA-VIOLATION chờ VS-GATE-LIVE (shared Python stream infrastructure)
  - VS-QA-CHAT chờ VS-GATE-LIVE + VS-AREA-VIOLATION (cần event data)
  - VS-KPI-ANALYTICS chờ VS-GATE-LIVE + VS-AREA-VIOLATION
- Shared conflict zones:
  - `python-worker/detection/` — VS-GATE-LIVE và VS-AREA-VIOLATION cùng sử dụng
  - `node-api/src/ws/` — VS-GATE-LIVE và VS-AREA-VIOLATION cùng sử dụng WS proxy
  - `frontend/src/hooks/` — tất cả frontend slices cùng dùng API client hooks

## Work Allocation

| Slice | Outcome | Owner | Branch convention | Ready? | Blocker |
|---|---|---|---|---|---|
| FDN-REPO-SCAFFOLD | Repository directories + manifests | Hữu Thuận | `feature/fdn-repo-scaffold` | yes | none |
| FDN-DB-MIGRATION | Prisma schema + 7 tables | Hữu Thuận | `feature/fdn-db-migration` | no | FDN-REPO-SCAFFOLD |
| FDN-PYTHON-DB | Python asyncpg pool | Hữu Thuận | `feature/fdn-python-db` | no | FDN-REPO-SCAFFOLD |
| FDN-WS-PROXY | Node→Browser WS proxy | Hữu Thuận | `feature/fdn-ws-proxy` | no | FDN-REPO-SCAFFOLD, FDN-API-CONTRACT |
| FDN-PYTHON-STREAM | YOLO stream pipeline | Hữu Thuận | `feature/fdn-python-stream` | no | FDN-REPO-SCAFFOLD |
| FDN-API-CONTRACT | Express REST scaffold | Hữu Thuận | `feature/fdn-api-contract` | no | FDN-REPO-SCAFFOLD |
| FDN-FRONTEND-API | Frontend API client + hooks | Hữu Thuận | `feature/fdn-frontend-api` | no | FDN-REPO-SCAFFOLD |
| VS-GATE-LIVE | LPR + live feed + alert + clip | Phạm Hưng | `feature/vs-gate-live` | no | All FDN-* |
| VS-AREA-VIOLATION | Zone detect + violation + floating alert | Hữu Thuận | `feature/vs-area-violation` | no | All FDN-*, VS-GATE-LIVE |
| VS-SETTINGS-VEHICLE | Vehicle CRUD + label toggle | Phạm Hưng | `feature/vs-settings-vehicle` | no | FDN-DB-MIGRATION, FDN-API-CONTRACT, FDN-FRONTEND-API |
| VS-SETTINGS-ZONE | Zone polygon CRUD | Phạm Hưng | `feature/vs-settings-zone` | no | FDN-DB-MIGRATION, FDN-API-CONTRACT, FDN-FRONTEND-API |
| VS-SETTINGS-LABEL | Object label + sample CRUD | Phạm Hưng | `feature/vs-settings-label` | no | FDN-DB-MIGRATION, FDN-API-CONTRACT, FDN-FRONTEND-API |
| VS-QA-CHAT | Gemini Q&A + clip ref | Hữu Thuận | `feature/vs-qa-chat` | no | FDN-DB-MIGRATION, FDN-API-CONTRACT, FDN-FRONTEND-API, VS-GATE-LIVE, VS-AREA-VIOLATION |
| VS-KPI-ANALYTICS | KPI dashboard cards | Hữu Thuận | `feature/vs-kpi-analytics` | no | VS-GATE-LIVE, VS-AREA-VIOLATION |

The team lead and members must confirm unassigned work before implementation. A local unpushed branch is not visible assignment evidence.

## Definition of Done

- [ ] Backend implementation and current API contract are verified.
- [ ] Frontend integrates the real verified API and required UI states.
- [ ] Relevant automated integrated checks pass.
- [ ] User acceptance testing passes.
- [ ] No required production path remains mocked.
- [ ] Peer review passes and PR is merged.
- [ ] Post-merge smoke passes on `main`.
- [ ] Worker task evidence is current and blockers are resolved.

## Blockers and decisions

| ID | Type | Affected work | Evidence | Owner/action | Resume point |
|---|---|---|---|---|---|
| none | — | — | — | — | — |

## Change and invalidation history

| Timestamp | Plan revision | Changed inputs/sections | Affected tasks | Preserved tasks | Decision |
|---|---|---|---|---|---|
| 2026-08-17T16:45:00+07:00 | 1 | initial baseline | FDN-REPO-SCAFFOLD, FDN-DB-MIGRATION, FDN-PYTHON-DB, FDN-WS-PROXY, FDN-PYTHON-STREAM, FDN-API-CONTRACT, FDN-FRONTEND-API, VS-GATE-LIVE, VS-AREA-VIOLATION, VS-SETTINGS-VEHICLE, VS-SETTINGS-ZONE, VS-SETTINGS-LABEL, VS-QA-CHAT, VS-KPI-ANALYTICS | none | created |
| 2026-08-17T17:03:00+07:00 | 1.1 | Work allocation | All tasks | All | Assigned owners: Phạm Hưng (VS-GATE-LIVE, VS-SETTINGS-*), Hữu Thuận (Foundations, VS-AREA-VIOLATION, VS-QA-CHAT, VS-KPI-ANALYTICS) |

## Planning status

- State: allocated
- Ready slices: FDN-REPO-SCAFFOLD
- Blocked slices: FDN-DB-MIGRATION, FDN-PYTHON-DB, FDN-WS-PROXY, FDN-PYTHON-STREAM, FDN-API-CONTRACT, FDN-FRONTEND-API, VS-GATE-LIVE, VS-AREA-VIOLATION, VS-SETTINGS-VEHICLE, VS-SETTINGS-ZONE, VS-SETTINGS-LABEL, VS-QA-CHAT, VS-KPI-ANALYTICS
- Unassigned slices: none
- Next team-lead action: Bắt đầu triển khai FDN-REPO-SCAFFOLD (Hữu Thuận)
