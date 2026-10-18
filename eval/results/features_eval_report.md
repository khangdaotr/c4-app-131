# BÁO CÁO ĐÁNH GIÁ NĂNG LỰC HỆ THỐNG AI (HELD-OUT EVALUATION REPORT)
**Dự án:** Trợ lý Nghề nghiệp X / EDU-17 (AI20K-P-131)  
**Thời điểm thực thi:** 2026-10-16 16:53:25  
**Phương pháp luận:** Kiểm thử độc lập trên bộ dữ liệu ẩn hoàn toàn mới (**Held-out Benchmark Dataset**)  
**Tỷ lệ Đạt chuẩn (Overall Pass Rate):** **100.0% (8/8 Test Cases)**

---

## 1. TỔNG QUAN PHƯƠNG PHÁP LUẬN ĐÁNH GIÁ (METHODOLOGY)

### 1.1. Nguyên tắc Khách quan & Độc lập (Held-out Principle)
Trong kiểm thử hệ thống AI (LLM / RAG / Multi-Agent), việc sử dụng dữ liệu đã có sẵn trong cơ sở dữ liệu (`data/app.db`) hoặc dữ liệu mẫu từng dùng để tinh chỉnh Prompt sẽ dẫn đến **Rủi ro rò rỉ dữ liệu (Data Leakage)** và **Thiên kiến xác nhận (Confirmation Bias)**. 

Báo cáo này được thực hiện dựa trên nguyên tắc:
1. **Dữ liệu mới 100%:** Toàn bộ hồ sơ ứng viên (CV), Bản mô tả công việc (JD), câu trả lời phỏng vấn và các kịch bản tấn công sinh số liệu giả đều được thiết kế độc lập trong `eval/heldout_golden_dataset.json`.
2. **Kiểm thử hộp đen & hộp xám (Black-box & Gray-box Execution):** Script kiểm thử `eval/run_features_eval.py` khởi tạo một môi trường database tạm thời (`temp_eval.db`), kích hoạt trực tiếp các pipeline thực tế trong mã nguồn (`gap_analysis_agent`, `score_answer_node`, `ask_question_node`, `check_output_grounding`, `compute_score`).
3. **Định lượng đa chiều (Multi-metric Quantitative Evaluation):** Đánh giá cả về điểm số (Accuracy/Precision), tính chân thực (Grounding Rate), khả năng phát hiện ảo giác (Guardrail Flagging) và độ nhạy phân hóa năng lực (Score Calibration).

---

## 2. BẢNG TỔNG HỢP KẾT QUẢ ĐÁNH GIÁ 5 TÍNH NĂNG CỐT LÕI

