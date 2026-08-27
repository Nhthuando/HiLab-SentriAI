# BAI-KIEM V9 Production Activation Design

## Quyết định đã duyệt

Chủ dự án chấp nhận các metric hiện tại và yêu cầu đưa `baikiem-v9-unified-candidate-final` lên runtime production để tự kiểm tra video, dù quality gate tự động chưa đạt. V8 hiện tại phải được giữ nguyên để rollback.

## Phạm vi

- Chỉ thay detector Area của camera `BAI-KIEM` sang V9 `UNIFIED` một lượt inference.
- Không thay Gate/LPR, video nguồn, zone, sự kiện, clip hoặc dữ liệu training.
- V9 chỉ cung cấp năm class đã train: `person`, `car`, `truck`, `forklift`, `reach_stacker`.
- `bicycle`, `motorcycle`, `bus`, `container_truck`, `mobile_crane` không được quảng bá là đã được V9 hỗ trợ.

## Cơ chế activation

V9 được đăng ký thành một model version có trạng thái `ACTIVE`, gắn với đúng model SHA-256, dataset hash, label map và evaluation hiện tại. Quality gate vẫn lưu `passed: false`; metadata bổ sung một manual-production approval minh bạch thay vì sửa metric thành đạt.

Activation thủ công phải cần đồng thời:

1. xác nhận override rõ ràng của chủ dự án;
2. model hash khớp `3772e978fc4635a6a2d3dffb59286bd89c0ebbc6cc6e27dc77532b5006eaab52`;
3. runtime mode là `UNIFIED`;
4. model và labels đọc được;
5. targeted regression và smoke test đạt.

Runtime chỉ chạy V9 một lần mỗi frame. Không chạy YOLO nền và V9 song song vì sẽ giảm FPS và tái tạo lỗi trùng box.

## Partial class coverage

Registry hiện có `bicycle` và `motorcycle`, trong khi V9 chưa train hai class này. Manual production approval cho phép V9 hoạt động với coverage một phần; các label không nằm trong V9 phải được báo `UNAVAILABLE`, không được đổi class hoặc âm thầm chạy model thứ hai.

Thêm label registry `Xe nâng container` → `reach_stacker` nếu chưa tồn tại. `Xe nâng` được route sang `forklift` trong manifest V9. Thay đổi registry phải được ghi trong rollback receipt.

## Threshold và hiệu năng

- Inference size production: `896` vì benchmark đạt 19.72 FPS, vượt gate 8 FPS.
- Initiation confidence: `person=0.25`, `car=0.30`, `truck=0.40`, `forklift=0.40`, `reach_stacker=0.05`.
- Continuation chỉ áp dụng cho track đã xác nhận và thấp hơn initiation để giảm mất box; nó không được mở event mới.

## Rollback

Trước activation phải lưu receipt chứa model/config đang dùng, hash V8, label registry và model-version status. Artifact V8 không bị sửa hoặc xóa.

Rollback đưa V9 về `INACTIVE`, phục hồi V8 và registry/config đã lưu. Nếu V9 load lỗi hoặc hash sai, worker phải fail closed về detector trước đó thay vì phát feed trống.

## Xác minh

- Python: taxonomy, zone sync, detection policy, unified one-pass và Area pipeline tests.
- Node: activation gate, taxonomy, label capability, typecheck.
- Runtime: log phải xác nhận `mode=UNIFIED`, đúng version key, đủ năm class và không load model Area thứ hai.
- API/feed: worker và node-api khởi động được, không có WebSocket reconnect storm.

## Trạng thái chất lượng

Activation này là quyết định vận hành của chủ dự án, không thay đổi kết luận đánh giá: V9 chưa đạt quality gate 85–90%. Báo cáo validation/locked và toàn bộ false negatives vẫn được giữ nguyên để đối chiếu.
