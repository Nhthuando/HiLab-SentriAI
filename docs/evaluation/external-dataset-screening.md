# Sàng lọc dataset ngoài cho Area Detection

- **Trạng thái:** Review-ready, chưa tải dữ liệu
- **Ngày kiểm tra:** 2026-08-22
- **Đối tượng đọc:** kỹ sư dữ liệu/ML quyết định dataset nào đủ điều kiện làm warm-start hoặc augmentation
- **Phạm vi:** BMD-45, VisDrone, MIO-TCD Localization, ba project Roboflow được nêu trong `improve.md`, và xView

## Kết luận vận hành

Không dataset nào dưới đây được dùng làm golden validation/test. Golden val/test vẫn phải là dữ liệu BAI-KIEM local. Không upload BAI-KIEM hoặc dữ liệu private ra dịch vụ ngoài.

| Dataset | License | Quy mô được công bố | Quyết định hiện tại |
|---|---|---:|---|
| BMD-45 | **VERIFIED:** CC BY 4.0 | 45.986 ảnh, khoảng 481.947 bbox; trang lưu trữ báo 153 GB | Có thể xét subset CCTV xe cộ sau khi duyệt dung lượng và attribution |
| VisDrone2019-DET | **UNKNOWN/BLOCKED:** repo chính thức không có grant license dataset rõ ràng | 8.599 ảnh theo toolkit challenge; các archive DET công bố khoảng 2,07 GB tổng cộng | Không train/redistribute cho đến khi chủ dataset xác nhận điều khoản |
| MIO-TCD Localization | **VERIFIED:** CC BY-NC-SA 4.0 | 137.743 ảnh localization; dung lượng byte không công bố | Chỉ dùng phi thương mại, attribution/share-alike; chưa tải |
| Forklift v1 (Roboflow) | **VERIFIED ở cấp trang project:** Public Domain | 4.474 ảnh trong v1; project hiện có 6.375 ảnh | Có thể xét subset sau audit provenance, bbox và duplicate |
| TIR Project (Roboflow) | **VERIFIED ở cấp trang project:** CC BY 4.0 | 47.318 ảnh ở project; số ảnh/dung lượng riêng version v4 chưa truy cập được | Chỉ xét `forklift`/`insan`; `Tir` bị chặn mapping đến khi audit |
| NRMM (Roboflow) | **VERIFIED ở cấp trang project:** Public Domain | 4.028 ảnh; dung lượng byte không công bố | Có thể xét `Reach Stacker`/`Mobile Crane` sau audit provenance và viewpoint |
| xView | **PARTIAL/BLOCKED:** tài liệu Ultralytics ghi CC BY-NC-SA 4.0; site challenge gốc không trả nội dung | khoảng 20,7 GB; 847 ảnh train có nhãn, 282 ảnh val không public label; hơn 1 triệu object/60 class | Chỉ auxiliary top-down; chưa tải, không coi là domain match |

`VERIFIED ở cấp trang project` chỉ xác nhận nhãn license do người đăng project khai báo. Nó không chứng minh provenance hoặc quyền tái cấp phép của từng ảnh; vì vậy ba dataset cộng đồng Roboflow vẫn phải qua audit trước khi dùng.

## 1. BMD-45

