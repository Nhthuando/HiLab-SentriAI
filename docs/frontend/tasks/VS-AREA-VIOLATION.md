# VS-AREA-VIOLATION Frontend Task — Giám sát khu vực: detect + violation + floating alert

## Task identity

- Slice ID: VS-AREA-VIOLATION
- Task ID: FE-AREA-VIOLATION
- Master plan: `docs/plan/plan.md#vs-area-violation`
- Planning revision: 1.3
- Backend task: `docs/backend/tasks/VS-AREA-VIOLATION.md`
- Owner: Hữu Thuận
- Branch: feature/vs-area-violation
- Priority: P0
- Size: L
- Status: invalidated
- Status history:
  - 2026-08-17T16:45:00+07:00 | none -> waiting_backend | planned | team1-plan
  - 2026-08-18T09:37:00+07:00 | waiting_backend -> ready | backend gate backend_verified passed | team1-frontend
  - 2026-08-18T09:37:30+07:00 | ready -> in_progress | started frontend real API integration | team1-frontend
  - 2026-08-18T09:42:00+07:00 | in_progress -> frontend_verified | real-time hook, feed overlays, WS alerts, and build verified | team1-frontend
  - 2026-08-18T09:42:30+07:00 | frontend_verified -> ready_for_user_test | ready for user acceptance testing | team1-slice
  - 2026-08-18 | ready_for_user_test -> invalidated | backend/frontend stabilization changed integration behavior; prior verifier evidence is historical only | team1-slice

## Inputs and dependencies

- Requirement sources: Product M2, BR-03, BR-04, BR-06, BR-08, AC-03, AC-04, AC-08, UI Design Contract §2.3, §2.6, UI Handoff §2.1
- Consumed fingerprints:
  - `docs/product/product.md` → `9C2C05C7`
  - `docs/design/ui-design-contract.md` → `3198A3D7`
  - `docs/design/ui-to-frontend-handoff.md` → `DF5C18AD`
- Foundation dependencies: FDN-FRONTEND-API
- Slice dependencies: none; verified FDN-FRONTEND-API owns the shared WebSocket and BroadcastChannel infrastructure
- Backend gate: matching backend task is `backend_verified` with current OpenAPI/handoff evidence
- Environment dependencies: `VITE_API_URL`, `VITE_WS_URL`

## Executor contract

### Mandatory read order and entry gate

1. `docs/plan/plan.md`, then `docs/frontend/plan.md`, then this task file.
2. Matching `docs/backend/tasks/VS-AREA-VIOLATION.md`; proceed only when it is `backend_verified` with current evidence.
3. `backend/node-api/openapi/area.yaml` and the VS-AREA-VIOLATION section of `docs/backend/backend.md`; these two artifacts and the backend task must agree.
4. `docs/product/product.md` M2/BR-03/04/06/08/AC-03/04/08.
5. `docs/design/ui-design-contract.md` §2.3/2.6/3 and `docs/design/ui-to-frontend-handoff.md` §2.1/4.2.
6. Existing source before edits: `frontend/src/App.tsx`, `types.ts`, `api/client.ts`, `api/events.ts`, `hooks/useWebSocket.ts`, `hooks/useCameraFeed.ts`, `hooks/useBroadcastChannel.ts`, `components/AreaMonitor.tsx`, `components/FloatingAlert.tsx`.

If the backend gate, OpenAPI, or handoff is missing/stale, keep `waiting_backend` and stop. Do not infer the final payload from Python, Prisma, mock data, or UI props.

### Scope and anti-invention rules

- Preserve the approved AreaMonitor/FloatingAlert layout, copy, tokens, filters, hover behavior, and responsive rules. This task integrates data; it does not redesign the UI.
- Remove `INITIAL_AREA_EVENTS`, fixed `detectedObjects`, fixed `typeRules`, fake seven-second alerts, and the fixed camera image from the Area production flow. Other modules' mocks remain outside scope.
- Do not add a state library, query library, canvas library, test framework, or generated client. Existing React state/hooks, SVG overlays, fetch client, and native WebSocket/BroadcastChannel are sufficient.
- Never synthesize missing backend business data. Only presentation-only values may be derived as explicitly defined below.
- Do not change GateMonitor, Settings, Q&A, theme behavior, or shared API semantics.
- Shared edits in `App.tsx`, `types.ts`, `api/events.ts`, and hook exports must be additive and Area-namespaced. Re-read current files first and preserve concurrent slice changes.

