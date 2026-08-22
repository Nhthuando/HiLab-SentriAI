# SentriAI — Kiến trúc kỹ thuật

## 1. Tóm tắt để ra quyết định

- **Mode:** `design-new`
- **Product revision đã đọc:** `docs/product/product.md` — Đã duyệt; extension `ext-20260820-object-detection-training` (r1) đã phê duyệt
- **Mục tiêu kỹ thuật:** Xây dựng hệ thống giám sát camera AI gồm 4 module (M1 Cổng, M2 Bãi Kiểm, M3 Cài đặt, M4 Q&A), chạy local, demo 2 tuần, single user
- **Kết luận feasibility:** Khả thi có điều kiện
- **Khuyến nghị chính:** Python AI Worker + Node.js/Express API + React Vite SPA + PostgreSQL Neon (cloud) + Prisma ORM + Gemini 3.5 Flash Lite function calling
- **Vì sao:** Tách AI pipeline (Python native) khỏi API layer (Node.js/TypeScript ecosystem), dùng WebSocket proxy cho real-time feed, Neon free tier đủ cho intern demo 2 tuần
- **Điều kiện:** Demo cần Internet (Neon + Gemini API); Python worker phải batch-insert để giảm latency round-trip lên Neon; cần `.env` chứa `NEON_DATABASE_URL` và `GEMINI_API_KEY`

---

## 2. Nguồn và phạm vi đã đọc

- **Product spec:** `docs/product/product.md` — Đã duyệt, HuuThuan, 2026-08-17
- **Architecture hiện tại:** Không có (design-new)
- **Code/config/infrastructure evidence:** Repository trống — chỉ có `docs/` và `proposal/`
- **Phạm vi đánh giá:** Toàn bộ MVP (M1 + M2 + M3 + M4), local deployment, single user
- **Phần không đánh giá:** File `Intern-LPR-Gate.dc.html` chưa có trong repository — layout UI chưa xác nhận chính xác (không blocking architecture)

---

## 3. Trace Product requirement sang kiến trúc

| Product requirement/constraint | Architectural response | Feasibility | Risk/dependency |
|---|---|---|---|
| Nhận RTSP hoặc video file, xử lý ≥ 5 FPS | Python AI Worker đọc stream bằng OpenCV, xử lý frame trong thread/asyncio loop riêng | Khả thi | GPU không bắt buộc cho YOLO-nano/small; cần benchmark trên máy intern |
| LPR nhận diện biển số khi xe vào zone làn IN | Python AI Worker: YOLO detect xe → kiểm tra point-in-polygon zone → PaddleOCR/EasyOCR đọc biển | Khả thi | Độ chính xác OCR phụ thuộc chất lượng video; BR-02 tự gán XE LẠ nếu biển chưa đăng ký |
| Phát hiện đối tượng trong zone đa giác (BAI-KIEM) | Python AI Worker: YOLO detect → point-in-polygon check → so khớp loại với zone rules | Khả thi | BR-03/BR-04 xử lý CHƯA XÁC ĐỊNH trong zone rule |
| Live feed với bbox overlay, badge, màu trạng thái | Python encode JPEG frame + bbox metadata → WebSocket nội bộ → Node.js proxy → Browser render trên Canvas/img | Khả thi | Latency phụ thuộc encoding speed; JPEG quality 70-80 đủ cho demo |
| Alert panel real-time + floating mini-alert cross-tab | Node.js nhận event từ Python, push SSE/WebSocket xuống browser; floating mini-alert dùng BroadcastChannel API giữa các tab | Khả thi | BroadcastChannel không hoạt động cross-origin; cùng origin là đủ |
| Clip 10s pre-saved ngay khi event xảy ra | Python AI Worker dùng circular buffer 10s frames; khi event xảy ra, flush buffer ra file MP4 trong background thread | Khả thi có điều kiện | Buffer 10s × 2 stream × ~5 FPS × JPEG ≈ ~50-100 MB RAM; cần giới hạn resolution |
| Zone update real-time không cần restart | Zone config lưu DB; Python Worker poll DB mỗi 5s hoặc Node.js push thông báo qua WebSocket nội bộ khi zone thay đổi | Khả thi | BR-07 yêu cầu hiệu lực ngay lập tức |
| Ghi sự kiện: timestamp, biển số, làn, trạng thái, ảnh cắt, clip path | Python Worker ghi vào PostgreSQL Neon qua asyncpg (batch insert); ảnh cắt và clip lưu local filesystem | Khả thi có điều kiện | Cần Internet cho Neon; disk local cho clip/ảnh |
| AI Q&A bằng ngôn ngữ tự nhiên, trả lời kèm clip reference | Node.js nhận câu hỏi → gọi Gemini 3.5 Flash Lite với bộ function tool riêng → function gọi Prisma query DB → LLM tổng hợp + trả clip reference | Khả thi | BR-09: chỉ query dữ liệu đã lưu, không real-time |
| Vẽ zone đa giác trên khung hình thật | React Canvas component cho phép click/drag vẽ polygon; lưu tọa độ % (normalized) vào DB qua Node.js API | Khả thi | Cần snapshot frame từ camera để làm nền vẽ |
| Nhãn đối tượng: import ảnh/video, vẽ bbox, đặt tên | React upload component + canvas bbox editor; lưu ảnh/metadata vào local filesystem + DB | Khả thi | Mẫu phải giữ liên kết tới media/frame gốc để có thể xuất dataset bất biến |
| Huấn luyện thủ công từ mẫu nhãn đối tượng | Node điều phối job riêng; Python training runner xuất dataset, fine-tune, đánh giá và tạo candidate model version | Khả thi có điều kiện | GPU 4 GB phải ưu tiên inference; candidate chỉ kích hoạt sau đánh giá và thao tác người dùng |
| Single user, no auth, local deployment | Không có authentication layer; CORS restricted đến localhost; env file cho secrets | Khả thi | Secret (Neon URL, Gemini key) không được commit vào Git |

