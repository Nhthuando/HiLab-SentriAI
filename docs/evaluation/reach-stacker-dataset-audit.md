# Audit dataset `826106ce49746e9a5e3dd934c4bc711333549d1a9e38f82e8ea2a3f818a64c12`

Snapshot: `826106ce49746e9a5e3dd934c4bc711333549d1a9e38f82e8ea2a3f818a64c12`  
Nguồn khai báo: `reach stacker.v1i.yolov8.zip`  

Lệnh tái lập từ `backend/python-worker`:

```powershell
& '.venv/Scripts/python.exe' -m training.dataset_audit <snapshot> --json-output <report.json> --markdown-output <report.md>
```

## Kết quả định lượng

| Chỉ số | Giá trị |
| --- | ---: |
| Ảnh | 200 |
| Bounding box | 222 |
| Nguồn | 200 |
| Ảnh negative/hard-negative | 0 (0.00%) |
| Box chạm mép ảnh | 58 |
| Exact duplicate groups | 0 |
| Near-duplicate pairs (dHash ≤ 5) | 0 |
| Source xuất hiện ở nhiều split | 0 |

## Split

| Split | Ảnh | Box | Negative | Nguồn |
| --- | ---: | ---: | ---: | ---: |
| train | 140 | 156 | 0 | 140 |
| val | 40 | 46 | 0 | 40 |
| test | 20 | 20 | 0 | 20 |

## Phân bố kích thước bbox

- Nhỏ hơn 1% diện tích ảnh: 0
- Từ 1% đến dưới 10%: 6
- Từ 10% trở lên: 216
- Median diện tích chuẩn hóa: 54.60948%

## Provenance và class mapping

- Loại nguồn trong manifest: `external_yolo_archive`.
- Archive trong manifest: `reach stacker.v1i.yolov8.zip`.
- Training profile: `không khai báo`.
- Phân bố class đo từ label files: Xe nâng: 222.

- Mapping nguồn `stacker` → `Xe nâng` / `reach stacker`.
- Manifest không đóng băng `requiredClasses`; class được suy ra từ samples theo quy tắc tương thích snapshot cũ.

## Kết luận từ evidence

- Có 200 sourceId phân biệt trong manifest/materialized output. Chỉ số này không tự chứng minh số camera, phiên quay hoặc time block độc lập.
- Có 0 bbox dưới 1%, 6 bbox từ 1% đến dưới 10%, và 216 bbox từ 10% diện tích ảnh trở lên.
- Không có ảnh negative, nên dataset không cung cấp evidence để định lượng false-positive rate trên cảnh không có target.
- Có 58 bbox chạm mép ảnh; đây là danh sách ưu tiên cho kiểm tra clipping thủ công.
- Không phát hiện exact duplicate hoặc near-duplicate ở ngưỡng dHash 5.
- Không phát hiện sourceId xuất hiện ở nhiều split.

## Đối soát số liệu median

Tài liệu trước đó ghi `54.77%`. Audit deterministic từ chính snapshot này xác minh `54.60948%`; chênh lệch `-0.16052` điểm phần trăm. Giá trị đã xác minh thay thế số cũ.

## Phạm vi kết luận

Công cụ chỉ đo metadata, annotation và đặc trưng ảnh có thể kiểm chứng. Nó không suy đoán loại background, mức độ gần/xa hay tính đúng nghĩa của bbox từ pixel; các nội dung đó cần người review thủ công.

Report này không tự gán dataset là golden validation set hoặc domain match; quyết định đó cần protocol đánh giá và provenance bổ sung ngoài các trường hiện có.
