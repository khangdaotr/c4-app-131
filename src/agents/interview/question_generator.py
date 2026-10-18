"""
Sinh câu hỏi phỏng vấn thử theo phương pháp STAR (US-SV-04).
Hoàn toàn sử dụng LLM để đọc và phân tích nội dung chi tiết của CV (kể cả văn bản sau OCR)
và Mô tả công việc (JD), sau đó tự động sinh ra 4 câu hỏi tình huống thực chiến.
Tuyệt đối không dùng câu hỏi văn mẫu hay khuôn mẫu cố định.

Câu hỏi ngắn gọn như người phỏng vấn thật nói (1–2 câu); không nhắc khung STAR, không liệt kê sẵn ý trả lời
(gợi ý STAR đã có ở cột bên phải màn hình phỏng vấn, gợi ý cụ thể nằm trong nhận xét sau khi chấm).
"""

import asyncio
import json
import logging
import re

from src.config import get_settings
from src.services.providers.gateway import provider_scope

logger = logging.getLogger(__name__)

THEMES = [
    "Nhiệm vụ & Kinh nghiệm tiêu biểu",
    "Xử lý khó khăn & Thử thách kỹ thuật",
    "Làm việc nhóm & Phối hợp",
    "Học hỏi & Định hướng phát triển",
]

# Câu hỏi quá dài hoặc tự gợi ý khung STAR thì yêu cầu AI viết lại một lần
MAX_QUESTION_CHARS = 240
_STAR_WORDS = re.compile(r"\b(situation|task|action|result|STAR)\b", re.IGNORECASE)
_MARKDOWN = re.compile(r"\*\*|__|`")

STYLE_RULES = f"""YÊU CẦU VỀ CÁCH HỎI (BẮT BUỘC):
- Mỗi câu hỏi NGẮN như người phỏng vấn thật nói: 1–2 câu, tối đa khoảng 35 từ (dưới {MAX_QUESTION_CHARS} ký tự), hỏi MỘT ý chính.
- KHÔNG nhắc các chữ Situation, Task, Action, Result, STAR hay "bối cảnh – nhiệm vụ – hành động – kết quả"; ứng viên đã có hướng dẫn riêng.
- KHÔNG liệt kê sẵn ý trả lời, công cụ hay các bước trong ngoặc; KHÔNG tự đặt chỉ tiêu số (ví dụ "giảm từ 800ms xuống 120ms", "độ phủ test > 90%").
- KHÔNG khẳng định chi tiết mà CV không có (sự cố, con số, khách hàng...); muốn hỏi tình huống chưa có trong CV thì hỏi "Nếu…" hoặc "Bạn sẽ…".
- Văn nói tự nhiên, xưng "bạn"; viết hoa chữ đầu câu và giữ đúng cách viết tên dự án/công cụ như trong CV; văn bản thuần, không markdown (không **, không `).
- Mỗi câu hỏi khác nhau, không lặp lại cùng một dự án ở cả 4 câu."""

GOOD_EXAMPLES = """VÍ DỤ ĐỘ DÀI ĐÚNG (chỉ tham khảo cách hỏi, không chép):
- "Trong dự án Maintenance Management Platform, phần nào bạn trực tiếp làm và khó nhất ở đâu?"
- "Kể về một lần API bạn viết chạy chậm hoặc lỗi trên môi trường thật. Bạn tìm ra nguyên nhân thế nào?"
- "Nếu QA báo lỗi nghiêm trọng ngay trước hạn phát hành, bạn sẽ trao đổi với nhóm ra sao?"
"""