---

## 4. Đánh giá feasibility và rủi ro

- **Điểm khả thi rõ:** Stack Python AI + Node.js + React đã được dùng rộng rãi; YOLO + OpenCV + PaddleOCR đủ cho demo; Gemini function calling đã được document rõ
- **Constraint kỹ thuật:**
  - Máy intern cần chạy 2 stream AI đồng thời ≥ 5 FPS → YOLO model size cần là `nano` hoặc `small`; resolution input nên giảm xuống 480p hoặc 640p
  - Circular buffer clip 10s: cần giới hạn RAM bằng cách encode frame JPEG với quality thấp hơn (Q=60) trong buffer
  - Neon free tier: ~500MB storage, 100 compute hours/tháng — đủ cho 2 tuần demo; batch-insert mỗi 0.5-1s thay vì ghi từng event
- **Risk cần giảm thiểu:**
  - **R1: Performance** — 2 stream YOLO đồng thời có thể quá tải CPU nếu không tối ưu. Mitigated bằng: dùng YOLO-nano, giảm resolution, dùng thread pool riêng cho mỗi stream
  - **R2: Neon connectivity** — Demo cần Internet. Mitigated bằng: hiển thị error rõ ràng nếu DB không kết nối được (AC-09 pattern)
  - **R3: Clip storage** — Không có giới hạn disk tự động. Mitigated bằng: cảnh báo khi disk còn < 1GB; clip field = null nếu ghi thất bại (BR-05)
  - **R4: OCR chất lượng thấp** — Biển số mờ vẫn ghi sự kiện với confidence thấp (Business rule đã cover)
  - **R5: Tranh chấp GPU train/inference** — Training không được làm FPS Area Monitor thấp hơn ngưỡng vận hành. Mitigated bằng GPU governor: giới hạn batch/VRAM, mixed precision, đo FPS/VRAM, pause training khi Area FPS tiến sát 8 FPS và chỉ resume khi ổn định; inference đang chạy luôn có quyền ưu tiên.
  - **R6: Mẫu nhãn kém hoặc lệch nguồn video** — Fine-tune có thể giảm chất lượng tổng quát. Mitigated bằng dataset snapshot, split theo source media, evaluation hold-out và không tự động thay model đang chạy.
