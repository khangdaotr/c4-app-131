"""Assistant contracts, real Chroma/BM25 retrieval and authenticated API flows.

Tests use temporary indexes/SQLite and deterministic embeddings, never remote LLMs
or model downloads. The existing conftest owns the temporary database.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from xml.etree import ElementTree

import pytest
from httpx import AsyncClient
from langchain_core.messages import HumanMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select

from src.api import assistant as assistant_api
from src.api.deps import get_current_user
from src.config import get_settings
from src.db.database import SessionLocal
from src.db.models import (
    AgentActionLog,
    AssistantConversation,
    AssistantFeedback,
    AssistantTurn,
    CvVersion,
    GapAnalysis,
    JobDescription,
    User,
)
from src.main import app
from src.models.assistant import (
    AgentAction,
    AssistantLlmOutput,
    ClientPageContext,
    FlatLlmAction,
    NavigateAction,
    SourceCitation,
    validate_llm_actions,
)
from src.services.assistant.agent import AssistantAgent, classify_intent, get_assistant_agent
from src.services.assistant.chunker import MarkdownDocChunker
from src.services.assistant.embedding import AssistantEmbeddingService
from src.services.assistant.hybrid_search import AssistantHybridRetriever, corpus_path, select_citation_chunks
from src.services.assistant.indexer import build_assistant_index
from src.services.assistant.vector_store import AssistantVectorStore
from tests.helpers import ADVISOR, STUDENT

API = "/api/v1/assistant"
UPLOAD_SELECTOR = '[data-agent-target="btn-upload-cv"]'


def context(role: str = "student") -> ClientPageContext:
    route = "/student/cv" if role == "student" else "/advisor/dashboard"
    return ClientPageContext(current_url=route, route=route, user_role=role)


def payload(message: str = "chuyển sang trang phân tích", role: str = "student", **extra: Any) -> dict[str, Any]:
    return {"message": message, "context": context(role).model_dump(), **extra}


@pytest.fixture(scope="module")
def knowledge_base(
    tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> Iterator[AssistantHybridRetriever]:
    patch = pytest.MonkeyPatch()
    settings = get_settings()
    patch.setattr(settings, "assistant_chroma_persist_dir", str(tmp_path_factory.mktemp("assistant-index")))
    patch.setattr(settings, "assistant_docs_dir", str(Path("docs/user-guide").resolve()))
    patch.setattr(settings, "assistant_chroma_collection", "assistant_test_knowledge")
    if getattr(request, "param", "hashing") == "e5":
        patch.setattr(AssistantEmbeddingService, "_instance", None)
        service = AssistantEmbeddingService()
        assert service.embedding_id.startswith("e5:"), "Cached E5 weights are required for this explicit evaluation"
    else:
        service = object.__new__(AssistantEmbeddingService)
        service._initialized = True
        service._model = None
        service._used_model = False
        service.model_name = settings.assistant_embedding_model
        service.dimension = 384
        patch.setattr(AssistantEmbeddingService, "_instance", service)
    assert build_assistant_index() > 0
    try:
        yield AssistantHybridRetriever()
    finally:
        patch.undo()


@pytest.fixture
def api_agent(knowledge_base: AssistantHybridRetriever) -> Iterator[AssistantAgent]:
    agent = AssistantAgent()
    app.dependency_overrides[get_assistant_agent] = lambda: agent
    try:
        yield agent
    finally:
        app.dependency_overrides.pop(get_assistant_agent, None)


def test_indexer_persists_eight_documents_and_selector(knowledge_base: AssistantHybridRetriever) -> None:
    store = knowledge_base.vector_store
    chunks = store.get_chunks()
    assert len({chunk.source for chunk in chunks}) == 8
    assert all(0 < len(chunk.content) <= 500 for chunk in chunks)
    assert any(chunk.selector == UPLOAD_SELECTOR and chunk.route == "/student/cv" for chunk in chunks)
    saved = json.loads(corpus_path(store).read_text(encoding="utf-8"))
    assert {item["chunk_id"] for item in saved["chunks"]} == {chunk.chunk_id for chunk in chunks}


def test_rebuild_replaces_removed_chunks(
    knowledge_base: AssistantHybridRetriever, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "assistant_chroma_persist_dir", str(tmp_path / "index"))
    docs = tmp_path / "docs"
    docs.mkdir()
    first = docs / "first.md"
    first.write_text(
        "---\nroute: /student/cv\nrole: student\ntitle: CV\ntags: [cv]\n---\n# CV\nTải CV PDF.", encoding="utf-8"
    )
    second = docs / "second.md"
    second.write_text(first.read_text(encoding="utf-8") + "\n\nMột phiên bản khác.", encoding="utf-8")
    initial_count = build_assistant_index(str(docs))
    second.unlink()
    count = build_assistant_index(str(docs))
    assert count < initial_count
    store = AssistantVectorStore()
    assert store.collection.count() == count
    assert {chunk.source for chunk in store.get_chunks()} == {"first.md"}
    assert build_assistant_index(str(docs)) == count
    assert AssistantVectorStore().collection.count() == count


def test_default_retriever_reuses_chroma_and_bm25_until_rebuild(knowledge_base, tmp_path, monkeypatch) -> None:
    from src.services.assistant.hybrid_search import get_assistant_retriever, invalidate_retriever

    monkeypatch.setattr(get_settings(), "assistant_chroma_persist_dir", str(tmp_path / "index"))
    docs = tmp_path / "docs"
    docs.mkdir()
    guide = docs / "cv.md"
    text = "---\nroute: /student/cv\nrole: student\ntitle: CV\ntags: [cv]\n---\n# CV\nTải CV PDF."
    guide.write_text(text, encoding="utf-8")
    try:
        build_assistant_index(str(docs))
        first = get_assistant_retriever()
        first.search("tải CV PDF", "student")
        student_index = first._indexes["student"]
        agent = AssistantAgent()
        for _ in range(3):
            result = agent._retrieve({"message": "tải CV PDF", "context": context(), "intent": "qa"})
            assert result["sources"]
            assert get_assistant_retriever() is first
            assert first._indexes["student"] is student_index

        guide.write_text(text.replace("PDF", "DOCX"), encoding="utf-8")
        build_assistant_index(str(docs))
        second = get_assistant_retriever()
        assert second is not first
        assert any("DOCX" in chunk.content for chunk in second.chunks)
        assert all("PDF" not in chunk.content for chunk in second.chunks)
        updated = agent._retrieve({"message": "tải CV DOCX", "context": context(), "intent": "qa"})
        assert updated["sources"]
        assert updated["docs_version"] != result["docs_version"]
    finally:
        invalidate_retriever()


def test_default_retriever_refreshes_on_external_corpus_change(knowledge_base, monkeypatch) -> None:
    import os

    from src.services.assistant.hybrid_search import get_assistant_retriever, invalidate_retriever

    path = corpus_path(knowledge_base.vector_store)
    original = path.stat()
    try:
        invalidate_retriever()
        first = get_assistant_retriever()
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000_000))
        assert get_assistant_retriever() is not first
        monkeypatch.setattr(get_settings(), "assistant_chroma_collection", "another_test_collection")
        assert get_assistant_retriever().vector_store.collection_name == "another_test_collection"
    finally:
        invalidate_retriever()


def test_failed_reindex_discards_cached_collection_handle(knowledge_base, monkeypatch) -> None:
    from src.services.assistant.hybrid_search import get_assistant_retriever, invalidate_retriever

    try:
        first = get_assistant_retriever()
        monkeypatch.setattr(AssistantVectorStore, "replace_chunks", MagicMock(side_effect=RuntimeError("failed")))
        with pytest.raises(RuntimeError, match="failed"):
            build_assistant_index()
        assert get_assistant_retriever() is not first
    finally:
        invalidate_retriever()


def test_chunker_preserves_hierarchy_faq_and_ui_target() -> None:
    document = """---
