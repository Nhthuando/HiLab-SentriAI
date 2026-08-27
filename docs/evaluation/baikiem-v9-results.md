# Kết quả BAI-KIEM V9 unified multi-class

## Kết luận

Model `baikiem-v9-unified-candidate-final` đã train xong và vượt gate tốc độ, nhưng **không vượt quality gate tự động**. Ngày 2026-08-26, chủ dự án chấp nhận metric hiện tại và phê duyệt activation production thủ công. V9 hiện là model database `ACTIVE`; V8 vẫn còn nguyên làm fallback/rollback.

V9 hiện chỉ hỗ trợ năm class đã có nhãn thật: `person`, `car`, `truck`, `forklift`, `reach_stacker`. Năm class trong hợp đồng V9 nhưng chưa đủ dữ liệu (`bicycle`, `motorcycle`, `bus`, `container_truck`, `mobile_crane`) không được khai báo là đã train.

## Dataset và model

| Mục | Giá trị |
|---|---:|
| Train frames | 1,962 |
| Validation frames | 343 |
| Locked-test frames | 200 |
| Empty/background train + validation | 329 |
| Train/validation image-hash overlap | 0 |
| Old locked-test frames bị loại khỏi train/validation | 484 |
| Dataset SHA-256 | `18421ca1738e9c5f272ee842d69755950324d31307d0c517860b68b322a3f4b1` |
| Model SHA-256 | `3772e978fc4635a6a2d3dffb59286bd89c0ebbc6cc6e27dc77532b5006eaab52` |

Số box train/validation:

| Class | Train | Validation |
|---|---:|---:|
| `person` | 3,008 | 546 |
| `car` | 892 | 120 |
| `truck` | 1,246 | 213 |
| `forklift` | 551 | 92 |
| `reach_stacker` | 1,182 | 229 |

Nguồn chính xác là `backend/data/training/datasets/baikiem-v9-reviewed-final/dataset-audit.json`.

## Training

- Khởi tạo từ YOLO11n pretrained, không nối checkpoint one-class của V8.
- Cấu hình tối đa 120 epoch, `imgsz=896`, AdamW, AMP, patience 20.
- Batch được tăng dần đến 8 và workers đến 1 sau khi kiểm tra GPU ổn định.
- Early stopping dừng ở epoch 76; checkpoint tốt nhất là epoch 56. Không ép chạy đủ 120 epoch.
- Thời gian train: 5,226.955 giây, khoảng 87.1 phút.

Metric Ultralytics trên validation ở `imgsz=896`:

| Precision | Recall | mAP50 | mAP50-95 |
|---:|---:|---:|---:|
| 82.43% | 78.52% | 83.79% | 53.77% |

Theo class:

| Class | Precision | Recall | mAP50 | mAP50-95 |
|---|---:|---:|---:|---:|
| `person` | 77.3% | 70.0% | 77.6% | 40.1% |
| `car` | 87.0% | 75.0% | 82.9% | 61.9% |
| `truck` | 76.4% | 72.8% | 75.0% | 40.1% |
| `forklift` | 91.4% | 92.3% | 93.7% | 73.7% |
| `reach_stacker` | 80.1% | 82.5% | 89.8% | 53.0% |

## Threshold validation

Threshold được chọn chỉ từ validation ở `imgsz=768`, sau đó đóng băng trước khi mở locked test:

| Class | Confidence |
|---|---:|
| `person` | 0.25 |
| `car` | 0.30 |
| `truck` | 0.40 |
| `forklift` | 0.40 |
| `reach_stacker` | 0.05 |

Kết quả tại threshold đã chọn: micro Precision 73.34%, Recall 78.42%, F1 75.80% (`TP=941`, `FP=342`, `FN=259`). Có 259 false negative trên 161 frame; toàn bộ index và ảnh render nằm trong `backend/data/training/evaluations/baikiem-v9-final/validation/false-negatives/`.

## Locked test

Locked test đã chạy đúng một lần trên 200 frame với model và threshold đã đóng băng. Không dùng locked test để train, chọn epoch hoặc đổi threshold.

| Chỉ số | Giá trị |
|---|---:|
| Micro Precision | 71.39% |
| Micro Recall | 81.04% |
| Micro F1 | 75.91% |
| Macro Precision | 71.58% |
| Macro Recall | 82.58% |
| Macro F1 | 76.27% |
| Macro mAP50-95 | 54.48% |
| TP / FP / FN | 594 / 238 / 139 |

Theo class tại threshold đã đóng băng:

