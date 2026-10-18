"""NER underthesea với chữ đặt dấu thanh kiểu cũ ("khoá", "thuỷ") và tham số thinking của DeepSeek."""

import pytest

from src.config import Settings
from src.services.privacy.ner import _modern_tone


def test_modern_tone_moves_marks_only_at_syllable_end_and_keeps_length():
    pairs = {
        "khoá học": "khóa học",
        "Hoá học": "Hóa học",
        "KHOÁ": "KHÓA",
        "thuỷ lợi": "thủy lợi",
        "Tuỳ vị trí": "Tùy vị trí",
        "hoà nhập": "hòa nhập",
        # Không đổi: dấu trong âm tiết có phụ âm cuối, "qu" là phụ âm đầu, chữ đã viết kiểu mới
        "Hoàng Huỳnh hoạt động": "Hoàng Huỳnh hoạt động",
        "quý Quỳ": "quý Quỳ",
        "khóa thủy": "khóa thủy",
    }
    for old, new in pairs.items():
        assert _modern_tone(old) == new
        assert len(_modern_tone(old)) == len(old)


def test_underthesea_alignment_accepts_old_style_tone_marks():
    pytest.importorskip("underthesea")
    from src.services.privacy.ner import UndertheseaNer

    ner = UndertheseaNer()
    text = "Nguyễn Thị Thuỷ tham gia khoá học Hoá, tuỳ chọn ở Hà Nội."
    spans = ner.detect(text)
    # Vị trí trả về là vị trí trên văn bản gốc (chưa đổi dấu)
    assert ("Nguyễn Thị Thuỷ", "PERSON") in [(text[s.start : s.end], s.kind) for s in spans]


@pytest.mark.parametrize(("thinking", "expected"), [("disabled", "disabled"), ("enabled", "enabled")])
def test_deepseek_chat_model_sends_thinking_flag(thinking, expected):
    settings = Settings(
        _env_file=None, llm_provider="deepseek", model_name="deepseek-flash", llm_thinking_agent=thinking
    )
    chat = settings.get_chat_model()
    assert chat.options["model"] == "deepseek-flash"
    assert chat.options["extra_body"] == {"thinking": {"type": expected}}


def test_deepseek_default_model_is_valid_when_model_name_is_another_provider():
    settings = Settings(_env_file=None, llm_provider="deepseek", model_name="openai/gpt-oss-120b")
    assert settings.get_chat_model().options["model"] == "deepseek-chat"
    groq = Settings(_env_file=None, llm_provider="groq", model_name="openai/gpt-oss-120b")
    assert "extra_body" not in groq.get_chat_model().options
