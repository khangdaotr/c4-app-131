"""Guide-only policy and cached answers; retrieval and TTL storage are reused."""

import hashlib
import json
import re

from pydantic import BaseModel, Field

from src.config import get_settings
from src.models.assistant import SourceCitation, UIAction, UIHighlight, UINavigate
from src.services.assistant.chunker import DocChunk
from src.services.assistant.guardrails import validate_ui_actions
from src.services.assistant.router.cache import ModelCache
from src.services.assistant.router.text import detect_language, normalize
from src.services.assistant.ui_registry import require_element, resolve_route


class AttachmentMetadata(BaseModel):
    route_id: str = ""
    ui_targets: list[str] = Field(default_factory=list)
    score: float = 0.0


class GuideAnswer(BaseModel):
    message: str
    sources: list[SourceCitation]
    attachment: AttachmentMetadata = Field(default_factory=AttachmentMetadata)


# The cache contains guide prose/citations only, never identities, history,
# resolved records, current-page context or already-sequenced UI actions.
AnswerCache = ModelCache[GuideAnswer]


def answer_cache_key(query: str, role: str, language: str, docs_version: str) -> str:
    return hashlib.sha256(f"{normalize(query).folded}|{role}|{language}|{docs_version}".encode()).hexdigest()


def corpus_version(chunks: list[DocChunk]) -> str:
    versions = {chunk.docs_version for chunk in chunks}
    if len(versions) == 1 and "" not in versions:
        return next(iter(versions))
    # Pre-migration indexes and injected retrievers have no corpus stamp. Hash
    # their actual guide models, rather than share a constant stale-cache key.
    return hashlib.sha256(
        json.dumps([chunk.model_dump() for chunk in sorted(chunks, key=lambda c: c.chunk_id)], sort_keys=True).encode()
    ).hexdigest()


def answer_language(message: str) -> str:
    return "en" if detect_language(message) == "en" else "vi"


def capability_menu(language: str, role: str) -> str:
    if language == "en":
        topics = (
            "uploading CVs, using the JD library, CV–JD analysis, interview practice, history and sharing"
            if role == "student"
            else "the advisor overview and assigned students"
        )
        return (
            "The CareerV usage guide does not cover this question. I can explain "
            + topics
            + ", highlight a registered control, or navigate to an allowed page. Which feature do you need help with?"
        )
    topics = (
        "tải CV, Thư viện JD, phân tích CV–JD, luyện phỏng vấn, lịch sử và chia sẻ"
        if role == "student"
        else "trang tổng quan cố vấn và danh sách sinh viên phụ trách"
    )
    return (
        "Tài liệu hướng dẫn CareerV chưa có thông tin phù hợp cho câu hỏi này. Tôi có thể hướng dẫn "
        + topics
        + ", chỉ vị trí nút hoặc mở trang được phép. Bạn cần hỗ trợ tính năng nào?"
    )


def attached_actions(metadata: AttachmentMetadata, role: str, current_route: str) -> list[UIAction]:
    """Only the top retrieved chunk can authorize a static registered target."""
    if metadata.score < get_settings().rag_ui_threshold:
        return []
    try:
        if metadata.ui_targets:
            element = require_element(metadata.ui_targets[0], role)
            if metadata.route_id and metadata.route_id != element.route_id:
                return []
            destination = resolve_route(element.route_id, {}, role)
            actions: list[UIAction] = []
            if current_route != destination:
                actions.append(UINavigate(route_id=element.route_id))
            actions.append(UIHighlight(element_id=element.element_id))
        elif metadata.route_id:
            resolve_route(metadata.route_id, {}, role)
            actions = [UINavigate(route_id=metadata.route_id)]
        else:
            return []
        return validate_ui_actions(actions, role)
    except ValueError:
        return []


def safe_guide_output(message: str, documents: list[str] | None = None) -> bool:
    """Conservative backstop for personal assertions/forged links, before caching.

    The grounding prompt is primary; this is not a semantic truth verifier.
    Impersonal instructions avoid ambiguous personal claims in either language.
    Bold labels quoted verbatim from the cited guides (e.g. the page "**CV của tôi**")
    are UI names, not claims about the user, so they are excluded from the check.
    """
    checked = message
    if documents:
        guides = "\n".join(documents)
        checked = re.sub(
            r"\*\*([^*\n]{1,80})\*\*", lambda m: " " if m.group(1).strip() in guides else m.group(0), message
        )
    text = normalize(checked).folded
    return bool(message.strip()) and not re.search(
        r"\b(?:your|yours|my|mine)\b|\bcua\s+(?:rieng\s+)?(?:ban|toi)\b"
        r"|\byou\s+(?:have|uploaded|scored|completed|lack|are missing)\b"
        r"|\bban\s+(?:da|dang)\b|\bban\s+co\s+\d"
        r"|\bi\s+(?:checked|read|reviewed|accessed|found|see|can see)\b"
        r"|\btoi\s+(?:da\s+)?(?:doc|xem|thay|kiem tra|phan tich)\b"
        r"|https?://|\]\s*\(|\[\^?\d+\]|data-(?:agent-target|assistant-id)",
        text,
    )