async def _invoke_llm_for_questions(prompt: str, timeout: float = 25.0) -> list[dict[str, str]]:
    """Gọi LLM với cơ chế tự động chuyển model dự phòng nếu model chính bị quá tải (rate limit)."""
    settings = get_settings()
    api_key, _ = settings.get_llm_credentials()

    is_placeholder = any(
        api_key.startswith(p) for p in ["your-", "sk-dummy", "gsk_your-", "sk-or-v1-your", "gsk_your_"]
    )
    if not api_key or is_placeholder:
        raise ValueError("Chưa cấu hình API Key cho LLM để tạo câu hỏi phỏng vấn.")

    provider = settings.llm_provider.lower()
    if provider == "deepseek":
        # None: để get_chat_model chọn model DeepSeek hợp lệ (MODEL_NAME có thể là model của nhà cung cấp khác)
        models_to_try: list[str | None] = [None]
    elif provider == "groq":
        models_to_try = [settings.model_name]
        if settings.model_name != "openai/gpt-oss-20b":
            models_to_try.append("openai/gpt-oss-20b")
    else:
        models_to_try = [settings.model_name]

    last_error: Exception | None = None
    for model_name in models_to_try:
        try:
            llm = (
                settings.get_chat_model(model=model_name, temperature=0.3)
                if model_name
                else settings.get_chat_model(temperature=0.3)
            )
            response = await asyncio.wait_for(llm.ainvoke(prompt), timeout=timeout)
            content = response.content.strip()

            json_match = re.search(r"\[.*\]", content, re.DOTALL)
            if not json_match:
                continue

            parsed = json.loads(json_match.group(0))
            if isinstance(parsed, list) and len(parsed) >= 4:
                return parsed[:4]
        except Exception as e:
            logger.warning("Thử model %s thất bại: %s", model_name, e)
            last_error = e

    raise last_error or ValueError("LLM không trả về danh sách câu hỏi hợp lệ.")


def clean_question(text: str) -> str:
    """Bỏ markdown (**, `) và khoảng trắng thừa; viết hoa chữ đầu câu."""
    text = " ".join(_MARKDOWN.sub("", text).split())
    return text[:1].upper() + text[1:]


def question_problems(text: str) -> list[str]:
    """Lý do câu hỏi cần viết lại: quá dài, tự nhắc khung STAR."""
    problems = []
    if len(text) > MAX_QUESTION_CHARS:
        problems.append(f"dài {len(text)} ký tự (tối đa {MAX_QUESTION_CHARS})")
    if _STAR_WORDS.search(text):
        problems.append("nhắc chữ Situation/Task/Action/Result/STAR")
    return problems


def _parse(raw_items: list[dict[str, str]]) -> list[tuple[str, str]]:
    result = []
    for i, item in enumerate(raw_items):
        theme = str(item.get("theme") or THEMES[i]).strip()
        q_text = clean_question(str(item.get("question") or ""))
        if not q_text:
            raise ValueError(f"Câu hỏi {i + 1} rỗng")
        result.append((theme, q_text))
    return result


