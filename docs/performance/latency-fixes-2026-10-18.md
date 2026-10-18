# Sửa latency backend — 18/10/2026

## Thay đổi

- **JD recommend:** giữ một lần `recommend_top_jds_from_cv`, có truyền điểm phân tích đã lưu; tư vấn được gọi một lần khi `generate_advice=true`. Toàn bộ thao tác nằm trong privacy scope của người dùng.
- **Chat stream:** sự kiện token chỉ cập nhật bộ đệm và hàng đợi SSE. Nội dung thay đổi được checkpoint theo `ASSISTANT_STREAM_CHECKPOINT_SECONDS` (mặc định `0.5` giây). Khi hoàn tất, huỷ hoặc lỗi, phần nội dung đã lọc được lưu lại. Lỗi SQLite tạm thời tại checkpoint được ghi log không chứa SQL/nội dung riêng tư, rồi thử lại ở nhịp sau. Phần cuối của output guard vẫn chịu giới hạn 16.000 ký tự.
- **Retriever:** tái sử dụng Chroma client, corpus và BM25 theo cấu hình và revision của file corpus. Reindex xoá cache trước khi thay collection; việc thay collection và truy vấn dùng chung lock. Reindex thất bại sau bước này cũng không giữ lại handle cũ. Cache giới hạn một cấu hình index trong mỗi process.
- **HTTP cache:** middleware giữ `Cache-Control` do endpoint đặt, ví dụ ảnh CV `private, max-age=3600`; response API thông thường vẫn mặc định `no-store`, SSE vẫn `no-cache`.

Lock hiện có vẫn bao quanh retrieval, gồm bước che PII dùng model NER chung. Các thao tác SQLite checkpoint vẫn là ORM đồng bộ với tần suất thấp hơn. Những thay đổi này không loại bỏ mọi nguyên nhân có thể chặn event loop trong backend.

## Kiểm thử

15 ca hồi quy mới đã chạy qua:

- Recommend bằng CV đã lưu hoặc văn bản, bật/tắt tư vấn; mỗi request chỉ chạy recommend một lần; từ chối CV của người khác trước khi thực hiện công việc.
- Burst 1.000 sự kiện token từ event loop hoặc thread chỉ tạo một commit trong phần stream được kiểm tra, đồng thời giữ nguyên toàn bộ nội dung.
- Checkpoint khi producer đang chờ; lưu phần trả lời khi lỗi; phục hồi sau một lần ghi SQLite thất bại; xử lý phần cuối output guard và giới hạn độ dài.
- Tái sử dụng cùng retriever/BM25; cập nhật sau reindex, thay file corpus hoặc cấu hình; bỏ handle cache sau reindex thất bại.

Các test có sẵn cũng kiểm tra huỷ stream, mất kết nối ASGI, lịch sử, privacy guard và SSE framing. Test API recommend dùng Chroma thật trong thư mục tạm với embedding xác định, được seed rõ ràng từ fixture để tránh phụ thuộc `data/chroma` hoặc tải model.

Kết quả các lượt kiểm tra (có test được chạy lại giữa các lượt):

| Phạm vi | Kết quả |
| --- | --- |
| Runs, stream, RAG, CV và auth — lượt rộng ban đầu | 168 passed, 3 failed; dừng sau 3 lỗi |
| Stream, how-to và các nhóm liên quan — lượt bổ sung | 58 passed, 3 failed; dừng sau 3 lỗi |
| Các ca tập trung, privacy, API và auth | 42 passed, 6 failed |
| 5 API recommend với fixture Chroma độc lập | 5 passed |
| Ảnh PDF thật, cache header và DOCX preview sau khi bổ sung dependency | 1 passed |
| Checkpoint bình thường và lỗi SQLite tạm thời | 2 passed |

Venv ban đầu thiếu `pypdfium2`, khiến test preview trả về kiểu `document` thay vì `pages`. Đã cài `pypdfium2 5.14.0`, phù hợp `requirements.txt` (`>=5.13.0`), rồi chạy lại thành công test ảnh PDF và header cache.

`ruff check src tests`, kiểm tra format các file thay đổi và `git diff --check` đã qua.

## Các lỗi còn thấy trong kiểm tra mở rộng

Các ca sau vẫn thất bại với hành vi hiện tại của repo; không thay kỳ vọng của chúng trong bản sửa latency:

| Test / nhóm | Kết quả thực tế |
| --- | --- |
| `test_unrelated_question_is_refused_without_sources` — câu hỏi tốc độ ánh sáng | Router trả fallback `result`, test đợi câu từ chối có chữ `CareerV` |
| `test_chat_persists_navigation_stub_without_actions` | Có UI action điều hướng `analysis_new`, test đợi danh sách rỗng |
| `test_retrieval_matches_frozen_prechange_baseline` | Chunk IDs của corpus hiện tại khác snapshot |
| `test_recorded_howto_cache_hit_skips_model_and_rebuilds_actions` | Model thực tế là `deepseek-v4.1-flash`, test đợi `deepseek-flash` |
| `test_out_of_corpus_abstention_precision_and_retrieval_regression[hashing]` | Chunk IDs khác cùng snapshot trên |
| `test_header_cannot_authenticate[student/advisor/admin]` — 3 ca | Fixture chung bật demo login; header demo được chấp nhận |
| `test_login_ignores_role_header_and_logout_revokes_cookie` | Test đọc `id` ở root, API trả thông tin người dùng trong `profile` |
| `test_login_rotates_existing_session` | Cookie của session cũ vẫn truy cập được `/me` sau lần đăng nhập mới |

Đã tái lập hai lỗi RAG và ba lỗi how-to bằng cách thay riêng `_retrieve` trong bộ test bằng implementation từ `HEAD`, không sửa file nguồn trong workspace. Đây là phép đối chiếu trực tiếp cho phần tối ưu retrieval; không phải chạy trên một checkout sạch khác.

Đã tái lập cả 5 lỗi auth khi thay thêm `OriginProtectionMiddleware.dispatch` bằng implementation từ `HEAD`: 5 failed, 1 passed. Vì vậy các lỗi auth này cũng tồn tại khi dùng chính sách middleware trước bản sửa cache.

Các test dùng dữ liệu tạm, hashing/embedding xác định và provider ghi sẵn hoặc fallback. Đánh giá E5 yêu cầu opt-in và weights đã cache được bỏ qua. Chưa đo latency theo giây trên môi trường deploy hoặc gọi LLM thật để benchmark.
