# UI Design Contract — SentriAI

> **Tài liệu hợp đồng thiết kế giao diện (UI Design Contract)**
> **Sản phẩm:** SentriAI — Hệ thống Giám sát Camera AI & Nhận diện Biển số
> **Trạng thái:** `Approved` (Đã được người dùng phê duyệt)
> **Mã nguồn tham chiếu:** `frontend/` (React 19 + TypeScript + Vite)
> **Golden Page:** `http://localhost:5173/`

---

## 1. Design System & Token Foundation

### 1.1 Bảng màu (Color Palette & Dark Tokens)
Giao diện áp dụng phong cách **Modern Industrial Dark UI** với nền tối có chiều sâu (Obsidian Slate), tạo sự tập trung cao độ vào khung hình camera và dữ liệu sự kiện:

| Token Name | Hex / Value | Mục đích sử dụng |
|---|---|---|
| `--bg` | `#0b0d11` | Nền chính của ứng dụng (Canvas Background) |
| `--bg-subtle` | `#0f1217` | Nền thứ cấp cho các container phụ |
| `--panel` | `#14171f` | Nền Header và các panel chính |
| `--panel-glass` | `rgba(20, 23, 31, 0.78)` | Nền kính mờ Glassmorphism (`backdrop-filter: blur(16px)`) |
| `--card` | `#1a1e27` | Nền thẻ KPI, Card cấu hình, bảng dữ liệu |
| `--card-hover` | `#212632` | Trạng thái hover của hàng và thẻ |
| `--raise` | `#262c39` | Nền các nút bấm phụ, tab bar, scrubber timeline |
| `--line` | `rgba(255, 255, 255, 0.08)` | Viền phân cách nhẹ |
| `--line2` | `rgba(255, 255, 255, 0.14)` | Viền thẻ và ô nhập dữ liệu |
| `--line3` | `rgba(255, 255, 255, 0.22)` | Viền active và focus |

### 1.2 Màu trạng thái & Nhận diện AI (Semantic Status Tokens)
| Token Name | Hex / Value | Ứng dụng nghiệp vụ |
|---|---|---|
| `--acc` | `#3b82f6` | Màu chủ đạo (Primary Accent), Nút chính, Tab active, Zone Blue |
| `--ok` | `#10b981` | Xe quen, Hợp lệ, Camera online, Điểm tin cậy cao >= 95% |
| `--p0` | `#f43f5e` | Cảnh báo vi phạm Zone, Xe lạ, Nút Xóa, Trực tiếp nhấp nháy |
| `--p1` | `#f59e0b` | Cảnh báo vừa, Biển số không đọc được |
| `--cyan` | `#06b6d4` | Bounding box nhận diện biển số LPR, Điểm tin cậy |
| `--purple` | `#a855f7` | Nhãn đối tượng đặc biệt (Xe cẩu, Reach Stacker) |

### 1.3 Kiểu chữ (Typography)
- **UI & Controls Font:** `'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`
  - Body Text: `13px` - `14px`, line-height: `1.5` - `1.65`
  - Section Title: `14px` - `15.5px`, font-weight: `700`, letter-spacing: `-0.02em`
  - KPI Stat: `26px`, font-weight: `700`, letter-spacing: `-0.02em`
- **Data & Numeric Font:** `'IBM Plex Mono', ui-monospace, Menlo, Monaco, Consolas, monospace`
  - Biển số xe: `13.5px`, font-weight: `700`, letter-spacing: `0.02em`
  - Timestamp & Clock: `11px` - `12px`, font-weight: `600`
  - Chỉ số KPI: `24px` - `26px`, font-weight: `700`

### 1.4 Bo góc & Đổ bóng (Border Radius & Elevations)
- **Bo góc:**
  - Nút bấm & Input: `8px` - `10px`
  - Thẻ nhỏ & Tag: `6px` - `20px` (pill)
  - Card & Container lớn: `14px` - `16px` (Squircle)
