"""Recommendation work is performed once, with stored scores and privacy scope intact."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api import analysis
from src.models.schemas import RecommendJDsRequest
from src.services.providers.gateway import provider_scope


@pytest.mark.asyncio
@pytest.mark.parametrize("generate_advice", [False, True])
@pytest.mark.parametrize("stored_cv", [False, True])
async def test_recommend_once_and_optional_advice(monkeypatch, generate_advice, stored_cv) -> None:
    user = SimpleNamespace(id="student", full_name="Student", email="student@example.test")
    db = MagicMock()
    db.get.return_value = SimpleNamespace(owner_id=user.id, content_text="Python SQL")
    scores = {"jd-python": {"match_score": 88}}
    latest = MagicMock(return_value=scores)
    seen_scopes = []

    def recommend(**kwargs):
        # A nested scope must reuse the identity dictionary primed for this request.
        with provider_scope() as scope:
            seen_scopes.append(scope)
        return [{"jd_id": "jd-python", "title": "Python Developer", "semantic_score": 0.8, "match_score": 88}]

    recommend_mock = MagicMock(side_effect=recommend)
    advice = AsyncMock(return_value={"summary": "Summary", "top_position_advice": "Advice", "action_plan": ["SQL"]})
    monkeypatch.setattr(analysis, "recommend_top_jds_from_cv", recommend_mock)
    monkeypatch.setattr(analysis, "generate_career_advice_with_llm", advice)
    monkeypatch.setattr(analysis, "_latest_analysis_scores", latest)
    request = RecommendJDsRequest(
        cv_version_id="cv-test" if stored_cv else None,
        cv_text=None if stored_cv else "Python SQL",
        top_n=2,
        generate_advice=generate_advice,
    )

    result = await analysis.recommend_jds(request, user, db)

    recommend_mock.assert_called_once_with(
        cv_text="Python SQL", db=db, top_n=2, known_scores=scores if stored_cv else None
    )
    assert seen_scopes[0].user_id == user.id
    assert seen_scopes[0].identities[0].email == user.email
    assert latest.call_count == int(stored_cv)
    assert advice.await_count == int(generate_advice)
    assert result.recommendations[0].match_score == 88
    assert (result.advice is not None) == generate_advice


@pytest.mark.asyncio
async def test_recommend_rejects_unowned_cv_before_work(monkeypatch) -> None:
    from src.api.errors import AppError

    db = MagicMock()
    db.get.return_value = SimpleNamespace(owner_id="other-student", content_text="Private CV")
    recommend = MagicMock()
    monkeypatch.setattr(analysis, "recommend_top_jds_from_cv", recommend)
    with pytest.raises(AppError):
        await analysis.recommend_jds(RecommendJDsRequest(cv_version_id="other-cv"), SimpleNamespace(id="student"), db)
    recommend.assert_not_called()