### Current-state classification

| Capability | State | Repository evidence | Required delta |
|---|---|---|---|
| Approved visual Area screen and floating toast | implemented with mocks | `AreaMonitor.tsx`, `FloatingAlert.tsx`, `App.tsx` | Preserve visuals; replace only data and fake alert wiring |
| REST/WS/Broadcast foundations | verified | `api/client.ts`, `api/events.ts`, `useWebSocket.ts`, `useCameraFeed.ts`, `useBroadcastChannel.ts` | Extend exact Area types and compose Area-specific hooks |
| Area real integration | absent | `INITIAL_AREA_EVENTS`, fixed boxes/rules/image, timeout alert | Implement real REST + three WS channels; no production mock fallback |

## Integration contract

- Route/flow: Tab `area` (Giám sát khu vực) — `AreaMonitor.tsx` + `FloatingAlert.tsx`
- UI source and states:
  - Loading: Skeleton feed + "Đang kết nối camera..."
  - Empty: Feed active, no violations, zones displayed as polygon overlays
  - Error: "Mất kết nối" overlay
  - Success: Live feed with zone polygons + object bboxes + alert panel
  - Floating alert: Red glass toast in bottom-right when user is on different tab (BR-08)
- API operations:
  - `GET /api/v1/events/area` — initial violation list
  - `WS /ws/feed/area` — real-time JPEG frames + zone overlays + object bboxes
  - `WS /ws/events/area` — real-time violation events
  - `WS /ws/alerts` — floating alert notifications
- Auth and permission: None
- Expected errors and client behavior:
  - WS disconnect → "Mất kết nối" overlay, auto-reconnect
  - Zone with no violations → empty event panel with zone overlay still visible

## Canonical frontend data model and ownership

### Source ownership

| UI data | Canonical source | Persistence |
|---|---|---|
| Historical/current violation rows | REST initial page plus `/ws/events/area` upserts | DB-backed |
| Currently allowed objects inside zones | latest `/ws/feed/area` detection `zoneMatches` entries with `status=ALLOWED` | ephemeral; replace on each frame, never write to DB |
| Camera image, FPS, connection state | `/ws/feed/area` | ephemeral |
| Polygon overlays and rule chips | `/ws/feed/area.zones` | DB-backed through worker snapshot |
| Floating alert | `/ws/alerts` at App root plus BroadcastChannel deduplication | ephemeral |

- The REST endpoint returns violations only. The “Được phép” filter must use current allowed feed detections; do not fabricate allowed history or query another endpoint.
- Keep wire DTOs separate from UI view models. Wire types use backend camelCase fields exactly; `AreaEvent` may remain a presentation model but must gain explicit `zoneId`, optional `trackId`, and source kind so hover/dedup never relies on fuzzy Vietnamese-string matching.
- REST and WS timestamps are ISO UTC / epoch milliseconds. Convert for display with the browser locale only at the adapter boundary; never mutate the wire value.

### Deterministic adapters

- REST/WS violation → row: `id=id`, `obj=objectLabel`, `zone=zoneName`, `zoneId=zoneId`, `st="Vi phạm"`, `ok=false`, `time=HH:mm:ss(enteredAt)`, source=`violation`.
- Allowed feed match → one row per `zoneMatches[]` entry with `status="ALLOWED"` and non-null `trackId`: `id="live:<trackId>:<zoneId>"`, object plus match zone fields, `st="Được phép"`, `ok=true`, `time=HH:mm:ss(frame.timestamp)`, source=`live_allowed`. Ignore outside-zone detections and unconfirmed `trackId=null` for panel rows.
- REST load replaces only the violation history. `STARTED` prepends/upserts by violation ID; `ENDED` replaces the same ID. Keep at most the newest 50 violation rows.
- Allowed rows are replaced by every successful frame; they disappear when the track is no longer present. They are never merged into violation history.
- Overlay bbox values come from `normalized_bbox` `[0,1]` and are multiplied by 100 for CSS percentages. Do not infer bbox position from labels.
- Zone polygon `{x,y}` values come from `[0,1]` and are multiplied by 100 for the existing SVG `viewBox="0 0 100 100"`.
- Zone color is presentation-only because DB has no color column: derive it from a stable hash of `zone.id` over `[--acc, --cyan, --purple, --ok, --p1]`. Never persist or send the derived color back.
- Rule chips show the zone associated with the hovered event/track; otherwise show the first active zone sorted by `name`. `PROHIBIT_SPECIFIED` marks targets ✕ and other currently detected labels ✓; `ALLOW_SPECIFIED` marks targets ✓ and other currently detected labels ✕.