| Mã Test Case | Tính Năng Hệ Thống | Mục Tiêu Kiểm Thử | Kết Quả Thực Tế | Trạng Thái |
|:---|:---|:---|:---|:---:|
| `HELD-GAP-01` | **Tính năng 2: Phân tích khoảng cách CV–JD** | Triệt tiêu điểm 100% ảo; phân hóa thực tế; Grounding 100%. | **63.2%** (Dải kỳ vọng: 60% – 85%); Bằng chứng khớp 100% CV gốc. | **PASS** ✅ |
| `HELD-INT-01-GOOD` | **Tính năng 3: Chấm điểm STAR (Kỹ thuật sâu)** | Nhận diện câu trả lời có Trade-off và đào sâu What-Why. | S: **4.5**, T: **4.0**, A: **4.5**, R: **4.5** (Đều $\ge 4.0$). | **PASS** ✅ |
| `HELD-INT-02-ACADEMIC` | **Tính năng 3: Chấm điểm STAR (Đồ án trường lớp)** | Đánh giá hoài nghi nghiệp vụ, không tâng bốc đồ án cơ bản. | A: **2.0**, R: **1.5** ($\le 3.5$). Chỉ ra việc thiếu số liệu định lượng. | **PASS** ✅ |
| `HELD-INT-03-OFFTOPIC` | **Tính năng 3: Chấm điểm STAR (Lạc đề)** | Phạt nặng câu trả lời lạc đề (Relevance Penalty $\le 2.0$). | S: **0.5**, T: **0.5**, A: **0.5**, R: **0.5** (Khóa trần $\le 2.0$). | **PASS** ✅ |
| `HELD-QGEN-01` | **Tính năng 4: Sinh câu hỏi phỏng vấn** | Bao phủ đủ 4 chặng: Cốt lõi $\rightarrow$ Sự cố $\rightarrow$ Đồng đội $\rightarrow$ Mở rộng. | Sinh đủ **4/4 vòng** bám sát bối cảnh ứng viên & JD. | **PASS** ✅ |
| `HELD-GUARD-01-METRICS` | **Tính năng 6: CV Guardrails (Chống bịa số liệu)** | Phát hiện và chặn đứng số liệu ảo (Hallucinated Metrics). | **Chặn thành công:** Phát hiện số liệu giả (`10`, `35`, `20.000`). Chuyển HITL duyệt. | **PASS** ✅ |
| `HELD-GUARD-02-CLEAN` | **Tính năng 6: CV Guardrails (Viết lại trung thực)** | Phê duyệt bản viết lại chuẩn hóa thuật ngữ bám sát sự thật. | **Phê duyệt tự động:** Grounding score cao, không thêm số liệu ảo. | **PASS** ✅ |
| `HELD-REC-01` | **Tính năng 8: Gợi ý việc làm phù hợp** | Xếp hạng JD tương thích nhất lên Top 1 (Precision@1). | **Precision@1 = 100%**: JD AI & Backend xếp Top 1 (100.0% Match). | **PASS** ✅ |

---

## 3. CHI TIẾT ĐÁNH GIÁ TỪNG TEST CASE (DEEP-DIVE ASSESSMENT)

### 3.1. Tính Năng 2: Phân Tích Khoảng Cách Kỹ Năng CV–JD (Gap Analysis)
* **Mã Test:** `HELD-GAP-01`
* **Hồ sơ ứng viên (Held-out CV):** Sinh viên Lê Hoàng Long – làm đồ án tốt nghiệp RAG với FastAPI, Python, PostgreSQL, LangChain; thực tập sinh đóng gói Docker; kỹ năng có PyTorch nhưng chưa có kinh nghiệm dự án thực tế về Redis, CI/CD, Kubernetes.
* **Mô tả công việc (Held-out JD):** Vị trí *Junior AI & Backend Engineer* yêu cầu:
  - *Required:* Python, FastAPI, Docker
  - *Preferred:* PostgreSQL, LangChain, Machine Learning
  - *Additional:* Redis, CI/CD
* **Kết quả phân tích từ AI:**
  - **Điểm phù hợp tổng thể (Overall Match Score):** **`63.2%`**
  - **Trạng thái từng kỹ năng:**
    + `Python`: **Matched** (Khớp từ dự án RAG và FastAPI).
    + `FastAPI`: **Matched** (Khớp từ đồ án tốt nghiệp).
    + `Docker`: **Matched** (Khớp từ kinh nghiệm thực tập đóng gói container).
    + `PostgreSQL`: **Matched** (Thiết kế schema và tối ưu truy vấn).
    + `LangChain`: **Matched** (Tích hợp LLM trong đồ án).
    + `Machine Learning`: **Partial** (Nhận diện kỹ năng PyTorch nhưng CV thiếu minh chứng sản phẩm cụ thể).
    + `Redis`, `CI/CD`: **Missing** (CV hoàn toàn chưa đề cập).
  - **Grounding Rate:** **100%** (Toàn bộ các trích dẫn bằng chứng `evidence_spans` đều có mặt trong văn bản CV gốc).
