# Weekly Journal — Team P-131

> Nhật ký quá trình nhóm xây dựng Trợ lý Nghề nghiệp X (CareerX/CareerV), tổng hợp theo lịch sử commit của repository. Nội dung ghi lại các mốc sản phẩm và bài học chung, không phân chia theo thành viên.

---

## Tuần 1: 14/09/2026–20/09/2026

### Đã làm gì?

- Xác định bài toán trọng tâm: sinh viên năm cuối và người mới đi làm cần hỗ trợ đánh giá CV theo vị trí ứng tuyển, luyện phỏng vấn và nhận phản hồi từ cố vấn.
- Soạn brief và PRD ban đầu, xác định persona, user story, phạm vi sản phẩm, nguồn tri thức dự kiến và các tiêu chí chấm CV–JD/phỏng vấn.
- Bổ sung nguyên tắc bảo vệ tính trung thực của CV, công bằng, giới hạn của AI và cách xử lý khi thiếu bằng chứng.
- Vẽ sơ đồ luồng dữ liệu và luồng giao diện để mô tả hành trình của sinh viên, cố vấn và quản trị viên; thiết lập cơ chế AI logging cho quá trình phát triển.

### Học được gì?

- Cần xác định người dùng, vấn đề và tiêu chí thành công trước khi quyết định cách triển khai kỹ thuật.
- Các gợi ý CV và điểm số chỉ có ý nghĩa khi có căn cứ; hệ thống cần phân biệt dữ liệu người dùng cung cấp với suy luận của AI.
- Luồng người dùng và sơ đồ dữ liệu giúp nhóm thống nhất cách các màn hình, API và dữ liệu cần phối hợp.

### Vướng gì?

- Phạm vi ban đầu rộng, gồm nhiều vai trò và chức năng nên cần ưu tiên luồng cốt lõi trước.
- Một số khái niệm như RAG, agent, rubric và guardrail còn mới; tài liệu sản phẩm cần được chuyển thành yêu cầu kỹ thuật cụ thể.
- Ở giai đoạn này, phần lớn nội dung là đặc tả và thiết kế; chưa thể xem các luồng AI là chức năng đã hoàn thiện.

### Dự định tuần sau

- Dựng các luồng backend cốt lõi cho hồ sơ CV, phân tích CV–JD và phỏng vấn.
- Bắt đầu giao diện Next.js để nhóm có thể kiểm tra hành trình sử dụng bằng sản phẩm chạy được.
- Tiếp tục đối chiếu phạm vi triển khai với PRD và ghi nhận rõ phần nào còn là thiết kế.

---

## Tuần 2: 21/09/2026–27/09/2026

### Đã làm gì?

- Bắt đầu triển khai các tác vụ đầu tiên của backend và cập nhật cách kết nối mô hình ngôn ngữ theo các commit ghi nhận hoàn thành T1/T2.
- Bổ sung các tác vụ backend tiếp theo và lớp guardrail để kiểm tra nội dung sinh ra.
- Khởi tạo frontend phiên bản đầu, tạo nền tảng để ghép các màn hình và API của sản phẩm.
- Chuẩn bị bước chuyển từ đặc tả sang MVP có thể phát triển và đánh giá theo từng luồng.

### Học được gì?

- Backend, giao diện và các quy tắc an toàn cần được phát triển cùng một hợp đồng dữ liệu; nếu không, các phần khó kết nối về sau.
- Guardrail cần được đưa vào luồng xử lý thay vì chỉ ghi trong tài liệu yêu cầu.
- Một MVP hữu ích cần có đường đi từ thao tác của người dùng tới API và kết quả trả về, thay vì chỉ có các màn hình rời rạc.

### Vướng gì?

- Commit ở giai đoạn đầu chỉ ghi tên tác vụ, chưa mô tả đầy đủ từng kết quả; cần tiếp tục xác minh bằng code và đánh giá chức năng.
- Kết nối giữa frontend mới khởi tạo và backend vẫn đang trong quá trình hình thành.
- Các chức năng AI cần dữ liệu và tiêu chí kiểm tra đủ rõ để tránh tạo kết quả có vẻ hợp lý nhưng thiếu căn cứ.

### Dự định tuần sau

