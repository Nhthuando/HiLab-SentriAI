# UI-to-Frontend Handoff — SentriAI

> **Tài liệu bàn giao UI sang Frontend & Backend Integration (UI-to-Frontend Handoff)**
> **Sản phẩm:** SentriAI — Hệ thống Giám sát Camera AI & Nhận diện Biển số
> **Trạng thái:** `Approved & Ready for Integration`
> **Mục tiêu:** Ánh xạ chi tiết từ các component giao diện Golden Page sang API contract, WebSocket stream và các quy tắc nghiệp vụ backend (BR-01 đến BR-09).

---

## 1. Cấu trúc Cây Component & Thư mục Mã nguồn

```
frontend/
├── index.html                     # HTML Template, Google Fonts (Inter, IBM Plex Mono), SEO
├── package.json                   # Dependencies: react 19, react-dom 19, lucide-react, vite
├── tsconfig.json                  # TypeScript config (strict, verbatimModuleSyntax)
├── public/
│   └── assets/
│       ├── cam-gate.png           # Frame camera thực tế Cổng vào (GATE-01)
│       └── cam-baikiem.png        # Frame camera thực tế Bãi kiểm (BAI-KIEM)
└── src/
    ├── index.css                  # Toàn bộ Design Tokens, Glassmorphism, Animations
    ├── types.ts                   # Định nghĩa Domain Type Interfaces
    ├── mockData.ts                # Dữ liệu mẫu chuẩn nghiệp vụ và CSDL tri thức QA
    ├── App.tsx                    # Root State & Router giả lập (Quản lý tab & Alert)
    └── components/
        ├── Header.tsx             # Navigation, Brand, Status Online, Live Clock
        ├── GateMonitor.tsx        # Phân hệ Giám sát cổng (GATE-01, KPI, LPR BBox, Lịch sử)
        ├── AreaMonitor.tsx        # Phân hệ Giám sát khu vực (BAI-KIEM, KPI, Zone, BBox, Sự kiện)
        ├── AIQAChat.tsx           # Phân hệ Hỏi đáp AI (Chat stream, Video player 10s, Download)
        ├── FloatingAlert.tsx      # Cảnh báo vi phạm zone dạng popup nổi đa tab
        └── Settings/
            ├── VehicleLabelTab.tsx # Gắn nhãn xe, Tìm kiếm, Sắp xếp lượt vào, Toggle Quen/Lạ
            ├── ZoneEditorTab.tsx   # Trình vẽ đa giác, Sửa đỉnh, Undo/Redo Ctrl+Z/Y, Đổi màu, Phân quyền
            └── ObjectLabelTab.tsx  # Gán nhãn mẫu từ ảnh/video frame, Phím tắt 1-8, Crosshair
```

---

## 2. Ánh xạ State & Mock Data sang API Endpoints Thực Tế

### 2.1 Bảng ánh xạ Phân hệ & API Contract

| Phân hệ / Component | Mock State hiện tại | Real API Endpoint / Method | Ghi chú & Payload |
|---|---|---|---|
| **Giám sát Cổng (`GateMonitor`)** | `gateEvents: GateEvent[]` | `GET /api/v1/events/gate?limit=50`<br>`WS /ws/events/gate` | Trả về danh sách sự kiện vào cổng kèm `plate`, `conf`, `zone`, `time`, `crop_url`. WebSocket bắn sự kiện real-time khi camera nhận diện được biển số. |
| **Giám sát Khu vực (`AreaMonitor`)** | `areaEvents: AreaEvent[]` | `GET /api/v1/events/area?limit=50`<br>`WS /ws/events/area` | Sự kiện đối tượng vào zone kèm `obj`, `zone`, `time`, `st` (Được phép / Cảnh báo vi phạm), `ok: boolean`. |
| **KPI Tổng quan** | Tính toán từ `events` | `GET /api/v1/analytics/kpis` | Trả về các chỉ số: tổng lượt xe, đọc thành công, không đọc được, độ tin cậy trung bình, số vi phạm khu vực. |
| **Gắn nhãn xe (`VehicleLabelTab`)** | `labels: Record<string, 'quen'\|'la'>` | `GET /api/v1/vehicles`<br>`PATCH /api/v1/vehicles/:plate/label` | Lấy danh sách xe đã lưu (`visits`, `last_seen`, `crop_url`, `label`) và cập nhật trạng thái `quen` / `la`. |
| **Cấu hình Zone (`ZoneEditorTab`)** | `zonesByCam: Record<string, PolygonZone[]>` | `GET /api/v1/zones?camera_id=:camId`<br>`POST /api/v1/zones`<br>`PUT /api/v1/zones/:id`<br>`DELETE /api/v1/zones/:id` | Lưu tọa độ đa giác percentage `points: [x, y][]`, `name`, `color`, và bảng phân quyền loại đối tượng `types: Record<string, 0\|1>`. |
| **Nhãn & Mẫu (`ObjectLabelTab`)** | `objLabels: ObjectLabel[]`<br>`annSamples: AnnotationSample[]` | `GET /api/v1/labels`<br>`POST /api/v1/labels`<br>`POST /api/v1/samples/batch` | Quản lý danh mục nhãn (`name`, `kind`) và lưu batch danh sách bounding box đã khoanh trên các frame ảnh/video. |
| **Hỏi đáp AI (`AIQAChat`)** | `QA_KNOWLEDGE_BASE` | `POST /api/v1/qa/query` | Body: `{ query: string }`. Response: `{ text: string, clip?: { cam, from, to, title, boxLabel, boxColor, tint, downloadUrl } }`. |
| **Video Clip 10s** | Mock thumbnail & timeline | `GET /api/v1/clips/:id/download`<br>`GET /api/v1/clips/:id/stream` | Stream và tải đoạn video 10 giây được trích xuất tự động quanh thời điểm phát hiện. |
| **Cảnh báo nổi (`FloatingAlert`)** | `floatingAlert: FloatingNotification` | `WS /ws/alerts` | Nhận bản tin vi phạm zone khẩn cấp khi người dùng đang thao tác tại tab Cài đặt / Hỏi đáp. |