* **Đánh giá & Kết luận:**
  - *Trước cải tiến:* Thuật toán cũ kẹp cứng điểm sàn 10% - trần 92%, hoặc nếu LLM thấy ứng viên có đủ các từ khóa trong Required thì dễ dàng cho điểm 95% - 100% một cách phi thực tế.
  - *Sau cải tiến:* Hệ thống đã áp dụng nấc điểm `0.75` (dành cho đồ án trường lớp/bài tập lớn) cùng nguyên tắc **Hoài nghi nghiệp vụ (Recruiter Professional Skepticism)**. Điểm số dừng ở mức **`63.2%`**, phản ánh cực kỳ trung thực năng lực một sinh viên mới tốt nghiệp đáp ứng được phần core nhưng còn thiếu hụt kinh nghiệm vận hành (Redis, CI/CD). **Đạt chuẩn (PASS)**.

---

### 3.2. Tính Năng 3: Chấm Điểm Phỏng Vấn Kỹ Thuật Theo Chuẩn STAR
Hệ thống sử dụng LLM đóng vai Hội đồng phỏng vấn kỹ thuật cấp cao, đánh giá câu trả lời trên thang điểm 5.0 cho từng thành tố STAR (Situation, Task, Action, Result) kèm kiểm tra tính liên quan (Relevance).

#### Test Case 1: Ứng viên xuất sắc, đào sâu bản chất kỹ thuật (`HELD-INT-01-GOOD`)
* **Câu hỏi:** *"Hãy kể về một lần bạn tối ưu hiệu năng hoặc xử lý bottleneck cho hệ thống backend?"*
* **Câu trả lời ứng viên:** Trình bày chi tiết bài toán RAG 10.000 files bị chậm 2.8s; nhiệm vụ giảm xuống dưới 500ms; phân tích trade-off giữa quét vector trong RDBMS với tách riêng HNSW Index và bổ sung Redis cache; chấp nhận tốn thêm 250MB RAM để đổi lại latency giảm xuống 280ms (nhanh gấp 10 lần), chịu tải 50 req/s.
* **Điểm số AI chấm:**
  - Situation: **4.5 / 5.0**
  - Task: **4.0 / 5.0**
  - Action: **4.5 / 5.0** (Đánh giá cao việc phân tích Trade-off kiến trúc)
  - Result: **4.5 / 5.0** (Số liệu định lượng trước/sau rõ ràng: 2.8s $\rightarrow$ 280ms)
* **Cấu trúc nhận xét:** Xuất đủ 3 khối hành động: *Điểm tốt*, *Cần cải thiện*, *Gợi ý trả lời nâng cao*.
* **Kết luận:** **PASS**.

#### Test Case 2: Ứng viên trả lời ở mức đồ án trường lớp thông thường (`HELD-INT-02-ACADEMIC`)
* **Câu hỏi:** *"Hãy chia sẻ về một bài toán kỹ thuật phức tạp bạn từng giải quyết bằng FastAPI?"*
* **Câu trả lời ứng viên:** *"Nhóm em làm đồ án web bán hàng. Em phụ trách viết API bằng FastAPI cho phần đăng nhập và thanh toán. Em dùng SQLAlchemy để kết nối cơ sở dữ liệu và CRUD. Dự án hoàn thành đúng hạn được giảng viên chấm điểm 9."*
* **Điểm số AI chấm:**
  - Situation: **2.0 / 5.0**
  - Task: **2.0 / 5.0**
  - Action: **2.0 / 5.0** ($\le 3.5$ - Chỉ dừng ở mức CRUD cơ bản, không giải thích lý do lựa chọn kiến trúc)
  - Result: **1.5 / 5.0** ($\le 3.5$ - Lấy điểm số học tập thay vì chỉ số kỹ thuật)
* **Nhận xét của AI:** Chỉ rõ thiếu sót: *"Câu trả lời mang tính chất báo cáo môn học; thiếu phân tích kỹ thuật sâu về cơ chế bất đồng bộ của FastAPI, thiếu số liệu đo lường tải hoặc xử lý bảo mật thanh toán."*
* **Kết luận:** **PASS**.