- **Đổ bóng & Ánh sáng viền:**
  - Card Shadow: `0 4px 16px -2px rgba(0, 0, 0, 0.45)`
  - Panel Shadow: `0 12px 32px -4px rgba(0, 0, 0, 0.6)`
  - Glow Accent: `0 0 24px -4px rgba(59, 130, 246, 0.35)`

### 1.5 Bảng màu Giao diện Sáng (Modern Industrial Light UI Tokens)
Khi kích hoạt chế độ Sáng (`[data-theme='light']`), giao diện chuyển sang tông màu thanh lịch, độ tương phản cao, tối ưu cho môi trường làm việc văn phòng ban ngày:

| Token Name | Hex / Value | Mục đích sử dụng trong Light Mode |
|---|---|---|
| `--bg` | `#f4f6fa` | Nền canvas chính (Crisp Slate Canvas) |
| `--bg-subtle` | `#eaedf3` | Nền thứ cấp cho toolbar và sub-nav |
| `--panel` | `#ffffff` | Nền Header và các panel chính dạng phẳng |
| `--panel-glass` | `rgba(255, 255, 255, 0.88)` | Nền kính mờ sáng (`backdrop-filter: blur(16px)`) |
| `--card` | `#ffffff` | Nền thẻ KPI, Card cài đặt, bảng dữ liệu |
| `--card-hover` | `#f1f4f9` | Trạng thái hover hàng và thẻ trong Light Mode |
| `--raise` | `#e2e8f0` | Nền nút bấm phụ, tab bar, table header |
| `--line` | `rgba(0, 0, 0, 0.08)` | Viền phân cách xám nhẹ |
| `--line2` | `rgba(0, 0, 0, 0.13)` | Viền ô nhập liệu và thẻ |
| `--ink` | `#0f172a` | Màu chữ chính (Charcoal Slate Đậm) |
| `--ink2` | `#334155` | Màu chữ thứ cấp |
| `--ink3` | `#64748b` | Màu chữ phụ, caption và placeholder |

---

## 2. Đặc tả các Component Giao diện Chuẩn

### 2.1 Header (`Header.tsx`)
- **Vị trí:** Sticky top (`z-index: 50`), kính mờ `backdrop-filter: blur(16px)`.
- **Cấu trúc:**
  - Trái: Logo Emblem khiên bảo vệ AI gradient + Tiêu đề thương hiệu `SentriAI` + Phụ đề nghiệp vụ.
  - Giữa: Thanh chuyển đổi 4 phân hệ (`Giám sát cổng`, `Giám sát khu vực`, `Cài đặt hệ thống`, `Hỏi đáp AI`) có icon và pill active.
  - Phải: **Nút Quick Theme Toggle (Icon Sun ☀️ / Moon 🌙)** chuyển đổi nhanh 1-click giữa Sáng và Tối + Badge trực tuyến `● 2 Cam Online` + Đồng hồ số `HH:mm:ss`.

### 2.2 Giám sát Cổng (`GateMonitor.tsx` — Tab `mon`)
- **4 Thẻ KPI:** Lượt xe qua cổng, Biển số đọc thành công, Không đọc được, Độ tin cậy trung bình.
- **Camera Feed GATE-01 (Tỉ lệ 16:9):**
  - Thanh HUD nổi trên video: Tên camera `GATE-01 · Làn xe vào chính`, `1080p · 25 FPS`, `● TRỰC TIẾP`.
  - SVG đa giác Làn vào (Làn IN 1, Làn IN 2).
  - LPR Bounding Box HUD: Khung cyan phát sáng viền kính với tag `15R-158.45 · 97%`.
