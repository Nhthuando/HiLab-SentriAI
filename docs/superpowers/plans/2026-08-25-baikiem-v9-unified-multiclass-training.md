# BAI-KIEM V9 Unified Multi-Class Training Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây dựng V9 YOLO11n đa class cho BAI-KIEM, cải thiện rõ rệt Precision, Recall và mAP50-95 trên video/camera đại diện, đồng thời giữ Area pipeline tối thiểu 9-10 FPS trên RTX 3050 Laptop 4 GB.

**Architecture:** V9 là model `UNIFIED` một lượt inference, khởi tạo từ `yolo11n.pt` COCO pretrained và sở hữu toàn bộ class được chứng nhận trong một class order cố định. Dữ liệu lấy từ video gốc, chia theo nguyên nguồn camera/video trước khi mining, loại gần trùng, pre-label để review trên CVAT, audit đầy đủ rồi mới train đúng một candidate; validation dùng để chọn model/threshold, locked test chỉ chạy một lần ở acceptance cuối. V8 `SUPPLEMENTAL` hiện tại luôn được giữ nguyên làm rollback.

**Tech Stack:** Python 3.12, Ultralytics 8.4.121/YOLO11n, PyTorch CUDA AMP, OpenCV, imageio-ffmpeg, ByteTrack, CVAT 2.71, TypeScript 5.6, Express, Prisma, unittest.

## Global Constraints

- Không cam kết độ chính xác cho camera hoàn toàn chưa xuất hiện trong dữ liệu; chỉ camera/domain vượt acceptance gate mới được gọi là `CERTIFIED`.
- Mục tiêu sản phẩm là Precision/Recall tổng thể ít nhất 0.90; hard floor từng class và từng camera đủ support là 0.85.
- `mAP50-95` không phải “accuracy phần trăm”; target V9 macro là ít nhất 0.55, stretch target 0.60, và `reach_stacker` phải tăng ít nhất 0.15 tuyệt đối so với V8.
- Area end-to-end FPS phải đạt ít nhất 8.0 trên RTX 3050 Laptop 4 GB; không dùng model latency riêng để thay thế số đo pipeline.
- Class order V9 cố định: `person`, `bicycle`, `car`, `motorcycle`, `bus`, `truck`, `container_truck`, `forklift`, `reach_stacker`, `mobile_crane`.
- `shipping_container` là hard-negative/background, không phải phương tiện và không nằm trong output V9.
- Mọi vật thể thuộc mười class V9 trong một frame được chọn đều phải được gắn nhãn; không chỉ gắn vật thể mà model bỏ sót.
- Không dùng pseudo-label làm ground truth. Mọi pre-label vẫn có trạng thái `PENDING_REVIEW` cho đến khi người dùng kiểm tra.
- Không đưa cùng một video, bản transcode, clip cắt chồng thời gian hoặc frame gần trùng sang nhiều split.
- Không dùng locked test để mining, cân bằng dataset, chọn epoch, chọn threshold hoặc quyết định augmentation.
- Không train khi CVAT chưa `Completed`, audit còn missing label, class chưa đủ dữ liệu hoặc split leakage chưa bằng 0.
- Không tự động activate V9. Candidate chỉ được activate sau validation, locked acceptance, benchmark FPS và xác nhận của người dùng.
- Giữ nguyên V8 active, Gate/LPR, clip, Zone CRUD, event lifecycle, Q&A và frontend hiện có cho đến khi V9 vượt mọi gate.
- Không upload video/frame riêng tư ra dịch vụ bên ngoài.
- Không commit, push, merge hoặc deploy nếu người dùng chưa yêu cầu rõ.

---

## Mục lục