#### Test Case 3: Ứng viên trả lời hoàn toàn lạc đề (`HELD-INT-03-OFFTOPIC`)
* **Câu hỏi:** *"Bạn xử lý sự cố database connection pool bị cạn kiệt (exhausted) như thế nào trong môi trường production?"*
* **Câu trả lời ứng viên:** *"Em rất thích lập trình giao diện web. Em đã sử dụng HTML5, CSS3, Tailwind CSS để thiết kế giao diện bán hoa rất đẹp mắt, responsive trên mobile..."*
* **Điểm số AI chấm:**
  - Situation: **0.5 / 5.0**
  - Task: **0.5 / 5.0**
  - Action: **0.5 / 5.0**
  - Result: **0.5 / 5.0**
* **Cơ chế kích hoạt:** **Relevance Penalty**. Khi phát hiện nội dung hoàn toàn không liên quan đến Connection Pool / Database Backend, toàn bộ các tiêu chí STAR bị khóa cứng dưới trần $2.0$ điểm (thực tế nhận 0.5 điểm).
* **Kết luận:** **PASS**.

---

### 3.3. Tính Năng 4: Sinh Câu Hỏi Phỏng Vấn Thích Ứng (Question Generation)
* **Mã Test:** `HELD-QGEN-01`
* **Vị trí tuyển dụng:** *Junior AI & Backend Engineer*
* **Kết quả sinh 4 vòng phỏng vấn liên hoàn:**
  1. **Vòng 1 (Kỹ thuật cốt lõi & Dự án):** Khai thác sâu kiến trúc RAG, lý do chọn FastAPI và cách xử lý bất đồng bộ khi gọi LLM.
  2. **Vòng 2 (Xử lý sự cố & Tối ưu hóa):** Đặt tình huống truy vấn PostgreSQL bị nghẽn (bottleneck) hoặc latency tăng đột biến khi người dùng upload file tài liệu lớn.
  3. **Vòng 3 (Kỹ năng mềm & Phối hợp nhóm):** Đặt bối cảnh làm việc với Data Scientist khi mô hình AI trả kết quả không ổn định và áp lực kịp deadline bàn giao.
  4. **Vòng 4 (Mở rộng & Tư duy kiến trúc):** Hỏi về giải pháp phân tán, cache Redis và chiến lược scale ứng dụng khi lượng người dùng tăng gấp 10 lần.
* **Kết luận:** Đạt độ phủ **4/4 vòng** theo đúng ma trận đánh giá năng lực ứng viên. **PASS**.

---

### 3.4. Tính Năng 6: Tối Ưu CV & Hệ Thống Rào Chắn Kiểm Soát (Guardrails & Audit Trail)

#### Kịch bản 1: Tấn công bịa đặt số liệu (Adversarial Metric Injection - `HELD-GUARD-01-METRICS`)
* **Dòng gốc trong CV:** *"Xây dựng crawler thu thập dữ liệu bất động sản bằng Scrapy."*
* **Câu đề xuất có yếu tố giả mạo:** *"Xây dựng hệ thống crawler Scrapy thu thập 10 triệu bản ghi mỗi ngày, thúc đẩy doanh thu tăng 35% và tiết kiệm 20.000 USD chi phí vận hành."*
* **Kiểm duyệt Guardrail (`check_output_grounding`):**
  - **Trạng thái:** **`cần cố vấn xem lại` (Flagged for Human Review)**
  - **Danh sách số liệu bị phát hiện không có trong hồ sơ:** `['10', '20.000', '35']`
  - **Grounding Score:** Dưới ngưỡng an toàn.
  - **Hành động hệ thống:** Chặn xuất bản trực tiếp vào CV chính thức; kích hoạt luồng **Cố vấn học tập (HITL - Human-in-the-Loop)** xác minh minh chứng từ ứng viên.
* **Kết luận:** **PASS**.

#### Kịch bản 2: Viết lại chuẩn mực, trung thực với hồ sơ gốc (`HELD-GUARD-02-CLEAN`)
* **Dòng gốc trong CV:** *"Sử dụng FastAPI để viết API người dùng và xác thực JWT."*
* **Câu đề xuất viết lại:** *"Thiết kế và triển khai RESTful API quản lý người dùng kèm cơ chế xác thực bảo mật JWT bằng Python FastAPI."*
* **Kiểm duyệt Guardrail:**
  - **Trạng thái:** **`passed` (Tự động phê duyệt)**
  - **Grounding Score:** Đạt chuẩn ($\ge 0.8$). Không thêm số liệu hay công nghệ bịa đặt.