- **Panel Biển số đã nhận diện:**
  - Header có bộ đếm và tab lọc nhanh `Tất cả` | `⚠ Xe lạ` | `✓ Xe quen` + Ô tìm kiếm tức thời.
  - Danh sách cuộn thời gian thực: Giờ vào, Biển số (font Mono), Tag phân loại `XE QUEN` / `XE LẠ`, Độ tin cậy kèm chấm trạng thái.
  - **Tương tác Hover:** Rê chuột vào 1 dòng sự kiện sẽ highlight duy nhất dòng đó và làm sáng khung biển số tương ứng trên video feed.

### 2.3 Giám sát Khu vực (`AreaMonitor.tsx` — Tab `area`)
- **4 Thẻ KPI:** Đối tượng trong khu, Vi phạm loại xe hôm nay, Xe nâng/container hoạt động, Zone giám sát.
- **Camera Feed BAI-KIEM (Tỉ lệ 16:9):**
  - Thanh HUD nổi: `BAI-KIEM · Bãi kiểm bốc dỡ`, `1080p · 25 FPS`, `● TRỰC TIẾP`.
  - SVG Polygon Zones với nhãn zone trung tâm.
  - Object Bounding Boxes: `XE NÂNG RS01 · ĐƯỢC PHÉP` (xanh), `BÃI CONTAINER LẠNH` (xanh), `NGƯỜI ĐI BỘ · CẢNH BÁO` (đỏ).
  - Chip quy tắc loại phương tiện: `✓ Xe nâng`, `✓ Xe container`, `✕ Xe hơi`, `✕ Xe máy`, `✕ Xe đạp`.
- **Panel Sự kiện khu vực:** Tab lọc `Tất cả` | `⚠ Vi phạm` | `✓ Được phép` + Lọc tìm kiếm.
- **Tương tác Hover:** Rê chuột vào 1 sự kiện sẽ highlight chính xác dòng đó và làm sáng đối tượng / zone tương ứng trên video.

### 2.4 Phân hệ Cài đặt (`set` — 4 Sub-tabs)
1. **Gắn nhãn xe (`VehicleLabelTab.tsx`):**
   - Thanh công cụ: Ô tìm kiếm đa trường + Lọc trạng thái (`Tất cả`, `✓ Xe quen`, `⚠ Xe lạ`) + Lọc theo loại xe (`Tất cả loại xe`, `Container`, `Xe tải`, `Xe con`...) + Bộ đếm kết quả.
   - Sắp xếp trực tiếp trên tiêu đề cột (Column Header Sorting): Bấm vào tiêu đề cột `Lượt vào` hoặc `Lần cuối ghi nhận` hoặc `Biển số xe` có mũi tên chỉ báo hướng tăng/giảm `↑` / `↓` ngay bên phải title.
   - Bảng dữ liệu: Ảnh crop, Biển số Mono, Loại xe, Lượt vào, Lần cuối ghi nhận, Nút bấm toggle tức thời `Xe quen (Hợp lệ)` ⇄ `Xe lạ (Cảnh báo)`.
2. **Vẽ Zone tương tác (`ZoneEditorTab.tsx`):**
   - Toolbar: Chọn camera (`Bãi Kiểm` / `Cổng vào`), Chế độ `Chọn / Sửa` vs `+ Vẽ zone mới`, Nút `Undo` (`Ctrl+Z`) / `Redo` (`Ctrl+Y`), Nút `✓ Hoàn tất zone (Enter)`.
   - Canvas tương tác:
     - **Lưu Zone nhanh bằng phím Enter:** Khi vẽ từ 3 đỉnh trở lên, nhấn phím `Enter` để hoàn tất và lưu zone ngay lập tức.
     - **Chống kéo nhầm:** Bấm vào Zone lần đầu để chọn (hiển thị viền và các đỉnh); chỉ khi Zone đã được chọn mới cho phép kéo di chuyển thân zone hoặc kéo đỉnh sửa hình dạng.
     - **Xóa góc / đỉnh đa giác:** Hỗ trợ Nhấp đúp (Double-click), Chuột phải (Context Menu) hoặc chọn đỉnh rồi nhấn phím `Delete` / `Backspace` để xóa đỉnh (giữ tối thiểu 3 đỉnh).
     - **Xóa Zone:** Chọn Zone và nhấn phím `Delete` hoặc `Backspace` để xóa tức thời (có lưu lịch sử Undo).
     - **Thêm góc:** Kéo điểm giữa (midpoint) của cạnh để chèn đỉnh mới.
   - Panel Quản lý Zone bên phải: Container dạng kính mờ đồng bộ chiều cao với camera feed (`maxHeight: 610px`, cuộn riêng biệt), có ô tìm kiếm zone tức thì, hiển thị số đỉnh, đổi màu sắc và tự động cuộn (auto-scroll) tới đúng Zone card khi người dùng click chọn Zone trên video feed.