- **Dependency ngoài:** Gemini API (cần API key), Neon PostgreSQL (cần account + connection string), PaddleOCR hoặc EasyOCR (pip install)
- **Giả định kỹ thuật:**
  - Máy intern có CPU đủ cho YOLO-nano × 2 stream tại 640×480
  - Demo chạy có Internet
  - Các class YOLO phổ biến (COCO) bao phủ xe tải, xe máy, người — một số loại (xe nâng, xe cẩu) có thể cần model fine-tuned hoặc mapping thủ công

---

## 5. Các lựa chọn kiến trúc quan trọng

| Quyết định | Phương án đã xem | Phương án chọn | Lý do | Điều kiện đổi |
|---|---|---|---|---|
| Backend AI language | Python thuần / Python + Node.js / Python + Next.js | Python Worker + Node.js API | Python native cho AI ecosystem; Node.js phù hợp TypeScript/Prisma/Express | Nếu team chỉ biết 1 ngôn ngữ → Python thuần |
| Real-time frame delivery | WebSocket Python→Node proxy / Node polling SSE / Browser trực tiếp Python | WebSocket Python → Node.js proxy → Browser | 1 entry point cho browser; Node kiểm soát rate; dễ debug | Nếu latency quá cao, thử MJPEG stream thay JPEG WebSocket |
| Database | SQLite local / PostgreSQL Neon / PostgreSQL local Docker | PostgreSQL Neon + Prisma | Setup 5 phút, free tier, Prisma ecosystem, schema migration rõ ràng | Nếu offline bắt buộc → PostgreSQL Docker local |
| LLM Q&A | Gemini / OpenAI / Ollama local | Gemini 3.5 Flash Lite + function calling | Có sẵn, tốc độ cao (350 tok/s), multimodal, function calling mạnh, có free tier | Nếu quota hết → đổi sang GPT-4o-mini |
| Q&A pattern | Text-to-SQL thuần / Function calling với bộ tool riêng | Function calling với tool set riêng | Kiểm soát query an toàn, tránh SQL injection từ LLM, dễ test từng function | Nếu query phức tạp hơn scope → thêm tool mới |
| Frontend framework | React Vite / Next.js / Vue 3 / Vanilla JS | React + Vite + TypeScript | SPA phù hợp, WebSocket render đơn giản, ecosystem phong phú | Nếu cần SSR → Next.js |

---

## 6. Kiến trúc đề xuất

### 6.1 Thành phần và trách nhiệm

```
+------------------------------------------------------------------+
|                         LOCAL MACHINE                            |
|                                                                  |
|  +----------------------+    +--------------------------------+  |
|  |  Python AI Worker    |    |   Node.js API Server           |  |
|  |  (port: 8001)        |    |   (port: 3001)                 |  |
|  |                      |    |                                |  |
|  | - OpenCV stream read |<-->| - Express REST API             |  |
|  | - YOLO detection     |    | - WebSocket proxy (feed)       |  |
|  | - PaddleOCR/EasyOCR  |    | - Prisma ORM                   |  |
|  | - Zone polygon check |    | - Gemini function calling      |  |
|  | - Circular buffer    |    | - Zone/label CRUD              |  |
|  | - Clip writer        |    | - Event/clip query             |  |
|  | - asyncpg -> Neon    |    |                                |  |
|  | - WebSocket server   |    |                                |  |
|  +----------------------+    +--------------------------------+  |
|           ^                              ^                       |
|           | RTSP / video file            | HTTP + WebSocket      |
|           |                              |                       |
|  +--------+----------+       +-----------+--------------------+  |
|  | Video Sources     |       |   React + Vite SPA             |  |
|  | (RTSP/file)       |       |   (port: 5173)                 |  |
|  +-------------------+       |                                |  |
|                              | - Live Feed Canvas (bbox)      |  |
|  +-------------------+       | - Alert Panel                  |  |
|  | Local Filesystem  |       | - Floating mini-alert          |  |
|  | /clips/*.mp4      |       | - Zone polygon editor          |  |
|  | /crops/*.jpg      |       | - Label tool                   |  |
|  +-------------------+       | - Q&A Chat                     |  |
|                              +--------------------------------+  |
+------------------------------------------------------------------+
         |                              |
         v                              v
+------------------------+   +--------------------------+
|  Neon PostgreSQL       |   |  Gemini 3.5 Flash Lite   |
|  (Internet required)   |   |  (Google AI API)         |
|  Prisma migrations     |   |  Function calling        |
+------------------------+   +--------------------------+
```