1. [Workflow sử dụng đầu tiên](#workflow-sử-dụng-đầu-tiên)
2. [Baseline và vấn đề V8](#baseline-và-vấn-đề-v8)
3. [Hợp đồng class V9](#hợp-đồng-class-v9)
4. [Quality gate bắt buộc](#quality-gate-bắt-buộc)
5. [Cấu trúc file dự kiến](#cấu-trúc-file-dự-kiến)
6. [Kế hoạch triển khai](#kế-hoạch-triển-khai)
7. [Điều kiện dừng và vòng bổ sung dữ liệu](#điều-kiện-dừng-và-vòng-bổ-sung-dữ-liệu)
8. [Kết quả bàn giao](#kết-quả-bàn-giao)

## Workflow sử dụng đầu tiên

1. Người dùng tải xong video vào một thư mục riêng; đường dẫn mặc định của kế hoạch là `D:\video_train_v9\raw`. Nếu video nằm nơi khác, Task 2 ghi đường dẫn thật vào file local bị Git ignore.
2. Chạy inventory và duplicate grouping; đầu ra đầu tiên là `backend/data/training/reports/baikiem-v9-video-inventory.md` để kiểm tra video nào thực sự có giá trị.
3. Khóa split theo nguồn trước khi chạy model: khoảng 70% source group train, 15% validation và 15% locked test; ưu tiên coverage class/điều kiện hơn tỷ lệ tuyệt đối.
4. Tạo hai task CVAT:
   - `BAI-KIEM-V9-TRAIN-VAL-REVIEW`: có pre-label toàn bộ class mà model hiện tại hỗ trợ.
   - `BAI-KIEM-V9-LOCKED-BLIND`: không import prediction của V9 candidate và không được dùng để chỉnh train/threshold.
5. Người dùng sửa class, sửa box, thêm toàn bộ vật thể còn thiếu, kiểm tra frame rỗng và đánh dấu tất cả job `Completed`.
6. Pipeline pull dữ liệu từ CVAT, audit missing label, class balance, duplicate và source leakage. Nếu audit không đạt, không train.
7. Train một V9 candidate từ `yolo11n.pt`, calibrate threshold trên validation, rồi chạy locked test đúng một lần.
8. Chỉ đăng ký V9 là `READY_FOR_APPROVAL` nếu accuracy, continuity và FPS đều đạt; V8 vẫn active cho đến khi người dùng xác nhận chuyển model.

## Baseline và vấn đề V8

Nguồn bằng chứng hiện tại: `backend/data/training/models/baikiem-reach-reviewed-v8-hardcases-ft-20260824/evaluation.json`.

| Chỉ số V8 | Giá trị | Ý nghĩa cho V9 |
|---|---:|---|
| Runtime mode | `SUPPLEMENTAL` | V8 chỉ bổ sung một class, không sửa được phân loại COCO `car/truck`. |
| Class thực tế | `reach_stacker` | Nhãn `car`, `truck`, `person`, `forklift` từng review không được train vào V8. |
| Precision | 0.75480 | Chưa đạt mục tiêu 0.90. |
| Recall | 0.87963 | Khá hơn precision nhưng vẫn có gap xa/nhỏ. |
| mAP50 | 0.80202 | Chưa đủ để chứng nhận. |
| mAP50-95 | 0.36161 | Localization/độ bền qua nhiều IoU còn yếu. |
| Quality gate | Failed | V8 phải là rollback, không phải baseline được coi là đạt. |

Kiểm tra raw V8 trên `KiemHoa-Hik (1)_fastseek.mp4` đã cho thấy từ giây 85–100 không có `reach_stacker` ngay cả ở confidence 0.05; giây 110 chỉ đạt 0.154 và giây 120 mới tăng lên 0.758. Đây là model miss thực sự, không thể sửa chỉ bằng tracker hoặc hạ confidence.

## Hợp đồng class V9

Class readiness được tính bằng **instance khác biệt**, không tính hàng trăm frame liên tiếp của cùng một vật thể là hàng trăm nguồn độc lập.

| ID | Canonical class | Nhãn UI | Mục tiêu instance tối thiểu | Nguồn độc lập tối thiểu | Hard-case bắt buộc |
|---:|---|---|---:|---:|---|
| 0 | `person` | Người | 1,000 | 5 | nhỏ/xa, che khuất, cạnh xe, nhiều người |
| 1 | `bicycle` | Xe đạp | 300 | 5 | nhỏ/xa, nghiêng, cạnh motorcycle |
| 2 | `car` | Xe con | 500 | 5 | xe vàng chở người, sedan, góc cao, partial |
| 3 | `motorcycle` | Xe máy | 500 | 5 | người ngồi trên xe, nhỏ/xa, blur |
| 4 | `bus` | Xe buýt | 300 | 5 | bus/minibus; không dùng xe tải làm bus |
| 5 | `truck` | Xe tải | 800 | 5 | truck thường, đầu/đuôi xe, che khuất, không chở container |
| 6 | `container_truck` | Xe đầu kéo container | 500 | 5 | có chassis/container evidence; phân biệt container tĩnh |
| 7 | `forklift` | Xe nâng hàng | 500 | 5 | mast/forks, nhiều kiểu thân xe, gần/xa/partial |
| 8 | `reach_stacker` | Xe nâng container | 800 | 5 | boom/spreader, 30% nhỏ/xa, nhiều hướng quay |
| 9 | `mobile_crane` | Xe cẩu tự hành | 300 | 5 | crane di động; loại fixed crane/background |

Quy tắc readiness:

- Class không đạt số instance hoặc nguồn tối thiểu được đánh dấu `INSUFFICIENT_DATA`, không được quảng bá là đã nhận diện sẵn.
- Nếu 20 GB video không chứa đủ một class, pipeline xuất danh sách thiếu chính xác; không nhân bản frame hoặc augmentation để giả đủ dữ liệu.
- 20–30% frame train/validation phải là hard negative hoặc background có container tĩnh, mái, cột, crane cố định, bóng đổ và bãi trống.
- Với `reach_stacker`, `forklift`, `container_truck`, tối thiểu 30% instance phải thuộc bucket nhỏ/xa, blur, occluded hoặc edge-touch.
- Xe vàng chở người được gắn `car` nhất quán trong mọi source nếu đây là quy ước nghiệp vụ đã duyệt.

## Quality gate bắt buộc

### Validation gate — dùng để chọn model và threshold

| Chỉ số | Hard gate | Stretch target |
|---|---:|---:|
| Macro Precision | ≥ 0.90 | ≥ 0.93 |
| Macro Recall | ≥ 0.90 | ≥ 0.93 |
| Macro F1 | ≥ 0.90 | ≥ 0.93 |
| mAP50 | ≥ 0.90 | ≥ 0.93 |
| Macro mAP50-95 | ≥ 0.55 | ≥ 0.60 |
| Mỗi class Precision | ≥ 0.85 | ≥ 0.90 |
| Mỗi class Recall | ≥ 0.85 | ≥ 0.90 |
| `reach_stacker` Precision/Recall | ≥ 0.90/0.90 | ≥ 0.93/0.93 |
| `reach_stacker` mAP50-95 | ≥ 0.51161 và tăng ≥ 0.15 so với V8 | ≥ 0.60 |
| Recall bucket nhỏ/xa của class ưu tiên | ≥ 0.85 | ≥ 0.90 |
| Confusion `car ↔ truck` | < 5% | < 3% |
| Confusion `truck ↔ reach_stacker` | < 5% | < 3% |
| Confusion `forklift ↔ reach_stacker` | < 5% | < 3% |

### Per-camera/source gate

- Với mỗi camera/source có ít nhất 20 ground-truth instance của một class, Precision và Recall class đó đều phải ≥ 0.85.
- Source có dưới 20 instance được báo `INSUFFICIENT_SUPPORT`, không được tính là pass và cũng không được gộp để che metric thấp.
- Một camera mới ngoài tập 20 GB không tự động được chứng nhận. Trước khi gọi là `CERTIFIED`, cần tối thiểu 300 frame đa dạng hoặc 100 instance/class cần dùng, sau đó vượt per-camera gate ≥ 0.85.

### Temporal và runtime gate

| Chỉ số | Gate |
|---|---:|
| Maximum visible-target detection gap | ≤ 0.50 giây |
| Duplicate box cùng vật thể sau arbitration | 0 |
| False alert | ≤ 0.05/phút video reviewed |
| Area end-to-end FPS trung bình | ≥ 8.0 |
| p95 end-to-end frame latency | ≤ 125 ms |
| Peak GPU VRAM | ≤ 3.6 GiB |
| WebSocket reconnect storm | 0 |
| Gate/LPR và Zone lifecycle regression | 0 |

Nếu bất kỳ metric bắt buộc nào undefined do không có đủ ground truth, gate phải fail thay vì đổi undefined thành 0 hoặc bỏ qua.

## Cấu trúc file dự kiến

### File tạo mới

- `backend/config/baikiem-v9-profile.json`: class order, display name, readiness và acceptance thresholds dùng chung.
- `backend/config/baikiem-v9-video-plan.local.json`: inventory/split chứa đường dẫn video riêng tư; Git ignore.
- `backend/python-worker/training/v9_profile.py`: parser/validator typed cho profile JSON.
- `backend/python-worker/training/v9_video_dataset.py`: inventory, duplicate grouping, source split, frame mining và package schema-v4.
- `backend/python-worker/evaluation/v9_acceptance.py`: per-class/per-source/per-size/continuity/FPS final gate.
- `backend/python-worker/tests/test_v9_profile.py`: contract và parity test profile.
- `backend/python-worker/tests/test_v9_video_dataset.py`: split, dedup, mining và CVAT round-trip tests.
- `backend/python-worker/tests/test_v9_acceptance.py`: metric gate tests.
- `backend/node-api/src/tests/test_v9_training_profile.ts`: Node readiness/profile tests.
- `docs/evaluation/baikiem-v9-results.md`: báo cáo cuối source-backed.

### File sửa

- `.gitignore`: bỏ qua `backend/config/baikiem-v9-video-plan.local.json` và artifact V9 dung lượng lớn.
- `backend/python-worker/training/local_video_dataset.py`: dùng class contract truyền vào thay vì hard-code schema V1.
- `backend/python-worker/training/cvat_import_review_task.py`: nhận class list/profile V9.
- `backend/python-worker/training/cvat_pull_reviewed_package.py`: giữ class theo tên, không làm rơi `car/truck/forklift` như V8 supplemental export.
- `backend/python-worker/training/dataset_audit.py`: readiness, source diversity, missing-label và per-size audit đa class.
- `backend/python-worker/training/runner.py`: schema-v4, V9 train args và validation gate đa class.
- `backend/python-worker/training/finalize_checkpoint.py`: gắn artifact/dataset hash và locked acceptance report.
- `backend/python-worker/evaluation/metrics.py`: metric từng class/source/camera/size/confusion.
- `backend/python-worker/evaluation/evaluate_local_video_model.py`: tổng quát hóa evaluator từ reach-only sang mười class.
- `backend/python-worker/training/benchmark_models.py`: V8/base/V9 một-pass benchmark matrix.
- `backend/python-worker/detection/tracked_detector.py`: xác nhận V9 `UNIFIED` chỉ chạy một model pass.
- `backend/node-api/src/training/yardTrainingProfile.ts`: readiness đa class lấy từ cùng contract.
- `backend/node-api/src/tests/test_yard_training_profile.ts`: regression cho profile cũ và V9.

## Kế hoạch triển khai

### Task 1: Khóa V9 taxonomy, profile và metric contract

**Files:**
- Create: `backend/config/baikiem-v9-profile.json`
- Create: `backend/python-worker/training/v9_profile.py`
- Create: `backend/python-worker/tests/test_v9_profile.py`
- Modify: `backend/node-api/src/training/yardTrainingProfile.ts`
- Create: `backend/node-api/src/tests/test_v9_training_profile.ts`

**Interfaces:**
- Consumes: `backend/config/detection-taxonomy.json`.
- Produces: `load_v9_profile(path: Path) -> V9Profile`, exact class order và shared readiness/acceptance constants.

- [ ] **Step 1: Viết Python contract test thất bại**

```python
EXPECTED_V9_CLASSES = (
    "person", "bicycle", "car", "motorcycle", "bus", "truck",
    "container_truck", "forklift", "reach_stacker", "mobile_crane",
)

def test_v9_profile_has_exact_class_order_and_no_static_container():
    profile = load_v9_profile(PROJECT_ROOT / "backend/config/baikiem-v9-profile.json")
    assert profile.classes == EXPECTED_V9_CLASSES
    assert "shipping_container" not in profile.classes
    assert profile.minimum_end_to_end_fps == 8.0
```

- [ ] **Step 2: Chạy test và xác nhận fail đúng lý do**

Run from `backend/python-worker`:

```powershell
& '.venv/Scripts/python.exe' -m unittest tests.test_v9_profile -v
```

Expected: FAIL vì profile/parser chưa tồn tại.

- [ ] **Step 3: Tạo JSON contract và strict parser**

JSON phải chứa `schemaVersion: 1`, `profile: BAIKIEM_V9_UNIFIED`, mười class theo đúng thứ tự, display name, minimum instances/sources và toàn bộ gate trong phần Quality gate. Parser reject unknown field, duplicate class, class thiếu trong taxonomy, threshold ngoài `[0,1]` và boolean giả số.

- [ ] **Step 4: Viết Node parity test và sửa readiness service**

```typescript
assert.deepEqual(
  v9Profile.classes.map((item) => item.baseClass),
  ['person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck',
   'container_truck', 'forklift', 'reach_stacker', 'mobile_crane'],
);
assert.equal(v9Readiness([]).ready, false);
```

- [ ] **Step 5: Chạy Python/Node tests**

```powershell
cd backend/python-worker
& '.venv/Scripts/python.exe' -m unittest tests.test_v9_profile -v
cd ../node-api
npm.cmd run typecheck
```

Expected: PASS.

- [ ] **Step 6: Ghi checkpoint**

Lưu output test vào report phiên làm việc; chỉ commit nếu người dùng yêu cầu.

### Task 2: Inventory 20 GB video và khóa source split trước inference

**Files:**
- Create: `backend/python-worker/training/v9_video_dataset.py`
- Create: `backend/python-worker/tests/test_v9_video_dataset.py`
- Create locally: `backend/config/baikiem-v9-video-plan.local.json`
- Modify: `.gitignore`
- Produce: `backend/data/training/reports/baikiem-v9-video-inventory.json`
- Produce: `backend/data/training/reports/baikiem-v9-video-inventory.md`

**Interfaces:**
- Consumes: video root mặc định `D:\video_train_v9\raw`, native video files và `imageio_ffmpeg.get_ffmpeg_exe()`.
- Produces: `inventory_videos(video_root: Path) -> VideoInventory` và `assign_source_splits(inventory, profile) -> SourcePlan`.

- [ ] **Step 1: Viết failing tests cho duplicate/source isolation**

```python
def test_transcodes_and_overlapping_clips_share_one_split():
    plan = assign_source_splits(fake_inventory_with_transcodes(), profile())
    split_by_group = {}
    for source in plan.sources:
        split_by_group.setdefault(source.duplicate_group, set()).add(source.split)
    assert all(len(splits) == 1 for splits in split_by_group.values())

def test_locked_sources_are_not_mineable():
    plan = assign_source_splits(fake_inventory(), profile())
    assert all(not item.mine_for_training for item in plan.sources if item.split == "test")
```

- [ ] **Step 2: Implement deterministic inventory**

Thu thập path tương đối, SHA-256 hoặc fast content signature, duration, FPS, width, height, codec, creation time và duplicate group. Không ghi absolute private path vào portable manifest; absolute root chỉ nằm trong file `.local.json` bị ignore.

- [ ] **Step 3: Khóa split theo source/camera**

Ưu tiên class/condition coverage; không ép 70/15/15 nếu làm một class biến mất khỏi validation/test. Mỗi duplicate group chỉ có một split. Existing locked test và các video đã dùng train V8 không được tự động chuyển vào V9 locked test mới.

- [ ] **Step 4: Chạy inventory thực tế**

```powershell
cd backend/python-worker
& '.venv/Scripts/python.exe' -m training.v9_video_dataset inventory `
  --video-root 'D:\video_train_v9\raw' `
  --profile '../../backend/config/baikiem-v9-profile.json' `
  --local-plan '../../backend/config/baikiem-v9-video-plan.local.json' `
  --report-root '../../backend/data/training/reports'
```

Expected: JSON/Markdown report có tổng file, giờ video, độ phân giải, duplicate groups và split, không có source group leakage.

- [ ] **Step 5: Review inventory trước mining**

Nếu một class không thể xuất hiện trong đủ năm nguồn, đánh dấu `INSUFFICIENT_SOURCE_COVERAGE`; chưa tạo claim nhận diện sẵn cho class đó.

- [ ] **Step 6: Ghi checkpoint**

Giữ local plan ngoài Git; chỉ commit code/profile nếu người dùng yêu cầu.

### Task 3: Mining frame gốc đa dạng và pre-label đầy đủ

**Files:**
- Modify: `backend/python-worker/training/v9_video_dataset.py`
- Modify: `backend/python-worker/training/local_video_dataset.py`
- Modify: `backend/python-worker/training/multiclass_hard_review_dataset.py`
- Modify: `backend/python-worker/tests/test_v9_video_dataset.py`
- Produce: `backend/data/training/annotation/baikiem-v9-train-val-review/`
- Produce: `backend/data/training/annotation/baikiem-v9-locked-blind/`

**Interfaces:**
- Consumes: locked source plan, `backend/python-worker/yolo11n.pt`, V8 `best.pt`, optional audited NRMM proposal model.
- Produces: `build_v9_review_packages(...) -> ReviewPackagePair` với native-resolution image, YOLO proposals, `review.csv`, `annotation-manifest.json` và CVAT ZIP.

- [ ] **Step 1: Viết selection tests**

```python
def test_near_duplicate_frames_are_suppressed_but_class_change_is_kept():
    selected = select_diverse_frames(candidate_frames(), max_frames=4000)
    assert no_adjacent_dhash_duplicates(selected, max_hamming=4)
    assert contains_low_confidence_and_class_disagreement(selected)

def test_locked_frames_never_receive_candidate_predictions():
    train_val, locked = build_fake_review_packages()
    assert train_val.prelabel_source_names
    assert locked.prelabel_source_names == []
```

- [ ] **Step 2: Mine 2,500–4,000 frame train/val đa dạng**

Sampling kết hợp khoảng thời gian, scene-change/dHash, class rarity, confidence thấp, disagreement `car/truck`, `truck/reach_stacker`, `forklift/reach_stacker`, small/far và hard-negative. Giữ frame native; không resize 2592×1520 trước CVAT.

- [ ] **Step 3: Pre-label mọi class mà model hiện tại hỗ trợ**

Base YOLO11n tạo proposal cho six COCO classes. V8 chỉ tạo `reach_stacker`. Proposal của class chưa có model không được giả lập; người review tự thêm `container_truck`, `forklift`, `mobile_crane`. Mọi frame giữ `PENDING_REVIEW` dù confidence cao.

- [ ] **Step 4: Loại overlap proposal nguy hiểm**

Không semantic-map `truck` thành class custom. Khi base/custom cùng phủ một vật thể, giữ cả disagreement trong sidecar để reviewer quyết định; CVAT không được silently xóa nhãn chỉ dựa trên heuristic.

- [ ] **Step 5: Tạo locked-blind package**

Chọn frame từ locked source groups, không chạy V9 candidate và không dùng chúng trong frame scoring. Locked task cần tối thiểu 100 GT instance cho mỗi class ưu tiên hoặc phải báo thiếu support.

- [ ] **Step 6: Audit package trước upload**

```powershell
cd backend/python-worker
& '.venv/Scripts/python.exe' -m unittest tests.test_v9_video_dataset tests.test_local_video_dataset -v
```

Expected: PASS; duplicate leakage = 0; absolute-path leak = 0.

### Task 4: Upload CVAT và dừng bắt buộc để người dùng review

**Files:**
- Modify: `backend/python-worker/training/cvat_import_review_task.py`
- Modify: `backend/python-worker/training/cvat_apply_yolo_proposals.py`
- Modify: `backend/python-worker/tests/test_cvat_pull_reviewed_package.py`
- Use: `.local/cvat/docker-compose.yml`

**Interfaces:**
- Consumes: hai review package Task 3 và V9 profile.
- Produces: hai CVAT task URL, class IDs đúng profile và proposal import receipt.

- [ ] **Step 1: Viết test class-order round trip**

```python
def test_cvat_round_trip_keeps_car_truck_forklift_and_reach_stacker():
    pulled = round_trip_reviewed_shapes([
        "car", "truck", "forklift", "reach_stacker"
    ])
    assert pulled.class_counts == {
        "car": 1, "truck": 1, "forklift": 1, "reach_stacker": 1,
    }
```

- [ ] **Step 2: Khởi động CVAT local và kiểm tra health**

```powershell
docker compose -f '.local/cvat/docker-compose.yml' up -d
docker compose -f '.local/cvat/docker-compose.yml' ps
```

Expected: CVAT UI/API healthy tại `http://localhost:8080`.

- [ ] **Step 3: Upload train/val review task có proposals**

Dùng `cvat_import_review_task.py` với task name `BAI-KIEM-V9-TRAIN-VAL-REVIEW`; import đúng mười labels từ profile.

- [ ] **Step 4: Upload locked blind task không có candidate proposals**

Dùng task name `BAI-KIEM-V9-LOCKED-BLIND`; không import predictions của V9.

- [ ] **Step 5: Bàn giao checklist review**

Người dùng phải sửa box/class, thêm tất cả vật thể bị thiếu, kiểm tra frame rỗng toàn ảnh và đánh dấu tất cả jobs `Completed`. Đặc biệt review xe vàng=`car`, forklift mast/forks, reach stacker boom/spreader và truck/container truck.

- [ ] **Step 6: STOP — chưa được train**

Không tiếp tục Task 5 cho đến khi người dùng xác nhận cả hai CVAT task đã review xong và `Completed`.

### Task 5: Pull CVAT, audit thiếu nhãn và tạo immutable V9 snapshot

**Files:**
- Modify: `backend/python-worker/training/cvat_pull_reviewed_package.py`
- Modify: `backend/python-worker/training/dataset_audit.py`
- Modify: `backend/python-worker/training/local_video_dataset.py`
- Modify: `backend/python-worker/tests/test_dataset_audit.py`
- Modify: `backend/python-worker/tests/test_v9_video_dataset.py`
- Produce: `backend/data/training/datasets/baikiem-v9-reviewed/`

**Interfaces:**
- Consumes: completed CVAT tasks và bốn reviewed local datasets còn giữ trong project.
- Produces: schema-v4 immutable snapshot, stable content hash, source provenance, `data.yaml` và audit report.

- [ ] **Step 1: Pull đúng annotation version**

Receipt phải ghi task ID, job IDs, states=`completed`, annotation version, frame count, per-class box count và timestamp. Nếu một job chưa completed thì fail.

- [ ] **Step 2: Viết audit regression test cho lỗi V8**

```python
def test_multiclass_finalize_never_projects_non_reach_labels_to_negative():
    snapshot = finalize_v9_reviewed_package(reviewed_frame_with_car_and_reach())
    assert classes_in(snapshot) == {"car", "reach_stacker"}
    assert box_count(snapshot, "car") == 1
```

- [ ] **Step 3: Merge dữ liệu cũ bằng tên class, không dùng numeric ID cũ**

Reindex bốn reviewed packages theo canonical name. Không dùng `export_reach_stacker_supplemental_snapshot()` cho V9 vì hàm đó chủ ý loại các class khác.

- [ ] **Step 4: Audit completeness và leakage**

Block khi có unknown class, invalid box, missing label file, missing review row, train/val/test hash overlap, duplicate group nhiều split, frame gần trùng nhiều split hoặc source provenance thiếu.

- [ ] **Step 5: Audit balance/readiness**

Báo frame, instance, sources, size buckets, hard negatives và confusion candidates từng class. Mọi required class phải đạt contract ở phần Hợp đồng class V9; nếu không đạt thì dừng và yêu cầu đúng loại video/annotation còn thiếu.

- [ ] **Step 6: Chạy test/audit**

```powershell
cd backend/python-worker
& '.venv/Scripts/python.exe' -m unittest `
  tests.test_cvat_pull_reviewed_package `
  tests.test_dataset_audit `
  tests.test_v9_video_dataset -v
```

Expected: PASS; audit gate `passed: true`.

### Task 6: Đo baseline đa class trước khi train

**Files:**
- Modify: `backend/python-worker/evaluation/metrics.py`
- Modify: `backend/python-worker/evaluation/evaluate_local_video_model.py`
- Create: `backend/python-worker/evaluation/v9_acceptance.py`
- Create: `backend/python-worker/tests/test_v9_acceptance.py`
- Produce: `backend/data/training/benchmarks/baikiem-v9-baseline.json`

**Interfaces:**
- Consumes: validation snapshot, base YOLO11n và V8 supplemental.
- Produces: `evaluate_v9_candidate(...) -> V9EvaluationReport` với per-class/source/size/confusion/continuity metrics.

- [ ] **Step 1: Viết metric tests với TP/FP/FN biết trước**

```python
def test_v9_report_keeps_per_source_and_small_far_buckets():
    report = evaluate_fixture()
    assert report["perClass"]["forklift"]["tp"] == 2
    assert report["perSource"]["camera-b"]["recall"] == 0.5
    assert report["sizeBuckets"]["small"]["fn"] == 1
```

- [ ] **Step 2: Tổng quát hóa evaluator**

Tính TP, FP, FN, Precision, Recall, F1, AP50, mAP50-95, confusion matrix, per-source, per-camera, small/medium/large, far/occluded/partial và maximum visible gap. Metric undefined phải mang lý do, không tự đổi thành 0.

- [ ] **Step 3: Chạy base+V8 baseline trên validation**

Không dùng locked test. Lưu artifact hash, dataset hash, thresholds, source list, resolution, hardware và Ultralytics version.

- [ ] **Step 4: Xuất toàn bộ lỗi baseline**

Xuất false negative, false positive và class confusion thành review index có source/timestamp/native frame reference. Đây là evidence, chưa được tự động đưa ngược vào train trong cùng split.

- [ ] **Step 5: Chạy tests**

```powershell
cd backend/python-worker
& '.venv/Scripts/python.exe' -m unittest tests.test_golden_metrics tests.test_v9_acceptance -v
```

Expected: PASS.

### Task 7: Train đúng một V9 candidate từ YOLO11n pretrained

**Files:**
- Modify: `backend/python-worker/training/runner.py`
- Modify: `backend/python-worker/tests/test_training_runner.py`
- Modify: `backend/python-worker/training/finalize_checkpoint.py`
- Produce: `backend/data/training/runs/baikiem-v9-unified-candidate/`
- Produce: `backend/data/training/models/baikiem-v9-unified-candidate/`

**Interfaces:**
- Consumes: schema-v4 reviewed snapshot và `backend/python-worker/yolo11n.pt`.
- Produces: V9 `best.pt`, `labels.json`, `evaluation.json`, dataset/artifact hashes và `runtimeMode: UNIFIED` candidate.

- [ ] **Step 1: Viết training-contract tests**

```python
def test_v9_runner_uses_unified_profile_and_never_validates_on_test():
    contract = training_contract(v9_manifest())
    assert contract["runtimeMode"] == "UNIFIED"
    assert contract["labels"] == list(EXPECTED_V9_CLASSES)
    assert contract["evaluationSplit"] == "val"
```

- [ ] **Step 2: Chạy một epoch VRAM probe, không chọn model từ probe**

Thử batch 4 tại `imgsz=896`; nếu CUDA OOM thì batch 2, sau đó batch 1. Chọn batch lớn nhất hoàn thành và peak VRAM ≤3.8 GiB. Probe không được dùng làm candidate.

- [ ] **Step 3: Khóa training arguments**

```python
V9_TRAIN_OPTIONS = {
    "epochs": 120,
    "imgsz": 896,
    "workers": 0,
    "device": 0,
    "amp": True,
    "patience": 20,
    "optimizer": "AdamW",
    "lr0": 0.001,
    "lrf": 0.01,
    "warmup_epochs": 1.0,
    "degrees": 0.0,
    "translate": 0.08,
    "scale": 0.35,
    "shear": 0.0,
    "perspective": 0.0,
    "flipud": 0.0,
    "fliplr": 0.5,
    "hsv_h": 0.01,
    "hsv_s": 0.35,
    "hsv_v": 0.25,
    "mosaic": 0.25,
    "mixup": 0.0,
    "close_mosaic": 15,
}
```

Không dùng augmentation phi thực tế, không tăng epoch chỉ để cứu dataset yếu và không khởi tạo thẳng từ V8 one-class.

- [ ] **Step 4: Chạy V9 training**

```powershell
cd backend/python-worker
$env:TRAINING_IMAGE_SIZE='896'
$env:TRAINING_PATIENCE='20'
$env:TRAINING_OPTIMIZER='AdamW'
$env:TRAINING_LR0='0.001'
$env:TRAINING_LRF='0.01'
$env:TRAINING_WARMUP_EPOCHS='1.0'
& '.venv/Scripts/python.exe' training/runner.py `
  '../../backend/data/training/datasets/baikiem-v9-reviewed/annotation-manifest.json' `
  'yolo11n.pt' `
  '../../backend/data/training' `
  'baikiem-v9-unified-candidate' `
  '120'
```

Expected: best checkpoint, no OOM, validation split only, candidate chưa active.

- [ ] **Step 5: Kiểm tra learning curves**

Reject run có NaN, class metric undefined, train/val divergence kéo dài, best epoch chỉ dựa vào một class hoặc quality gate không đạt. Early stopping được chấp nhận; không resume để ép đủ 120 epoch.

- [ ] **Step 6: Chạy training tests**

```powershell
cd backend/python-worker
& '.venv/Scripts/python.exe' -m unittest tests.test_training_runner -v
```

Expected: PASS.

### Task 8: Calibrate confidence trên validation, không retrain và không nhìn test

**Files:**
- Modify: `backend/python-worker/evaluation/metrics.py`
- Modify: `backend/python-worker/evaluation/evaluate_local_video_model.py`
- Modify: `backend/python-worker/tests/test_golden_metrics.py`
- Produce: `backend/data/training/evaluations/baikiem-v9-validation-sweep.json`

**Interfaces:**
- Consumes: V9 `best.pt` và validation predictions cache.
- Produces: per-class initiation/continuation thresholds cùng PR/F1 curves.

- [ ] **Step 1: Cache prediction một lần ở confidence 0.05**

Chạy model một lần trên validation và lưu raw predictions; threshold sweep không được infer lại nhiều lần hoặc chạm locked test.

- [ ] **Step 2: Sweep threshold 0.05–0.60 bước 0.025**

Với mỗi class báo TP, FP, FN, Precision, Recall, F1 và AP. Chọn threshold có recall cao nhất trong các điểm Precision ≥0.90; nếu không có điểm đạt, candidate fail thay vì âm thầm chọn maximum-F1.

- [ ] **Step 3: Tách initiation/continuation**

Initiation dùng threshold đã calibrate. Continuation có thể thấp hơn nhưng chỉ tiếp tục track đã confirmed; không mở event mới từ low-confidence hit. Giữ 2-of-3 confirmation cho custom classes.

- [ ] **Step 4: Chạy validation gate**

Mọi metric trong bảng Validation gate phải pass. Nếu giảm confidence vẫn không đạt recall, không sửa bằng tracker; chuyển sang vòng dữ liệu ở phần Điều kiện dừng.

- [ ] **Step 5: Chạy tests**

```powershell
cd backend/python-worker
& '.venv/Scripts/python.exe' -m unittest tests.test_golden_metrics tests.test_v9_acceptance -v
```

Expected: PASS.

### Task 9: Xác minh runtime UNIFIED một-pass và benchmark FPS

**Files:**
- Modify: `backend/python-worker/detection/tracked_detector.py`
- Modify: `backend/python-worker/tests/test_area_pipeline.py`
- Modify: `backend/python-worker/training/benchmark_models.py`
- Produce: `backend/data/training/benchmarks/baikiem-v9-runtime-matrix.json`

**Interfaces:**
- Consumes: V9 candidate, per-class thresholds và production video sources.
- Produces: one-pass Area feed benchmark và runtime regression evidence.

- [ ] **Step 1: Viết test một inference pass**

```python
def test_v9_unified_calls_only_one_model_per_frame():
    detector = prepared_unified_detector()
    detector.track(sample_frame())
    assert detector.unified_model.track.call_count == 1
    assert detector.base_model.track.call_count == 0
    assert detector.custom_model is None
```

- [ ] **Step 2: Benchmark inference size 768 và 896**

Không train lại. So sánh PyTorch AMP cho accuracy, average/p95 latency, FPS và VRAM. Chọn 896 nếu đạt ≥8 FPS; chỉ chọn 768 nếu 896 fail FPS và 768 vẫn vượt toàn bộ accuracy gates.

- [ ] **Step 3: Chạy end-to-end Area benchmark**

Đo decode, inference, tracking, arbitration, JPEG, WebSocket publish và tổng FPS trên video gần/xa/đông vật thể. Chạy warm-up trước, báo steady-state ít nhất 60 giây/source.

- [ ] **Step 4: Regression seek/delete/event**

Tua nhiều mốc, xóa tất cả sự kiện khi violation đang mở, xác nhận không reconnect storm, không retry DB vô hạn, không duplicate event và FPS vẫn ≥8.

- [ ] **Step 5: Chạy Python regression suite**

```powershell
cd backend/python-worker
& '.venv/Scripts/python.exe' -m unittest discover -s tests -v
```

Expected: toàn bộ tests PASS.

### Task 10: Chạy locked acceptance đúng một lần

**Files:**
- Modify: `backend/python-worker/evaluation/v9_acceptance.py`
- Modify: `backend/python-worker/training/finalize_checkpoint.py`
- Modify: `backend/python-worker/tests/test_v9_acceptance.py`
- Produce: `backend/data/training/evaluations/baikiem-v9-locked-acceptance.json`

**Interfaces:**
- Consumes: exact dataset hash, artifact hash, frozen thresholds, locked-blind reviewed task và runtime benchmark.
- Produces: final immutable `passed/failed` activation gate.

- [ ] **Step 1: Bind report với exact hashes**

Reject nếu dataset content hash, model SHA-256, threshold hash hoặc locked source manifest không khớp candidate đã calibrate.

- [ ] **Step 2: Chạy candidate trên locked test**

Không thay threshold, augmentation, class list hoặc frame selection sau khi xem kết quả. Báo per-class/per-source/per-size metrics, confusion, continuity và false alerts.

- [ ] **Step 3: Áp dụng strict gate**

```python
assert report.review_complete is True
assert report.macro_precision >= 0.90
assert report.macro_recall >= 0.90
assert report.macro_map50_95 >= 0.55
assert min_supported_class_precision(report) >= 0.85
assert min_supported_class_recall(report) >= 0.85
assert report.performance.end_to_end_fps >= 8.0
assert report.temporal.max_gap_seconds <= 0.50
```

- [ ] **Step 4: Không fake pass cho class thiếu support**

Class/source chưa đủ ground truth phải trả về `INSUFFICIENT_SUPPORT`; nếu đó là required class thì toàn gate fail.

- [ ] **Step 5: Chạy acceptance tests**

```powershell
cd backend/python-worker
& '.venv/Scripts/python.exe' -m unittest tests.test_v9_acceptance -v
cd ../node-api
npx.cmd ts-node src/tests/test_model_activation_gate.ts
```

Expected: Python acceptance test và Node activation-gate test đều PASS.

### Task 11: Đăng ký candidate, manual approval và rollback

**Files:**
- Modify: `backend/node-api/src/routes/trainingJobs.ts`
- Modify: `backend/node-api/src/tests/test_model_activation_gate.ts`
- Modify: `backend/python-worker/detection/taxonomy.py`
- Modify: `backend/python-worker/tests/test_detection_taxonomy.py`
- Create: `docs/evaluation/baikiem-v9-results.md`

**Interfaces:**
- Consumes: passed locked acceptance và V8 active version.
- Produces: V9 status `READY_FOR_APPROVAL`, explicit activate action và V8 rollback record.

- [ ] **Step 1: Viết activation rejection tests**

Reject candidate thiếu class, hash mismatch, failed/undefined metric, FPS thấp, locked review chưa complete hoặc chưa có rollback version.

- [ ] **Step 2: Đăng ký nhưng không activate**

Lưu V9 `best.pt`, `labels.json`, validation report, locked report, thresholds và hashes. Trạng thái phải là `READY_FOR_APPROVAL`, không phải `ACTIVE`.

- [ ] **Step 3: Yêu cầu người dùng xác nhận activate**

Trình bày V8→V9 metric/FPS comparison và các camera/source đã certified. Chỉ sau xác nhận mới đổi active version.

- [ ] **Step 4: Smoke test sau activation**

Khởi động worker, xác nhận log load đúng `baikiem-v9-unified-candidate`, nhận đủ mười class manifest, WebSocket frame hợp lệ và không chạy model base thứ hai.

- [ ] **Step 5: Xác minh rollback**

Rollback về V8 phải khôi phục chính xác artifact và thresholds trước V9 mà không xóa V9 candidate.

- [ ] **Step 6: Chạy full project checks**

```powershell
cd backend/python-worker
& '.venv/Scripts/python.exe' -m unittest discover -s tests -v
cd ../node-api
npm.cmd run typecheck
cd ../../frontend
npm.cmd run lint
npm.cmd run build
```

Expected: PASS.

- [ ] **Step 7: Hoàn thiện báo cáo**

`docs/evaluation/baikiem-v9-results.md` phải có dataset/source counts, class coverage, V8 baseline, V9 validation/locked metrics, confusion matrix, false negatives, FPS/VRAM, certified sources, unresolved limitations và rollback version.

## Điều kiện dừng và vòng bổ sung dữ liệu

Sau lần train V9 đầu tiên:

1. Nếu Precision thấp nhưng Recall cao, kiểm tra false positives, annotation consistency và threshold trước; chưa train lại.
2. Nếu Recall thấp và raw model không phát box ở confidence 0.05, threshold/tracker không thể cứu; tạo review package mới từ false negatives của validation.
3. Nếu `car/truck`, `forklift/reach_stacker` hoặc `truck/container_truck` confusion ≥5%, mine cặp hard-negative/hard-positive cân bằng từ frame gốc.
4. Nếu mAP50 tốt nhưng mAP50-95 thấp, ưu tiên audit box tightness, partial/occluded policy và resolution thay vì chỉ thêm epoch.
5. Nếu FPS <8 ở 896, benchmark 768 với cùng checkpoint. Không đổi sang model lớn hơn trước khi chứng minh YOLO11n không đạt accuracy và YOLO11s vẫn có khả năng đạt FPS gate.
6. Mỗi vòng bổ sung phải loại near-duplicate, review CVAT đầy đủ và tạo dataset hash mới.
7. Không train vòng tiếp theo cho đến khi người dùng kiểm tra package bổ sung và xác nhận `Completed`.
8. Locked test đã mở kết quả không được dùng làm nguồn active learning. Nếu thay đổi model/data sau locked failure, tạo locked source set mới độc lập trước lần acceptance tiếp theo.

## Kết quả bàn giao

Kế hoạch chỉ được coi là hoàn thành khi có đủ:

- Inventory 20 GB video và duplicate/source split report.
- Hai CVAT tasks với review receipt `Completed`.
- Immutable V9 schema-v4 dataset và audit pass.
- V8/base baseline trên validation.
- V9 validation threshold sweep có TP/FP/FN/Precision/Recall/F1/AP từng class.
- Locked acceptance report gắn exact dataset/model/threshold hashes.
- Per-camera certification table; camera chưa đủ support phải ghi rõ chưa chứng nhận.
- End-to-end Area FPS/p95/VRAM benchmark.
- V9 candidate artifact và V8 rollback còn nguyên.
- Full Python/Node/frontend regression pass.
- Không có claim “mọi camera đều 90%” nếu chưa có ground truth đại diện cho camera đó.

## Tài liệu tham chiếu

- Existing unified plan: `docs/superpowers/plans/2026-08-23-baikiem-local-video-unified-yolo11n.md`
- Annotation policy: `docs/evaluation/bai-kiem-annotation-checklist.md`
- Current V8 evaluation: `backend/data/training/models/baikiem-reach-reviewed-v8-hardcases-ft-20260824/evaluation.json`
- Ultralytics YOLO11: https://docs.ultralytics.com/models/yolo11
- Ultralytics training mode: https://docs.ultralytics.com/modes/train
- Ultralytics tracking mode: https://docs.ultralytics.com/modes/track
