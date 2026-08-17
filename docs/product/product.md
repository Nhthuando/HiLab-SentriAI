# SentriAI — Product Specification

## 1. Trạng thái và quyết định

- **Trạng thái:** Đã duyệt
- **Người duyệt:** HuuThuan
- **Thời điểm duyệt:** 2026-08-17T14:43:00+07:00
- **Nguồn đầu vào chính:** `proposal/proposal.md` (v1.0 · 17/08/2026) + 5 câu grill qua chat

**Quyết định bổ sung so với proposal gốc:**

| # | Nội dung quyết định | Kết quả |
|---|---|---|
| Q1 | Clip 10s: pre-saved hay on-demand? | Pre-saved tự động khi event xảy ra |
| Q2 | Labeling tool: train model hay define type? | Define type (gán nhãn tên Việt cho class model gốc); loại ngoài model → `CHƯA XÁC ĐỊNH` |
| Q3 | Alert vi phạm zone hiển thị thế nào? | Bbox đỏ + alert panel list + floating mini-alert góc dưới phải khi ở tab khác |
| Q4 | Hiển thị xe quen/lạ trên feed cổng? | Có — xanh/`XE QUEN`, vàng/`XE LẠ` + hiển thị trong alert panel |
| Q5 | Vi phạm kéo dài: bao nhiêu alert? | 1 sự kiện mở lúc vào, đóng lúc ra, ghi tổng thời gian; clip từ lúc vào |

---

## 2. Vấn đề và người dùng

- **Vấn đề:** Nhân viên bảo vệ / quản lý kho bãi không thể đồng thời quan sát cổng ra vào và nhiều khu vực bên trong. Vi phạm (xe lạ, người không phận sự, phương tiện cấm vào zone) xảy ra mà không được phát hiện hoặc không có bằng chứng để tra cứu sau.
- **Người dùng chính:** Bảo vệ / quản lý kho bãi đang trực ca
- **Core job:** Biết ngay khi có sự kiện bất thường tại cổng hoặc khu vực, và có thể tra cứu lại lịch sử sự kiện kèm video bằng ngôn ngữ tự nhiên
- **Giá trị mong đợi:** Giảm thiểu vi phạm không bị phát hiện; có bằng chứng video cho mọi sự kiện đã lưu

---

## 3. Phạm vi

### MVP

**M1 — Giám sát cổng (GATE-01, 2 làn IN)**
- Nhận luồng video (RTSP hoặc file giả lập); xử lý >= 5 FPS
- Nhận diện biển số (LPR) khi xe vào zone làn IN 1 / IN 2
- Hiển thị live feed với bounding box màu theo trạng thái:
  - Xanh + badge `XE QUEN` nếu biển số đã đăng ký trong danh sách
  - Vàng + badge `XE LẠ` nếu biển số chưa có trong danh sách
- Hiển thị biển số + độ tin cậy (confidence) trên khung hình
- Alert panel bên cạnh feed hiển thị real-time: timestamp, biển số, làn, trạng thái quen/lạ
- Ghi sự kiện: thời gian, biển số, làn, trạng thái, ảnh cắt biển số, clip 10s pre-saved

**M2 — Giám sát khu vực (BAI-KIEM, góc trên cao)**
- Nhận luồng video; xử lý >= 5 FPS
- Phát hiện đối tượng trong các zone đa giác theo cấu hình
- Phân loại đối tượng theo danh sách đã define; loại không khớp model gốc → nhãn `CHƯA XÁC ĐỊNH`
- Kiểm tra đối tượng có nằm trong zone không (point-in-polygon)
- Khi đối tượng bị cấm đi vào zone:
  - Bbox chuyển màu đỏ + label `VI PHẠM` trên live feed
  - Mở sự kiện vi phạm (ghi thời gian vào, loại đối tượng, zone, clip 10s từ lúc vào)
  - Thêm item vào alert panel bên cạnh feed (real-time)
  - Hiển thị floating mini-alert góc dưới phải khi user đang ở tab khác trong app
- Khi đối tượng rời zone: đóng sự kiện, ghi thời gian ra + tổng thời gian lưu lại
- 1 sự kiện vi phạm per lần vào/ra; không sinh alert lặp trong khi đối tượng còn ở trong zone