async def generate_interview_questions(
    role: str,
    jd_text: str = "",
    cv_text: str | None = None,
    mode: str = "with_cv",
) -> list[tuple[str, str]]:
    """
    Sử dụng trực tiếp LLM để đọc toàn bộ nội dung CV (sau OCR/trích xuất) và JD,
    tự động suy nghĩ và tạo ra 4 câu hỏi phỏng vấn STAR thực chiến cá nhân hóa, ngắn gọn.
    """
    clean_role = role.strip() or "Vị trí tuyển dụng"
    jd_snippet = (jd_text or "")[:3500].strip()
    cv_snippet = (cv_text or "")[:3500].strip()

    output_format = f"""Trả về DUY NHẤT một object JSON có mảng 4 câu hỏi (không kèm markdown khác):
{{"questions": [
  {{"theme": "{THEMES[0]}", "question": "..."}},
  {{"theme": "{THEMES[1]}", "question": "..."}},
  {{"theme": "{THEMES[2]}", "question": "..."}},
  {{"theme": "{THEMES[3]}", "question": "..."}}
]}}"""

    if mode == "with_cv" and cv_snippet and len(cv_snippet) > 40:
        prompt = f"""Bạn là người phỏng vấn chuyên môn đang trực tiếp phỏng vấn ứng viên cho vị trí: {clean_role}.

Nhiệm vụ: đọc CV của ứng viên (trích từ file/OCR) và JD dưới đây, rồi đặt ĐÚNG 4 câu hỏi phỏng vấn hành vi để ứng viên kể lại trải nghiệm thật (ứng viên sẽ tự trả lời theo STAR).

NỘI DUNG CÂU HỎI:
- Không dùng câu hỏi văn mẫu chung chung; mỗi câu gắn với một dự án, công việc hoặc kỹ năng cụ thể trong CV liên quan tới JD (nêu tên dự án/công việc ngắn gọn).
- Hỏi vào việc ứng viên trực tiếp làm, cách xử lý vấn đề, phối hợp và học hỏi.

{STYLE_RULES}

{GOOD_EXAMPLES}
=== VỊ TRÍ ỨNG TUYỂN ===
{clean_role}

=== BẢN MÔ TẢ CÔNG VIỆC (JD) ===
{jd_snippet or clean_role}

=== HỒ SƠ CV CỦA ỨNG VIÊN (TRÍCH XUẤT TỪ OCR/FILE) ===
{cv_snippet}

=== 4 CHỦ ĐỀ CÂU HỎI CẦN TẠO ===
1. '{THEMES[0]}': một dự án/nhiệm vụ nổi bật trong CV liên quan đến vị trí {clean_role}.
2. '{THEMES[1]}': một lần gặp lỗi, sự cố hoặc vấn đề khó với công cụ/nghiệp vụ trong CV và cách xử lý.
3. '{THEMES[2]}': phối hợp, bất đồng hoặc áp lực tiến độ khi làm việc với người khác.
4. '{THEMES[3]}': một yêu cầu trong JD mà CV chưa thể hiện rõ, và cách ứng viên học hoặc vận dụng kinh nghiệm sẵn có.

{output_format}"""
    else:
        prompt = f"""Bạn là người phỏng vấn chuyên môn đang phỏng vấn ứng viên cho vị trí: {clean_role}.
Ứng viên chọn phỏng vấn dựa trên Bản mô tả công việc (JD), không có CV.

Nhiệm vụ: đọc JD dưới đây và đặt ĐÚNG 4 câu hỏi phỏng vấn hành vi để ứng viên kể lại trải nghiệm thật (ứng viên sẽ tự trả lời theo STAR).

NỘI DUNG CÂU HỎI:
- Không dùng câu hỏi văn mẫu chỉ ghép tên vị trí vào; mỗi câu gắn với một trách nhiệm, công cụ hoặc bài toán cụ thể trong JD.
- Ứng viên có thể chưa đi làm: cho phép kể từ đồ án, bài tập lớn, dự án cá nhân.

{STYLE_RULES}

{GOOD_EXAMPLES}
=== VỊ TRÍ ỨNG TUYỂN ===
{clean_role}

=== BẢN MÔ TẢ CÔNG VIỆC (JD) ===
{jd_snippet or clean_role}

=== 4 CHỦ ĐỀ CÂU HỎI CẦN TẠO ===
1. '{THEMES[0]}': một nhiệm vụ cốt lõi trong JD mà ứng viên đã từng làm (ở đồ án hoặc công việc).
2. '{THEMES[1]}': một lần xử lý lỗi, sự cố hoặc vấn đề khó với công nghệ trong JD.
3. '{THEMES[2]}': làm việc nhóm, giao tiếp hoặc xử lý bất đồng trong môi trường của vị trí {clean_role}.
4. '{THEMES[3]}': tự học công nghệ mới hoặc thích ứng với quy trình mà công việc này cần.

{output_format}"""

    # Cổng gateway che tên, email, số điện thoại trong CV trước khi gửi; câu hỏi trả về được đổi mã ẩn về chữ thật
    with provider_scope() as scope:
        questions = await _questions(prompt)
        return [(theme, _restore(scope, q)) for theme, q in questions]


def _restore(scope, text: str) -> str:
    return text if scope.mask_only else scope.restore_business(text)


async def _questions(prompt: str) -> list[tuple[str, str]]:
    questions = _parse(await _invoke_llm_for_questions(prompt))
    problems = {i: p for i, (_, q) in enumerate(questions) if (p := question_problems(q))}
    if problems:
        # Viết lại một lần các câu chưa đạt; vẫn chưa đạt thì giữ bản đã bỏ markdown
        notes = "\n".join(f"- Câu {i + 1} {', '.join(p)}: {questions[i][1]}" for i, p in problems.items())
        retry = f"{prompt}\n\nLẦN TRƯỚC CÓ CÂU CHƯA ĐẠT, hãy viết lại cả 4 câu ngắn gọn hơn, đúng yêu cầu cách hỏi:\n{notes}"
        try:
            rewritten = _parse(await _invoke_llm_for_questions(retry))
            questions = [
                new if not question_problems(new[1]) or len(new[1]) < len(old[1]) else old
                for old, new in zip(questions, rewritten, strict=True)
            ]
        except Exception as e:
            logger.warning("Viết lại câu hỏi phỏng vấn thất bại: %s", e)
    return questions