### 6.2 Luồng hoạt động và loại dữ liệu

**Luồng 1 — Khởi động và cấu hình:**
Node.js API Server khởi động → load zone config và label config từ Neon DB qua Prisma → expose REST API cho frontend. Python AI Worker khởi động → đọc zone config từ Neon qua asyncpg → bắt đầu đọc 2 video stream (GATE-01 + BAI-KIEM) qua OpenCV. Python Worker duy trì background poller mỗi 5s để detect zone config thay đổi và áp dụng ngay (đáp ứng BR-07).

**Luồng 2 — Real-time frame processing và delivery:**
Python AI Worker đọc frame → resize xuống 640×480 → chạy YOLO inference → với mỗi detection: kiểm tra point-in-polygon cho từng zone active → xác định trạng thái (XE QUEN/XE LẠ/VI PHẠM/BÌNH THƯỜNG) → encode frame thành JPEG + đóng gói metadata bbox → gửi qua WebSocket nội bộ (localhost:8001/ws/{camera_id}) → Node.js WebSocket proxy nhận và forward xuống browser. Browser render JPEG lên Canvas element, vẽ overlay bbox từ metadata JSON.

**Luồng 3 — LPR tại cổng (M1):**
Frame vào zone làn IN → YOLO detect xe → crop vùng biển số → PaddleOCR/EasyOCR đọc text → tra danh sách biển số đã đăng ký trong DB → gán trạng thái XE QUEN/XE LẠ → ghi event vào DB (batch mỗi 500ms) → lưu ảnh cắt biển số vào `/crops/` → flush circular buffer thành clip 10s vào `/clips/`. Node.js nhận event notification từ Python qua WebSocket nội bộ → push event xuống browser để hiển thị alert panel.

**Luồng 4 — Zone violation detection (M2):**
Frame có đối tượng → YOLO detect với class mapping sang loại nhãn tiếng Việt → point-in-polygon kiểm tra tâm đối tượng với từng zone active → nếu loại đối tượng nằm trong danh sách cấm của zone: Python mở event vi phạm (ghi thời gian vào, clip buffer bắt đầu từ lúc vào) → gửi violation event tới Node.js → Node.js push tới browser (alert panel + floating mini-alert nếu tab không active). Khi đối tượng rời zone: Python đóng event (ghi thời gian ra + duration) → lưu clip 10s từ lúc vào. Không sinh alert lặp khi đối tượng vẫn trong zone (BR-06).

**Luồng 5 — Floating mini-alert cross-tab:**
Browser tab giám sát nhận violation event qua WebSocket → nếu tab không visible (document.hidden = true), post message qua BroadcastChannel("sentriai-alerts") → các tab khác trong cùng app listen BroadcastChannel và hiển thị floating mini-alert góc dưới phải → khi user quay về tab giám sát, BroadcastChannel clear mini-alert (BR-08).

**Luồng 6 — Cài đặt (M3):**
Vẽ zone: React lấy snapshot frame từ API → render lên canvas → user vẽ polygon (click góc, kéo điểm) → lưu tọa độ (normalized 0-1) qua REST API → Node.js/Prisma ghi DB → Python Worker nhận cập nhật qua poller → zone có hiệu lực ngay (AC-05). Gắn nhãn biển: REST CRUD danh sách biển số + trạng thái. Nhãn đối tượng: upload ảnh/video frame → React canvas bbox editor → POST label data → lưu metadata vào DB + ảnh vào local filesystem.