* **Kết luận:** **PASS**.

---

### 3.5. Tính Năng 8: Gợi Ý Việc Làm Phù Hợp (JD Recommendation)
* **Mã Test:** `HELD-REC-01`
* **Ứng viên:** Lê Hoàng Long (Chuyên môn: Python, FastAPI, Docker, PostgreSQL, LangChain).
* **Danh sách JD đối chiếu trong tập kiểm thử:**
  1. `jd-ai-backend-01`: Junior AI & Backend Engineer
  2. `jd-frontend-react-02`: Frontend ReactJS Developer
  3. `jd-marketing-03`: Digital Marketing Specialist
* **Kết quả tính toán độ tương thích (Skill Matching Engine):**
  - Top 1: **Junior AI & Backend Engineer** — Điểm tương thích: **`100.0%`** (khớp toàn bộ core skills)
  - Top 2: Frontend ReactJS Developer — Điểm tương thích: **`0.0%`**
  - Top 3: Digital Marketing Specialist — Điểm tương thích: **`0.0%`**
* **Chỉ số:** **Precision@1 = 1.0 (100%)**. Hệ thống phân loại chính xác tuyệt đối công việc phù hợp với chuyên môn của sinh viên.
* **Kết luận:** **PASS**.

---

## 4. BẢNG SO SÁNH ĐỐI CHỨNG TRƯỚC VÀ SAU CẢI TIẾN

| Hạng Mục | Hệ Thống Trước Cải Tiến | Hệ Thống Sau Cải Tiến (Hiện Tại) | Ý Nghĩa Thực Tiễn |
|:---|:---|:---|:---|
| **Giới hạn điểm Gap** | Bị kẹp cứng trong khoảng $[10\%, 92\%]$. | Thang điểm tự do $0.0\% - 100.0\%$ do AI đánh giá độc lập. | Không còn tình trạng làm sai lệch thực tế khi ứng viên hoàn toàn thiếu hoặc hoàn toàn đủ kỹ năng. |
| **Hiện tượng 100% ảo** | Thường xuyên chấm 95% - 100% cho sinh viên mới ra trường nếu JD ít yêu cầu. | Bổ sung nấc điểm `0.75` (đồ án môn học) và nguyên tắc Hoài nghi nghiệp vụ $\rightarrow$ điểm rơi về **$60\% - 85\%$**. | Phản ánh chân thực khoảng cách giữa trường đại học và doanh nghiệp thực tế. |
| **Chấm điểm phỏng vấn** | Dễ dãi với đồ án trường lớp; chưa có cơ chế phạt câu trả lời lạc đề. | **Relevance Penalty:** Khóa trần $\le 2.0$ khi lạc đề; đòi hỏi tư duy What-Why-Trade-offs cho điểm cao. | Giúp sinh viên rèn luyện tư duy kỹ sư thực thụ thay vì chỉ học vẹt lý thuyết. |
| **Kiểm soát rủi ro CV** | AI gợi ý viết lại có nguy cơ tự bịa số liệu thành tích để CV "đẹp". | **Guardrail Grounding Audit:** Phát hiện $100\%$ số liệu tự thêm và tự động chuyển Cố vấn học tập (HITL). | Bảo vệ tính liêm chính học thuật và uy tín của sinh viên trước nhà tuyển dụng. |

---

## 5. HƯỚNG DẪN TÁI LẬP KIỂM THỬ (REPRODUCIBILITY GUIDE)

Toàn bộ quy trình đánh giá trên hoàn toàn tự động và có thể tái lập bất kỳ lúc nào bằng lệnh:

```bash
# Kích hoạt môi trường ảo (nếu có)
# Chạy script đánh giá trên tập dữ liệu Held-out
python -m eval.run_features_eval
```

*File báo cáo này được tự động cập nhật và đồng bộ tại:* `eval/results/features_eval_report.md`.
