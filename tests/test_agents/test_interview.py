import pytest

from src.agents.interview.graph import interview_agent
from src.agents.interview.nodes.score_answer import (
    STARScoreOutput,
    evaluate_answer_fallback,
)


def test_star_score_validation_and_clamping():
    """Kiểm tra schema validation thang điểm 0-5 và cơ chế chuẩn hóa dữ liệu."""
    # Điểm chuẩn trong khoảng 0-5
    valid_data = {
        "situation_score": 4.5,
        "task_score": 4.0,
        "action_score": 3.5,
        "result_score": 4.2,
        "feedback_text": "Câu trả lời có cấu trúc STAR rõ ràng, dẫn chứng số liệu tốt.",
        "next_question": "Hãy chia sẻ về một lần tối ưu DB?",
    }
    validated = STARScoreOutput.model_validate(valid_data)
    assert validated.situation_score == 4.5
    assert validated.task_score == 4.0
    assert validated.action_score == 3.5
    assert validated.result_score == 4.2

    # Tự động scale điểm từ thang 10 về thang 5 (nếu LLM nhầm lẫn)
    scale_data = {
        "situation_score": 8.0,  # 8.0 / 2 = 4.0
        "task_score": 9.0,  # 9.0 / 2 = 4.5
        "action_score": 7.0,  # 7.0 / 2 = 3.5
        "result_score": 10.0,  # 10.0 / 2 = 5.0
        "feedback_text": "Cần làm rõ đóng góp cá nhân hơn.",
    }
    validated_scaled = STARScoreOutput.model_validate(scale_data)
    assert validated_scaled.situation_score == 4.0
    assert validated_scaled.task_score == 4.5
    assert validated_scaled.action_score == 3.5
    assert validated_scaled.result_score == 5.0


def test_evaluate_answer_fallback_logic():
    """Kiểm tra logic chấm điểm fallback khi mất mạng hoặc không có API key."""
    answer = (
        "Trong dự án xây dựng hệ thống thanh toán với FastAPI và PostgreSQL, "
        "nhiệm vụ của tôi là tối ưu hóa thời gian xử lý đơn hàng. "
        "Tôi đã thiết kế lại kiến trúc cache với Redis và tạo composite index, "
        "kết quả giúp giảm 45% thời gian phản hồi từ 800ms xuống còn 120ms."
    )
    result = evaluate_answer_fallback(
        user_answer=answer,
        job_role="Backend Engineer",
        current_round=1,
        total_rounds=3,
    )
    assert 0.0 <= result.situation_score <= 5.0
    assert 0.0 <= result.task_score <= 5.0
    assert 0.0 <= result.action_score <= 5.0
    assert 0.0 <= result.result_score <= 5.0
    assert len(result.feedback_text) > 20
    assert result.next_question is not None

    # Kiểm tra vòng cuối cùng (current_round == total_rounds)
    last_round_result = evaluate_answer_fallback(
        user_answer=answer,
        job_role="Backend Engineer",
        current_round=3,
        total_rounds=3,
    )
    assert last_round_result.next_question is None


@pytest.mark.asyncio
async def test_interview_agent_start_round_flow():
    """Kiểm tra luồng khởi tạo buổi phỏng vấn (chưa gửi câu trả lời)."""
    state = {
        "job_role": "Python Backend Developer",
        "current_round": 1,
        "total_rounds": 3,
    }
    result = await interview_agent.ainvoke(state)
    assert "current_question" in result
    assert len(result["current_question"]) > 10
    assert result.get("is_finished") is False


@pytest.mark.asyncio
async def test_interview_agent_scoring_round_flow():
    """Kiểm tra luồng nộp câu trả lời và chấm điểm vòng 1 (3 vòng cố định)."""
    user_answer = (
        "Bối cảnh: Khi làm dự án tốt nghiệp AI Chatbot, server bị quá tải khi có hơn 500 CCU. "
        "Nhiệm vụ: Cần giảm tải cho inference server mà không làm giảm độ chính xác. "
        "Hành động: Tôi đã áp dụng kỹ thuật batching requests và caching câu trả lời phổ biến bằng Redis. "
        "Kết quả: Tăng throughput lên gấp 3 lần và giảm 60% latency xử lý."
    )
    state = {
        "job_role": "AI Engineer",
        "user_answer": user_answer,
        "current_round": 1,
        "total_rounds": 3,
        "current_question": "Hãy kể về một bài toán khó bạn từng giải quyết?",
    }
    result = await interview_agent.ainvoke(state)

    # 1. Kiểm tra 4 đầu điểm theo thang 0-5
    for key in ["situation_score", "task_score", "action_score", "result_score"]:
        assert key in result
        score = result[key]
        assert isinstance(score, (int, float))
        assert 0.0 <= score <= 5.0, f"{key} ({score}) không nằm trong thang 0-5!"

    # 2. Kiểm tra nhận xét feedback_text
    assert "feedback_text" in result
    assert isinstance(result["feedback_text"], str)
    assert len(result["feedback_text"]) > 10

    # 3. Kiểm tra câu hỏi tiếp theo và trạng thái vòng
    assert "next_question" in result
    assert result["next_question"] is not None
    assert result.get("is_finished") is False