**M3 — Cài đặt**
- Gắn nhãn xe: Danh sách biển số đã thu thập; đánh dấu từng xe là `XE QUEN` / `XE LẠ`
- Vẽ zone: Chọn camera (Cổng / Bãi Kiểm); vẽ polygon trên khung hình thật; zone lưu cập nhật ngay trên màn hình giám sát
- Nhãn đối tượng: Import ảnh hoặc video, vẽ bounding box, chọn loại từ class model gốc, đặt tên nhãn tiếng Việt; nhãn đã lưu xuất hiện trong danh sách loại của mọi zone

**M4 — Hỏi đáp AI**
- Khung chat; người dùng hỏi bằng ngôn ngữ tự nhiên về sự kiện đã lưu
- Trả lời gồm: số liệu + chi tiết sự kiện + tham chiếu clip 10s (camera, từ giây nào đến giây nào) + nút tải clip
- Ví dụ: "Hôm nay có bao nhiêu xe lạ vào?", "Có xe máy nào vào khu cấm không?", "Xe máy ở trong khu cấm bao lâu?"

**Giao diện chung**
- Bám theo luồng nghiệp vụ của `Intern-LPR-Gate.dc.html` (không cần pixel-perfect)
- Công nghệ web tự chọn

### Làm sau (LATER)

- Fine-tune / re-train model detection từ dataset nhãn đã lưu
- Docker-compose hoàn chỉnh cho production deployment
- Nhận diện làn xe ra (OUT lane)
- Push notification ra ngoài app (email, Telegram...)
- Phân quyền Admin / Bảo vệ / Viewer

### Không làm (REJECT)

- Phân loại xe được phép / không được phép tại cổng (proposal nói rõ không cần)
- Âm thanh cảnh báo
- Quản lý đa site / đa tổ chức

---

## 4. Luồng sản phẩm chính

```
[Cài đặt] Vẽ zone + define loại xe + gắn nhãn biển số
        ↓
[Giám sát] Nhận stream → detect → kiểm tra zone → sinh event
        ↓
[Lưu trữ] Ghi sự kiện + ảnh cắt + clip 10s vào CSDL
        ↓
[Hỏi đáp] Người dùng query → AI truy vấn CSDL → trả lời + clip
```

**Luồng nhận diện cổng (chi tiết):**
Xe vào làn IN → LPR detect biển số → Tra danh sách quen/lạ → Hiển thị bbox màu + badge → Ghi sự kiện + clip 10s + ảnh cắt → Hiện trong alert panel

**Luồng vi phạm zone (chi tiết):**
Đối tượng bị cấm đi vào zone → Mở sự kiện + lưu clip 10s → Bbox đỏ + alert panel + floating mini-alert → Đối tượng rời zone → Đóng sự kiện + ghi duration

---

## 5. Business rules

| # | Rule |
|---|---|
| BR-01 | LPR chỉ kích hoạt khi xe đi vào zone làn IN; không detect xe đang đứng yên ngoài zone |
| BR-02 | Biển số chưa có trong danh sách → tự động gán `XE LẠ`; không chặn xe |
| BR-03 | Đối tượng detect không khớp class model gốc → gán `CHƯA XÁC ĐỊNH`; vẫn kiểm tra zone rules |
| BR-04 | `CHƯA XÁC ĐỊNH` trong zone có rule "chỉ cho phép loại cụ thể" → bị coi là vi phạm |
| BR-05 | Clip 10s được pre-saved ngay khi event xảy ra; sự kiện vi phạm tính clip từ lúc đối tượng vào zone |
| BR-06 | Mỗi lần vào/ra zone = 1 sự kiện vi phạm; không spam alert trong khi đối tượng ở yên trong zone |
| BR-07 | Zone cập nhật từ Cài đặt có hiệu lực ngay lập tức trên màn hình giám sát đang chạy |
| BR-08 | Floating mini-alert chỉ xuất hiện khi user đang ở tab khác trong app; tắt khi quay về tab giám sát |
| BR-09 | AI Q&A chỉ query trên dữ liệu đã lưu; không phân tích stream real-time |

---

## 6. Vai trò và quyền ở mức sản phẩm

- **MVP:** Không có phân quyền — single user, local deployment cho intern demo
- **LATER:** Phân quyền Admin / Bảo vệ / Viewer nếu deploy thật

---

## 7. Trạng thái và ngoại lệ quan trọng

