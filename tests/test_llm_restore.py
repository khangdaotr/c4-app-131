"""invoke_json đổi mã ẩn ("[[PERSON_..]]") trong câu trả lời của LLM về chữ thật trước khi hiển thị cho SV."""

import pytest

from src.services import llm
from src.services.providers.gateway import provider_scope


@pytest.mark.asyncio
async def test_invoke_json_restores_placeholders_from_the_same_scope(monkeypatch):
    with provider_scope() as scope:
        token = scope.vault.store("Trần Văn Bình", "PERSON", "message")

        async def fake_once(prompt, temperature, timeout):
            return {"feedback_text": f"Điểm tốt: {token} nêu rõ bối cảnh.", "items": [{"note": token}], "score": 4}

        monkeypatch.setattr(llm, "_invoke_json_once", fake_once)
        data = await llm.invoke_json("prompt")
    assert data == {
        "feedback_text": "Điểm tốt: Trần Văn Bình nêu rõ bối cảnh.",
        "items": [{"note": "Trần Văn Bình"}],
        "score": 4,
    }
    assert "[[" not in str(data)
