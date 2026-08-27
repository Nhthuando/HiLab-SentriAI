# BAI-KIEM V9 Official Runtime Design

## Quyết định đã duyệt

V9 `baikiem-v9-unified-candidate-final` trở thành model Area chính thức. V8 không còn được dùng làm fallback tự động, nhưng artifact V8 vẫn được giữ nguyên trên ổ đĩa để cứu hộ thủ công khi thật sự cần.

## Hiện trạng và nguyên nhân

- V9 vẫn nhận diện và phát feed bình thường.
- `GET /api/v1/labels` và các API zone lỗi vì Node API/Python Worker hiện được khởi chạy trong sandbox không được phép kết nối Neon.
- Một truy vấn `SELECT 1` từ Node chạy ngoài sandbox đã thành công, xác nhận dữ liệu Neon không bị mất và chuỗi kết nối vẫn dùng được.
- `GET /api/v1/cameras/BAI-KIEM/playback` đang trả `seekable: true` cùng duration/position hợp lệ. Thanh tua phụ thuộc vào dữ liệu này, nên phải xuất hiện lại sau khi service được chạy đúng quyền và trang được tải lại.

## Cấu hình model chính thức

- DB tiếp tục có duy nhất V9 ở trạng thái `ACTIVE` với runtime mode `UNIFIED`.
- Cấu hình model mặc định trong `backend/.env` được chuyển từ artifact/version/hash V8 sang đúng artifact/version/hash V9.
- Runtime chỉ chạy một lượt inference V9 cho mỗi frame; không chạy V8 song song và không tự quay về V8.
- V8 không bị xóa, sửa hoặc đổi hash. Rollback sang V8 chỉ còn là thao tác thủ công có chủ đích.
- Không sửa metric hoặc tuyên bố quality gate V9 đã đạt nếu báo cáo đánh giá không chứng minh điều đó.

## Khôi phục API và giao diện

Node API và Python Worker được dừng đúng PID hiện tại rồi khởi động lại ngoài sandbox, từ đúng thư mục dự án và dùng cấu hình V9 chính thức. Frontend chỉ cần khởi động lại nếu build/HMR hiện tại không phản ánh trạng thái mới.

Không tạo lại hoặc xóa dữ liệu Neon. Không seed đè danh mục nhãn, zone, sự kiện hoặc mẫu gắn nhãn.

Sau khi kết nối DB phục hồi:

- Settings phải tải lại danh mục nhãn thật từ Neon;
- Zone Editor phải tải lại zone và `targetLabels` thật;
- Object Training phải xác minh lại profile thay vì báo `Failed to fetch`;
- Area Monitor phải hiển thị thanh tua khi playback API báo nguồn video có thể seek.

`GET /api/v1/vehicles` phải là read-only. Việc đăng ký biển số mới đã được Gate pipeline thực hiện khi chấp nhận sự kiện, nên route danh sách không được quét lịch sử rồi `upsert` tuần tự mỗi lần Settings tải trang; thao tác đó làm nghẽn burst API ban đầu và tăng nguy cơ lỗi kết nối Neon tạm thời.

## Xử lý lỗi

- Nếu service không kết nối Neon khi chạy ngoài sandbox, dừng triển khai và giữ nguyên dữ liệu; không dùng dữ liệu giả để lấp UI.
- Nếu playback API thành công nhưng thanh tua chưa hiện, kiểm tra frontend state/render và sửa giới hạn ở luồng playback, không thay đổi detector V9.
- Nếu V9 không load đúng hash/class manifest sau restart, không xóa V8; báo lỗi runtime và giữ artifact cứu hộ.

## Xác minh hoàn tất

1. `GET /api/v1/labels` trả `200` và danh mục nhãn thật.
2. API zone BAI-KIEM trả `200` và zone đã lưu.
3. API playback trả `seekable: true`, position và duration hợp lệ.
4. UI Settings hiện nhãn/zone; Area Monitor hiện thanh tua.
5. Worker log xác nhận V9 `UNIFIED` với năm class `person`, `car`, `truck`, `forklift`, `reach_stacker` và không load V8.
6. Feed BAI-KIEM tiếp tục có frame/detection và FPS đạt mức vận hành hiện tại.
7. Artifact V8 vẫn tồn tại nhưng không còn xuất hiện trong cấu hình runtime đang dùng.

## Phạm vi không thực hiện

- Không xóa artifact V8.
- Không train thêm model.
- Không chỉnh confidence/IoU/tracking trong lần sửa này.
- Không migrate hoặc reset cơ sở dữ liệu.