**Luồng 7 — Q&A AI (M4):**
User nhập câu hỏi → React POST tới Node.js API → Node.js gọi Gemini 3.5 Flash Lite với system prompt mô tả DB schema và bộ tool có sẵn → LLM chọn function phù hợp (ví dụ: `get_stranger_vehicles_today`, `get_violations_by_zone`, `get_clip_reference`) → Node.js execute function với Prisma → trả kết quả về LLM → LLM tổng hợp câu trả lời kèm clip reference → Node.js trả response kèm `clip_url` → frontend hiển thị nút tải clip (BR-09: chỉ query data đã lưu).

### 6.3 Công nghệ

| Phần | Quyết định | Lý do | Khi cần đổi |
|---|---|---|---|
| AI pipeline | Python 3.11+ | YOLO, OpenCV, PaddleOCR native Python | — |
| Object detection | YOLOv8-nano hoặc YOLOv8-small (Ultralytics) | Nhanh, CPU-friendly, COCO class phủ đủ loại xe/người | Nếu accuracy thấp → YOLOv8-medium |
| LPR/OCR | PaddleOCR (ưu tiên) hoặc EasyOCR | PaddleOCR nhanh hơn, hỗ trợ tiếng Việt; EasyOCR dễ install hơn | Nếu accuracy biển số thấp → thử cả hai |
| Zone detection | Shapely (Python) | Point-in-polygon chính xác với polygon phức tạp | — |
| Stream reading | OpenCV + ffmpeg | Hỗ trợ RTSP + video file, frame extraction dễ | — |
| Clip writer | OpenCV VideoWriter hoặc ffmpeg subprocess | Ghi MP4 từ frame buffer | — |
| AI process server | FastAPI + uvicorn (async) | Cần WebSocket server + HTTP callback endpoint | — |
| API server | Node.js + Express + TypeScript | Prisma chỉ chạy Node.js/TS; ecosystem mạnh | Nếu cần API routes SSR → Next.js |
| ORM | Prisma (Node.js) | Schema migration, type-safe, Neon-compatible | — |
| Python DB driver | asyncpg | Async, nhanh, tương thích PostgreSQL | psycopg2 nếu sync đủ |
| Database | PostgreSQL (Neon cloud) | Free tier 500MB đủ demo; serverless, setup 5 phút | PostgreSQL Docker nếu offline bắt buộc |
| LLM | Gemini 3.5 Flash Lite | 350 tok/s, function calling, multimodal, có free tier | GPT-4o-mini nếu quota hết |
| LLM integration | Google Generative AI SDK (Node.js) | Official SDK, function calling support | — |
| Frontend | React 18 + Vite + TypeScript | SPA real-time, WebSocket dễ, ecosystem phong phú | — |
| UI state | Zustand hoặc React Context | Lightweight state cho alert panel, zone editor | Redux nếu state phức tạp hơn |
| Real-time (browser) | WebSocket (từ Node.js proxy) | Bidirectional, low latency, native browser support | SSE nếu chỉ cần server-push |
| Cross-tab alert | BroadcastChannel API | Native browser, không cần server roundtrip | SharedWorker nếu cần complex logic |
| Inter-process (Python↔Node) | WebSocket (Python expose ws server, Node connect) | Đơn giản, JSON message, không cần gRPC | HTTP polling nếu latency không quan trọng |
| Custom model lifecycle | Dataset snapshot + Ultralytics fine-tune process + immutable candidate versions | Tái lập được kết quả, tách train khỏi inference, rollback rõ ràng | Nếu candidate không đạt ngưỡng accuracy/FPS → giữ nguyên model active |

---

## 7. Chạy dự án và nơi triển khai

**Môi trường:** Local machine, chạy offline trừ Neon DB và Gemini API (cần Internet).

**Cách chạy:**
1. Copy `.env.example` → `.env`, điền `NEON_DATABASE_URL` và `GEMINI_API_KEY`
2. `cd python-worker && pip install -r requirements.txt && python main.py`
3. `cd node-api && npm install && npx prisma migrate deploy && npm run dev`
4. `cd frontend && npm install && npm run dev`
5. Mở `http://localhost:5173`