| Class | GT | Precision | Recall | F1 | TP | FP | FN | mAP50-95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `person` | 156 | 84.14% | 78.21% | 81.06% | 122 | 23 | 34 | 57.51% |
| `car` | 24 | 52.78% | 79.17% | 63.33% | 19 | 17 | 5 | 48.44% |
| `truck` | 346 | 71.01% | 83.53% | 76.76% | 289 | 118 | 57 | 51.23% |
| `forklift` | 17 | 84.21% | 94.12% | 88.89% | 16 | 3 | 1 | 66.61% |
| `reach_stacker` | 190 | 65.78% | 77.89% | 71.33% | 148 | 77 | 42 | 48.61% |

`forklift` chỉ có 17 ground-truth instance trong locked test nên kết quả class này có độ hỗ trợ thống kê thấp. Locked test có 139 false negative trên 108 frame, được lưu tại `backend/data/training/evaluations/baikiem-v9-final/locked/false-negatives/`.

## Tốc độ runtime

Benchmark dùng pipeline Area `UNIFIED` một lượt inference trên `KiemHoa-Hik (2).mp4`, RTX 3050 Laptop GPU, 10 frame warm-up và 80 frame đo:

| Image size | End-to-end FPS | Detector median | Detector p95 |
|---:|---:|---:|---:|
| 768 | 21.18 | 14.72 ms | 19.41 ms |
| 896 | 19.72 | 23.77 ms | 26.83 ms |

Cả hai cấu hình vượt gate 8 FPS. Benchmark ngắn này xác nhận throughput pipeline, chưa thay thế bài soak test 60 giây/source và kiểm tra seek/delete/reconnect trên web.

## Gate và quyết định

Candidate **FAIL** vì:

- macro Precision/Recall/F1 thấp hơn 90%;
- nhiều class thấp hơn floor Precision/Recall 85%;
- macro mAP50-95 validation thấp hơn 0.55 và locked test 0.5448 vẫn thấp hơn nhẹ;
- chỉ có 5/10 canonical class có dữ liệu;
- chưa có per-camera, temporal-gap và false-alert acceptance đầy đủ;
- chưa chạy full regression + soak test sau activation.

Model không được coi là tự động vượt gate hoặc được chứng nhận 85–90%. Activation hiện tại là manual-production override có audit riêng; các metric thất bại không bị sửa thành đạt. Dữ liệu locked test đã mở kết quả không được dùng cho vòng train tiếp theo; nếu tiếp tục cải thiện phải tạo nguồn validation/locked độc lập mới theo plan.

## Production activation

- Version: `baikiem-v9-unified-candidate-final`
- Runtime: `UNIFIED`, một model Area mỗi frame.
- Database state: đúng một model `ACTIVE`, quality gate vẫn `false`, owner approval `true`.
- Production inference size: 896.
- Class hoạt động: `person`, `car`, `truck`, `forklift`, `reach_stacker`.
- `motorcycle` và `bicycle` trong registry được báo unavailable vì checkpoint chưa train hai class này.
- Worker startup xác nhận đúng model/hash và không load model Area thứ hai.
- Live WebSocket smoke test: 80 frame, median 20 frame cuối 9.5 FPS, min/max 9.5/9.7 FPS.
- Cảnh báo partial coverage được rate-limit còn đúng một lần mỗi version/class set.
- Dry-run rollback: `DRY_RUN_OK`; V8 artifact và SHA-256 vẫn khớp.

Giới hạn môi trường smoke test: Node API playback và WebSocket feed hoạt động, nhưng Prisma trên Windows sandbox không mở được TLS tới Neon nên `/api/v1/labels` trả 500. Python worker kết nối cùng database bình thường. Đây là lỗi kết nối Node/Prisma độc lập với checkpoint V9 và cần kiểm tra lại khi chạy Node từ terminal người dùng.

## Artifact

- Model: `backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt`
- Metadata đánh giá và manual-production approval: `backend/data/training/models/baikiem-v9-unified-candidate-final/evaluation.json`
- Training receipt: `backend/data/training/reports/baikiem-v9-unified-candidate-final-training.json`
- Validation: `backend/data/training/evaluations/baikiem-v9-final/validation/val-evaluation.json`
- Frozen thresholds: `backend/data/training/evaluations/baikiem-v9-final/validation/frozen-thresholds.json`
- Locked test: `backend/data/training/evaluations/baikiem-v9-final/locked/test-evaluation.json`
- Runtime benchmark: `backend/data/training/benchmarks/baikiem-v9-final-runtime.json`
- Production pre-activation benchmark: `backend/data/training/benchmarks/baikiem-v9-production-preactivation.json`
- Activation/rollback receipt: `backend/data/training/activation-backups/baikiem-v9-20260826T102022Z.json`
