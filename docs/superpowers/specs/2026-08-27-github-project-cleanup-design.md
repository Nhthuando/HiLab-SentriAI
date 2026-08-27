# HiLab-SentriAI GitHub Project Cleanup Design

## Mục tiêu

Dọn repository HiLab-SentriAI để có thể đưa lên GitHub mà không làm thay đổi chức năng runtime, độ chính xác, tốc độ hoặc byte nội dung của model V9 production. Toàn bộ dữ liệu train và công sức review phải được chuyển sang một archive ngoài repository thay vì xóa.

## Trạng thái đã khảo sát

- Workspace hiện dùng khoảng 18,7 GB, không tính `.git` khoảng 75 MB.
- `backend/data` dùng khoảng 12,91 GB.
- `backend/python-worker/.venv` dùng khoảng 5,32 GB.
- Hai thư mục `node_modules` dùng tổng cộng khoảng 312 MB.
- Model V9 production là `backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt`, dung lượng khoảng 5,27 MB.
- SHA-256 hiện tại của V9 là `3772E978FC4635A6A2D3DFFB59286BD89C0EBBC6CC6E27DC77532B5006EAAB52`.
- Runtime đang trỏ tới version `baikiem-v9-unified-candidate-final` bằng `CUSTOM_AUGMENT_ARTIFACT=training/models/baikiem-v9-unified-candidate-final/best.pt`.
- Toàn bộ `backend/data/training/` hiện bị `.gitignore` loại khỏi Git, vì vậy clone GitHub hiện tại sẽ thiếu model V9 production.

## Phạm vi bảo vệ

Không được xóa, sửa hoặc đổi nội dung các thành phần sau:

- Toàn bộ source code, test, tài liệu, package manifest và lockfile.
- Prisma schema, migration và cấu hình mẫu.
- `backend/data/training/models/baikiem-v9-unified-candidate-final/` gồm `best.pt`, `labels.json`, `evaluation.json` và `training-receipt.json`.
- Các model nền trong `backend/python-worker/models/` để tránh làm mất chức năng inference hoặc training hiện hữu.
- `.local/cvat/` để người dùng tiếp tục khởi động CVAT khi cần.
- Các ảnh public/proposal đang được Git theo dõi.

Trước và sau cleanup phải xác minh lại SHA-256 của V9. Nếu hash thay đổi hoặc artifact bị thiếu, cleanup bị xem là thất bại và phải dừng trước khi xóa thêm.

## Archive ngoài repository

Tạo thư mục:

`D:\HuuThuan - Project\HiLab-SentriAI-training-archive\2026-08-27`

Di chuyển, không xóa, các nhóm dữ liệu sau sang archive và giữ nguyên cấu trúc tương đối:

- Mọi nội dung trong `backend/data/training/` ngoại trừ thư mục V9 production được bảo vệ.
- `backend/data/external-datasets/`, bao gồm `NRMM.v22i.yolov11.zip`.
- `backend/data/evaluation/`.

Archive phải có manifest JSON ghi thời điểm, đường dẫn nguồn, đường dẫn đích, số file và tổng số byte của từng nhóm. Sau mỗi lần di chuyển phải so sánh số file và tổng byte ở nguồn/đích trước khi tiếp tục. Không được xóa bản nguồn bằng một bước riêng nếu thao tác move không hoàn tất.

Ước tính khoảng 12,9 GB được chuyển khỏi repository. Archive không nằm trong Git và vẫn có thể được đưa trở lại đúng vị trí khi cần train hoặc audit.

## Nội dung có thể xóa và tái tạo

Sau khi archive đã được xác minh, xóa các dependency/build/cache sau:

- `backend/python-worker/.venv/`.
- `backend/node-api/node_modules/`.
- `frontend/node_modules/`.
- `backend/node-api/dist/`.
- `frontend/dist/`.
- Tất cả `__pycache__/`, `.pytest_cache/` và cache Vite nằm trong workspace.

Các thư mục này chỉ được xóa theo đường dẫn tuyệt đối đã resolve và xác minh nằm dưới workspace. Không dùng wildcard hoặc recursive delete với đường dẫn chưa kiểm tra. Các file `requirements.txt`, `package.json` và `package-lock.json` phải được giữ để tái tạo dependency.

Ước tính khoảng 5,65 GB được giải phóng vĩnh viễn từ các thành phần tái tạo được.

## Đóng gói V9 cho GitHub

Cập nhật `.gitignore` để tiếp tục ignore toàn bộ dữ liệu train sinh ra, nhưng cho phép Git theo dõi duy nhất bốn file trong thư mục V9 production. Không đổi đường dẫn runtime hiện tại.

Trước khi stage phải dùng `git check-ignore` và `git status` để xác nhận:

- Không có dataset, annotation, run, locked test, CVAT export hoặc model cũ nào được đưa vào Git.
- Chỉ thư mục V9 production đã duyệt được phép xuất hiện ngoài source hiện có.
- Không có `.env`, secret, video, clip hoặc cache nào được stage.

Model `best.pt` nhỏ hơn giới hạn file 100 MB của GitHub nên có thể theo dõi trực tiếp mà không cần Git LFS.

## Xác minh hoàn tất

Cleanup chỉ hoàn tất khi đạt tất cả điều kiện sau:

1. Model V9 production còn đủ bốn file và SHA-256 của `best.pt` không đổi.
2. Archive tồn tại, manifest hợp lệ, và số file/tổng byte của dữ liệu đã chuyển khớp với nguồn trước khi chuyển.
3. `git status` không chứa dữ liệu lớn hoặc secret ngoài bundle V9 đã cho phép.
4. Backend Node build lại được sau `npm ci`.
5. Frontend build lại được sau `npm ci`.
6. Python dependency có thể được tái tạo từ `requirements.txt`; test không phụ thuộc model phải chạy được sau khi tạo lại `.venv`.
7. Cấu hình mẫu vẫn mô tả đúng đường dẫn V9 production.
8. Dung lượng workspace sau cleanup được đo và báo cáo cùng dung lượng đã archive/xóa.

Việc cài lại toàn bộ dependency chỉ phục vụ xác minh khi cần; nếu cài lại ngay sẽ làm thư mục nặng trở lại. Có thể xác minh lockfile và source trước, sau đó cung cấp lệnh phục hồi rõ ràng cho người dùng.

## Khôi phục

- Dependency: chạy `npm ci` trong `frontend` và `backend/node-api`, sau đó tạo lại `.venv` và cài `backend/python-worker/requirements.txt`.
- Dữ liệu train: đưa các thư mục trong archive trở lại đúng đường dẫn tương đối dưới repository.
- Runtime V9: không cần khôi phục vì bundle production luôn được giữ trong repository và theo dõi bằng Git.

## Ngoài phạm vi

- Không retrain, convert, quantize hoặc thay model V9.
- Không thay confidence, image size, tracker, Zone logic hoặc pipeline inference.
- Không thay database record hoặc xóa dữ liệu database/CVAT Docker volume.
- Không dọn lịch sử Git hoặc force-push.