**Cấu trúc thư mục đề xuất:**
```
HiLab-SentriAI/
├── python-worker/         # AI pipeline (Python)
│   ├── main.py
│   ├── requirements.txt
│   ├── stream/            # OpenCV stream reader
│   ├── detection/         # YOLO + OCR logic
│   ├── zone/              # Point-in-polygon, zone state
│   ├── buffer/            # Circular frame buffer + clip writer
│   └── db/                # asyncpg client
├── node-api/              # API server (Node.js/TypeScript)
│   ├── src/
│   │   ├── routes/        # REST endpoints
│   │   ├── ws/            # WebSocket proxy
│   │   ├── ai/            # Gemini function calling
│   │   └── prisma/        # Prisma client
│   └── prisma/
│       └── schema.prisma
├── frontend/              # React + Vite SPA
│   ├── src/
│   │   ├── pages/         # Gate, Area, Settings, QA
│   │   ├── components/    # Feed, AlertPanel, ZoneEditor...
│   │   └── hooks/         # useWebSocket, useBroadcastChannel...
│   └── vite.config.ts
├── data/
│   ├── clips/             # MP4 clips (local)
│   └── crops/             # Crop images (local)
│   └── training/          # Dataset snapshots, báo cáo evaluation (local)
├── models/
│   └── versions/          # Candidate/active custom model artifacts, immutable theo version
├── docs/
│   ├── product/product.md
│   └── architecture/architecture.md
└── .env.example
```

**Deployment:** Local only cho MVP. Không có cloud deploy trong scope.

---

## 8. Security, reliability và operations

| Safeguard | Risk/requirement liên quan | Cách đáp ứng | Trade-off |
|---|---|---|---|
| Secret không commit vào Git | NEON_DATABASE_URL và GEMINI_API_KEY bị lộ nếu push lên GitHub public | `.env` trong `.gitignore`; cung cấp `.env.example` | Intern cần nhớ tự điền `.env` |
| Clip ghi thất bại không crash | BR-05: disk đầy → ghi sự kiện vẫn thành công; clip = null | Python Worker wrap clip writer trong try/except; ghi event trước khi ghi clip | Không có recovery clip đã miss |
| Stream ngắt không crash app | AC-09: stream ngắt → hiển thị "Mất kết nối", không crash | Python Worker reconnect loop với backoff; gửi disconnect event qua WebSocket tới Node.js | Reconnect có thể tạo gap trong event history |
| Concurrent write Python + Node.js | Python Worker ghi event qua asyncpg; Node.js đọc/ghi config qua Prisma — cùng DB | Prisma và asyncpg đều dùng connection pooling; Neon xử lý concurrent connection | Neon free tier limit concurrent connections (~10) |
| Zone config stale | Python Worker dùng zone config cũ nếu không poll kịp | Python poll zone mỗi 5s; Node.js gửi "zone_updated" message qua WebSocket nội bộ khi có thay đổi | Tối đa 5s delay trước khi zone mới có hiệu lực (acceptable) |
| RAM overflow từ circular buffer | 2 stream × buffer 10s × 5 FPS = 100 frames/stream | Giới hạn buffer size bằng deque(maxlen=50); encode JPEG Q=60 trong buffer (~15-30KB/frame) | Chất lượng clip buffer thấp hơn live feed |
| Gemini API timeout | Q&A phụ thuộc Gemini external API | Timeout 15s; trả lỗi rõ ràng cho user nếu timeout | Không có local fallback LLM |
| LLM query an toàn | LLM không sinh SQL tùy tiện vào DB | Function calling với tool set định nghĩa sẵn — LLM chỉ gọi được các function đã define | Nếu user hỏi ngoài scope tool → LLM báo "không tìm thấy thông tin" |
| Training không làm gián đoạn monitor | BR-11 và ngưỡng FPS Area Monitor | Training runner là process tách biệt; governor giảm batch/tạm dừng trước khi ảnh hưởng inference; active model không bị ghi đè | Thời gian train dài hơn trên GPU 4 GB |
| Candidate model an toàn | Fine-tune lỗi, OOM, hoặc regression | Artifact version bất biến, checksum/metadata, evaluate trước promote, activate nguyên tử và giữ version trước để rollback | Cần thêm dung lượng local cho artifact/dataset |
| Dataset tái lập và không rò split | Accuracy phải đo trên dữ liệu chưa thấy khi train | Snapshot mẫu tại thời điểm chạy; split theo source image/video, không theo frame đơn lẻ; báo cáo sample bị loại | Dataset nhỏ có thể chưa đủ đại diện mọi video |