| Tình huống | Hành vi |
|---|---|
| Stream ngắt kết nối | Hiển thị trạng thái "Mất kết nối" trên feed; không crash app |
| Clip 10s không ghi được (disk đầy...) | Ghi sự kiện vẫn thành công; clip field = null; Q&A báo "không có clip" |
| Biển số nhận diện mờ / confidence thấp | Vẫn ghi sự kiện với biển số tạm + confidence; không bỏ qua |
| Đối tượng vào rồi ra zone rất nhanh (< 1s) | Vẫn sinh sự kiện vi phạm; duration = thực tế |

---

## 8. Success metrics

- Demo chạy được với 2 video mẫu (cổng + bãi kiểm) không crash
- LPR nhận diện đúng >= 80% biển số rõ nét trong video mẫu
- Vi phạm zone được phát hiện và alert xuất hiện trong <= 2s
- AI Q&A trả lời đúng >= 5 câu hỏi mẫu cơ bản có kèm clip tham chiếu
- Bộ nhãn: >= 5 loại, mỗi loại >= 20 mẫu đã gắn nhãn
- Demo video 3-5 phút bao phủ đủ 4 module

---

## 9. Acceptance criteria

| ID | Tiêu chí | Có thể kiểm tra bằng |
|---|---|---|
| AC-01 | Xe vào làn IN → bbox + biển số + badge quen/lạ xuất hiện trên feed trong <= 500ms | Xem live feed với video mẫu cổng |
| AC-02 | Sự kiện cổng được ghi: timestamp, biển số, làn, trạng thái, ảnh cắt, clip 10s | Kiểm tra CSDL sau khi xe đi qua |
| AC-03 | Đối tượng bị cấm vào zone → bbox đỏ + alert panel + floating mini-alert (khi ở tab khác) | Test với video mẫu bãi kiểm |
| AC-04 | Sự kiện vi phạm có: thời gian vào, thời gian ra, duration, clip 10s từ lúc vào | Kiểm tra CSDL sau khi đối tượng ra khỏi zone |
| AC-05 | Vẽ zone mới trong Cài đặt → zone active ngay trên màn hình giám sát (không cần restart) | Thao tác trực tiếp trong app |
| AC-06 | Nhãn đối tượng đã lưu → xuất hiện trong dropdown loại của zone config | Thao tác trực tiếp trong app |
| AC-07 | Query "Hôm nay có bao nhiêu xe lạ vào?" → số đúng + chi tiết + clip reference + nút tải | So sánh với dữ liệu DB |
| AC-08 | Đối tượng không khớp class model → hiện nhãn `CHƯA XÁC ĐỊNH`, vẫn kiểm tra zone rule | Test với vật thể lạ trong video |
| AC-09 | Stream ngắt → app hiện "Mất kết nối", không crash | Ngắt nguồn video file giả lập |

---

## 10. Ràng buộc, giả định và câu hỏi mở

**Ràng buộc:**
- Thời gian: 2 tuần; review với mentor mỗi tuần 1 lần
- Nguồn video: RTSP hoặc video file giả lập
- Xử lý >= 5 FPS
- Giao diện bám theo luồng nghiệp vụ `Intern-LPR-Gate.dc.html`; không cần pixel-perfect

**Giả định:**
- 2 camera cố định: GATE-01 (cổng) và BAI-KIEM (bãi kiểm)
- Các loại xe trong proposal đều nằm trong class của model detection phổ biến
- Single user, không cần authentication cho MVP
- Chạy local, không cần deploy cloud

**Câu hỏi mở (không blocking MVP):**
- File `Intern-LPR-Gate.dc.html` có sẵn chưa? Cần để Architecture xác nhận layout và flow UI chính xác.

---

## 11. Handoff sang Architecture

- **Mode:** `design-new`
- **Project root:** `d:/HuuThuan - Project/HiLab-SentriAI`
- **Canonical product path:** `docs/product/product.md`
- **Product constraints cần giữ nguyên:** >= 5 FPS; clip pre-saved ngay khi event; zone update real-time không cần restart; floating mini-alert cross-tab trong app
- **Feasibility/risk cần kiểm tra:** Performance khi chạy đồng thời 2 stream + LPR + object detection + clip ghi liên tục trên máy intern; dung lượng storage clip 10s tích lũy
- **Tích hợp cần lưu ý:** LLM cho Q&A (text-to-SQL hoặc function calling) — model và API key cần xác định ở Architecture; file UI mẫu `Intern-LPR-Gate.dc.html` cần được đọc để xác nhận layout

---

## Extension registry

Chưa có extension.