- Kết nối frontend với API backend và hoàn thiện các màn hình sinh viên quan trọng.
- Làm rõ luồng lưu phiên bản CV, phân tích theo JD và luyện phỏng vấn.
- Bổ sung kiểm thử và tài liệu phản ánh đúng trạng thái thực tế của MVP.

---

## Tuần 3: 28/09/2026–04/10/2026

### Đã làm gì?

- Kết nối API backend với frontend trong MVP v1 và xây dựng giao diện sinh viên gồm dashboard, CV của tôi và quản lý phiên bản CV.
- Hoàn thiện dần các màn hình luyện phỏng vấn, phòng phỏng vấn và báo cáo; bổ sung lịch sử, chia sẻ kết quả với cố vấn và trang cài đặt.
- Xây dựng luồng phân tích CV–JD, trang kết quả phân tích và trình tối ưu CV; mở rộng giao diện cố vấn với dashboard và danh sách sinh viên.
- Bổ sung tài liệu quy trình xây dựng kho vector cho JD, bản đồ kiến trúc cấp cao, cây component frontend, bản đồ API, luồng agent, ERD và kiến trúc triển khai; cập nhật README.

### Học được gì?

- Sản phẩm cần được xây theo các hành trình xuyên suốt: tải CV, chọn JD, xem khoảng cách kỹ năng, cải thiện CV và luyện phỏng vấn.
- Mỗi luồng cần có trạng thái và dữ liệu nhất quán giữa giao diện, API và database.
- Sơ đồ kiến trúc và tài liệu API giúp việc tích hợp nhanh hơn, đồng thời làm lộ ra những phần chưa được triển khai thật.

### Vướng gì?

- Nhiều màn hình được bổ sung trong thời gian ngắn nên cần rà lại trải nghiệm, tính nhất quán nội dung và trạng thái dữ liệu.
- Các tuyên bố về chất lượng AI cần được kiểm chứng bằng input/output và bộ tiêu chí có thể lặp lại.
- Giao diện cố vấn phụ thuộc vào quyền chia sẻ và phân công sinh viên; đây là phần cần kiểm tra kỹ về quyền truy cập.

### Dự định tuần sau

- Đo lường riêng chất lượng gợi ý JD và ghi lại phương pháp cùng dữ liệu đánh giá.
- Bổ sung chatbot có thể trả lời dựa trên tài liệu hướng dẫn của sản phẩm.
- Kiểm tra các luồng chính và cập nhật tài liệu đánh giá trung thực với kết quả quan sát được.

---

## Tuần 4: 05/10/2026–11/10/2026

### Đã làm gì?

- Bổ sung luồng so sánh/xếp hạng nhiều JD và xây dựng bộ tình huống, kết quả đánh giá cho chức năng gợi ý việc làm.
- Cập nhật README, nhật ký và phạm vi báo cáo đánh giá; làm rõ cách phân loại kết quả và giới hạn của bằng chứng.
- Triển khai chatbot trợ lý với RAG và retrieval, sau đó bổ sung chat widget, bộ nhớ hội thoại và các hành động điều khiển giao diện có highlight.
- Mở rộng trợ lý backend với hybrid search, agent actions và evaluation suite; cập nhật cấu hình Docker và CORS để hỗ trợ môi trường triển khai.
- Bổ sung chức năng trích xuất kỹ năng và roadmap học tập từ kết quả phân tích CV–JD.

### Học được gì?

- Retrieval cần được đánh giá bằng dữ liệu và tiêu chí cụ thể; một điểm số tốt chỉ có ý nghĩa khi phương pháp tính và phạm vi thử nghiệm rõ ràng.
- Chatbot hướng dẫn cần kết hợp câu trả lời có nguồn với ngữ cảnh trang hiện tại; các thao tác thay đổi dữ liệu cần có bước xác nhận phù hợp.
- Ghi nhận cả trường hợp thất bại giúp phân biệt lỗi chất lượng câu trả lời với lỗi chạy hệ thống và xác định việc cần làm tiếp theo.

### Vướng gì?

- Bằng chứng đánh giá các tính năng khác nhau không thể gộp thành một chỉ số chất lượng chung.
- Trợ lý có nhiều lớp (tài liệu, retrieval, API, widget, action dispatcher), nên cần kiểm tra tích hợp toàn luồng.
- Việc triển khai lên môi trường thật kéo theo yêu cầu cấu hình cổng, CORS, biến môi trường và đồng bộ dữ liệu chỉ mục.