---

## 9. Blocker cần trả về Product

**Không có PRODUCT_BLOCKER.**

Một câu hỏi mở không blocking:
- File `Intern-LPR-Gate.dc.html` chưa có trong repository — architecture không phụ thuộc file này; khi có, team frontend đọc để xác nhận layout component.

---

## 10. Giả định và câu hỏi kỹ thuật còn mở

| # | Giả định/câu hỏi | Impact nếu sai | Hành động |
|---|---|---|---|
| GA-01 | Máy intern đủ CPU chạy YOLOv8-nano × 2 stream tại 640×480, ≥ 5 FPS | Phải giảm thêm resolution hoặc chạy 1 stream tại 1 thời điểm | Benchmark ngay khi có máy; fallback: YOLOv8-nano ở 320×320 |
| GA-02 | Demo luôn có Internet (Neon + Gemini) | Cần chuyển sang SQLite hoặc PostgreSQL Docker | Quyết định lúc cần; không thay đổi architecture tổng thể |
| GA-03 | Mẫu gán nhãn đủ đa dạng để fine-tune các lớp ngoài COCO (ví dụ xe nâng) | Candidate không đạt accuracy hoặc dễ nhầm lớp xe | Chỉ đánh giá/promotion khi đạt ngưỡng trên hold-out theo source; bổ sung mẫu từ video thất bại nếu chưa đạt |
| GA-04 | PaddleOCR hoặc EasyOCR đạt ≥ 80% accuracy với biển số Việt Nam trong video mẫu | Phải thử cả hai, có thể cần preprocessing (sharpen, denoise) | Không thay đổi architecture; chỉ đổi OCR engine |
| GA-05 | Neon free tier đủ (~500MB, 100 compute hours) cho 2 tuần demo | Cần nâng gói hoặc chuyển sang local PostgreSQL | Theo dõi usage; fallback rõ ràng |

---

## 11. Bổ sung kiến trúc: huấn luyện từ mẫu nhãn đối tượng

**Luồng 8 — Train, đánh giá và kích hoạt model:** Người dùng yêu cầu train thủ công trong M3 → Node tạo training job và chụp snapshot bất biến của các sample hợp lệ → dataset exporter resolve media gốc, trích frame video đúng timestamp, chuẩn hoá bbox và tách train/validation theo source media → Python training runner fine-tune custom detector Ultralytics trong process riêng → GPU governor theo dõi FPS của Area Monitor, VRAM và tiến trình train; governor hạ batch hoặc pause/resume job trước khi inference bị ảnh hưởng → runner đánh giá candidate trên validation hold-out, đo quality lẫn tốc độ inference và regression cho người/các lớp xe nền → lưu artifact, metrics và trạng thái candidate version → chỉ thao tác activate rõ ràng của người dùng mới nạp candidate như một lớp bổ sung vào pipeline hybrid; base YOLO vẫn tiếp tục nhận diện người/container/các xe COCO. Lỗi hoặc đánh giá không đạt giữ nguyên baseline và custom version đang active.

**Ranh giới thành phần:** React chỉ khởi tạo job, hiển thị tiến độ/báo cáo và yêu cầu activate/rollback. Node API là owner của job state, dataset snapshot metadata, version state và quyền chuyển trạng thái. Python Worker tiếp tục phục vụ video inference; Python training runner độc lập, không dùng cùng model instance đang active. PostgreSQL lưu metadata bền vững; local filesystem chỉ lưu media, dataset snapshot và model artifact theo version. Database/API/UI schema chi tiết thuộc tài liệu downstream, không được suy diễn trong extension này.

