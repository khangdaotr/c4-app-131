---
route: /student/interview
role: student
title: "Hướng dẫn phỏng vấn thử theo STAR"
tags: [interview, mock-interview, star, questions, feedback]
---

# Hướng dẫn phỏng vấn thử theo STAR

## Tổng quan

Phỏng vấn thử giúp sinh viên luyện trả lời theo bối cảnh CV và vị trí ứng tuyển. AI hỏi **4 câu** và chấm theo khung **STAR**: **Situation** (Bối cảnh), **Task** (Nhiệm vụ), **Action** (Hành động bạn thực hiện), **Result** (Kết quả). Báo cáo cho biết điểm từng phần và hướng dẫn cải thiện.

Route `/student/interview` trong frontmatter theo hợp đồng Assistant. Giao diện thiết lập buổi tại `/student/interview/new`, phòng chờ tại `/student/interview/start`, buổi phỏng vấn tại `/student/interview/{id}` và báo cáo tại `/student/interview/{id}/report`.

## Các bước thực hiện

1. Chuẩn bị CV và mở `/student/interview/new` (mục **Luyện phỏng vấn** trên thanh bên). Bấm **Hướng dẫn** nếu muốn xem lại cách luyện.
2. Kiểm tra số lượt còn lại, ví dụ **Còn 2 / 3 buổi tuần này**. Mỗi vị trí có giới hạn số buổi mỗi tuần.
3. Ở **Chọn CV**, chọn CV dùng làm bối cảnh, hoặc chọn **Không dùng CV** để AI chỉ hỏi theo yêu cầu của vị trí (dùng được cả khi chưa tải CV). Ở **Chọn vị trí**, chọn một vị trí trong **Gợi ý & đã lưu** hoặc **Đã phân tích**; bấm **Tìm trong Thư viện JD** nếu chưa thấy.
4. Kiểm tra khung **Buổi phỏng vấn của bạn** (vị trí, CV, 4 câu · khoảng 20 phút, chấm theo STAR thang 5), rồi bấm **Vào phòng chờ**.
5. Trong phòng chờ, đọc luật và chờ mục **Chuẩn bị giọng nói trên thiết bị** tải, lưu và khởi động PhoWhisper của VinAI. Thanh tiến độ cho biết số MB và phần trăm đã chuẩn bị; những lần sau dùng bản đã lưu nếu trình duyệt còn giữ bộ nhớ đệm. Khi giọng nói sẵn sàng, bấm **Sẵn sàng**. Nếu không muốn dùng micro hoặc thiết bị không hỗ trợ, chọn **Tiếp tục bằng cách gõ**. Buổi phỏng vấn chỉ được tạo và tính giờ khi bạn bấm Sẵn sàng.
6. Với mỗi câu, xác định tình huống và nhiệm vụ cần kể, nêu hành động của chính bạn và kết quả cụ thể. Có thể gõ câu trả lời hoặc bấm **Nói câu trả lời** để nói bằng tiếng Việt (có thể xen thuật ngữ tiếng Anh). PhoWhisper nhận diện ngay trên thiết bị, không gửi âm thanh lên máy chủ; chữ nháp cập nhật trong lúc nói. Nói xong bấm **Dừng nói**, chờ nhận diện nốt rồi sửa chữ nếu cần. Mỗi lần ghi tối đa khoảng 5 phút. Nếu thiết bị xử lý chậm, chọn **Giữ chữ hiện có và gõ tiếp**. Bấm **Gửi câu trả lời**; ở câu cuối, nút là **Gửi và kết thúc**. Có thể bấm **Kết thúc sớm**, nhưng buổi kết thúc sớm không được lưu.
7. Mở báo cáo để xem **Điểm buổi phỏng vấn** (thang **0–5**), điểm từng phần S, T, A, R, **Hướng dẫn cải thiện** và **Chi tiết từng câu**. Từ báo cáo có thể bấm **Chia sẻ với cố vấn** hoặc **Luyện lại vị trí này**.
8. Xem lại các buổi tại `/student/history` hoặc mục **Buổi gần đây** trên trang Luyện phỏng vấn.

## Các nút và thành phần giao diện

Các selector dưới đây đã được gắn vào trang thiết lập phỏng vấn.

- **Nút "Vào phòng chờ"**: Selector `[data-agent-target="btn-start-interview"]`. Mở phòng chờ với CV và vị trí đã chọn; bấm **Sẵn sàng** trong phòng chờ mới tạo buổi. Nút không khả dụng khi thiếu thông tin hoặc hết lượt.
- **Danh sách chọn vị trí**: Selector `[data-agent-target="select-jd"]`. Chọn vị trí sẽ được hỏi.
- **Ô chọn CV**: Selector `[data-agent-target="select-cv"]`. Chọn CV dùng làm bối cảnh cho câu hỏi.

## Đánh giá buổi phỏng vấn

Cuối báo cáo có câu hỏi **Bạn thấy buổi luyện phỏng vấn này thế nào?**. Bấm **Đánh giá buổi này** để chọn số sao, lý do (khi chấm 1–3 sao) và viết góp ý nếu muốn. Ở từng câu trong **Chi tiết từng câu** có nút thích/không thích cho nhận xét của AI; bấm lại để huỷ nếu bấm nhầm.

## Câu hỏi thường gặp (FAQ)

**Q: STAR khác kể chuyện thông thường ở đâu?**

A: STAR giúp câu trả lời có bối cảnh, nhiệm vụ, hành động cá nhân và kết quả. Hãy làm rõ bạn đóng góp gì thay vì chỉ kể việc của cả nhóm.

**Q: Vì sao không bắt đầu được buổi phỏng vấn?**

A: Kiểm tra đã chọn CV và vị trí. Nếu hết lượt trong tuần cho vị trí này, xem ngày làm mới trên trang hoặc chọn vị trí khác.

**Q: Điểm STAR có cùng thang với Match Score không?**

A: Không. STAR dùng thang 0–5 để đánh giá câu trả lời; Match Score dùng 0–100% để đánh giá mức phù hợp CV với JD.

**Q: Hệ thống có viết sẵn câu trả lời cho tôi không?**

A: Không. Hệ thống chỉ gợi ý cách trình bày; hãy trả lời bằng trải nghiệm thật của bạn.

**Q: Tôi tìm báo cáo cũ ở đâu?**

A: Vào `/student/history`, chọn bộ lọc **Phỏng vấn** và bấm **Báo cáo** ở buổi cần xem. So sánh các buổi cùng vị trí để thấy tiến bộ rõ hơn.
