# Incident Notifications & AI Shift Reporting Design

## 1. Goal

Nâng cấp SentriAI với hai hệ thống chức năng phục vụ người dùng thực tế:
1. **Hệ thống Cảnh báo Đa kênh (Incident Notification System):** Gửi cảnh báo tức thì qua Telegram Bot và báo cáo/cảnh báo qua Email khi có vi phạm khu vực (`ZoneViolation`) hoặc phương tiện bất thường qua cổng (`GateEvent` status `STRANGER`/blacklist).
2. **Xuất Biên bản Vi phạm PDF & Báo cáo Giao ca Tự động bằng AI (Incident PDF & AI Shift Handover Report):**
   - Cho phép xuất file PDF biên bản xử lý vi phạm có hình ảnh bằng chứng hiện trường và chữ ký.
   - Nâng cấp AI Copilot với Domain Skill mở rộng và Function Tool thống kê theo ca (`get_shift_report_data`), cho phép tự động tổng hợp số liệu ca trực và xuất thành biên bản bàn giao ca định dạng PDF.

---

## 2. Approved Runtime Behavior

### 2.1. Cảnh báo Đa kênh (Telegram & Email)
- **Kích hoạt (Triggering):**
  - Khi một sự kiện vi phạm khu vực mới được mở (`ZoneViolation` status `OPEN`) hoặc một xe lạ qua cổng (`GateEvent` status `STRANGER`), sự kiện được chuyển tiếp đến `NotificationService`.
- **Cơ chế Chống Spam (Anti-spam / Debouncing):**
  - Áp dụng sliding-window debounce theo `(cameraId, zoneId, objectLabel)` hoặc `licensePlate`. Cùng một đối tượng vi phạm không gửi cảnh báo trùng lặp trong khoảng thời gian cooldown (mặc định 3 phút).
- **Telegram Bot Dispatch:**
  - Gửi tin nhắn HTML format chuẩn kèm icon cảnh báo, vị trí, zone, loại đối tượng, thời gian.
  - Nếu có ảnh cắt/khung hình (snapshot crop), đính kèm ảnh trực tiếp thông qua API `sendPhoto`.
- **Email Dispatch:**
  - Hỗ trợ gửi email cảnh báo nóng (Instant Alert) cho các vi phạm nghiêm trọng và cấu hình danh sách người nhận linh hoạt.
  - Hỗ trợ gửi email báo cáo tổng kết cuối ngày (Daily Digest).
- **Cấu hình & Quản lý:**
  - Cấu hình bật/tắt độc lập từng kênh (Telegram, Email) qua bảng `system_settings` trong DB hoặc file cấu hình, có fallback biến môi trường `.env`.
  - Có endpoint `POST /api/v1/notifications/test` để kiểm tra kết nối (Test connection) trực tiếp từ giao diện Settings.

### 2.2. Xuất Biên bản Vi phạm PDF (Incident PDF Export)
- **API Endpoint:** `GET /api/v1/events/area/:id/export-pdf`
- **Nội dung biên bản:**
  - Quốc hiệu & Tiêu đề cơ quan/hệ thống SentriAI.
  - Tên biên bản: **BIÊN BẢN GHI NHẬN SỰ CỐ VI PHẠM AN NINH KHU VỰC**.
  - Mã sự kiện (Incident UUID), Thời gian lập biên bản.
  - Bảng thông tin chi tiết: Camera, Khu vực/Zone, Loại đối tượng/phương tiện, Thời điểm bắt đầu vi phạm, Thời điểm rời khỏi, Tổng thời lượng vi phạm.
  - Bằng chứng thị giác: Tự động nhúng ảnh snapshot crop hiện trường vào trang PDF.
  - Khu vực chữ ký: Nhân viên phụ trách ca trực và Người điều khiển phương tiện/Người vi phạm.
- **Định dạng tải về:** Stream nhị phân `application/pdf`, tự động kích hoạt tải file `Bien-ban-vi-pham-[ID].pdf` trên trình duyệt.