---

## 3. Quy tắc Nghiệp vụ (Business Rules Mapping)

| Quy tắc | Mô tả chi tiết | Component UI phụ trách | Hành vi giao diện |
|---|---|---|---|
| **BR-01** | Nhận diện biển số xe và phân loại Quen / Lạ tại Cổng vào. | `GateMonitor.tsx`, `VehicleLabelTab.tsx` | Hiển thị bounding box cyan kèm nhãn biển số + độ tin cậy. Nút toggle tức thời chuyển đổi Quen ⇄ Lạ. |
| **BR-02** | Giám sát bãi kiểm container, phân loại đúng đối tượng (Xe nâng, Container, Người đi bộ). | `AreaMonitor.tsx` | Bounding box màu xanh cho đối tượng hợp lệ, màu đỏ cho cảnh báo vi phạm. |
| **BR-03** | Cho phép người dùng cấu hình vẽ Zone đa giác tùy ý và gán quyền loại xe được phép/bị cấm. | `ZoneEditorTab.tsx` | Kéo đỉnh, thêm góc, di chuyển zone, hỗ trợ `Ctrl+Z` / `Ctrl+Y`, đổi màu sắc và đổi tên zone trực tiếp. |
| **BR-04** | Cho phép gán nhãn đối tượng mới bằng tiếng Việt và gắn mẫu bounding box từ video/hình ảnh. | `ObjectLabelTab.tsx` | Hỗ trợ phím tắt số `1-8`, đường dóng chữ thập (crosshair) căn chỉnh và lưu batch mẫu đã gắn. |
| **BR-05** | Hỏi đáp sự kiện tự nhiên với AI kèm trích xuất video clip 10s làm bằng chứng. | `AIQAChat.tsx` | Phản hồi ngôn ngữ tự nhiên, hiển thị trình phát clip 10s có đánh dấu đoạn vi phạm và nút tải clip. |
| **BR-06** | Gom nhóm sự kiện vào/ra zone thành 1 chu kỳ vi phạm duy nhất để tránh spam thông báo. | `AreaMonitor.tsx`, Backend Service | Sự kiện lưu 1 lần kèm khoảng thời gian `from - to`. |
| **BR-07** | Nhận diện biển số không đọc được phải gắn nhãn "Không đọc được" và lưu ảnh crop phục vụ rà soát. | `GateMonitor.tsx` | Dòng sự kiện có biển số `—` hiển thị nhãn cam `Không đọc được`. |
| **BR-08** | Cảnh báo vi phạm zone phải hiển thị tức thời ngay cả khi người dùng không ở tab Giám sát. | `FloatingAlert.tsx` | Toast thông báo đỏ nhung nổi góc dưới kèm nút 1-click chuyển về đúng camera. |
| **BR-09** | Đồng bộ tương tác Hover giữa danh sách sự kiện và khung hình camera. | `GateMonitor.tsx`, `AreaMonitor.tsx` | Rê chuột vào 1 sự kiện sẽ chỉ highlight duy nhất 1 dòng đó và làm sáng bbox/zone tương ứng trên camera feed. |

---

## 4. UI State Transitions & Trạng thái Tương tác

### 4.1 Zone Editor State Machine
```
[Select Mode] ──(Bấm '+ Vẽ zone mới')──> [Draw Mode (Draft Points = [])]
      │                                                │
      │ (Kéo đỉnh / Điểm giữa / Thân / Đổi màu)         │ (Click trên feed thêm điểm)
      ▼                                                ▼
[Zone Modified -> Push to History Stack]        [Draft Points >= 3]
      │                                                │
      │ (Nhấn Ctrl+Z / Nút Undo)                       │ (Bấm điểm đầu hoặc 'Hoàn tất zone')
      ▼                                                ▼
[Revert to Previous History State]             [Zone Created -> Select Mode -> Push to History]
```

### 4.2 LPR & Area Event Hover Synchronization
- Khi `hoveredEventId = 'e1'`:
  - Dòng sự kiện `e1`: Nền `var(--card-hover)`, viền trái `3px solid var(--cyan)` (hoặc `var(--p0)` / `var(--ok)`).
  - Khung hình camera: Bbox / Zone tương ứng nhận `boxShadow: 0 0 24px`, scale nhẹ `1.04`, viền sáng trắng.
  - Khi chuột rời khỏi (`onMouseLeave`): Trở về trạng thái chuẩn, hủy bỏ toàn bộ highlight.

---

## 5. Danh sách Kiểm tra Chất lượng (Quality Gate Checklist)

- [x] Giao diện chạy mượt mà trên Vite dev server (`http://localhost:5173/`).
- [x] Typecheck `tsc -b` và `vite build` hoàn thành 100% thành công không có lỗi type.
- [x] Giữ trọn vẹn visual DNA theo phong cách Modern Industrial Dark UI cao cấp.
- [x] Đã lược bỏ toàn bộ câu từ quảng cáo dư thừa, giữ lại trải nghiệm vận hành trực quan.
- [x] Đáp ứng đầy đủ 4 phân hệ theo Product Spec và Prototype trong Proposal.
- [x] Đã xuất đầy đủ `docs/design/ui-design-contract.md` và `docs/design/ui-to-frontend-handoff.md`.
