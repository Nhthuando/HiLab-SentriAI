# BAI-KIEM — trạng thái cải thiện nhận diện

Trạng thái hiện tại: **BLOCKED_PENDING_HUMAN_REVIEW**. Không checkpoint thử nghiệm nào được kích hoạt; model COCO nền vẫn giữ nguyên.

## Kết quả ứng viên v3

- Checkpoint: `baikiem-reach-reviewed-v3-ft-20260824/best.pt`
- SHA-256: `f494378cd99ef7a60b3eafe27d793db81f78396602fc0339965ad4ab1a32bb8b`
- Validation gộp tại 768 px, ngưỡng khóa `0.220703125`: precision `95.24%`, recall `90.91%`, truck→reach `0%`.
- Locked test độc lập 60 frame: precision `0%`, recall `0%`, `35` false positive và `22` false negative.
- Nguyên nhân quan sát được: model nhầm cụm container cố định ở góc dưới-phải thành reach stacker và bỏ sót reach stacker rất nhỏ/xa ở phía trên ảnh.

Validation tốt nhưng locked test thất bại chứng minh ứng viên chưa tổng quát hóa. Vì vậy ứng viên v3 bị loại và không được đăng ký `ACTIVE`.

## Dữ liệu v4 đang chờ duyệt

CVAT task 7 bổ sung đúng miền còn thiếu: vật thể nhỏ/xa, ban đêm, mưa và hard negative container tĩnh.

| Tập | Frame | Proposal |
|---|---:|---:|
| Train | 150 | 295 |
| Validation | 30 | 29 |
| Locked test | 120 | 278 |
| Tổng | 300 | 602 |

- Job: `http://localhost:8080/tasks/7/jobs/6`
- CVAT ZIP SHA-256: `73b5355e5b78e27d10de212002dcd1c3133c3c19d1ddfcac069ca721e47e6a2b`
- Trạng thái job đã xác minh: `new / annotation`.
- Proposal chỉ là gợi ý. Mọi frame, kể cả frame không có box, phải được con người kiểm tra trước khi đóng băng dataset.

Sau khi job được đánh dấu `Completed`, chuỗi tự động tiếp theo là: export CVAT, kiểm tra toàn vẹn và khóa snapshot, gộp dataset, train YOLO11n supplemental v4, chọn ngưỡng trên validation, mở locked rain test đúng một lần, rồi benchmark end-to-end. Chỉ ứng viên vượt đồng thời precision/recall, truck-confusion, continuity và `>= 8 FPS` mới đủ điều kiện kích hoạt.

## Runtime và kiểm thử

- Model supplemental có thể dùng `AREA_CUSTOM_INFERENCE_SIZE` riêng với model COCO nền; mặc định vẫn giữ hành vi cũ.
- Công cụ end-to-end ghi cả `baseImageSize` và `customImageSize`, tránh đánh đổi độ chính xác class nền chỉ để tăng tốc reach stacker.
- Detector hỗ trợ xác nhận thời gian 2/3 cơ hội inference và giữ box/nhãn đã xác nhận giữa các nhịp inference.
- Focused tests: Area pipeline `37/37`, local-video evaluation `5/5`.
- `git diff --check` không phát hiện lỗi whitespace.