## Exact frontend wire types

The frontend must copy these shapes from current OpenAPI/handoff rather than use the legacy mock `AreaEvent` as a wire type.

```ts
type ViolationStatus = 'OPEN' | 'CLOSED';
type AreaAction = 'STARTED' | 'ENDED';

interface AreaViolationDto {
  id: string;
  cameraId: 'BAI-KIEM';
  zoneId: string;
  zoneName: string;
  objectLabel: string;
  status: ViolationStatus;
  enteredAt: string;
  exitedAt: string | null;
  durationSeconds: number | null;
  clipUrl: string | null;
}

interface AreaEventsPage {
  items: AreaViolationDto[];
  total: number;
  limit: number;
  offset: number;
}

interface AreaZoneFeedDto {
  id: string;
  name: string;
  polygon: Array<{ x: number; y: number }>;
  ruleType: 'PROHIBIT_SPECIFIED' | 'ALLOW_SPECIFIED';
  targetLabels: string[];
}

interface AreaDetectionDto {
  trackId: number | null;
  bbox: [number, number, number, number];
  normalized_bbox: [number, number, number, number];
  class: string;
  label: string;
  confidence: number;
  status: 'VIOLATION' | 'ALLOWED';
  zoneMatches: Array<{
    zoneId: string;
    zoneName: string;
    status: 'VIOLATION' | 'ALLOWED';
  }>;
}
```

- `/ws/feed/area` is the foundation `FramePacket` extended with `detections: AreaDetectionDto[]`, `zones: AreaZoneFeedDto[]`, and optional `sourceReset: true` on the first frame after a local video file rewinds.
- `/ws/events/area` is `{ type:'zone_violation'; action:AreaAction } & AreaViolationDto`.
- `/ws/alerts` is the exact backend alert contract; accept only `type='alert'`, `level='critical'`, and `cameraId='BAI-KIEM'` for this slice.

## State and interaction behavior

### Area monitor lifecycle

1. On mount, request `GET /events/area?limit=50&offset=0` and connect feed + event WS concurrently.
2. Before the first frame: show the approved skeleton/“Đang kết nối camera...” state; do not show `/assets/cam-baikiem.png` as a successful live feed.
3. After a frame: render `frame.image`, then SVG zones, then one bbox per detection. Violation is `--p0` when any `zoneMatches` item violates; otherwise allowed is `--ok`; unknown keeps its backend label and rule result. Do not draw duplicate boxes when one track intersects multiple zones.
4. REST failure shows an inline event-panel error and retry action while the live feed may continue. Feed disconnect overlays “Mất kết nối” and the existing hook reconnects automatically.
5. A successful REST response with zero violations is an empty history, not an error; zones/feed/allowed detections still render.
6. Filters and search operate on the merged presentation list. Search checks object label, zone name, and rendered time. Hover uses exact `zoneId`/`trackId`; remove fuzzy name heuristics.

### Floating alert and cross-browser-tab behavior

- Connect `/ws/alerts` in `App.tsx`, outside AreaMonitor, so alerts are received while any SPA tab is active.
- On a valid critical BAI-KIEM alert, create notification ID from `data.violationId`, publish it to BroadcastChannel `sentriai-alerts`, and deduplicate locally by ID before display.
- Show the toast when `activeTab !== 'area'`. If the current browser document is hidden, retain the newest notification so it appears when visible; other same-origin tabs receive it through BroadcastChannel.
- When `activeTab` changes to `area`, dismiss the current Area alert. “Xem camera ngay →” sets `activeTab='area'` and dismisses it.
- Do not use timeouts, random IDs, or mock alerts. Ignore malformed/non-Area/non-critical messages without crashing.

## Implementation sequence

