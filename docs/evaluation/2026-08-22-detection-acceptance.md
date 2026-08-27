# Detection reliability acceptance — 2026-08-22

## Kết luận

Phần triển khai, audit, test và benchmark có thể thực hiện an toàn trong repository đã hoàn tất. Runtime mới đạt cổng hiệu năng Area `>= 8 FPS` trên toàn bộ sáu cell YOLO11n đo được. Các cổng accuracy vẫn **BLOCKED/NOT EVALUATED** vì 26 frame thuộc split `test` (65 candidate tổng cộng) chưa được review/annotate; báo cáo không suy diễn hoặc tạo metric giả.

Không có commit, push, deploy, database write, training, model activation, model export/download, dependency install hoặc upload dữ liệu BAI-KIEM/private trong công việc này.

## Trạng thái acceptance theo `improve.md`

| Mục tiêu | Trạng thái | Bằng chứng / giá trị |
| --- | --- | --- |
| Registry là whitelist; chỉ sáu COCO class chính xác và exact custom manifest class | **PASS** | Taxonomy parity 19 case + 25 malformed case; unknown/unavailable bị loại trước feed, Zone và event |
| `truck`, `container_truck`, `shipping_container` không bị trộn nghĩa | **PASS** | Semantic-lock tests; không còn geometry/prompt/alias relabel trong runtime |
| Snapshot registry/model/zone atomic và fail-closed | **PASS** | Refresh lỗi giữ nguyên object cũ; manifest/path/SHA lỗi tắt custom nhưng COCO vẫn hoạt động |
| Low-confidence chỉ continuation; không mở event mới | **PASS** | Base `0.30/0.14`, custom `0.45/0.25`; state-machine tests đạt |
| Custom confirmation 2/3 | **PASS** | Full-frame và ROI dùng opportunity clock riêng; temporal tests đạt |
| Zone lifecycle không regression | **PASS** | 1 giây confirm, 3 observed-exit frame, 12 giây missing-track reconnect và exact-class re-ID đều đạt test |
| ROI tile bounded, mặc định tắt, không duplicate/cross-semantic merge | **PASS** | 640 px, overlap 0.20, mỗi 3 frame, tối đa 8 tile; 12 ROI tests đạt |
| Frontend fail-closed theo capability server | **PASS** | Registry loading/error/ retry, unavailable state và exact Zone mapping; build/lint đạt |
| Audit dataset reach-stacker hiện hữu | **PASS** | 200 ảnh, 222 bbox, 0 negative, 0 bbox <1%, 58 edge-touch, median area 54.60948%; ước lượng cũ 54.77% bị supersede |
| Golden BAI-KIEM local, portable, chống leakage | **PASS** | 65 ảnh trích tuần tự; split time-block 120 giây: calibration 14, validation 25, test 26; không absolute path |
| Evaluator IoU/AP50/PR/sweep/gates fail-closed | **PASS** | Exact IoU 0.50, PR points, per-class/source initiation/continuation sweep, split mặc định `test`, PASS/FAIL/BLOCKED gates |
| Area end-to-end FPS >=8 trên RTX 3050 Laptop 4 GB | **PASS** | Sáu cell YOLO11n FP16: 11.878–20.682 FPS; gồm decode/resize, ByteTrack, registry, ZoneChecker, buffer, JPEG/base64 và `AreaPipeline.publish_result` |
| Reach-stacker precision >=90% | **BLOCKED/NOT EVALUATED** | 26/26 test frame còn `PENDING`; precision undefined |
| Reach-stacker recall >=85% | **BLOCKED/NOT EVALUATED** | 26/26 test frame còn `PENDING`; recall undefined |
| Truck bị nhận thành reach-stacker <5% | **BLOCKED/NOT EVALUATED** | Chưa có reviewed truck/reach-stacker ground truth |
| False alert/phút giảm rõ so baseline | **BLOCKED/NOT EVALUATED** | Evaluator chỉ trả số khi review event hoàn tất hoặc có reviewed-duration rõ ràng; chưa có reviewed baseline |
| Recall vật thể xa tốt hơn baseline | **BLOCKED/NOT EVALUATED** | Chưa có annotation/tag `far` và baseline cùng split |
| Base COCO không regression accuracy đáng kể | **BLOCKED/NOT EVALUATED** | Routing/unit regression đạt, nhưng chưa có reviewed BAI-KIEM ground truth để định lượng accuracy |
| YOLO11s comparison | **BLOCKED_MISSING_LOCAL_ASSET** | Không có `yolo11s.pt`; benchmark không kích hoạt auto-download |
| TensorRT comparison | **BLOCKED_MISSING_LOCAL_ASSET** | Không có `.engine`; không export hoặc cài TensorRT |
| Gate/LPR integration regression | **BLOCKED/NOT EVALUATED** | Code path không bị sửa và WS pure suite đạt; API suites ghi shared Neon được chủ động bỏ qua, không có isolated DB được cấp |

## Benchmark end-to-end

