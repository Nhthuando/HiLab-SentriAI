# SentriAI

SentriAI là hệ thống giám sát camera bằng AI, hỗ trợ nhận diện phương tiện, theo dõi hoạt động trong khu vực và hỏi đáp bằng ngôn ngữ tự nhiên.

## Chức năng chính

- Theo dõi cổng ra vào, nhận diện biển số và phân loại phương tiện đã đăng ký hoặc chưa xác định.
- Phát hiện xe nâng, xe tải và các đối tượng hợp lệ trong từng khu vực giám sát.
- Ghi nhận thời gian vào, thời gian ra, thời lượng hoạt động và trạng thái vi phạm.
- Hỏi đáp AI bằng tiếng Việt, ví dụ: “Hôm nay có bao nhiêu xe tải ra vào?” hoặc “Xe nâng hoạt động thế nào?”.
- Tạo clip sự kiện khi người dùng bấm **Xem video**, tránh sinh sẵn nhiều file không cần thiết.
- Quản lý khu vực, biển số đăng ký, nhãn nhận diện và mô hình AI.

## Công nghệ sử dụng

- **Frontend:** React, TypeScript, Vite.
- **Backend API:** Node.js, Express, Prisma, WebSocket.
- **AI hỏi đáp:** Google Gemini và bộ quy tắc nghiệp vụ riêng của SentriAI.
- **Xử lý camera:** Python, FastAPI, OpenCV, Ultralytics YOLO.
- **Cơ sở dữ liệu:** PostgreSQL trên Neon.

## Cấu trúc dự án

```text
HiLab-SentriAI/
├── frontend/                 Giao diện web
├── backend/
│   ├── node-api/             API, WebSocket, Prisma và AI hỏi đáp
│   ├── python-worker/        Nhận diện hình ảnh và xử lý camera/video
│   ├── config/               Cấu hình dùng chung
│   └── .env.example          Mẫu biến môi trường cho backend
└── docs/                     Tài liệu sản phẩm và kỹ thuật
```

## Yêu cầu

Trước khi chạy dự án, cần chuẩn bị:

- Node.js và npm.
- Python 3.11 trở lên.
- Một cơ sở dữ liệu PostgreSQL trên Neon.
- Gemini API key.
- Camera RTSP hoặc video cục bộ để làm nguồn kiểm thử.
- GPU NVIDIA là tùy chọn, nhưng nên có nếu cần xử lý video nhanh.

## Cài đặt

Các lệnh bên dưới được chạy từ thư mục gốc của dự án.

### 1. Tạo file môi trường

Từ thư mục gốc của dự án:

```powershell
Copy-Item backend/.env.example backend/.env
Copy-Item frontend/.env.example frontend/.env
```

Nếu dùng macOS hoặc Linux:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

Mở `backend/.env` và điền tối thiểu các giá trị sau:

```dotenv
NEON_DATABASE_URL=postgresql://...
GEMINI_API_KEY=...
GATE_CAMERA_URL=...
AREA_CAMERA_URL=...
CLIP_SOURCE_ROOTS=backend/data/samples
```

`GATE_CAMERA_URL` và `AREA_CAMERA_URL` có thể là URL RTSP hoặc đường dẫn tới video cục bộ. Đường dẫn tương đối được tính từ thư mục gốc của dự án. Video cục bộ phải nằm trong `CLIP_SOURCE_ROOTS`; dùng dấu `;` để ngăn cách nhiều thư mục trên Windows và dấu `:` trên macOS/Linux.

Không đưa file `.env` hay API key lên GitHub.

### 2. Cài Backend API

```bash
cd backend/node-api
npm install
npx prisma migrate deploy
```

### 3. Cài Python Worker

```bash
cd backend/python-worker
python -m venv .venv
```

Kích hoạt môi trường ảo trên Windows:

```powershell
.venv\Scripts\Activate.ps1
```

Hoặc trên macOS/Linux:

```bash
source .venv/bin/activate
```

Sau đó cài thư viện:

```bash
pip install -r requirements.txt
```

### 4. Cài Frontend

```bash
cd frontend
npm install
```

## Chạy dự án

Từ thư mục gốc, chạy cả ba dịch vụ bằng một lệnh:

```bash
npm run dev
```