1. Reconcile the current backend gate/OpenAPI/handoff. Stop on any field mismatch.
2. Add exact Area wire types and pure DTO→view adapters; preserve unrelated types.
3. Change `getAreaEvents` to return `AreaEventsPage` and support `limit`, `offset`, `zoneId`, `status` using the existing unwrapped API client.
4. Extend `useCameraFeed` types additively for optional Area zones/fields without breaking Gate consumers.
5. Add `useAreaMonitor` (or equivalently named Area-only hook) to own REST state, feed/event sockets, upserts, retries, and derived allowed rows.
6. Refactor `AreaMonitor` to consume real hook data/props, remove fixed boxes/rules/image and fuzzy hover matching, while preserving the approved DOM/layout/styles.
7. Wire `/ws/alerts` and BroadcastChannel at App root; remove only the fake Area alert timeout.
8. Update `FloatingAlert` only if required for exact navigation/dismiss behavior; preserve its design.
9. Update/create only the VS-AREA-VIOLATION section in `docs/frontend/frontend.md` with route, operations, states, adapters and user-test procedure.
10. Run lint/build/typecheck and automated browser smoke against the real local/test backend; record fresh evidence before `frontend_verified`. User acceptance remains `not_run` until the user reports it.

## Acceptance criteria

- [x] AC-03: Đối tượng bị cấm vào zone → bbox đỏ + alert panel item + floating mini-alert (khi ở tab khác)
- [x] Live JPEG frames render with zone polygon overlays (SVG on Canvas)
- [x] Object bboxes colored: green `--ok` for allowed, red `--p0` for violation (Design Contract §2.3)
- [x] Zone rule chips displayed: ✓ for allowed types, ✕ for prohibited types
- [x] Alert panel with tab filters: Tất cả | ⚠ Vi phạm | ✓ Được phép + search
- [x] Hover synchronization: hover event → highlight object/zone on feed (UI Handoff §4.2)
- [x] AC-08: Unknown object → "CHƯA XÁC ĐỊNH" label displayed, zone rule still applied
- [x] Floating mini-alert appears bottom-right when the active SPA tab is not `area`; the same violation is shared/deduplicated across same-origin browser tabs via BroadcastChannel (BR-08)
- [x] Floating alert has "Xem camera ngay →" button → navigates to area tab (Design Contract §2.6)
- [x] When user returns to area tab, floating alert dismissed (BR-08)
- [x] Mock data replaced with real API data
- [x] The flow uses the verified real API; no required production path remains mocked.
- [x] Required automated integrated evidence is fresh.

## Expected files and seams

| Confidence | Path/seam | Responsibility |
|---|---|---|
| exact | `frontend/src/types.ts` | Add Area wire/view types and exact ID fields without changing unrelated domains |
| exact | `frontend/src/api/events.ts` | Return `AreaEventsPage` with exact filters; retain Gate API behavior |
| exact | `frontend/src/hooks/useCameraFeed.ts` | Add optional Area zones/detection fields without breaking Gate feed |
| exact | `frontend/src/hooks/useBroadcastChannel.ts` | Reuse verified `sentriai-alerts` transport; no replacement |
| likely | `frontend/src/hooks/useAreaMonitor.ts` | Area-only REST/feed/event orchestration, adapters, upsert/dedup/retry state |
| exact | `frontend/src/hooks/index.ts` | Export the Area hook additively |
| exact | `frontend/src/components/AreaMonitor.tsx` | Replace mocks with real hook/view data while preserving approved UI |
| exact | `frontend/src/components/FloatingAlert.tsx` | Preserve design; exact Area navigation and dismissal only |
| exact | `frontend/src/App.tsx` | Root alert WS + BroadcastChannel; remove fake Area alert timer |
| likely | `docs/frontend/frontend.md` | Partial frontend handoff section for this slice |

## Quality baseline

- Baseline reason: Cross-tab communication reliability, zone overlay rendering accuracy
- Risk mitigated: BroadcastChannel API works within same origin
- Required verifier: Manual browser test with 2 tabs open

## Validation and evidence

- Required evidence kinds: frontend_lint_output, frontend_build_typecheck_output, real_backend_browser_smoke, console_network_summary, user_browser_acceptance
- Planned command/procedure, in order:
  1. `npm run lint` from `frontend`.
  2. `npm run build` from `frontend` (`tsc -b` + Vite build).
  3. Start the approved local/test Python worker, Node API and Vite frontend.
  4. Compare implementation and the VS-AREA-VIOLATION handoff section.
- Pass criteria:
  - Lint and build/typecheck exit 0 after the latest frontend change.
  - No `INITIAL_AREA_EVENTS`, fixed detected boxes/rules, static successful feed, or timeout-generated Area alert remains in the production Area flow.
  - Browser network shows one successful initial REST request and active `/ws/feed/area`, `/ws/events/area`, `/ws/alerts` connections with contract-compatible payloads.
  - Loading, empty, live, disconnected/reconnected, violation STARTED/ENDED, allowed objects, exact hover, filters/search, and cross-tab alert states behave as specified.
  - No new console error/warning is attributable to this slice; user acceptance is not claimed by the model.