Hardware: Windows 11, NVIDIA GeForce RTX 3050 Laptop GPU 4 GB, PyTorch `2.6.0+cu124`, CUDA available. Precision mode: PyTorch FP16. Video được decode tuần tự và resize 1280×720. Timer bắt đầu trước read/decode frame measured đầu tiên và kết thúc sau output path.

| imgsz | ROI | FPS | detector p95 ms | ROI p95 ms | peak CUDA allocated/reserved MiB |
| ---: | --- | ---: | ---: | ---: | ---: |
| 640 | off | 19.036 | 22.584 | 0.010 | 44.1 / 66.0 |
| 640 | on | 13.017 | 104.851 | 88.286 | 48.8 / 66.0 |
| 896 | off | 20.682 | 25.178 | 0.009 | 52.1 / 66.0 |
| 896 | on | 12.573 | 116.520 | 102.141 | 52.5 / 68.0 |
| 960 | off | 18.074 | 28.890 | 0.008 | 54.8 / 70.0 |
| 960 | on | 11.878 | 126.683 | 103.270 | 55.2 / 70.0 |

Mỗi cell có probe STARTED/ENDED không tính vào timer đi qua `AreaPipeline.publish_result`: 2 Area event, 1 alert, 1 create, 1 close; adapter injected ghi `externalWrites=0`. Trước thay đổi này repository không có matrix Area E2E tái lập được, nên không có số “before” hợp lệ để so sánh. “After” chính là matrix trên; không dùng model-only latency làm baseline giả.

Cấu hình performance-only được giữ làm ứng viên benchmark là YOLO11n, imgsz 896, ROI mỗi frame thứ ba: 12.573 FPS và scale lớn hơn 640. Đây chưa phải lựa chọn accuracy; ROI mặc định vẫn **off** cho đến khi golden validation/test được review.

## Lệnh kiểm chứng đã chạy

```powershell
cd backend/python-worker
& '.venv/Scripts/python.exe' -m unittest discover -s tests -v
# 88/88 PASS

& '.venv/Scripts/python.exe' evaluation/golden_dataset.py validate '..\data\evaluation\bai-kiem-golden-v1\golden-manifest.json'
# valid=true, frames=65, evaluatable=0

& '.venv/Scripts/python.exe' training/benchmark_models.py --area-video 'D:\video_test\KiemHoa-Hik (1).mp4' --output '..\data\training\benchmarks\20260822-bai-kiem-area-baseline.json' --matrix-imgsz 640 --matrix-imgsz 896 --matrix-imgsz 960 --matrix-frames 40 --matrix-warmup 5
# exit 0; 6 MEASURED, 18 BLOCKED_MISSING_LOCAL_ASSET

cd ../node-api
npm.cmd run typecheck
npx.cmd ts-node src/tests/test_detection_taxonomy.ts
npx.cmd ts-node src/tests/test_label_capabilities.ts
npx.cmd ts-node src/tests/test_zone_label_validation.ts
npx.cmd ts-node src/tests/test_zone_validation.ts
npx.cmd ts-node src/tests/test_yard_training_profile.ts
npx.cmd ts-node src/tests/test_ws_proxy.ts
# PASS; DB-writing API suites intentionally skipped

cd ../../frontend
npx.cmd tsc -b
npm.cmd run lint
npm.cmd run build
# PASS; Vite only reports two ineffective dynamic-import bundle warnings

cd ..
git diff --check
```

## Artifacts

- Dataset audit: `docs/evaluation/reach-stacker-dataset-audit.md` và `.json`.
- Golden annotation procedure: `docs/evaluation/bai-kiem-annotation-checklist.md`.
- Golden local artifact (gitignored): `backend/data/evaluation/bai-kiem-golden-v1/`.
- Golden evaluator report: `docs/evaluation/bai-kiem-baseline-report.md` và `.json`.
- Full benchmark matrix (gitignored): `backend/data/training/benchmarks/20260822-bai-kiem-area-baseline.json`.
- External dataset/license screening: `docs/evaluation/external-dataset-screening.md`; không dataset nào đã được tải.
- Design/implementation plan: `docs/superpowers/specs/2026-08-22-detection-reliability-design.md` và `docs/superpowers/plans/2026-08-22-detection-reliability.md`.

## Exact next action để mở khóa accuracy

Review local 26 ảnh thuộc split `test` (khuyến nghị hoàn tất cả 65 ảnh) theo `docs/evaluation/bai-kiem-annotation-checklist.md`: đặt mỗi record thành `ANNOTATED` hoặc `NEGATIVE`, tạo YOLO label tương ứng, thêm tag `far`/static-container và review event false-alert theo checklist. Không upload ảnh ra dịch vụ ngoài. Sau đó chạy evaluator trên split `validation` để calibrate threshold, khóa cấu hình, rồi chạy riêng split `test` để nhận PASS/FAIL cuối cùng. Nếu muốn mở rộng matrix model, cung cấp artifact local đã duyệt cho YOLO11s/TensorRT; không cần tải dataset ngoài để hoàn tất annotation local.
