# Frontend Architecture & Slice Integration Reference

> Maintained by frontend workers for handoff to team leads and QA/acceptance testers.

## 1. VS-AREA-VIOLATION — Giám sát khu vực (Camera BAI-KIEM)

- **Status**: Stabilized implementation; formal verification pending
- **Assigned Slice**: `VS-AREA-VIOLATION`
- **Owner**: Hữu Thuận
- **Branch**: `feature/vs-area-violation`
- **Matching Backend Gate**: `docs/backend/tasks/VS-AREA-VIOLATION.md` (stabilized; evidence must be refreshed)
- **OpenAPI Contract**: `backend/node-api/openapi/area.yaml`

Latest follow-up behavior: backend identity continuity now prevents repeated rows for one continuous person/container entry, and clip URLs point to the shared Node-served media directory. Existing historical rows are not rewritten.

### 1.1 Route & UI View

- **Tab**: `area` — Giám sát khu vực (`frontend/src/components/AreaMonitor.tsx`)
- **Visuals**:
  - Live video feed rendered via `useCameraFeed('BAI-KIEM')` connected to `WS /ws/feed/area`.
  - Dynamic SVG polygon zones rendered on canvas with deterministic theme color palette (`var(--acc)`, `var(--cyan)`, `var(--purple)`, `var(--ok)`, `var(--p1)`).
  - Bounding boxes: `--p0` red for violation, `--ok` green for allowed, with class/Vietnamese labels.
  - Dynamic rule chips showing prohibited and allowed target vehicle/object classes.
  - Alert panel with real-time events (`WS /ws/events/area` push + `GET /api/v1/events/area` initial load), filter tabs (`Tất cả`, `⚠ Vi phạm`, `✓ Được phép`), and quick search.
  - Hover sync between event row, video bbox, and zone polygon.
  - 10-second MP4 video clip popup playback modal on event rows with `clipUrl`.
  - Cross-tab floating toast alert (`frontend/src/components/FloatingAlert.tsx`) triggered via `WS /ws/alerts` and synchronized across browser tabs using `BroadcastChannel("sentriai-alerts")`.

### 1.2 State & API Wiring

| Source | Hook / API | Transport | Target Component |
|---|---|---|---|
| Historical violations | `getAreaEvents()` (`api/events.ts`) | REST `GET /api/v1/events/area` | `AreaMonitor.tsx` via `useAreaMonitor` |
| Video frame + boxes + zones | `useCameraFeed('BAI-KIEM')` | `WS /ws/feed/area` | `AreaMonitor.tsx` |
| Live violation events | `useWebSocket('/ws/events/area')` | `WS /ws/events/area` | `AreaMonitor.tsx` via `useAreaMonitor` |
| Cross-tab urgent alert | `useWebSocket('/ws/alerts')` + `useBroadcastChannel` | `WS /ws/alerts` + BroadcastChannel | `App.tsx` -> `FloatingAlert.tsx` |

### 1.3 UI States Verified

1. **Loading State**: Displays skeleton / animated spinner with `"Đang kết nối camera bãi kiểm (BAI-KIEM)..."` before first frame.
2. **Online / Live State**: Real-time JPEG frames with bounding boxes, zone overlays, and HUD header `TRỰC TIẾP · 640x480 · FPS`.
3. **Disconnected State**: Overlays `"Mất kết nối camera"` with `"Thử kết nối lại"` action on WebSocket disconnect.
4. **Violation Event Lifecycle**:
   - `STARTED`: Real-time entry appears in event panel with red badge.
   - `ENDED`: Event row updates with duration (`<1s` or `Ns`).
   - Ephemeral allowed detections appear under `"✓ Được phép"` filter while active on feed.
5. **Cross-Tab Alerting**: Red glass toast appears bottom-right when user is on Settings (`/set`), Q&A (`/qa`), or Gate (`/mon`). Clicking `"Xem camera ngay →"` navigates to `/area` and dismisses the alert.

### 1.4 Manual User Acceptance Procedure

1. Start Python worker (`main.py`), Node API (`src/index.ts`), and frontend (`npm run dev`).
2. Open browser tab 1 on **"Giám sát khu vực"**: confirm live feed, SVG polygon zones, and bounding boxes.
3. Trigger prohibited object entering zone: confirm red bbox, alert row in panel.
4. Move object out of zone: confirm row closes with duration.
5. Open browser tab 2 on **"Cài đặt"** or **"Hỏi đáp AI"**: trigger prohibited object entry, confirm red glass floating alert appears in bottom-right.
6. Click **"Xem camera ngay →"**: confirm tab switches to Area monitor and alert is dismissed.

## 2. VS-SETTINGS-ZONE — BAI-KIEM Zone Editor

- **Status**: Implementation complete; real API/browser acceptance pending.
- **Branch**: `feature/vs-settings-zone` (stacked on the committed Area branch).
- **Flow**: Settings → Vẽ zone uses real BAI-KIEM zone data only; Gate selection is intentionally unavailable for this testing phase.
- **API**: Loads/persists `/api/v1/zones?camera_id=BAI-KIEM`, creates/updates/deletes zones, and requests `/api/v1/cameras/BAI-KIEM/snapshot` for the editor background.
- **States**: Loading overlay before snapshot/zones arrive; retry control; static BAI-KIEM image only when camera snapshot fails; API errors are surfaced in the editor.
- **Rule adapter**: UI permission chips for `Người` and `Container` are translated to the compact backend `ALLOW_SPECIFIED` or `PROHIBIT_SPECIFIED` rule plus target-label set. Color remains presentation-only.
- **Basic evidence**: TypeScript/Vite build passes. User must verify browser CRUD and wait approximately five seconds for the Area worker poll before checking the new overlay/rule.