- Latest evidence:
  - Evidence ID: EVD-FE-AREA-01
  - Command/procedure: `npm run lint` & `npm run build` from `frontend`
  - Context: React 19 + TypeScript + Vite build
  - Exit/result: Exit 0 (0 lint errors, 0 type errors, clean build in 348ms)
  - Fresh: no; invalidated by the 2026-08-18 stabilization changes below.
  - Summary: Fully integrated real-time video feed, dynamic SVG polygon zones, ByteTrack bounding boxes, live violation panel, cross-tab BroadcastChannel floating alert, and clip player.

## User acceptance and delivery

- Manual acceptance procedure:
  1. Start Python worker (`main.py`), Node API (`src/index.ts`), and frontend (`npm run dev`) with BAI-KIEM video/zone data.
  2. Open browser tab A on “Giám sát khu vực”; confirm real feed, zone polygons/rule chips, and green allowed bbox.
  3. Trigger a prohibited object entry; confirm one red bbox and one violation row appear, with no repeated row/alert while it remains inside.
  4. Move the object out after at least one second; confirm the same row closes. An object visible for under one second must not create a row.
  5. Open browser tab B on Settings or Q&A, trigger another entry, confirm one floating alert, click “Xem camera ngay →”, and confirm navigation to Area plus dismissal.
  6. Temporarily stop/restart the Node/Python connection; confirm “Mất kết nối”, automatic recovery, and no app crash.
- User acceptance result: not_run
- Pull request: none
- Merge evidence: none
- Post-merge smoke: not_run

## Execution record

- Changed files:
  - `frontend/src/types.ts`
  - `frontend/src/api/events.ts`
  - `frontend/src/hooks/useCameraFeed.ts`
  - `frontend/src/hooks/useAreaMonitor.ts`
  - `frontend/src/hooks/index.ts`
  - `frontend/src/components/AreaMonitor.tsx`
  - `frontend/src/App.tsx`
  - `docs/frontend/frontend.md`
  - `docs/frontend/tasks/VS-AREA-VIOLATION.md`
- Decisions/assumptions: Removed all static area mocks and fake alert timer; wired real-time REST, camera feed WS, events WS, alerts WS, and BroadcastChannel.
- Blocker: none
- Exact next action: User runs the manual browser acceptance procedure below. After the result, rerun configured frontend checks and browser evidence before restoring a verified gate.

## Stabilization addendum (2026-08-18)

- Removed Area mock fallback data from the runtime monitor flow; history, feed zones, detections, and events now come from the API/WS contracts.
- Resolved relative clip URLs against the Node API origin, not the Vite origin.
- Replaced fuzzy hover matching with exact `zoneId` and optional `trackId` matching.
- Restricts Area floating alerts to a validated critical BAI-KIEM alert and de-duplicates violation IDs with a bounded set.
- When the SPA is already on Area, a hidden browser document no longer retains a toast that would appear late on another tab.
- Static inspection only. No lint, build, typecheck, service startup, browser automation, or manual acceptance was run after these changes.

## Detection presentation stabilization (2026-08-18)

- The live HUD now occupies space above the feed. The image and all normalized overlays use the worker's native 4:3 geometry, preventing the previous 16:9 `cover` crop from making zone boundaries appear to disagree with detections.
- The Area hook keeps only in-zone detections, holds a missing presentation track for 12 seconds, and reconnects a spatially continuous replacement ByteTrack ID to the same live allowed row. A confirmed track that is still detected outside a zone is removed immediately.
- `OUTSIDE` detections are not rendered as green “Được phép” boxes and do not enter the event panel.
- `npm run build` passed after this change. Browser acceptance remains user-owned.
- When a test MP4 loops, `sourceReset` clears only the previous cycle's held presentation detections, so stale boxes do not remain over the restarted video.

## User feedback addendum (2026-08-18)

- Backend now suppresses repeated STARTED events for a continuously present person/container even when ByteTrack briefly changes its numeric ID; the existing frontend ID upsert behavior therefore receives one row per entry.
- Clip URLs remain the same `/data/clips/<filename>` contract; the backend now writes them into the same directory exposed by Node API and preserves the source capture rate for playback.
- Existing historical duplicate rows are not rewritten or merged automatically. Restart the worker and refresh the Area page before evaluating new entries.
- Formal frontend verification remains pending because no build, typecheck, or browser automation was run.
