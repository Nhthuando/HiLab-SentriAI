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

## Yêu cầu môi trường

Trước khi cài đặt, máy tính cần chuẩn bị:

- **Node.js**: Phiên bản 18.x trở lên và npm.
- **Python**: Phiên bản 3.11 hoặc 3.12 (khuyến nghị Python 3.12).
- **Cơ sở dữ liệu**: Chuỗi kết nối PostgreSQL (Neon cloud) do nhóm cung cấp hoặc tự tạo.
- **Gemini API Key**: Key Google AI Studio để sử dụng tính năng hỏi đáp AI.
- **Video kiểm thử**: Các file video mp4 mẫu (được gửi kèm riêng) hoặc luồng RTSP thực tế.
- **Kết nối Internet**: Cần thiết ở lần chạy đầu tiên để tải các thư viện và AI model cơ sở (`yolo11n.pt`, `fast-alpr`).

---

## Hướng dẫn cài đặt chi tiết (Dành cho thành viên mới clone về)

Thực hiện lần lượt theo các bước bên dưới từ thư mục gốc của dự án:

### Bước 1: Clone mã nguồn về máy

```bash
git clone https://github.com/Nhthuando/HiLab-SentriAI.git
cd HiLab-SentriAI
```

### Bước 2: Cài đặt Backend API (Node.js)

```bash
cd backend/node-api
npm install
npx prisma generate
```

> [!NOTE]
> Nếu bạn kết nối vào Database mới hoàn toàn, chạy thêm lệnh: `npx prisma migrate deploy` để đồng bộ bảng.

### Bước 3: Cài đặt Frontend (React + Vite)

```bash
cd ../../frontend
npm install
```

### Bước 4: Cài đặt Python AI Worker

```bash
cd ../backend/python-worker
```

Tạo môi trường ảo Python (**Bắt buộc đặt tên là `.venv`** để script chạy tự động nhận diện được):

```bash
python -m venv .venv
```

Kích hoạt môi trường ảo:
- Trên **Windows (PowerShell)**:
  ```powershell
  .venv\Scripts\Activate.ps1
  ```
  *(Nếu gặp lỗi script execution policy trên PowerShell, mở bằng quyền Admin và gõ: `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`)*
- Trên **macOS / Linux**:
  ```bash
  source .venv/bin/activate
  ```

Cài đặt các gói phụ thuộc:
```bash
pip install -r requirements.txt
```

### Bước 5: Cấu hình biến môi trường (`backend/.env`)

1. Tạo file `backend/.env` (bằng cách sao chép file `.env` được gửi hoặc tạo từ `backend/.env.example`).
2. Mở file `backend/.env` và **chỉnh sửa các thông số đường dẫn video cho đúng với máy của bạn**:

```dotenv
# ─── CSDL & Gemini API ───────────────────────────────────────────
NEON_DATABASE_URL="postgresql://..."
GEMINI_API_KEY="..."

# ─── NGUỒN VIDEO KIỂM THỬ (QUAN TRỌNG: Cần trỏ đúng vị trí file trên máy bạn) ──
# Ví dụ: Nếu bạn để video tại C:\SentriAI_Videos
GATE_CAMERA_URL=C:\SentriAI_Videos\GATE\Gate-In2.mp4
AREA_CAMERA_URL=C:\SentriAI_Videos\KiemHoa\KiemHoa-Hik (1).mp4
CLIP_SOURCE_ROOTS=C:\SentriAI_Videos

# (Hoặc nếu để video trong thư mục backend/data/samples của dự án)
# GATE_CAMERA_URL=backend/data/samples/gate_sample.mp4
# AREA_CAMERA_URL=backend/data/samples/area_sample.mp4
# CLIP_SOURCE_ROOTS=backend/data/samples
```

> [!IMPORTANT]
> **LƯU Ý VỀ VIDEO TEST:**
> Các file video dung lượng lớn không đưa lên GitHub. Nếu đường dẫn video trong `.env` không tồn tại trên máy bạn, hệ thống sẽ tự fallback về **ảnh chụp tĩnh** (không có chuyển động, không nhận diện xe mới và không phát sinh clip). Hãy chắc chắn bạn đã tải video mẫu và sửa đường dẫn trong `.env` trỏ đúng vào đó.

---

## Khởi động hệ thống

Từ **thư mục gốc** của dự án (`HiLab-SentriAI`), bạn chỉ cần chạy một lệnh duy nhất:

```bash
npm run dev
```

Script sẽ tự động khởi động đồng thời cả 3 dịch vụ:
- `[worker]` **Python AI Worker**: Chạy trên cổng `8001`
- `[api]` **Backend Node API**: Chạy trên cổng `3001`
- `[web]` **Frontend Web App**: Chạy trên `http://localhost:5173`

👉 Mở trình duyệt và truy cập: **`http://localhost:5173`**

Nhấn `Ctrl + C` trong terminal để dừng toàn bộ dịch vụ một cách an toàn.

---

### Tùy chọn: Chạy riêng từng dịch vụ (Nếu muốn debug riêng)

Nếu bạn không muốn chạy bằng lệnh `npm run dev` tổng hợp, mở 3 cửa sổ terminal riêng biệt:

1. **Terminal 1 - Python Worker**:
   ```powershell
   cd backend/python-worker
   .\.venv\Scripts\python.exe main.py
   ```
   *(Trên macOS/Linux: `source .venv/bin/activate && python main.py`)*

2. **Terminal 2 - Backend API**:
   ```bash
   cd backend/node-api
   npm run dev
   ```

3. **Terminal 3 - Frontend**:
   ```bash
   cd frontend
   npm run dev
   ```

---

## Đổi nguồn camera / video (Hot-reload không cần restart)

Khi hệ thống đang chạy, bạn có thể đổi video kiểm thử bằng cách sửa file `backend/.env` và bấm **Save**:

```dotenv
GATE_CAMERA_URL=C:\SentriAI_Videos\GATE\another_gate_video.mp4
AREA_CAMERA_URL=C:\SentriAI_Videos\KiemHoa\another_area_video.mp4
```

Python Worker sẽ tự nhận diện sau 2 giây và chuyển video mà không cần dừng server hay tải lại AI model.

---

## Xử lý các lỗi thường gặp (Troubleshooting)

1. **Lỗi `[dev] Thiếu Python trong backend/python-worker/.venv...`:**
   - Nguyên nhân: Môi trường ảo Python chưa được tạo hoặc tạo với tên khác `.venv`.
   - Khắc phục: Đảm bảo thư mục môi trường ảo nằm đúng tại `backend/python-worker/.venv`.

2. **Video trên web không chạy, chỉ hiện ảnh tĩnh:**
   - Nguyên nhân: Đường dẫn `GATE_CAMERA_URL` hoặc `AREA_CAMERA_URL` trong `backend/.env` bị sai, file video không tồn tại trên máy bạn.
   - Khắc phục: Kiểm tra lại đường dẫn tuyệt đối hoặc tương đối tới file video thực tế trên máy tính của bạn.

3. **Bấm "Xem video" ở bảng sự kiện báo lỗi không tạo được clip:**
   - Nguyên nhân: Thư mục chứa video gốc chưa được khai báo trong `CLIP_SOURCE_ROOTS`.
   - Khắc phục: Thêm thư mục chứa video vào `CLIP_SOURCE_ROOTS` trong `backend/.env` rồi khởi động lại worker.

4. **Lỗi thiếu Prisma Client trong Node API:**
   - Khắc phục: Vào thư mục `backend/node-api` và chạy lệnh `npx prisma generate`.

5. **Lỗi xung đột cổng (Port already in use 3001 / 8001 / 5173):**
   - Khắc phục: Đảm bảo đã tắt các tiến trình cũ trước khi chạy `npm run dev`.

---

## Kiểm tra mã nguồn

Chạy từng nhóm lệnh từ thư mục gốc của dự án nếu cần kiểm thử chất lượng code:

**Backend API và AI hỏi đáp:**
```bash
cd backend/node-api
npm run typecheck
npm run build
npm run test:qa
npm run test:domain-skill
```

**Frontend:**
```bash
cd frontend
npm run lint
npm run build
```

---

## Tài liệu tham khảo thêm

- [Mô tả sản phẩm](docs/product/product.md)
- [Kiến trúc hệ thống](docs/architecture/architecture.md)
- [Tài liệu backend](docs/backend/backend.md)
- [Tài liệu frontend](docs/frontend/frontend.md)
- [Kế hoạch triển khai](docs/plan/plan.md)
- [Bộ quy tắc nghiệp vụ cho AI](backend/node-api/src/ai/domain/sentriai-operations/SKILL.md)
