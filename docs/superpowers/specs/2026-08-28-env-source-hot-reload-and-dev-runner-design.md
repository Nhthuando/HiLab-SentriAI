# Thiết kế hot-reload nguồn video và lệnh chạy dự án hợp nhất

Ngày: 2026-08-28
Trạng thái: Đã duyệt thiết kế

## 1. Bối cảnh

SentriAI hiện đọc `GATE_CAMERA_URL` và `AREA_CAMERA_URL` từ `backend/.env` khi Python Worker khởi động. Mỗi lần đổi video kiểm thử, người phát triển phải dừng và chạy lại worker, khiến model AI, kết nối cơ sở dữ liệu và các tài nguyên pipeline bị khởi tạo lại.

Dự án cũng cần ba terminal riêng cho Python Worker, Node API và Frontend. README hiện hướng dẫn `python main.py` trong phần chạy dự án nhưng không nói rõ terminal mới phải kích hoạt môi trường ảo trước.

## 2. Mục tiêu

- Tự nhận thay đổi của `GATE_CAMERA_URL` và `AREA_CAMERA_URL` trong `backend/.env` mà không khởi động lại Python Worker.
- Chỉ thay nguồn và reset pipeline bị ảnh hưởng; pipeline còn lại tiếp tục hoạt động.
- Giữ model AI, FastAPI và kết nối cơ sở dữ liệu trong bộ nhớ.
- Bảo toàn ranh giới dữ liệu giữa video cũ và video mới.
- Cho phép chạy ba dịch vụ bằng một lệnh từ thư mục gốc.
- Dùng toàn bộ đường dẫn tương đối với repository để dự án chạy được sau khi clone sang thư mục khác.
- Cập nhật README bằng hướng dẫn đúng cho Windows, macOS và Linux.

## 3. Ngoài phạm vi

- Không chọn hoặc upload video từ giao diện web.
- Không hot-reload các biến môi trường ngoài hai biến nguồn camera.
- Không tự xóa lịch sử hoạt động khi đổi video.
- Không tạo clip trước; clip vẫn chỉ được tạo khi người dùng yêu cầu.
- Agent không chạy test tự động, replay video hoặc kiểm thử dữ liệu thật. Người dùng tự nghiệm thu sau khi bàn giao.

## 4. Theo dõi `backend/.env`

Python Worker khởi tạo một tác vụ nền nhẹ trong vòng đời FastAPI. Tác vụ kiểm tra `backend/.env` mỗi giây và chỉ đọc lại file khi dấu thời gian hoặc nội dung file thay đổi.

Để tránh đọc file trong lúc trình soạn thảo đang ghi, watcher chờ một khoảng debounce ngắn rồi đọc snapshot hoàn chỉnh. Snapshot chỉ lấy:

- `GATE_CAMERA_URL`, ánh xạ tới `GATE-01`.
- `AREA_CAMERA_URL`, ánh xạ tới `BAI-KIEM`.

Giá trị được chuẩn hóa trước khi so sánh để việc lưu lại `.env` mà không đổi URL không làm reset pipeline.

Watcher chạy ngoài luồng xử lý frame và không thực hiện decode hoặc inference. Vì vậy kiểm tra một file nhỏ mỗi giây không làm giảm FPS đáng kể.

## 5. Xác thực nguồn mới

Nguồn mạng được chấp nhận khi dùng giao thức `rtsp://`, `http://` hoặc `https://`.

Nguồn file cục bộ phải:

- Tồn tại và là file.
- Có phần mở rộng video được hỗ trợ.
- Nằm trong một thư mục được khai báo bởi `CLIP_SOURCE_ROOTS`.

Mỗi máy tự cấu hình `backend/.env`; file này không được commit. Đường dẫn nguồn có thể là tuyệt đối hoặc tương đối. Đường dẫn tương đối được phân giải ổn định từ thư mục gốc repository, không phụ thuộc terminal được mở tại đâu.

Nếu nguồn mới không hợp lệ, worker ghi log lỗi và giữ nguyên nguồn hiện tại. Không chuyển âm thầm sang video giả lập.

## 6. Thay nguồn an toàn

Mỗi pipeline cung cấp một thao tác thay nguồn có khóa đồng bộ. Trình tự chung:

1. Ghi nhận trạng thái active và viewer hiện tại.
2. Tạm dừng đọc frame của pipeline tương ứng.
3. Chờ frame đang xử lý hoàn tất.
4. Giải phóng `VideoCapture` và preview capture của nguồn cũ.
5. Tạo reader mới và xác nhận nguồn mở thành công.
6. Reset trạng thái chỉ thuộc timeline cũ.
7. Khôi phục trạng thái active/viewer trước đó.
8. Ghi log kết quả đổi nguồn.