### 2.3. Báo cáo Giao ca Tự động bằng AI (AI Shift Handover Report)
- **Quy tắc Nghiệp vụ trong Domain Skill (`SKILL.md`):**
  - Định nghĩa khái niệm ca trực (ví dụ: Ca 1: 06:00 - 14:00, Ca 2: 14:00 - 22:00, Ca 3: 22:00 - 06:00 hôm sau; hoặc khung giờ linh hoạt theo câu hỏi).
  - Quy định cấu trúc 3 phần bắt buộc của một biên bản giao ca chuẩn:
    1. **Hoạt động Cổng:** Tổng lượt xe, tỷ lệ xe quen/xe lạ, danh sách biển số lạ đáng chú ý.
    2. **An ninh Khu vực:** Tổng số lượt di chuyển trong zone, số vụ vi phạm, danh sách đối tượng vi phạm, thời lượng, trạng thái tồn đọng.
    3. **Đánh giá & Bàn giao:** Đánh giá mức độ an toàn của ca trực, ghi chú các phương tiện cần theo dõi.
  - Tuân thủ nghiêm ngặt Coverage Semantics: Nếu dữ liệu chỉ là `PARTIAL`, AI phải nêu rõ mức độ bao phủ và không khẳng định số liệu là tuyệt đối của cả ca.
- **Function Tool mới (`get_shift_report_data`):**
  - Nhận tham số: `startTime` (ISO/HH:mm), `endTime` (ISO/HH:mm), `date` (YYYY-MM-DD, mặc định hôm nay theo timezone `Asia/Bangkok`).
  - Truy vấn đồng thời dữ liệu Cổng (`GateEvent`) và Khu vực (`AreaActivitySession` & `ZoneViolation`) trong đúng khung thời gian ca trực.
- **Xuất PDF Báo cáo Ca trực:**
  - Endpoint `POST /api/v1/qa/export-shift-pdf`: Chuyển đổi nội dung báo cáo AI thành văn bản tài liệu PDF chính thức với logo, kẻ bảng biểu số liệu và phần chữ ký bàn giao.

---

## 3. Architecture & Data Flow

```
[Camera Stream / AI Worker]
       │
       ▼ (Phát hiện Vi phạm / Xe lạ)
[POST /api/v1/events/gate | area]
       │
       ├──> [channelManager (WebSocket)] ──> Frontend Live Feed & Alert Panel
       │
       └──> [NotificationService] (Async)
                 │
                 ├──[Debounce / Cooldown Filter]
                 │
                 ├──[Telegram Bot Dispatcher] ──> Telegram Bot API ──> Nhóm Chat Bảo vệ (kèm ảnh)
                 └──[Email Dispatcher]       ──> Nodemailer (SMTP)   ──> Hộp thư Quản lý

[Frontend Client]
       │
       ├──> [Bấm "In biên bản PDF"] ──> [GET /api/v1/events/area/:id/export-pdf]
       │                                     │
       │                                     └──> [PdfService] ──> Render PDF có ảnh snapshot ──> Download
       │
       └──> [Hỏi đáp AI: "Báo cáo ca 1"] ──> [POST /api/v1/qa/chat]
                                                   │
                                                   ▼
                                             [Gemini AI]
                                                   │
                                                   ├── (Gọi Tool) ──> [get_shift_report_data] ──> Prisma DB
                                                   │
                                                   ▼ (Tổng hợp theo Domain Skill)
                                             [Văn bản Báo cáo Ca] ──> [Nút "Tải PDF Báo cáo"]
```

---

## 4. Component Details & File Modifications

### 4.1. Backend (`backend/node-api`)

1. **Thư viện bổ sung (`package.json`):**
   - `pdfkit` & `@types/pdfkit`: Dùng để vẽ và xuất tài liệu PDF chất lượng cao, nhẹ và độc lập môi trường.
   - `nodemailer` & `@types/nodemailer`: Dùng để gửi email thông báo bảo mật qua SMTP.
2. **Notification Subsystem (`src/services/`):**
   - `notificationService.ts`: Điều phối thông báo đa kênh, xử lý debounce cooldown, kiểm tra trạng thái bật/tắt.
   - `telegramService.ts`: Gọi Telegram Bot API (`sendMessage`, `sendPhoto`).
   - `emailService.ts`: Tạo transporter Nodemailer, render HTML email template, gửi đính kèm ảnh.
3. **PDF Generation Subsystem (`src/services/`):**
   - `pdfService.ts`:
     - Hàm `generateViolationPdf(violationRecord)`: Tạo buffer PDF biên bản vi phạm có hình ảnh.
     - Hàm `generateShiftReportPdf(reportData)`: Tạo buffer PDF báo cáo giao ca trực từ dữ liệu và tóm tắt AI.
4. **AI & Domain Skill Subsystem (`src/ai/`):**
   - `domain/sentriai-operations/SKILL.md`: Bổ sung section nghiệp vụ ca trực và quy chuẩn báo cáo giao ca (bảo đảm vượt qua `validateDomainSkill`).
   - `tools.ts`: Thêm tool `get_shift_report_data` trong `QA_TOOL_DECLARATIONS` và cài đặt hàm xử lý truy vấn DB theo khung giờ.