**Chính sách hybrid và GPU:** Base YOLO là detector luôn-on cho người/container/các phương tiện COCO. Custom candidate chỉ đóng góp các lớp đã train (ví dụ `forklift`) và không được đổi label COCO nền nếu không có bằng chứng regression. Activate chỉ thay custom version đang bổ sung; rollback tắt custom version đó để base YOLO tiếp tục chạy. Trên máy hiện tại RTX 3050 Laptop 4 GB, fine-tune ưu tiên cấu hình adaptive batch, mixed precision và checkpoint/resume. Governor coi Area FPS 8 FPS là ngưỡng bảo vệ: khi metric đến sát hoặc thấp hơn ngưỡng, training chuyển sang paused/throttled; chỉ tiếp tục sau một cửa sổ FPS ổn định. Training không được làm dừng Gate/Area stream.

## Extension registry

### Extension: `ext-20260820-object-detection-training` — architecture r1

```yaml
schema: team1-extension/v1
extension_id: ext-20260820-object-detection-training
title: "Huấn luyện thủ công từ mẫu nhãn đối tượng"
artifact: architecture
revision: 1
status: approved
depends_on: []
supersedes: []
sources:
  product: 1
approved_at: "2026-08-20T16:00:00+07:00"
approved_by: "HuuThuan — chat approval of GPU governor and hybrid base-model preservation"
```

#### Architecture delta

Thêm lifecycle local cho custom detection model: training job thủ công, snapshot dataset từ LabelSample, Python training runner tách inference, candidate model version, evaluation hold-out và activate/rollback có chủ đích. Candidate là augmentation của base YOLO, không phải thay thế model nền; đánh giá bắt buộc gồm regression người/các lớp xe nền. GPU governor bảo vệ Area Monitor tại ngưỡng 8 FPS thay vì coi GPU là tài nguyên không giới hạn.

#### Canonical sections changed

§1, §3, §4, §6.3, §7, §8, §10 và §11; các quyết định nền Python Worker + Node API + React + PostgreSQL và luồng Gate/Area hiện có không đổi.

#### Components and interfaces affected

M3 label workflow, Node job/version orchestration, local dataset/artifact storage, Python training runner, base/custom hybrid detector và Area inference telemetry. Contract API, schema database và UI chi tiết sẽ được chốt ở database design và delivery plan.

#### Security, reliability and operational impact

Không nhận arbitrary artifact/path từ client; artifact được version hoá bất biến và kiểm tra trước promote. Job lỗi/OOM không chạm active model. Split theo source media giảm leakage; sample lỗi bị báo cáo và loại khỏi snapshot, không sửa mẫu gốc. Governor có telemetry và resume để vận hành không bị silent degradation.

#### Backend and frontend handoff impact

Backend cần job state, validation/export, process supervision, version registry và atomic activation. Frontend cần điều khiển train thủ công, hiển thị tiến độ/metrics/cảnh báo pause, danh sách candidate và activate/rollback. Cả hai phải giữ nhãn đã lưu tiếp tục dùng cho zone ngay cả khi chưa train.

#### Unchanged architecture decisions

Inference real-time tiếp tục ở Python Worker, browser qua Node proxy, metadata bền vững ở PostgreSQL và media/artifact cục bộ. Base YOLO luôn chạy; custom model chỉ augment các class đã train. Không thêm cloud training, auth layer hoặc thay transport realtime.

#### Validation and blockers

Architecture hợp lệ khi downstream database design định nghĩa metadata/version/job tối thiểu và delivery plan có benchmark giữ Area ≥8 FPS, held-out evaluation theo source, OOM/pause/resume và rollback test. Không có architecture blocker; accuracy tuyệt đối trên mọi video không thể cam kết nếu dữ liệu train không đại diện.