route: /student/cv
role: student
title: Hướng dẫn CV
tags: [cv, upload]
---
# Hướng dẫn CV
## Giao diện
### Tải lên
- **Nút tải CV**: Selector `[data-agent-target="btn-upload-cv"]`. Chọn PDF.
## FAQ
**Q: Dùng DOCX được không?**

A: Có, hệ thống nhận PDF và DOCX.
"""
    chunks = MarkdownDocChunker().chunk(document, source="sample.md")
    target = next(chunk for chunk in chunks if chunk.selector)
    assert target.section == "Hướng dẫn CV > Giao diện > Tải lên"
    assert target.selector == UPLOAD_SELECTOR
    assert target.tags == ["cv", "upload"]
    assert any("**Q:" in chunk.content and "A: Có" in chunk.content for chunk in chunks)


def test_embedding_uses_e5_query_and_passage_prefixes() -> None:
    service = object.__new__(AssistantEmbeddingService)
    service._used_model = False
    calls: list[list[str]] = []

    def encode(texts: list[str], **options: Any) -> SimpleNamespace:
        calls.append(texts)
        assert options["normalize_embeddings"] is True
        return SimpleNamespace(tolist=lambda: [[1.0, 0.0] for _ in texts])

    service._model = SimpleNamespace(encode=encode)
    assert service.embed_query("Tải CV") == [1.0, 0.0]
    assert service.embed_documents(["PDF", "DOCX"]) == [[1.0, 0.0], [1.0, 0.0]]
    assert calls == [["query: Tải CV"], ["passage: PDF", "passage: DOCX"]]


def test_hybrid_finds_upload_target_and_computes_rrf(knowledge_base: AssistantHybridRetriever) -> None:
    results = knowledge_base.search("nút tải lên CV PDF DOCX", "student")
    assert any(item["selector"] == UPLOAD_SELECTOR for item in results)
    for item in results:
        expected = sum(1 / (60 + item[key]) for key in ("vector_rank", "bm25_rank") if key in item)
        assert item["rrf_score"] == pytest.approx(expected)
        assert item["score"] >= 0.7 * results[0]["score"]
        assert item["role"] in ("student", "all")
    advisors = knowledge_base.search("nhận xét sinh viên báo cáo", "advisor")
    assert advisors and all(item["role"] in ("advisor", "all") for item in advisors)
    assert knowledge_base.search("CV", "unknown") == []
    assert knowledge_base.search("", "student") == []
    assert knowledge_base.search("CV", "student", top_k=0) == []


@pytest.mark.parametrize(
    ("scores", "expected_ids"),
    [
        ([], []),
        ([0.249, 0.2], []),
        ([0.25], []),
        ([0.419], []),
        ([0.42], ["0"]),
        ([0.5, 0.419], ["0"]),
        ([0.8, 0.56, 0.559, 0.25], ["0", "1"]),
        ([0.8, 0.79, 0.78, 0.77, 0.76], ["0", "1", "2"]),
    ],
)
def test_dynamic_cutoff_threshold_ratio_and_cap(scores: list[float], expected_ids: list[str]) -> None:
    chunks = [{"chunk_id": str(i), "score": score} for i, score in enumerate(scores)]
    selected = select_citation_chunks(list(reversed(chunks)))
    assert [chunk["chunk_id"] for chunk in selected] == expected_ids


def dense_retriever(distances: list[float], routes: list[str] | None = None) -> AssistantHybridRetriever:
    """Exercise real fusion/cutoff with controlled absolute vector evidence."""
    retriever = object.__new__(AssistantHybridRetriever)
    retriever.vector_store = MagicMock()
    retriever.chunks = []
    retriever._indexes = {}
    retriever.vector_store.search_vector.return_value = [
        {
            "chunk_id": str(i),
            "content": "Tải CV PDF DOCX.",
            "title": "Hướng dẫn CV",
            "section": "Tải CV",
            "role": "student",
            "route": routes[i] if routes else "/student/cv",
            "distance": distance,
        }
        for i, distance in enumerate(distances)
    ]
    return retriever


def test_route_prior_boosts_rrf_by_fifteen_percent_without_overriding_relevance() -> None:
    retriever = dense_retriever([0.1, 0.12, 0.9], ["/student/analysis", "/student/cv", "/student/cv"])
    baseline = {chunk["chunk_id"]: chunk for chunk in retriever.search("CV", "student")}
    boosted = retriever.retrieve("CV", "student", route="/student/cv")
    assert boosted[0]["chunk_id"] == "1"
    assert "2" not in {chunk["chunk_id"] for chunk in boosted}
    for chunk in boosted:
        multiplier = 1.15 if chunk["route"] == "/student/cv" else 1.0
        assert chunk["rrf_score"] == pytest.approx(baseline[chunk["chunk_id"]]["rrf_score"] * multiplier)
        assert chunk["score"] == pytest.approx(baseline[chunk["chunk_id"]]["score"] * multiplier)


@pytest.mark.parametrize("quote", ['"', "'"])
def test_source_snippet_removes_selectors_and_preserves_action_metadata(quote: str) -> None:
    selector = f"[data-agent-target={quote}btn-upload-cv{quote}]"
    source = SourceCitation(
        chunk_id="upload",
        title="CV",
        route="/student/cv",
        section="Tải CV",
        snippet=f"Nút Tải CV `{selector}` chọn PDF. {selector}",
        selector=selector,
    )
    assert source.snippet == "Nút Tải CV chọn PDF."
    assert source.selector == selector


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["Công thức nấu bánh pizza?", "Tốc độ ánh sáng trong chân không là bao nhiêu?"])
async def test_unrelated_question_is_refused_without_sources(
    knowledge_base: AssistantHybridRetriever, message: str
) -> None:
    llm, structured = fake_llm()
    agent = AssistantAgent(knowledge_base, llm)
    state = agent._retrieve({"message": message, "context": context()})
    assert state["confidence"] == "low" and state["sources"] == []
    response = await agent.respond(message, context())
    assert response.sources == []
    assert "CareerV" in response.message
    assert response.message.startswith("Xin lỗi,") or "Tài liệu hướng dẫn" in response.message
    assert response.actions == []
    structured.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_precise_question_returns_one_to_three_relevant_sources(
    knowledge_base: AssistantHybridRetriever,
) -> None:
    response = await AssistantAgent(knowledge_base).respond("Làm sao dùng nút Chọn file để tải CV lên?", context())
    assert 1 <= len(response.sources) <= 3
    assert all(source.route == "/student/cv" for source in response.sources)
    assert any(source.selector == UPLOAD_SELECTOR for source in response.sources)
    assert all("data-agent-target" not in source.snippet for source in response.sources)
    assert "data-agent-target" not in response.message


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("Match score là gì?", "qa"),
        ("Nút tải CV ở đâu?", "qa"),
        ("Làm sao bắt đầu phân tích CV?", "qa"),
        ("chuyển sang trang phân tích", "action"),
        ("Hãy mở trang CV", "action"),
        ("Làm sao phỏng vấn thử? Mở giúp tôi luôn", "hybrid"),
        ("Hướng dẫn phân tích và mở trang phân tích", "hybrid"),
        ("Đừng mở trang CV", "qa"),
    ],
)
def test_classifies_intent(message: str, intent: str) -> None:
    assert classify_intent(message) == intent


@pytest.mark.parametrize(
    ("action_type", "params"),
    [
        ("NAVIGATE_PAGE", {"route": "/student/cv"}),
        ("HIGHLIGHT_ELEMENT", {"selector": UPLOAD_SELECTOR}),
        ("FILL_FILTER", {"filter_name": "status", "value": "flagged"}),
        ("OPEN_MODAL", {"modal_id": "upload-cv-modal"}),
        ("START_ANALYSIS", {"cv_id": "cv-1", "jd_id": "jd-1"}),
        ("SELECT_STUDENT", {"student_id": "sv-1"}),
        ("SCROLL_TO", {"position": "top"}),
        ("RESET_VIEW", {}),
    ],
)
def test_all_eight_action_variants(action_type: str, params: dict[str, Any]) -> None:
    action = TypeAdapter(AgentAction).validate_python(
        {
            "action_type": action_type,
            "params": params,
            "description_vi": "Thao tác giao diện",
        }
    )
    assert action.requires_confirmation == (action_type == "START_ANALYSIS")
    assert action.id


@pytest.mark.parametrize(
    "action",
    [
        {"action_type": "NAVIGATE_PAGE", "params": {"route": "https://evil.example"}},
        {"action_type": "NAVIGATE_PAGE", "params": {"route": "/student/../advisor/dashboard"}},
        {"action_type": "HIGHLIGHT_ELEMENT", "params": {"selector": "script[onclick]"}},
        {"action_type": "START_ANALYSIS", "params": {"cv_id": "cv-1", "jd_id": "jd-1"}, "requires_confirmation": False},
        {"action_type": "START_ANALYSIS", "params": {"cv_id": "cv-1"}},
        {"action_type": "SCROLL_TO", "params": {"position": "top", "selector": UPLOAD_SELECTOR}},
        {"action_type": "RUN_JS", "params": {"script": "alert(1)"}},
        {"action_type": "RESET_VIEW", "params": {"javascript": "alert(1)"}},
    ],
)
def test_rejects_invalid_actions(action: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(AgentAction).validate_python({"description_vi": "Thao tác", **action})


def fake_llm(result: Any = None, error: Exception | None = None) -> tuple[MagicMock, AsyncMock]:
    llm = MagicMock()
    structured = AsyncMock()
    llm.with_structured_output.return_value = structured
    structured.ainvoke.return_value = (
        AssistantLlmOutput.model_validate({"thought": "Thuộc phạm vi; có tài liệu trực tiếp.", **result})
        if isinstance(result, dict)
        else result
    )
    structured.ainvoke.side_effect = error
    return llm, structured


@pytest.mark.asyncio
async def test_business_filter_neutralizes_name_without_restoration(knowledge_base):
    from src.services.privacy.types import Identity
    from src.services.providers.gateway import provider_scope

    llm, structured = fake_llm(
        {
            "message": "Đã chuẩn bị bộ lọc.",
            "intent": "qa",
            "actions": [
                {
                    "action_type": "FILL_FILTER",
                    "description_vi": "Lọc theo tên",
                    "params": {"filter_name": "keyword", "value": "Alice Morgan"},
                }
            ],
        }
    )
    agent = AssistantAgent(retriever=knowledge_base, llm=llm)
    with provider_scope(identities=(Identity(name="Alice Morgan"),)):
        response = await agent.respond("Làm sao dùng nút Chọn file để tải CV lên? Name: Alice Morgan", context())
    structured.ainvoke.assert_awaited_once()
    assert response.actions == []  # The model cannot supply business/UI commands in v2.
    assert "Alice Morgan" not in str(structured.ainvoke.call_args.args[0])


@pytest.mark.asyncio
async def test_llm_receives_history_and_returns_only_grounded_safe_actions(
    knowledge_base: AssistantHybridRetriever,
) -> None:
    llm, structured = fake_llm(
        {
            "message": "Bạn có thể tải CV PDF hoặc DOCX.",
            "intent": "qa",
            "sources": [],
            "actions": [
                {
                    "action_type": "HIGHLIGHT_ELEMENT",
                    "params": {"selector": UPLOAD_SELECTOR},
                    "description_vi": "Chỉ nút tải CV",
                },
                {
                    "action_type": "HIGHLIGHT_ELEMENT",
                    "params": {"selector": '[data-agent-target="not-in-docs"]'},
                    "description_vi": "Nút lạ",
                },
                {
                    "action_type": "NAVIGATE_PAGE",
                    "params": {"route": "/advisor/dashboard"},
                    "description_vi": "Mở cố vấn",
                },
                {"action_type": "SELECT_STUDENT", "params": {"student_id": "sv-1"}, "description_vi": "Chọn sinh viên"},
            ],
        }
    )
    agent = AssistantAgent(retriever=knowledge_base, llm=llm)
    response = await agent.respond(
        "Làm sao dùng nút Chọn file để tải CV lên?",
        context(),
        history=[{"role": "user", "content": "Tôi có CV"}, {"role": "assistant", "content": "Bạn có thể tải lên"}],
    )
    assert response.sources
    assert response.message == "Bạn có thể tải CV PDF hoặc DOCX."
    llm.with_structured_output.assert_called_once_with(AssistantLlmOutput, method="function_calling")
    assert response.actions == []
    messages = structured.ainvoke.call_args.args[0]
    assert len(messages) == 2 and isinstance(messages[1], HumanMessage)
    data = ElementTree.fromstring(f"<data>{messages[-1].content}</data>")
    history = json.loads(data.findtext("untrusted_chat_history"))
    assert history == [{"role": "user", "content": "Tôi có CV"}, {"role": "assistant", "content": "Bạn có thể tải lên"}]
    assert json.loads(data.findtext("untrusted_page_context"))["current_url"] == "/student/cv"
    evidence = json.loads(data.findtext("retrieved_documents"))
    assert all("data-agent-target" not in source["snippet"] for source in evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer",
    [
        "Xin lỗi, tài liệu hướng dẫn hiện tại chưa có thông tin chi tiết về nội dung này.",
        "Xin lỗi, hiện tại tài liệu hướng dẫn chưa có thông tin chi tiết về nội dung này. "
        "Bạn vui lòng nêu rõ thao tác cần hỗ trợ.",
        "Tôi chỉ hỗ trợ tính năng CareerV và không thể trả lời chủ đề đó.",
    ],
)
@pytest.mark.parametrize("refusal_flag", [True, False, None])
async def test_llm_refusal_omits_retrieved_sources_and_actions(
    knowledge_base: AssistantHybridRetriever, answer: str, refusal_flag: bool | None
) -> None:
    llm, structured = fake_llm(
        {
            **({"is_refusal": refusal_flag} if refusal_flag is not None else {}),
            "message": answer,
            "intent": "qa",
            "actions": [
                {
                    "action_type": "NAVIGATE_PAGE",
                    "params": {"route": "/student/cv"},
                    "description_vi": "Mở trang CV",
                }
            ],
        }
    )
    response = await AssistantAgent(knowledge_base, llm).respond("Làm sao dùng nút Chọn file để tải CV lên?", context())
    structured.ainvoke.assert_awaited_once()
    assert response.message == answer
    assert response.sources == []
    assert response.actions == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError("LLM timeout"), ValueError("invalid JSON")])
async def test_llm_failure_uses_grounded_fallback(knowledge_base: AssistantHybridRetriever, failure: Exception) -> None:
    llm, _ = fake_llm(error=failure)
    result = await AssistantAgent(knowledge_base, llm).respond("Làm sao dùng nút Chọn file để tải CV lên?", context())
    assert result.sources and result.message.startswith("Theo tài liệu")


@pytest.mark.asyncio
async def test_low_cosine_does_not_use_rrf_as_similarity() -> None:
    retriever = dense_retriever([0.9])
    llm, structured = fake_llm()
    result = await AssistantAgent(retriever, llm).respond("Một chủ đề không có trong hướng dẫn", context())
    assert result.sources == []
    assert result.actions == []
    structured.ainvoke.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(("distances", "count"), [([0.0, 0.1, 0.2, 0.3, 0.9], 3), ([0.0, 0.9], 1)])
async def test_agent_applies_cutoff_instead_of_padding_sources(distances: list[float], count: int) -> None:
    agent = AssistantAgent(dense_retriever(distances))
    result = await agent.respond("Làm sao tải CV PDF DOCX?", context())
    assert len(result.sources) == count
    assert [source.chunk_id for source in result.sources] == [str(i) for i in range(count)]


@pytest.mark.asyncio
async def test_selector_crossing_snippet_length_limit_is_cleaned_before_truncation() -> None:
    retriever = dense_retriever([0.0])
    chunk = retriever.vector_store.search_vector.return_value[0]
    chunk.update(content="CV " * 160 + f"`{UPLOAD_SELECTOR}` PDF", selector=UPLOAD_SELECTOR)
    response = await AssistantAgent(retriever).respond("Làm sao tải CV PDF?", context())
    assert response.sources[0].snippet.endswith("PDF")
    assert "data-agent-target" not in response.sources[0].snippet
    assert response.sources[0].selector == UPLOAD_SELECTOR


@pytest.mark.asyncio
async def test_v2_never_proposes_analysis_writes(knowledge_base: AssistantHybridRetriever) -> None:
    ctx = context().model_copy(update={"selected_cv_id": "cv-1", "page_state": {"selected_jd_id": "jd-1"}})
    response = await AssistantAgent(knowledge_base).respond("Hãy bắt đầu phân tích CV", ctx)
    assert response.actions == []
    absent = await AssistantAgent(knowledge_base).respond("Hãy bắt đầu phân tích CV", context())
    assert all(action.action_type != "START_ANALYSIS" for action in absent.actions)


@pytest.mark.asyncio
async def test_locate_analysis_start_control(knowledge_base: AssistantHybridRetriever) -> None:
    ctx = context().model_copy(update={"route": "/student", "current_url": "/student"})
    response = await AssistantAgent(knowledge_base).respond("Nút bắt đầu phân tích ở đâu?", ctx)
    assert response.actions == []
    assert [action.type for action in response.ui_actions] == ["navigate", "highlight"]
    assert response.ui_actions[0].route_id == "analysis_new"
    assert response.ui_actions[1].element_id == "btn-start-analysis"


@pytest.mark.asyncio
async def test_advisor_can_select_only_assigned_students(knowledge_base: AssistantHybridRetriever) -> None:
    llm, _ = fake_llm(
        {
            "message": "Chọn hồ sơ sinh viên được phân công.",
            "intent": "action",
            "actions": [
                {
                    "action_type": "SELECT_STUDENT",
                    "params": {"student_id": student_id},
                    "description_vi": "Chọn sinh viên",
                }
                for student_id in ("sv-assigned", "sv-other")
            ],
        }
    )
    response = await AssistantAgent(knowledge_base, llm).respond(
        "Chọn sinh viên cần nhận xét báo cáo", context("advisor"), allowed_student_ids=["sv-assigned"]
    )
    assert response.actions == []  # Student selection is outside the read-only v2 UI protocol.


@pytest.mark.asyncio
async def test_question_cannot_start_analysis_even_if_llm_requests_it(knowledge_base: AssistantHybridRetriever) -> None:
    llm, _ = fake_llm(
        {
            "message": "Phân tích đối chiếu CV với JD.",
            "intent": "action",
            "actions": [
                {
                    "action_type": "START_ANALYSIS",
                    "params": {"cv_id": "cv-1", "jd_id": "jd-1"},
                    "description_vi": "Phân tích CV",
                }
            ],
        }
    )
    ctx = context().model_copy(update={"selected_cv_id": "cv-1", "page_state": {"selected_jd_id": "jd-1"}})
    response = await AssistantAgent(knowledge_base, llm).respond("Làm sao bắt đầu phân tích CV?", ctx)
    assert response.intent == "qa" and response.actions == []


@pytest.mark.asyncio
async def test_negative_command_cannot_navigate(knowledge_base: AssistantHybridRetriever) -> None:
    llm, _ = fake_llm(
        {
            "message": "Bạn có thể quản lý CV ở trang CV.",
            "intent": "action",
            "actions": [
                {"action_type": "NAVIGATE_PAGE", "params": {"route": "/student/cv"}, "description_vi": "Mở CV"}
            ],
        }
    )
    response = await AssistantAgent(knowledge_base, llm).respond("Đừng mở trang CV", context())
    assert response.actions == []


@pytest.mark.asyncio
async def test_chat_persists_navigation_stub_without_actions(client: AsyncClient, api_agent: AssistantAgent) -> None:
    result = await client.post(f"{API}/chat", json=payload(), headers=STUDENT)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["intent"] == "qa"
    assert data["route"] == "navigate"
    assert data["actions"] == data["ui_actions"] == data["sources"] == []
    with SessionLocal() as db:
        conversation = db.get(AssistantConversation, data["conversation_id"])
        turn = db.get(AssistantTurn, data["turn_id"])
        assert conversation.user_id == "sv-0142" and conversation.role == "student"
        assert turn.context_json["user_id"] == "sv-0142"
        assert turn.sources_json == data["sources"]
        assert db.scalar(select(func.count()).select_from(AgentActionLog).where(AgentActionLog.turn_id == turn.id)) == 0


@pytest.mark.asyncio
async def test_followup_reuses_conversation_and_supplies_history(
    client: AsyncClient, api_agent: AssistantAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = (await client.post(f"{API}/chat", json=payload(), headers=STUDENT)).json()
    spy = AsyncMock(wraps=api_agent.respond)
    monkeypatch.setattr(api_agent, "respond", spy)
    second = await client.post(
        f"{API}/chat", json=payload("Nút tải CV ở đâu?", conversation_id=first["conversation_id"]), headers=STUDENT
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == first["conversation_id"]
    assert second.json()["turn_id"] != first["turn_id"]
    assert spy.call_args.kwargs["history"][0]["content"] == "chuyển sang trang phân tích"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["owned", "foreign_cv", "foreign_jd", "missing_cv", "empty_cv"])
async def test_analysis_actions_require_accessible_cv_and_jd(
    client: AsyncClient, api_agent: AssistantAgent, kind: str
) -> None:
    with SessionLocal() as db:
        foreign_id = f"sv-{uuid4().hex[:12]}"
        db.add(User(id=foreign_id, role="student", full_name="Other", email=f"{foreign_id}@example.test"))
        owner_id = foreign_id if kind == "foreign_cv" else "sv-0142"
        version = (db.scalar(select(func.max(CvVersion.version)).where(CvVersion.owner_id == owner_id)) or 0) + 1
        cv = CvVersion(
            id=f"cv-{uuid4().hex[:12]}",
            owner_id=owner_id,
            version=version,
            file_name="CV.docx",
            file_type="docx",
            size_bytes=100,
            content_text="" if kind == "empty_cv" else "Python SQL projects",
        )
        db.add(cv)
        jd = db.scalar(select(JobDescription).where(JobDescription.source == "library"))
        if kind == "foreign_jd":
            jd = JobDescription(
                id=f"jd-{uuid4().hex[:12]}",
                source="pasted",
                owner_id=foreign_id,
                title="Private JD",
                content="Python development",
            )
            db.add(jd)
        db.commit()
        cv_id = "missing-cv" if kind == "missing_cv" else cv.id
        jd_id = jd.id
        analyses_before = db.scalar(select(func.count()).select_from(GapAnalysis))
    body = payload("Hãy bắt đầu phân tích CV")
    body["context"].update(selected_cv_id=cv_id, page_state={"selected_jd_id": jd_id})
    response = await client.post(f"{API}/chat", json=body, headers=STUDENT)
    assert response.status_code == 200, response.text
    starts = [action for action in response.json()["actions"] if action["action_type"] == "START_ANALYSIS"]
    assert starts == []
    with SessionLocal() as db:
        # V2 never proposes or starts a background job, even with owned IDs.
        assert db.scalar(select(func.count()).select_from(GapAnalysis)) == analyses_before


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["library", "own", "hidden", "foreign", "own_deleted"])
async def test_navigate_to_jd_detail_only_for_visible_jds(
    client: AsyncClient, api_agent: AssistantAgent, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    with SessionLocal() as db:
        jd = db.scalar(
            select(JobDescription).where(
                JobDescription.source == "library",
                JobDescription.status.is_(None) | (JobDescription.status == "published"),
            )
        )
        if kind != "library":
            other = f"sv-{uuid4().hex[:12]}"
            db.add(User(id=other, role="student", full_name="Other", email=f"{other}@example.test"))
            jd = JobDescription(
                id=f"jd-{uuid4().hex[:12]}",
                source="library" if kind == "hidden" else "pasted",
                owner_id=None if kind == "hidden" else (other if kind == "foreign" else "sv-0142"),
                title="Business Analyst",
                content="Phân tích yêu cầu, SQL",
                status={"hidden": "hidden", "own_deleted": "deleted"}.get(kind),
            )
            db.add(jd)
            db.commit()
        route = f"/student/library/{jd.id}"
    llm, _ = fake_llm(
        {
            "message": "Mở chi tiết vị trí trong Thư viện JD.",
            "intent": "action",
            "actions": [
                {"action_type": "NAVIGATE_PAGE", "params": {"route": route}, "description_vi": "Mở chi tiết JD"}
            ],
        }
    )
    monkeypatch.setattr(api_agent, "_llm", llm)
    response = await client.post(f"{API}/chat", json=payload("Mở chi tiết JD trong thư viện JD"), headers=STUDENT)
    assert response.status_code == 200, response.text
    assert response.json()["actions"] == []  # Navigation resolution is deferred to M4.
    with SessionLocal() as db:
        user = db.get(User, "sv-0142")
        safe = assistant_api._resource_actions(
            db, user, [NavigateAction(description_vi="Open JD", params={"route": route})], []
        )
        assert bool(safe) == (kind in ("library", "own"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"user_role": "advisor"},
        {"user_id": "someone-else"},
        {"route": "/advisor/dashboard"},
        {"current_url": "/advisor/dashboard"},
    ],
)
async def test_chat_rejects_forged_context(
    client: AsyncClient, api_agent: AssistantAgent, overrides: dict[str, str]
) -> None:
    body = payload()
    body["context"].update(overrides)
    assert (await client.post(f"{API}/chat", json=body, headers=STUDENT)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "body"),
    [
        ("chat", payload()),
        ("action/confirm", {"action_id": "missing", "status": "executed"}),
        ("feedback", {"turn_id": "missing", "rating": 1}),
        ("reindex", None),
    ],
)
async def test_assistant_endpoints_require_auth(client: AsyncClient, endpoint: str, body: Any) -> None:
    assert (await client.post(f"{API}/{endpoint}", json=body)).status_code == 401


def legacy_audited_chat(chat: dict[str, Any]) -> dict[str, Any]:
    """Seed a historical action to test the retained audit endpoint independently of v2."""
    action = NavigateAction(description_vi="Open CV", params={"route": "/student/cv"})
    with SessionLocal() as db:
        db.add(
            AgentActionLog(
                id=action.id,
                turn_id=chat["turn_id"],
                action_type=action.action_type,
                params_json=action.params.model_dump(mode="json"),
                status="pending",
            )
        )
        db.commit()
    return {**chat, "actions": [action.model_dump(mode="json")]}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["executed", "rejected", "failed"])
async def test_action_status_is_persisted_and_idempotent(
    client: AsyncClient, api_agent: AssistantAgent, status: str
) -> None:
    chat = legacy_audited_chat((await client.post(f"{API}/chat", json=payload(), headers=STUDENT)).json())
    action_id = chat["actions"][0]["id"]
    body = {"action_id": action_id, "status": status, "error_message": "Selector absent"}
    response = await client.post(f"{API}/action/confirm", json=body, headers=STUDENT)
    assert response.status_code == 200
    with SessionLocal() as db:
        action = db.get(AgentActionLog, action_id)
        assert action.status == status
        assert (action.client_executed_at is not None) == (status == "executed")
        assert action.error_message == ("Selector absent" if status == "failed" else None)
        timestamp = action.client_executed_at
    assert (await client.post(f"{API}/action/confirm", json=body, headers=STUDENT)).status_code == 200
    with SessionLocal() as db:
        assert db.get(AgentActionLog, action_id).client_executed_at == timestamp
    body["status"] = "failed" if status != "failed" else "executed"
    assert (await client.post(f"{API}/action/confirm", json=body, headers=STUDENT)).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("final_status", ["executed", "rejected", "failed"])
async def test_action_confirmation_precedes_terminal_status(
    client: AsyncClient, api_agent: AssistantAgent, final_status: str
) -> None:
    chat = legacy_audited_chat((await client.post(f"{API}/chat", json=payload(), headers=STUDENT)).json())
    action_id = chat["actions"][0]["id"]
    body = {"action_id": action_id, "status": "confirmed"}
    for _ in range(2):
        response = await client.post(f"{API}/action/confirm", json=body, headers=STUDENT)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "confirmed"
    with SessionLocal() as db:
        action = db.get(AgentActionLog, action_id)
        assert action.status == "confirmed"
        assert action.client_executed_at is None
    body["status"] = final_status
    assert (await client.post(f"{API}/action/confirm", json=body, headers=STUDENT)).status_code == 200
    body["status"] = "confirmed"
    assert (await client.post(f"{API}/action/confirm", json=body, headers=STUDENT)).status_code == 409


@pytest.mark.asyncio
async def test_feedback_persists_and_updates_without_duplicate(client: AsyncClient, api_agent: AssistantAgent) -> None:
    chat = (await client.post(f"{API}/chat", json=payload(), headers=STUDENT)).json()
    body = {"turn_id": chat["turn_id"], "rating": 1, "comment": "Hữu ích"}
    first = await client.post(f"{API}/feedback", json=body, headers=STUDENT)
    assert first.status_code == 200
    body.update(rating=-1, comment="Cần rõ hơn")
    second = await client.post(f"{API}/feedback", json=body, headers=STUDENT)
    assert second.status_code == 200 and first.json()["id"] == second.json()["id"]
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(AssistantFeedback).where(AssistantFeedback.turn_id == chat["turn_id"])
            )
            == 1
        )
        assert db.get(AssistantFeedback, second.json()["id"]).comment == "Cần rõ hơn"
    # Bấm lại nút đã chọn để huỷ; huỷ lần nữa vẫn thành công
    for _ in range(2):
        undo = await client.delete(f"{API}/feedback/{chat['turn_id']}", headers=STUDENT)
        assert undo.status_code == 204
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(AssistantFeedback).where(AssistantFeedback.turn_id == chat["turn_id"])
            )
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("rating", [0, 2, True, "1"])
async def test_feedback_rejects_invalid_ratings(client: AsyncClient, rating: Any) -> None:
    assert (
        await client.post(f"{API}/feedback", json={"turn_id": "missing", "rating": rating}, headers=STUDENT)
    ).status_code == 422


@pytest.mark.asyncio
async def test_other_student_cannot_access_conversation_action_or_feedback(
    client: AsyncClient, api_agent: AssistantAgent
) -> None:
    first = legacy_audited_chat((await client.post(f"{API}/chat", json=payload(), headers=STUDENT)).json())
    other = User(
        id=f"sv-{uuid4().hex[:12]}", role="student", full_name="Other student", email=f"{uuid4().hex}@example.test"
    )
    with SessionLocal() as db:
        db.add(other)
        db.commit()
    app.dependency_overrides[get_current_user] = lambda: other
    try:
        cases = [
            ("chat", payload(conversation_id=first["conversation_id"])),
            ("action/confirm", {"action_id": first["actions"][0]["id"], "status": "executed"}),
            ("feedback", {"turn_id": first["turn_id"], "rating": 1}),
        ]
        for endpoint, body in cases:
            assert (await client.post(f"{API}/{endpoint}", json=body, headers=STUDENT)).status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_reindex_requires_advisor_and_refreshes_retrieval(client: AsyncClient, api_agent: AssistantAgent) -> None:
    assert (await client.post(f"{API}/reindex", headers=STUDENT)).status_code == 403
    response = await client.post(f"{API}/reindex", headers=ADVISOR)
    assert response.status_code == 200 and response.json()["chunks_indexed"] > 0
    chat = await client.post(f"{API}/chat", json=payload("Làm sao dùng nút Chọn file để tải CV lên?"), headers=STUDENT)
    assert chat.status_code == 200
    assert any(source["selector"] == UPLOAD_SELECTOR for source in chat.json()["sources"])


@pytest.mark.asyncio
async def test_reindex_failure_is_sanitized(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(assistant_api, "build_assistant_index", MagicMock(side_effect=RuntimeError("internal details")))
    response = await client.post(f"{API}/reindex", headers=ADVISOR)
    assert response.status_code == 503 and response.json()["code"] == "assistant_index_unavailable"
    assert "internal details" not in response.text


def test_llm_tool_schema_has_flat_actions_without_polymorphic_union() -> None:
    schema = convert_to_openai_tool(AssistantLlmOutput)["function"]["parameters"]
    action = schema["properties"]["actions"]["items"]
    assert action["type"] == "object"
    assert action["properties"]["action_type"]["type"] == "string"
    assert action["properties"]["params"]["type"] == "object"
    assert "discriminator" not in json.dumps(schema)
    assert "oneOf" not in json.dumps(schema)
    assert "thought" in schema["required"]
    assert "sources" not in schema["properties"]


def test_flat_actions_keep_valid_peers_and_enforce_confirmation() -> None:
    actions = [
        FlatLlmAction(action_type="NAVIGATE_PAGE", params={"route": "/student/history"}, description_vi="Mở lịch sử"),
        FlatLlmAction(action_type="RUN_JS", params={"script": "alert(1)"}, description_vi="Lệnh không hợp lệ"),
        FlatLlmAction(action_type="NAVIGATE_PAGE", params={"route": "https://evil.example"}, description_vi="Route lạ"),
        FlatLlmAction(action_type="START_ANALYSIS", params={"cv_id": "cv-1"}, description_vi="Thiếu JD"),
        FlatLlmAction(
            action_type="START_ANALYSIS",
            params={"cv_id": "cv-1", "jd_id": "jd-1"},
            description_vi="Phân tích chưa xác nhận",
            requires_confirmation=False,
        ),
        FlatLlmAction(
            action_type="START_ANALYSIS", params={"cv_id": "cv-1", "jd_id": "jd-1"}, description_vi="Phân tích CV"
        ),
    ]
    validated = validate_llm_actions(actions)
    assert [action.action_type for action in validated] == ["NAVIGATE_PAGE", "START_ANALYSIS"]
    assert validated[1].requires_confirmation is True and validated[1].confirmation_message


@pytest.mark.parametrize("query", ["thời tiết ngày mai như thế nào", "ngày hôm nay", "astronomy", "cvx"])
def test_dense_similarity_cannot_replace_topic_keyword_overlap(query: str) -> None:
    retriever = dense_retriever([0.0])
    assert retriever.search(query, "student", route="/student/cv") == []


@pytest.mark.parametrize("matched_field", ["title", "content", "tags"])
def test_topic_overlap_accepts_title_content_or_tags(matched_field: str) -> None:
    retriever = dense_retriever([0.0])
    chunk = retriever.vector_store.search_vector.return_value[0]
    chunk.update(title="Hướng dẫn", content="Tài liệu", tags=[])
    chunk[matched_field] = ["history"] if matched_field == "tags" else "history"
    assert retriever.search("history", "student")


@pytest.mark.asyncio
async def test_low_confidence_with_stale_sources_never_echoes_documents() -> None:
    llm, structured = fake_llm()
    result = await AssistantAgent(llm=llm)._generate(
        {
            "message": "Nội dung chưa có tài liệu",
            "context": context(),
            "intent": "qa",
            "confidence": "low",
            "sources": [
                SourceCitation(
                    chunk_id="stale",
                    title="Lịch sử",
                    route="/student/history",
                    section="Bộ lọc thời gian",
                    snippet="Chọn khoảng 30 ngày.",
                )
            ],
        }
    )
    response = result["response"]
    assert (
        response.message == "Xin lỗi, tôi chưa tìm thấy tài liệu phù hợp để trả lời câu hỏi này trong hệ thống CareerV."
    )
    assert response.actions == [] and response.sources == []
    structured.ainvoke.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["thời tiết ngày mai như thế nào", "hôm nay ăn gì"])
async def test_chat_api_refuses_out_of_scope_without_actions_or_sources(
    client: AsyncClient, api_agent: AssistantAgent, monkeypatch: pytest.MonkeyPatch, message: str
) -> None:
    retriever = MagicMock()
    llm, structured = fake_llm()
    monkeypatch.setattr(api_agent, "_retriever", retriever)
    monkeypatch.setattr(api_agent, "_llm", llm)
    result = await client.post(f"{API}/chat", json=payload(message), headers=STUDENT)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["message"].startswith("Xin lỗi,") and "CareerV" in data["message"]
    assert data["actions"] == [] and data["sources"] == []
    assert "Bộ lọc thời gian" not in data["message"]
    assert "thought" not in data
    retriever.search.assert_not_called()
    structured.ainvoke.assert_not_called()
    with SessionLocal() as db:
        turn = db.get(AssistantTurn, data["turn_id"])
        assert turn.sources_json == [] and turn.assistant_message == data["message"]
        assert db.scalar(select(func.count()).select_from(AgentActionLog).where(AgentActionLog.turn_id == turn.id)) == 0


@pytest.mark.asyncio
async def test_chat_history_question_uses_history_document_and_flat_schema(
    client: AsyncClient,
    api_agent: AssistantAgent,
    knowledge_base: AssistantHybridRetriever,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    question = "Làm sao để xem lịch sử phỏng vấn?"
    # Earlier API reindex tests replace the collection; refresh the handle.
    chunks = AssistantHybridRetriever().search(question, "student", route="/student/cv")
    assert any(chunk["source"].endswith("history.md") for chunk in chunks)
    answer = (
        "Mở [Lịch sử & Tiến bộ](/student/history), chọn vị trí và khoảng thời gian, "
        "chọn Mock Interview rồi chọn phiên phỏng vấn để mở báo cáo."
    )
    llm, structured = fake_llm({"message": answer, "intent": "qa", "actions": []})
    monkeypatch.setattr(api_agent, "_llm", llm)
    with caplog.at_level("DEBUG", logger="src.services.assistant.agent"):
        result = await client.post(f"{API}/chat", json=payload(question), headers=STUDENT)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["message"] == answer
    assert any(source["route"] == "/student/history" for source in data["sources"])
    assert "thought" not in data
    assert "Assistant scope/evidence decision" not in caplog.text
    assert "Assistant generation unavailable" not in caplog.text
    llm.with_structured_output.assert_called_once_with(AssistantLlmOutput, method="function_calling")
    structured.ainvoke.assert_awaited_once()