@pytest.mark.asyncio
async def test_interview_agent_final_round_termination():
    """Kiểm tra vòng phỏng vấn cuối cùng (vòng 3/3 hoặc 4/4): next_question phải là None."""
    user_answer = (
        "Trong dự án trước, khi gặp xung đột về việc nên dùng FastAPI hay Django, "
        "tôi đã làm PoC đo benchmark cụ thể để thuyết phục cả nhóm thống nhất giải pháp."
    )
    state = {
        "job_role": "Python Backend Developer",
        "user_answer": user_answer,
        "current_round": 3,
        "total_rounds": 3,
        "current_question": "Bạn đã giải quyết bất đồng quan điểm kỹ thuật như thế nào?",
    }
    result = await interview_agent.ainvoke(state)

    # Thang điểm 0-5
    for key in ["situation_score", "task_score", "action_score", "result_score"]:
        assert 0.0 <= result[key] <= 5.0

    # Vòng cuối cùng: next_question BẮT BUỘC là None (null) và is_finished = True
    assert result.get("next_question") is None
    assert result.get("is_finished") is True


def test_question_style_checks_and_cleanup():
    """Câu hỏi ngắn, không tự nhắc khung STAR, không markdown; viết hoa chữ đầu câu."""
    from src.agents.interview.question_generator import MAX_QUESTION_CHARS, clean_question, question_problems

    short = clean_question("trong dự án **Maintenance Platform**, phần nào bạn trực tiếp làm?")
    assert short == "Trong dự án Maintenance Platform, phần nào bạn trực tiếp làm?"
    assert question_problems(short) == []
    assert question_problems("Hãy kể Situation và Result của dự án.") != []
    assert question_problems("x" * (MAX_QUESTION_CHARS + 1)) != []


def test_feedback_is_plain_text_with_three_parts():
    """Nhận xét bỏ markdown, giữ 3 dòng Điểm tốt / Cần cải thiện / Gợi ý trả lời (kể cả khi chấm dự phòng)."""
    validated = STARScoreOutput.model_validate(
        {
            "situation_score": 3,
            "task_score": 3,
            "action_score": 3,
            "result_score": 3,
            "feedback_text": "**Điểm tốt:** rõ dự án\n- **Cần cải thiện:** thiếu số liệu\nGợi ý trả lời: nêu `p95`",
        }
    )
    assert validated.feedback_text == "Điểm tốt: rõ dự án\nCần cải thiện: thiếu số liệu\nGợi ý trả lời: nêu p95"
    fallback = evaluate_answer_fallback("Trong dự án thư viện em viết API bằng FastAPI.", "Backend Intern", 1, 4)
    assert [line.split(":")[0] for line in fallback.feedback_text.splitlines()] == [
        "Điểm tốt",
        "Cần cải thiện",
        "Gợi ý trả lời",
    ]


def test_evaluate_answer_fallback_structural_scoring():
    """Fallback chấm theo tín hiệu khách quan (kể đủ các bước, vai trò cá nhân, con số), không đếm từ khoá."""
    detailed_answer = (
        "Trong dự án backend, nhiệm vụ của tôi là chọn giải pháp lưu trữ cache cho session. "
        "Tôi đã quyết định sử dụng Redis thay vì Memcached vì Redis hỗ trợ cấu trúc dữ liệu phong phú hơn. "
        "Redis còn có cơ chế persistence, mặc dù chi phí RAM có phần cao hơn so với giải pháp thông thường. "
        "Kết quả giúp hệ thống chạy ổn định và giảm 40% latency."
    )
    result = evaluate_answer_fallback(
        user_answer=detailed_answer,
        job_role="Backend Engineer",
        current_round=1,
        total_rounds=3,
    )
    assert result.action_score >= 3.5
    assert "Điểm tốt" in result.feedback_text