### Dự định tuần sau

- Kiểm tra lại các luồng assistant và JD recommendation trên phiên bản tích hợp.
- Hoàn thiện giao diện và trải nghiệm cho sinh viên, cố vấn và quản trị viên.
- Bổ sung tài khoản thật, các chức năng hồ sơ và thông báo, đồng thời kiểm tra luồng đăng nhập.

---

## Tuần 5: 12/10/2026–18/10/2026

### Đã làm gì?

- Cập nhật giao diện sinh viên và bổ sung các màn hình cố vấn, landing page, trang xác thực và trường thông tin hồ sơ cá nhân.
- Mở rộng xử lý CV bằng OCR; bổ sung nhập câu trả lời phỏng vấn bằng giọng nói và bản chép lời trực tiếp, cùng cấu hình voice và các điều chỉnh liên quan.
- Bổ sung tài khoản thật, thông báo, API cài đặt, đăng nhập demo, tìm kiếm nhanh bằng Ctrl+K và vai trò quản trị viên; mở rộng thư viện JD có cấu trúc, đánh giá/rating, gợi ý và so sánh JD.
- Làm mới nhận diện sản phẩm, giao diện trợ lý, chế độ tối và sidebar; bổ sung lịch sử so sánh, liên kết roadmap, trình xem CV trong ứng dụng và xuất CV theo mẫu Harvard.
- Cập nhật luồng tối ưu CV và phỏng vấn: gợi ý câu CV, chọn ngày sinh, câu hỏi ngắn hơn, phản hồi theo ba phần và mẹo cải thiện câu trả lời.
- Sửa các vấn đề tích hợp và triển khai, gồm OCR/LLM, chấm điểm gợi ý trên thư viện JD, chỉ mục tài liệu assistant, email đặt lại mật khẩu, đăng xuất và cấu hình triển khai frontend.

### Học được gì?

- Sản phẩm phát triển từ một công cụ hỗ trợ CV và phỏng vấn thành một ứng dụng có nhiều vai trò, tài khoản, thư viện JD, trợ lý hướng dẫn và nhiều cách nhập liệu.
- Các tính năng OCR và giọng nói mở rộng cách người dùng tương tác, nhưng cần kiểm tra độ chính xác của dữ liệu trích xuất trước khi dùng cho phân tích hoặc chấm điểm.
- Sau mỗi lần mở rộng, chất lượng phụ thuộc nhiều vào tích hợp và dữ liệu xuyên suốt; sửa riêng một màn hình chưa đủ để xác nhận luồng hoàn chỉnh.

### Vướng gì?

- Nhiều tính năng mới được phát triển gần nhau; cần tiếp tục kiểm tra hồi quy và độ ổn định trên các luồng đăng nhập, tải CV, phân tích, phỏng vấn và chia sẻ.
- Các kết quả AI về kỹ năng thiếu, điểm phù hợp và nội dung CV cần được trình bày có căn cứ, đồng thời để người dùng kiểm soát quyết định cuối cùng.
- Báo cáo đánh giá trong repository có phạm vi và thời điểm khác nhau; cần gắn mỗi kết luận với đúng phiên bản, dữ liệu và phương pháp.

### Dự định tuần sau

- Kiểm tra xuyên suốt các hành trình sinh viên và cố vấn trên bản triển khai hiện tại.
- Đối chiếu tài liệu giới thiệu, số liệu đánh giá và chức năng thực tế; cập nhật những nội dung chưa khớp.
- Ưu tiên sửa lỗi tích hợp, kiểm tra quyền truy cập và xác nhận độ tin cậy của OCR, giọng nói cùng các gợi ý AI.

---

## Mẫu ghi cho các tuần tiếp theo

### Đã làm gì?

- [Ghi 2–4 việc thực sự đã làm trong tuần, dựa trên thay đổi sản phẩm hoặc bằng chứng cụ thể.]

### Học được gì?

- [Ghi điều nhóm hiểu thêm trong quá trình xây dựng và kiểm tra sản phẩm.]

### Vướng gì?

- [Ghi khó khăn thực tế và phần chưa được xác minh hoặc giải quyết.]

### Dự định tuần sau

- [Ghi 2–4 việc cụ thể, vừa sức và có thể kiểm tra được.]