**Bằng chứng chính thức.** [Dataset card của IISc AIM](https://huggingface.co/datasets/iisc-aim/BMD-45) ghi CC BY 4.0, 45.986 ảnh 1920×1080, khoảng 481.947 bbox, 14 class, COCO JSON/ImageFolder và tổng file-size do host báo là 153 GB. Card cũng ghi ảnh đến từ 3.679 camera CCTV Bengaluru.

- **Class liên quan:** `Hatchback`, `Sedan`, `SUV`, `Bus`, `Truck`.
- **Mapping cho phép:** `Hatchback|Sedan|SUV -> car`; `Bus -> bus`; `Truck -> truck`.
- **Không map:** `MUV`, `LCV`, `Van`, `Other` vì biên nghĩa có thể chồng `car`/`truck`; `Two-wheeler` và `Bicycle` vì định nghĩa bbox của card gộp cả người lái, không tương đương bbox COCO `motorcycle`/`bicycle` và `person`.
- **Subset tối thiểu đề xuất:** metadata-first, 500–1.000 ảnh có các class cho phép, ưu tiên xe nhỏ/xa, che khuất và nhiều camera; không lấy test không có nhãn. Chỉ thực hiện nếu cơ chế đọc chọn lọc không kéo toàn bộ 153 GB được xác minh.
- **Cảnh báo domain:** fixed CCTV và giao thông dày là hữu ích, nhưng đây là đường phố Bengaluru ban ngày, không phải bãi container. Chỉ dùng warm-start/augment cho class COCO xe; không sinh `container_truck`, `reach_stacker`, `forklift`, `mobile_crane` hay `shipping_container`.

## 2. VisDrone2019-DET

**Bằng chứng chính thức.** [Repo dataset của VisDrone](https://github.com/VisDrone/VisDrone-Dataset) mô tả toàn benchmark gồm 288 video/261.908 frame và 10.209 ảnh tĩnh; riêng các archive DET được công bố 1,44 GB train, 0,07 GB val, 0,28 GB test-dev và 0,28 GB test-challenge. [Toolkit DET chính thức](https://github.com/VisDrone/VisDrone2018-DET-toolkit) mô tả bbox TXT tám trường `left,top,width,height,score,class,truncation,occlusion`, các class và 6.471 train + 548 val + 1.580 test-challenge. Con số 1.610 test-dev trên repo mới và 1.580 test-challenge trong toolkit là hai split khác nhau, không cộng/trộn chúng.

- **License:** **UNKNOWN/BLOCKED.** Repo dataset không có license dataset rõ ràng; toolkit chỉ nói *code library* dùng cho research purpose. Điều này không phải grant chính xác cho pixels/annotations hoặc commercial training.
- **Mapping cho phép sau khi license được gỡ chặn:** `pedestrian -> person`, `bicycle -> bicycle`, `car -> car`, `truck -> truck`, `bus -> bus`, `motor -> motorcycle`.
- **Không map:** `people` không phải một cá thể `person`; `van`, `tricycle`, `awning-tricycle`, `others` không có canonical class tương đương.
- **Subset tối thiểu đề xuất:** 800–1.200 ảnh train/val có đối tượng nhỏ/xa thuộc mapping cho phép, giữ metadata occlusion/truncation; không dùng test-challenge không có nhãn. Phân phối chính thức chỉ được xác minh ở cấp archive split, nên cần duyệt trước nếu phải kéo cả 1,51 GB train+val rồi mới lọc local.
- **Cảnh báo domain:** UAV/góc cao hữu ích cho small-object robustness nhưng khác camera CCTV cố định của bãi; chỉ auxiliary, không dùng để kết luận accuracy trên BAI-KIEM.

## 3. MIO-TCD Localization

**Bằng chứng chính thức.** [Trang challenge MIO-TCD](https://tcd.miovision.com/challenge/dataset.html) ghi 137.743 ảnh high-resolution trong localization, 11 nhãn và license CC BY-NC-SA 4.0. Trang cho thấy ảnh JPEG và cung cấp code load/save bbox, nhưng không hiển thị encoding annotation hoặc dung lượng archive.

- **Format:** ảnh JPEG được xác minh; encoding bbox và archive bytes là **UNKNOWN** cho đến khi kiểm tra loader/manifest chính thức mà không kéo dataset.
- **Mapping cho phép:** `Pedestrian -> person`, `Bicycle -> bicycle`, `Car -> car`, `Motorcycle -> motorcycle`, `Bus -> bus`, `Articulated truck|Single unit truck -> truck`.
- **Không map:** `Pickup truck`, `Work van`, `Motorized vehicle`, `Non-motorized vehicle`; nhãn quá rộng hoặc chồng canonical class. Đặc biệt `Articulated truck` không tự động trở thành `container_truck`.
- **Subset tối thiểu đề xuất:** 1.000–2.000 ảnh localization cân bằng sáu canonical class cho phép, ưu tiên object nhỏ/xa và hard negatives. **BLOCKED** cho đến khi biết archive size/cơ chế selective access; không tải toàn bộ 137.743 ảnh.
- **Cảnh báo domain:** traffic camera Canada/Mỹ, không có bằng chứng về yard equipment hoặc static container; license NC/SA cần review pháp lý nếu sản phẩm thương mại.

## 4. Forklift Public Domain — Roboflow v1

**Bằng chứng chính thức.** [Trang project](https://universe.roboflow.com/forklift-4ulnu/forklift-uo0vm) khai báo Public Domain, 6.375 ảnh và hai class `forklift`, `person`. [Version v1 được nêu trong yêu cầu](https://universe.roboflow.com/forklift-4ulnu/forklift-uo0vm/dataset/1) có 4.474 ảnh (3.132 train/896 val/446 test), không preprocess/augment và cho export YOLOv11 TXT+YAML, COCO JSON, Pascal VOC XML, TFRecord cùng các format khác. Dung lượng archive không được công bố.

- **Mapping cho phép:** `forklift -> forklift`, `person -> person`.
- **Subset tối thiểu đề xuất:** fork/filter 300–600 ảnh gốc không augment, gồm ít nhất 200 ảnh có forklift và 100 hard negatives/person gần xe; sau đó audit bbox, duplicate và leakage giữa split.
- **Cảnh báo domain:** tác giả không công bố mô tả/provenance. Nhãn Public Domain trên host chưa đủ để chứng minh chuỗi quyền của pixels. Download/fork có thể cần đăng nhập Roboflow; **BLOCKED chờ tài khoản/API key và duyệt của người dùng**, không thực hiện ở lần sàng lọc này.

## 5. TIR Project — Roboflow

**Bằng chứng chính thức.** [Trang project TIR](https://universe.roboflow.com/iheb/tir_project) khai báo CC BY 4.0, 47.318 ảnh và ba class `forklift`, `insan`, `Tir`. Trang báo bốn dataset version nhưng version v4 không truy cập được trong lần kiểm tra; dung lượng archive, split và preprocessing của v4 là **UNKNOWN**.

- **Mapping cho phép:** `forklift -> forklift`; `insan -> person` chỉ sau khi audit xác nhận mỗi bbox là một người (tên class tiếng Thổ Nhĩ Kỳ nghĩa là người nhưng ontology/bbox chưa được mô tả).
- **Mapping bị chặn:** `Tir -> truck|container_truck` là **BLOCKED**. Tên không chứng minh xe tải chung hay đầu kéo/chở container; tuyệt đối không gán `container_truck` chỉ từ chuỗi `Tir`.
- **Format:** object detection trên Roboflow được xác minh ở cấp project; format export cụ thể của version v4 là **UNKNOWN** vì trang version không truy cập được.
- **Subset tối thiểu đề xuất:** sau khi fork/filter bằng tài khoản được duyệt, lấy 300–500 ảnh `forklift` và tối đa 300 ảnh `insan`; không lấy `Tir` trước khi audit 100 bbox ngẫu nhiên và chốt ontology.
- **Cảnh báo domain:** project cộng đồng không công bố nguồn ảnh, camera, bbox policy hoặc duplicate policy. Quy mô lớn không thay thế audit.

## 6. NRMM — Roboflow

**Bằng chứng chính thức.** [Trang NRMM](https://universe.roboflow.com/nrmm-project/nrmm-gzju4) khai báo Public Domain, 4.028 ảnh và 14 class, trong đó có `Reach Stacker` và `Mobile Crane`. Trang không mô tả nguồn ảnh/viewpoint, archive bytes hoặc format export của dataset.

- **Mapping cho phép:** `Reach Stacker -> reach_stacker`; `Mobile Crane -> mobile_crane`.
- **Không map:** `Container Crane` không phải `shipping_container`; `Straddle Carrier` không phải `forklift`; các class máy công trình còn lại không thuộc taxonomy hiện tại. Không ép `Dump Truck` thành `container_truck`.
- **Subset tối thiểu đề xuất:** 200–400 ảnh chứa hai class liên quan, tối thiểu 100 instance/class nếu dữ liệu có đủ; thêm 100 hard negatives `Container Crane`/`Straddle Carrier` để đo confusion. Chỉ tải sau khi xem được distribution và audit bbox/provenance.
- **Cảnh báo domain:** domain fit là **UNKNOWN** vì publisher không mô tả nguồn/viewpoint. Danh sách class tương tự thiết bị overhead không đủ để kết luận ảnh là CCTV yard. Download/fork có thể cần tài khoản/API key và đang **BLOCKED chờ duyệt**.

## 7. xView

**Bằng chứng.** Site challenge gốc được nêu trong yêu cầu không trả nội dung trong lần kiểm tra. [Tài liệu xView chính thức của Ultralytics](https://docs.ultralytics.com/datasets/detect/xview/) ghi CC BY-NC-SA 4.0, download thủ công khoảng 20,7 GB, 847 TIF train có nhãn + 282 TIF val không public label, bbox GeoJSON, hơn 1 triệu object/60 class. [Baseline chính thức của DIUx](https://github.com/DIUx-xView/xView1_baseline) xác nhận taxonomy có `Reach stacker`, `Mobile crane`, `Truck`, `Truck Tractor`, `Shipping container` và nhiều class gần nghĩa; license Apache-2.0 của repo chỉ áp dụng cho code, không được dùng thay license data.

- **License:** **PARTIAL/BLOCKED** cho commercial use cho đến khi lưu được điều khoản từ publisher/challenge gốc; tài liệu Ultralytics ghi NC/SA nên mặc định coi là non-commercial.
- **Mapping cho phép:** `Reach stacker -> reach_stacker`, `Mobile crane -> mobile_crane`, `Shipping container -> shipping_container`, `Truck -> truck`.
- **Không map:** `Truck Tractor`, các biến thể tractor+trailer và `Cargo Truck` không tự động thành `container_truck`; `Container Crane`, `Container Ship`, `Shipping container lot` không phải `shipping_container`.
- **Subset tối thiểu đề xuất:** không tải val không nhãn. Nếu được duyệt download thủ công, chỉ lấy `train_images.zip` + train labels (khoảng 15 GB theo tài liệu), sau đó local crop/tile 100–300 instance cho mỗi class liên quan và lấy hard negatives gần nghĩa. Phân phối gốc không có endpoint subset được xác minh, nên hiện tại **không tải**.
- **Cảnh báo domain:** vệ tinh top-down 0,3 m GSD khác hoàn toàn CCTV yard. Chỉ auxiliary để warm-start hình dáng nhỏ/top-down; không dùng làm domain validation, không trộn với golden BAI-KIEM và không tuyên bố domain match.

## Gate trước mọi download/training

1. Người dùng duyệt dataset, version, dung lượng tải tối đa và mọi tài khoản/API key cần dùng.
2. Dataset manifest phải ghi URL/version, ngày truy cập, license text/link, attribution/citation, checksum archive, mapping class và các class bị loại.
3. Chạy audit bbox, source provenance, duplicate/near-duplicate, split leakage, class balance, edge-touch và kích thước bbox trước khi train.
4. Roboflow/community data không được dùng nếu provenance hoặc quyền redistribution vẫn UNKNOWN.
5. External data chỉ warm-start/augment; mọi PR curve, threshold và acceptance metric phải tính trên golden validation/test BAI-KIEM local.

## Ưu tiên nếu được duyệt sau này

1. **Forklift v1 subset** cho `forklift`, vì mapping trực tiếp và dataset version nhỏ hơn các lựa chọn khác; vẫn cần provenance/bbox audit.
2. **NRMM subset** cho `reach_stacker`/`mobile_crane`, chỉ khi audit chứng minh viewpoint hữu ích.
3. **BMD-45 hoặc MIO-TCD subset** cho class COCO xe để tăng đa dạng CCTV; không dùng để tạo custom semantic class.
4. **VisDrone/xView** chỉ auxiliary cho small/top-down sau khi license được gỡ chặn; không ưu tiên trước dữ liệu BAI-KIEM local.