Log trong terminal được gắn nhãn `[worker]`, `[api]` và `[web]`. Nhấn `Ctrl+C` một lần để dừng cả ba dịch vụ. Hãy dừng các dịch vụ đang chạy riêng trước khi dùng lệnh này để tránh trùng cổng.

Nếu muốn chạy riêng từng dịch vụ, dùng các lệnh bên dưới.

**Python Worker trên Windows**

```powershell
cd backend/python-worker
.\.venv\Scripts\python.exe main.py
```

**Python Worker trên macOS/Linux**

```bash
cd backend/python-worker
.venv/bin/python main.py
```

**Backend API**

```bash
cd backend/node-api
npm run dev
```

**Frontend**

```bash
cd frontend
npm run dev
```

Sau khi khởi động thành công:

- Giao diện: `http://localhost:5173`
- Backend API: `http://localhost:3001`
- Python Worker: `http://localhost:8001`

## Đổi nguồn camera hoặc video

Khi Python Worker đang chạy, sửa một trong hai giá trị trong `backend/.env` rồi lưu file:

```dotenv
GATE_CAMERA_URL=backend/data/samples/gate_sample.mp4
AREA_CAMERA_URL=backend/data/samples/area_sample.mp4
```

Worker phát hiện thay đổi trong khoảng hai giây; thời gian mở nguồn mới phụ thuộc vào file hoặc kết nối RTSP. Không cần `Ctrl+C`, không reload model AI và không khởi động lại Node API hoặc Frontend. Chỉ pipeline có URL thay đổi được reset.

Nếu file hoặc URL mới không hợp lệ, nguồn đang chạy được giữ nguyên và terminal sẽ hiển thị lỗi. Khi thay đổi `CLIP_SOURCE_ROOTS`, cần khởi động lại Python Worker vì allowlist này được cố định trong suốt một phiên chạy.

### Tự kiểm tra hot-reload

1. Chạy `npm run dev` và chờ ba dịch vụ sẵn sàng.
2. Đổi riêng `AREA_CAMERA_URL`, lưu `.env` và kiểm tra BAI-KIEM chuyển video còn GATE-01 giữ nguyên.
3. Đổi riêng `GATE_CAMERA_URL` và kiểm tra theo chiều ngược lại.
4. Thử một đường dẫn không tồn tại và xác nhận video cũ vẫn chạy.
5. Nhấn `Ctrl+C` một lần và xác nhận cả ba dịch vụ đã dừng.

## Cách hệ thống ghi nhận hoạt động

Mỗi lượt hoạt động được tạo khi một đối tượng đi vào khu vực giám sát và kết thúc khi đối tượng rời khỏi khu vực. AI hỏi đáp thống kê từ các lượt đã được hệ thống lưu, không đếm lại video mỗi khi người dùng đặt câu hỏi.

Clip không được tạo sẵn cho mọi lượt hoạt động. Khi người dùng chọn **Xem video**, hệ thống mới lấy đoạn video liên quan và tạo clip để phát lại.

## Kiểm tra mã nguồn

Chạy từng nhóm lệnh từ thư mục gốc của dự án.

**Backend API và AI hỏi đáp**

```bash
cd backend/node-api
npm run typecheck
npm run build
npm run test:qa
npm run test:domain-skill
```

**Frontend**

```bash
cd frontend
npm run lint
npm run build
```

## Tài liệu thêm

- [Mô tả sản phẩm](docs/product/product.md)
- [Kiến trúc hệ thống](docs/architecture/architecture.md)
- [Tài liệu backend](docs/backend/backend.md)
- [Tài liệu frontend](docs/frontend/frontend.md)
- [Kế hoạch triển khai](docs/plan/plan.md)
- [Bộ quy tắc nghiệp vụ cho AI](backend/node-api/src/ai/domain/sentriai-operations/SKILL.md)

## Lưu ý

- Các file video, clip, model AI và dữ liệu sinh ra khi chạy có thể rất lớn nên không nên đưa lên GitHub.
- Kết quả nhận diện phụ thuộc vào model, chất lượng camera, góc quay và cấu hình khu vực.
- Mỗi máy tự cấu hình đường dẫn video trong `backend/.env`; không sửa `.env.example` theo đường dẫn cá nhân.