3. **Nhãn đối tượng (`ObjectLabelTab.tsx`):**
   - Strip thumbnails media nguồn (ảnh/video).
   - Scrubber timeline video với các mốc keyframe.
   - Canvas gắn mẫu: Đường dóng chữ thập (crosshair) đi theo con trỏ chuột, kéo thả vẽ bounding box, lưu N mẫu đã gắn.
   - Phím tắt chuyển nhanh nhãn: Nhấn phím số `1` đến `8` trên bàn phím để đổi ngay loại nhãn đang chọn.
4. **Tùy biến Giao diện & Chủ đề (`ThemeSettingsTab.tsx`):**
   - **Bộ chọn 3 Chế độ:** 🌙 `Giao diện Tối (Dark Industrial)`, ☀️ `Giao diện Sáng (Modern Light)`, 💻 `Tự động theo hệ điều hành (System Sync)`.
   - **Thẻ xem trước trực quan (Live Preview Cards):** Hiển thị mô phỏng thu nhỏ sinh động của Header, Video Feed, Bounding Box và Event List theo từng theme.
   - **Bộ chọn Accent Color (5 màu):** Classic Blue `#3b82f6`, Emerald Green `#10b981`, Cyan Teal `#06b6d4`, Royal Purple `#a855f7`, Amber Orange `#f59e0b`.
   - **Tùy chọn hiển thị nâng cao:** Bật/Tắt hiệu ứng kính mờ (Glassmorphism), Chế độ mật độ gọn gàng (Compact Mode) và Nút Khôi phục mặc định.
   - **Lưu trữ cấu hình:** Tự động đồng bộ với `localStorage` (`sentriai_theme`, `sentriai_accent`, `sentriai_glass`, `sentriai_compact`).

### 2.5 Hỏi đáp AI (`AIQAChat.tsx` — Tab `qa`)
- Giao diện chat trực quan, không câu từ quảng cáo dư thừa.
- Nút *"Xóa lịch sử chat"* và nút *"Sao chép"* câu trả lời.
- Các thẻ gợi ý câu hỏi nhanh dạng chip bấm tức thời.
- **Thẻ Video Clip 10s đối chứng:** Khung xem video với timeline có đánh dấu phân đoạn vi phạm (giây 03 - 07), playhead thumb, nút Play/Pause và nút "Tải clip 10s".

### 2.6 Floating Alert (`FloatingAlert.tsx`)
- Toast thông báo khẩn cấp dạng kính mờ đỏ viền nhung nổi góc dưới phải màn hình khi người dùng ở tab khác và có vi phạm zone phát sinh.
- Nút *"Xem camera ngay →"* điều hướng 1-click về đúng camera đang xảy ra sự kiện.

---

## 3. Responsive Breakpoints

| Breakpoint | Layout Behavior |
|---|---|
| **>= 1200px (Desktop)** | Layout chuẩn 2 cột (Feed 1.58fr : Event Panel 1fr). |
| **768px - 1199px (Tablet)** | Layout 1 cột xếp chồng (Feed trên, Event Panel dưới). |
| **< 768px (Mobile)** | Header thu gọn icon, table hỗ trợ cuộn ngang, modal floating alert full width đáy màn hình. |
