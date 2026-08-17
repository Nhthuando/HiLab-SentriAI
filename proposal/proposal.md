
SENTRIAI · CHƯƠNG TRÌNH THỰC TẬP HILAB
RFP — Bài tập Intern: Giám sát cổng & khu vực bằng camera AI
Phiên bản 1.0 · 17/08/2026 · Tài liệu nội bộ dành cho intern kỹ thuật
Sản phẩm mẫu	File giao diện Intern-LPR-Gate.dc.html — dùng làm đặc tả UI/UX chuẩn. Nhiệm vụ của intern là hiện thực hóa backend + AI thật cho giao diện này.
Công nghệ gợi ý	Tự chọn: YOLO / Supervision / OpenCV hoặc tương đương cho phát hiện; OCR biển số bất kỳ; LLM cho hỏi đáp. Không ràng buộc framework.
1. Mục tiêu
Xây dựng một ứng dụng giám sát camera thu nhỏ gồm 4 phần: Giám sát cổng, Giám sát khu vực, Cài đặt và Hỏi đáp AI. Ứng dụng nhận luồng video (hoặc video file giả lập camera), phát hiện sự kiện theo cấu hình zone, lưu sự kiện kèm video, và trả lời câu hỏi về các sự kiện đã lưu.

2. Phạm vi chức năng
2.1. Giám sát cổng (camera GATE-01 — 2 làn IN)
Chỉ nhận diện biển số (LPR) khi xe đi vào zone làn IN 1 / IN 2 — không cần phân loại xe được phép hay không tại cổng.
Hiển thị khung nhận diện + biển số + độ tin cậy trên khung hình trực tiếp.
Ghi sự kiện: thời gian, biển số, làn, ảnh cắt biển số.
2.2. Giám sát khu vực (camera BAI-KIEM — góc trên cao)
Phát hiện đối tượng trong các zone đa giác: loại xe (container, xe tải, xe nâng, xe cẩu, xe con, xe máy, xe đạp…) và người.
Mỗi zone có danh sách loại được phép / bị cấm (cấu hình trong Cài đặt). Đối tượng bị cấm đi vào zone → sinh cảnh báo vi phạm.
Ví dụ: xe nâng, xe container được vào bãi; xe hơi, xe máy, xe đạp, người không phận sự thì không.
2.3. Cài đặt
Gắn nhãn xe: danh sách biển số đã thu thập, đánh dấu từng xe là xe quen / xe lạ.
Vẽ zone: chọn camera (Bãi Kiểm, Cổng vào), vẽ zone đa giác trên khung hình thật: bấm thêm từng góc để vẽ, kéo đỉnh để sửa hình dạng, kéo điểm giữa cạnh để thêm góc, kéo thân để di chuyển. Zone lưu lại phải cập nhật ngay ở các màn giám sát.
Nhãn đối tượng: import hình hoặc video (chọn khung hình), vẽ ô bao quanh đối tượng trên hình, chọn loại (người / hình dáng xe), đặt tên nhãn và lưu mẫu. Sau khi lưu có thể import hình mới để gắn nhãn tiếp. Nhãn đã lưu xuất hiện trong danh sách chọn loại của mọi zone.
2.4. Hỏi đáp AI về sự kiện
Khung chat hỏi bằng ngôn ngữ tự nhiên về sự kiện đã lưu, ví dụ: "Hôm nay có bao nhiêu xe lạ vào?", "Có xe máy nào vào khu vực cấm không?".
Câu trả lời nêu số liệu + chi tiết sự kiện, và luôn kèm đoạn video 10 giây của sự kiện liên quan (camera nào, từ giây nào đến giây nào), có nút tải clip.
3. Yêu cầu kỹ thuật tối thiểu
Hạng mục	Yêu cầu
Nguồn video	RTSP hoặc video file giả lập; xử lý gần realtime (≥ 5 FPS).
Phát hiện & phân loại	Model phát hiện đối tượng + OCR biển số; kiểm tra tâm đối tượng nằm trong zone đa giác (point-in-polygon).
Lưu sự kiện	CSDL sự kiện (thời gian, camera, zone, loại đối tượng, biển số, trạng thái) + trích và lưu clip 10s quanh thời điểm sự kiện.
Hỏi đáp	LLM truy vấn trên CSDL sự kiện (text-to-SQL hoặc function calling); trả lời kèm tham chiếu clip.
Giao diện	Bám theo file mẫu Intern-LPR-Gate.dc.html (bố cục, luồng thao tác); công nghệ web tự chọn.
4. Sản phẩm bàn giao
Mã nguồn (repo Git) + hướng dẫn chạy (README, docker-compose nếu có).
Demo chạy được với 2 video mẫu (cổng + bãi kiểm).
Bộ nhãn đối tượng đã gắn (tối thiểu 5 nhãn, mỗi nhãn ≥ 20 mẫu).
Video demo 3–5 phút trình bày đủ 4 phần chức năng.
5. Thời gian & liên hệ
Thời gian thực hiện: 2 tuần kể từ ngày nhận đề.
Review: mỗi tuần 1 lần với mentor — demo tiến độ đến thời điểm đó.
Hỏi đáp về đề bài: qua kênh chat trực tiếp với mentor.
Lưu ý: Giao diện mẫu chỉ dùng dữ liệu giả lập — mọi số liệu, biển số, sự kiện trong đó là minh họa. Intern không cần sao chép giao diện từng pixel; quan trọng là đúng luồng nghiệp vụ: cấu hình → phát hiện → lưu sự kiện kèm clip → hỏi đáp có trích dẫn.