Reader mới phải được mở thành công trước khi thay reader hiện tại. Nếu bước mở nguồn thất bại, reader cũ tiếp tục được sử dụng.

### 6.1. Pipeline GATE-01

Khi đổi nguồn GATE-01, hệ thống reset tracker biển số, cache OCR, passage state, circular buffer và tracking generation. Detector YOLO, LPR reader, executor và emitter được giữ nguyên.

### 6.2. Pipeline BAI-KIEM

Khi đổi nguồn BAI-KIEM, hệ thống:

- Kết thúc an toàn các activity/violation đang mở của nguồn cũ.
- Tăng runtime generation để tác vụ từ timeline cũ không ghi sang nguồn mới.
- Làm sạch tracker, buffer và trạng thái chuyển tiếp trong bộ nhớ.
- Khởi tạo coverage theo fingerprint, độ dài và loại của nguồn mới.
- Giữ detector, zone synchronizer, hàng đợi persistence, clip service và emitter.

Hoạt động đã lưu trước đó không bị tính lại. Mỗi bản ghi tiếp tục giữ metadata nguồn của chính nó. `CLIP_SOURCE_ROOTS` là allowlist ổn định để clip cũ vẫn có thể được tạo theo yêu cầu sau khi nguồn hiện tại thay đổi.

## 7. Quan sát và xử lý lỗi

Log thành công có camera ID và không lộ thông tin đăng nhập của URL mạng:

```text
[BAI-KIEM] Detected AREA_CAMERA_URL change
[BAI-KIEM] Source switched successfully
```

Log thất bại nêu lý do và xác nhận nguồn cũ vẫn chạy:

```text
[BAI-KIEM] New source is invalid; keeping current source
```

Endpoint health bổ sung trạng thái reload gần nhất ở mức an toàn, gồm camera ID, trạng thái, thời điểm và loại nguồn; không trả về URL RTSP chứa credential hoặc đường dẫn cục bộ đầy đủ.

Tác vụ watcher bị dừng sạch trong FastAPI lifespan khi worker tắt.

## 8. Chạy toàn bộ dự án bằng một lệnh

Repository bổ sung root `package.json` và một Node process runner không cần thư viện ngoài. Lệnh mặc định:

```bash
npm run dev
```

Runner khởi động:

- Python Worker trong `backend/python-worker`.
- Node API trong `backend/node-api`.
- Frontend trong `frontend`.

Runner tự chọn Python theo hệ điều hành:

- Windows: `backend/python-worker/.venv/Scripts/python.exe`.
- macOS/Linux: `backend/python-worker/.venv/bin/python`.

Log được gắn tiền tố `[worker]`, `[api]` và `[web]`. Nếu thiếu `.venv`, `backend/.env` hoặc dependency Node, runner dừng sớm với thông báo dễ hiểu. Khi nhận `Ctrl+C`, runner gửi tín hiệu dừng tới cả ba cây tiến trình và không để dịch vụ con chạy ngầm.

Việc hợp nhất terminal không tạo thêm pipeline hay model và không làm tăng đáng kể CPU, GPU hoặc RAM so với chạy ba terminal riêng.

## 9. README

README được cập nhật để:

- Dùng `.\.venv\Scripts\python.exe main.py` khi chạy riêng worker từ `backend/python-worker` trên Windows.
- Dùng `.venv/bin/python main.py` trên macOS/Linux.
- Đề xuất `npm run dev` từ thư mục gốc làm cách chạy thông thường.
- Hướng dẫn đổi video bằng cách sửa hai biến camera trong `backend/.env`.
- Giải thích `CLIP_SOURCE_ROOTS` là cấu hình riêng trên từng máy.
- Nêu rõ nguồn hợp lệ sẽ được áp dụng tự động và nguồn sai không thay thế nguồn đang chạy.

## 10. Tiêu chí nghiệm thu

- Lưu `backend/.env` mà không đổi URL không reset pipeline.
- Đổi `AREA_CAMERA_URL` chỉ thay nguồn BAI-KIEM.
- Đổi `GATE_CAMERA_URL` chỉ thay nguồn GATE-01.
- Đường dẫn sai giữ nguyên video đang chạy và tạo log rõ ràng.
- Đổi nguồn không reload model AI hoặc khởi động lại FastAPI.
- Không tự tạo clip trong lúc đổi nguồn.
- Dữ liệu của hai nguồn không bị trộn vào cùng một phiên hoạt động.
- `npm run dev` khởi động đủ ba dịch vụ.
- `Ctrl+C` tại root runner dừng đủ ba dịch vụ.
- Người dùng tự chạy và nghiệm thu; agent không chạy test, replay hoặc dữ liệu thật.