5. **REST API Routes (`src/routes/`):**
   - `notifications.ts` (NEW):
     - `GET /api/v1/notifications/settings`: Lấy cấu hình thông báo hiện tại.
     - `PUT /api/v1/notifications/settings`: Cập nhật cấu hình (bật/tắt, bot token, chat ID, email).
     - `POST /api/v1/notifications/test`: Gửi tin nhắn test kiểm tra kết nối Telegram/Email.
   - `areaEvents.ts` (UPDATE):
     - Thêm route `GET /api/v1/events/area/:id/export-pdf` để tải biên bản vi phạm PDF.
   - `qa.ts` (UPDATE):
     - Thêm route `POST /api/v1/qa/export-shift-pdf` để xuất PDF báo cáo giao ca.

### 4.2. Frontend (`frontend/src`)

1. **Area Monitor (`AreaMonitor.tsx`):**
   - Thêm nút biểu tượng **"In biên bản (PDF)"** tại mỗi dòng sự kiện vi phạm trong danh sách vi phạm. Khi bấm, mở link tải PDF trực tiếp.
2. **AI QA Chat (`AIQAChat.tsx`):**
   - Thêm các chip gợi ý câu hỏi giao ca: `[📋 Báo cáo ca sáng (06:00 - 14:00)]`, `[📋 Báo cáo ca chiều (14:00 - 22:00)]`.
   - Hiển thị nút bấm **"📄 Tải PDF Báo Cáo Ca"** bên dưới câu trả lời tóm tắt giao ca của AI.
3. **Settings (`components/Settings/`):**
   - Thêm tab mới `NotificationTab.tsx` trong Modal Cài đặt:
     - Form cấu hình Telegram: Bot Token, Chat ID, checkbox Bật/Tắt, nút "Gửi tin nhắn thử".
     - Form cấu hình Email: SMTP Server, Port, User, Pass, Danh sách Email nhận, checkbox Bật/Tắt, nút "Gửi email thử".

---

## 5. Verification & E2E Testing Plan

### 5.1. Automated Backend & E2E Tests
1. **`src/tests/test_notifications.ts`**:
   - Test `telegramService` và `emailService` với mock network và credentials.
   - Test debounce cooldown: gửi 3 vi phạm giống nhau trong 1 giây -> chỉ dispatch 1 thông báo.
   - Test endpoint test connection `POST /api/v1/notifications/test`.
2. **`src/tests/test_pdf_export.ts`**:
   - Tạo test violation trong DB -> gọi `generateViolationPdf` -> kiểm tra buffer nhị phân bắt đầu bằng `%PDF-1.`, kích thước > 10KB.
   - Gọi `generateShiftReportPdf` với dữ liệu ca trực mẫu -> kiểm tra cấu trúc PDF hợp lệ.
3. **`src/tests/test_shift_qa_and_domain_skill.ts`**:
   - Chạy validator `validateDomainSkill` để đảm bảo `SKILL.md` cập nhật đúng quy chuẩn và không chứa placeholder.
   - Chạy test tool `get_shift_report_data` với mock data Cổng & Bãi Kiểm -> verify tính đúng tổng số lượt, xe quen, xe lạ, vi phạm trong khung giờ.

### 5.2. Manual & System E2E Verification
1. **Kiểm thử Thông báo Telegram/Email:**
   - Mở Settings -> Tab Thông báo -> Nhập thông tin thử nghiệm -> Bấm "Gửi tin nhắn thử" -> Nhận thông báo trên Telegram / Hộp thư.
   - Kích hoạt sự kiện vi phạm mô phỏng -> Kiểm tra bot Telegram tự động bắn tin nhắn kèm ảnh.
2. **Kiểm thử Xuất PDF Biên bản:**
   - Vào tab Bãi Kiểm -> Tìm một sự kiện vi phạm -> Bấm "In biên bản (PDF)" -> File PDF tự động tải về, mở lên xem rõ nét văn bản, bảng số liệu và ảnh crop.
3. **Kiểm thử Báo cáo Giao ca AI:**
   - Vào AI QA Chat -> Bấm chip "Báo cáo ca sáng (06:00 - 14:00)" -> AI trả lời đầy đủ số liệu 3 phần theo chuẩn `SKILL.md`.
   - Bấm nút "Tải PDF Báo Cáo Ca" -> Tải file PDF báo cáo giao ca đầy đủ, định dạng đẹp mắt.
