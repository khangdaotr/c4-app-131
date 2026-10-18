"""LangGraph Assistant: intent -> role-aware retrieval -> validated response."""

import json
import logging
import re
from collections.abc import Callable
from contextvars import ContextVar
from functools import lru_cache
from html import escape
from typing import Any, Literal, TypedDict
from urllib.parse import urlsplit
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from src.config import get_settings
from src.models.assistant import (
    ROUTES,
    AgentAction,
    AnalysisAction,
    AssistantChip,
    AssistantLlmOutput,
    AssistantResponse,
    ClientPageContext,
    HighlightAction,
    Intent,
    NavigateAction,
    ResetAction,
    SourceCitation,
    clean_citation_snippet,
    route_allowed,
    validate_llm_actions,
)
from src.prompts.assistant_prompts import ASSISTANT_SYSTEM_PROMPT, HOWTO_SYSTEM_PROMPT
from src.services.assistant.chunker import DocChunk
from src.services.assistant.guardrails import (
    has_careerv_topic,
    is_chitchat,
    is_refusal_response,
    is_role_forbidden,
)
from src.services.assistant.howto import (
    AnswerCache,
    AttachmentMetadata,
    GuideAnswer,
    answer_cache_key,
    answer_language,
    attached_actions,
    capability_menu,
    corpus_version,
    safe_guide_output,
)
from src.services.assistant.hybrid_search import (
    ASSISTANT_INDEX_LOCK,
    AssistantHybridRetriever,
    get_assistant_retriever,
    select_citation_chunks,
)
from src.services.assistant.locate import locate_actions
from src.services.assistant.router import LocalRouter
from src.services.assistant.router.models import LocateSlots, NavSlots, RouterDecision
from src.services.assistant.text import fold_diacritics as normalized
from src.services.llm import assistant_llm_configured as llm_configured
from src.services.llm import get_assistant_llm
from src.services.privacy.types import MaskingError
from src.services.providers.gateway import GatewayError, provider_scope, wrap_chat
from src.services.providers.llm_client import ContentDelta, Done, LlmClient

logger = logging.getLogger(__name__)
_event_sink: ContextVar[Callable[[str, dict[str, Any]], None] | None] = ContextVar("assistant_events", default=None)


def _result_metric(message: str) -> str | None:
    from src.services.assistant.router.data import LEXICONS
    from src.services.assistant.router.matching import SurfaceText, matches

    folded = SurfaceText(message).folded
    found = [name for name, phrases in LEXICONS["metrics"].items() if matches(folded, phrases)]
    return found[0] if len(found) == 1 else None


def _facts_card_values(facts: dict[str, Any], record_type: str) -> dict[str, str | int | float | None]:
    values: dict[str, str | int | float | None] = {}
    for key, value in facts.items():
        if key == "category_scores" and isinstance(value, list):
            for category in value:
                if not isinstance(category, dict):
                    continue
                prefix = str(category.get("importance", "category"))
                for field in ("total", "matched", "partial", "missing", "earned", "possible"):
                    if category.get(field) is not None:
                        values[f"{prefix}_{field}"] = category[field]
        elif key == "missing_skills" and isinstance(value, list):
            values.update({f"missing_skill_{index}": skill for index, skill in enumerate(value[:5], 1)})
        elif isinstance(value, (str, int, float)) or value is None:
            values[key] = value
    return values


def emit_event(name: str, data: dict[str, Any]) -> None:
    sink = _event_sink.get()
    if sink is not None:
        sink(name, data)


def classify_intent(message: str) -> Intent:
    """An imperative is distinct from asking how to perform an action."""
    text = normalized(message)
    command = bool(
        re.search(
            r"(?:^|[.!?;\n]\s*|\bva\s+)(?:hay\s+|vui long\s+)?"
            r"(?:mo\b|chuyen\b|dieu huong\b|loc\b|tim\b|dien\b|chon\b|cuon\b|dat lai\b|"
            r"khoi phuc\b|bat dau\b|phan tich\b|highlight\b|reset\b)",
            text,
        )
        or re.search(r"\b(?:mo|chuyen|loc|dien|chon|cuon)\s+giup\b", text)
    )
    if re.search(r"(?:^|[.!?;\n]\s*)(?:dung|khong duoc|khong can)\b", text):
        command = False
    question = bool(re.search(r"\b(?:lam sao|cach nao|huong dan|o dau|la gi|y nghia|tai sao|the nao)\b", text))
    return "hybrid" if command and question else "action" if command else "qa"


def _selector_key(selector: str) -> str:
    match = re.fullmatch(r"\[data-agent-target=['\"]([\w-]+)['\"]\]", selector)
    return match.group(1) if match else selector


class AssistantState(TypedDict, total=False):
    message: str
    decision: RouterDecision
    chip: AssistantChip | None
    locate_fallback: bool
    input_allowed: bool
    context: ClientPageContext
    history: list[dict[str, str]]
    allowed_student_ids: list[str]
    intent: Intent
    sources: list[SourceCitation]
    confidence: Literal["low", "high"]
    response: AssistantResponse
    retrieved_chunks: list[dict[str, Any]]
    masked_query: str
    docs_version: str
    howto: bool
    nav_db: Any
    nav_user: Any
    previous_targets: list[Any]


class AssistantAgent:
    def __init__(self, retriever: AssistantHybridRetriever | None = None, llm: Any = None) -> None:
        self._retriever = retriever
        self._llm = llm
        self._ui_router: LocalRouter | None = None
        settings = get_settings()
        self.answer_cache = AnswerCache(
            maxsize=settings.rag_answer_cache_maxsize, ttl_s=settings.rag_answer_cache_ttl_s
        )
        builder = StateGraph(AssistantState)
        builder.add_node("inspect", self._inspect)
        builder.add_node("agent", self._agent_path)
        builder.add_node("classify", self._classify)
        builder.add_node("retrieve", self._retrieve)
        builder.add_node("generate", self._generate)
        builder.add_edge(START, "inspect")
        builder.add_conditional_edges(
            "inspect", self._next_after_inspect, {"classify": "classify", "agent": "agent", "end": END}
        )
        builder.add_edge("agent", END)
        builder.add_edge("classify", "retrieve")
        builder.add_edge("retrieve", "generate")
        builder.add_edge("generate", END)
        self.graph = builder.compile()

    @staticmethod
    def _next_after_inspect(state: AssistantState) -> str:
        decision = state.get("decision")
        if not state["input_allowed"]:
            return "end"
        if decision and decision.route in {"navigate", "result"} and decision.nav_mode == "agent":
            return "agent"
        return "classify"

    async def _agent_path(self, state: AssistantState) -> dict[str, Any]:
        from src.services.assistant.agent_path import run_agent_path

        decision = state["decision"]
        response = await run_agent_path(
            message=state["message"],
            db=state.get("nav_db"),
            user=state.get("nav_user"),
            context=state["context"],
            route_kind=decision.route,
            llm=self._llm if isinstance(self._llm, LlmClient) or hasattr(self._llm, "chat") else None,
            retriever=self._retriever,
        )
        return {"response": response}

    def _inspect(self, state: AssistantState) -> dict[str, Any]:
        context = state["context"]
        if self._ui_router is None:
            self._ui_router = LocalRouter()
        decision = self._ui_router.decide(
            state["message"],
            role=context.user_role,
            page_route_id=context.route,
            previous_targets=state.get("previous_targets", ()),
        )
        chip = state.get("chip")
        if chip is not None:
            slots = (
                LocateSlots.model_validate(chip.slots)
                if chip.route == "locate"
                else NavSlots.model_validate(chip.slots)
            )
            decision = RouterDecision(
                route=chip.route,
                source="rules",
                confidence=1.0,
                language=decision.language,
                slots=slots,
                nav_mode="fast" if chip.route == "navigate" else None,
            )
        emit_event("route", decision.model_dump(mode="json"))
        language = "en" if decision.language == "en" else "vi"
        response = None
        if decision.route == "smalltalk":
            response = AssistantResponse(
                message="Hello! How can I help you use CareerV?"
                if language == "en"
                else "Chào bạn! Tôi có thể giúp bạn sử dụng CareerV như thế nào?",
                intent="qa",
            )
        elif decision.route == "deny":
            response = AssistantResponse(
                message="I can only help with permitted CareerV features. Please choose a feature from the usage guide."
                if language == "en"
                else "Xin lỗi, tôi chỉ hỗ trợ các tính năng CareerV được phép. Bạn hãy chọn tính năng cần hướng dẫn.",
                intent="qa",
            )
        elif decision.route == "clarify":
            response = AssistantResponse(
                message=decision.clarify_question,
                intent="qa",
                chips=[chip.model_dump(mode="json") for chip in decision.chips],
            )
        elif decision.route == "navigate" and decision.nav_mode == "fast":
            response = self._resolve_navigation(state, decision, language)
        elif decision.route == "result" and decision.nav_mode == "fast":
            response = self._resolve_result(state, decision, language)
        elif decision.route in {"navigate", "result"} and decision.nav_mode == "agent":
            response = None
        elif decision.route in {"navigate", "result"}:
            response = AssistantResponse(message=capability_menu(language, context.user_role), intent="qa")
        elif decision.route == "locate":
            actions = locate_actions(state["message"], context.user_role, context.route)
            if actions:
                response = AssistantResponse(
                    message="Here is the control you are looking for."
                    if language == "en"
                    else "Đây là nút bạn cần tìm.",
                    intent="action",
                    ui_actions=actions,
                )
        return {
            "decision": decision,
            "input_allowed": response is None,
            "response": response,
            "howto": True,
            "locate_fallback": decision.route == "locate",
            "intent": "qa",
        }

    @staticmethod
    def _resolve_result(state: AssistantState, decision: RouterDecision, language: str) -> AssistantResponse:
        from src.services.assistant.facts import get_result_facts
        from src.services.assistant.resolvers import ResolutionContext, resolve
        from src.services.assistant.router.matching import SurfaceText
        from src.services.assistant.ui_registry import resolve_route

        user, db, slots = state.get("nav_user"), state.get("nav_db"), decision.slots
        lang = "en" if language == "en" else "vi"
        templates = {
            "en": {
                "none": "I couldn’t find a matching record. Here are nearby options you can open.",
                "multiple": "Choose a result below to see its figures.",
                "role": "Result records are available only to student accounts.",
                "facts": "Result figures",
                "latest": "Latest result for {label} ({date}): {metric} {value}.",
                "value": "For {label} ({date}), {metric} {value}.",
                "metric_score": "match score",
                "metric_status": "status",
                "metric_count": "count",
                "metric_date": "date",
                "unknown": "I couldn’t read the stored result figures.",
            },
            "vi": {
                "none": "Không tìm thấy hồ sơ phù hợp. Đây là một số lựa chọn gần nhất để mở.",
                "multiple": "Hãy chọn một kết quả bên dưới để xem các số liệu.",
                "role": "Kết quả hồ sơ chỉ dành cho tài khoản sinh viên.",
                "facts": "Số liệu kết quả",
                "latest": "Kết quả gần nhất cho {label} ({date}): {metric} {value}.",
                "value": "Với {label} ({date}), {metric} {value}.",
                "metric_score": "điểm match",
                "metric_status": "trạng thái",
                "metric_count": "số lượng",
                "metric_date": "ngày",
                "unknown": "Không đọc được số liệu kết quả đã lưu.",
            },
        }
        if user is None or db is None or user.role != "student" or not isinstance(slots, NavSlots):
            return AssistantResponse(message=templates[lang]["role"], intent="qa", route="result")
        emit_event("status", {"status": "resolving"})
        resolved = resolve(ResolutionContext(user=user, db=db), slots)
        if resolved.status == "none":
            return AssistantResponse(
                message=templates[lang]["none"],
                intent="qa",
                route="result",
                chips=[
                    {
                        "label": target.label[:200],
                        "route": "navigate",
                        "slots": {},
                        "route_id": target.route_id,
                        "params": target.params,
                    }
                    for target in resolved.targets[:4]
                ],
            )
        if resolved.status in {"multiple", "needs_info"}:
            return AssistantResponse(
                message=templates[lang]["multiple"],
                intent="qa",
                route="result",
                chips=[
                    {
                        "label": target.label[:200],
                        "route": "navigate",
                        "slots": {},
                        "route_id": target.route_id,
                        "params": target.params,
                    }
                    for target in resolved.targets[:5]
                ],
            )
        target = resolved.targets[0]
        record_id = target.params.get("analysis_id") or target.params.get("session_id")
        record_type = "analysis" if "analysis_id" in target.params else "interview"
        facts = get_result_facts(db, user.id, record_type, record_id or "")
        if facts is None:
            return AssistantResponse(message=templates[lang]["none"], intent="qa", route="result")
        resolve_route(target.route_id, target.params, user.role)
        metric_key = _result_metric(state.get("message", ""))
        folded_question = SurfaceText(state.get("message", "")).folded
        metric_value: Any = None
        metric_label = templates[lang][f"metric_{metric_key}"] if metric_key else ""
        if metric_key == "score":
            if record_type == "analysis":
                importance = next((item for item in ("required", "preferred") if item in folded_question), None)
                category = (
                    next(
                        (item for item in facts.get("category_scores", []) if item.get("importance") == importance),
                        None,
                    )
                    if importance
                    else None
                )
                if category:
                    metric_value = f"{category['earned']}/{category['possible']}"
                    importance_label = (
                        importance if lang == "en" else ("bắt buộc" if importance == "required" else "ưu tiên")
                    )
                    metric_label = (
                        f"{importance_label} earned/possible" if lang == "en" else f"tỉ lệ {importance_label} đạt/tổng"
                    )
                else:
                    metric_value = facts.get("overall_match_score")
            else:
                criterion = next(
                    (item for item in ("situation", "task", "action", "result") if item in folded_question), None
                )
                metric_value = facts.get(f"{criterion}_average") if criterion else facts.get("overall_star_score")
                if criterion:
                    metric_label = f"{criterion} STAR score" if lang == "en" else f"điểm STAR {criterion}"
                else:
                    metric_label = "STAR score" if lang == "en" else "điểm STAR"
        elif metric_key == "status":
            metric_value = facts.get("status")
        elif metric_key == "date":
            metric_value = facts.get("created_at") if record_type == "analysis" else facts.get("started_at")
        elif metric_key == "count":
            if record_type == "interview":
                metric_value = facts.get("question_count")
            else:
                importance = next((item for item in ("required", "preferred") if item in folded_question), None)
                measure = next(
                    (item for item in ("missing", "partial", "matched") if item in folded_question),
                    "missing",
                )
                matches_filter = any(word in folded_question for word in ("matched", "match", "dat", "ach duoc"))
                if matches_filter:
                    measure = "matched"
                if importance:
                    metric_value = facts.get(f"{importance}_{measure}_count")
                    if lang == "en":
                        metric_label = f"{importance} {measure} count"
                    else:
                        importance_label = "bắt buộc" if importance == "required" else "ưu tiên"
                        measure_label = {"missing": "thiếu", "partial": "một phần", "matched": "đạt"}[measure]
                        metric_label = f"số lượng {measure_label} {importance_label}"
                else:
                    required_count = facts.get(f"required_{measure}_count", 0)
                    preferred_count = facts.get(f"preferred_{measure}_count", 0)
                    metric_value = (
                        f"{required_count} required; {preferred_count} preferred"
                        if lang == "en"
                        else f"{required_count} bắt buộc; {preferred_count} ưu tiên"
                    )
                    measure_label = {"missing": "missing", "partial": "partial", "matched": "matched"}[measure]
                    metric_label = f"{measure_label} counts" if lang == "en" else f"số lượng {measure_label}"
        if metric_value is None:
            return AssistantResponse(message=templates[lang]["unknown"], intent="qa", route="result")
        label = facts.get("jd_label") if record_type == "analysis" else facts.get("position_label")
        if record_type == "analysis" and facts.get("cv_label"):
            label = f"{label}, CV {facts['cv_label']}"
        date_value = facts.get("created_at") if record_type == "analysis" else facts.get("started_at")
        date_label = str(date_value or "")[:10]
        value_label = f"{metric_value}%" if metric_key == "score" and record_type == "analysis" else str(metric_value)
        message = templates[lang]["latest" if slots.latest else "value"].format(
            label=label or "result", date=date_label, metric=metric_label, value=value_label
        )
        card_facts = _facts_card_values(facts, record_type)
        if record_type == "analysis" and "overall_match_score" in card_facts:
            card_facts["overall_match_score_percent"] = card_facts.pop("overall_match_score")
        return AssistantResponse(
            message=message,
            intent="qa",
            route="result",
            cards=[
                {
                    "ref": f"facts-{target.ref}",
                    "label": templates[lang]["facts"],
                    "route_id": target.route_id,
                    "params": target.params,
                    "kind": "facts",
                    "facts": card_facts,
                },
                {
                    "ref": target.ref,
                    "label": (label or target.label)[:200],
                    "sublabel": (target.sublabel or date_label)[:300],
                    "route_id": target.route_id,
                    "params": target.params,
                    "kind": "link",
                },
            ],
        )

    @staticmethod
    def _resolve_navigation(state: AssistantState, decision: RouterDecision, language: str) -> AssistantResponse:
        from src.services.assistant.resolvers import ResolutionContext, ResolveResult, Target, resolve
        from src.services.assistant.ui_registry import load_routes, resolve_route

        slots = decision.slots
        user = state.get("nav_user")
        db = state.get("nav_db")
        if decision.card_target is not None:
            result = ResolveResult(
                status="found",
                targets=[
                    Target(
                        ref=decision.card_target.ref,
                        route_id=decision.card_target.route_id,
                        params=decision.card_target.params,
                        label=decision.card_target.label,
                    )
                ],
            )
        elif user is None or db is None or not isinstance(slots, NavSlots):
            result = None
        elif user.role != "student" and slots.target != "page":
            result = None
        else:
            emit_event("status", {"status": "resolving"})
            result = resolve(ResolutionContext(user=user, db=db), slots)

        templates = {
            "en": {
                "found": "I found the requested page. You can open it now.",
                "multiple": "I found a few possible matches. Choose one to open.",
                "none": "I couldn’t find a matching record. Here are nearby options you can open.",
                "needs_info": "Please choose which page you want to open.",
                "role": "Record navigation is available for student accounts. I can open permitted pages for your role.",
            },
            "vi": {
                "found": "Đã tìm thấy trang phù hợp. Bạn có thể mở trang này.",
                "multiple": "Có một vài kết quả phù hợp. Hãy chọn kết quả muốn mở.",
                "none": "Không tìm thấy hồ sơ phù hợp. Đây là một số lựa chọn gần nhất để mở.",
                "needs_info": "Hãy chọn trang bạn muốn mở.",
                "role": "Điều hướng đến hồ sơ chỉ dành cho tài khoản sinh viên. Tôi có thể mở các trang được phép cho vai trò của bạn.",
            },
        }
        language = "en" if language == "en" else "vi"
        if result is None:
            return AssistantResponse(message=templates[language]["role"], intent="qa", route="navigate")

        cards = (
            [
                {
                    "ref": target.ref,
                    "label": target.label,
                    "sublabel": target.sublabel,
                    "route_id": target.route_id,
                    "params": target.params,
                }
                for target in result.targets[:5]
            ]
            if result.status == "found"
            else []
        )
        chips = []
        chip_targets = result.targets[:5]
        if result.status == "needs_info":
            defaults = ("cv_list", "jd_list", "analysis_new", "interview_history")
            chip_targets = [
                Target(
                    ref=f"page-{route_id}",
                    route_id=route_id,
                    params={},
                    label=(load_routes()[route_id].labels_en or [route_id])[0],
                )
                for route_id in defaults
                if route_id in load_routes() and user is not None and user.role in load_routes()[route_id].roles
            ]
        if result.status in {"multiple", "none", "needs_info"}:
            chips = [
                {
                    "label": target.label,
                    "route": "navigate",
                    "slots": {},
                    "route_id": target.route_id,
                    "params": target.params,
                }
                for target in chip_targets[:5]
            ]
        if result.status == "none" and isinstance(slots, NavSlots):
            target_name = {
                "cv": ("CV", "CV"),
                "jd": ("JD", "JD"),
                "analysis": ("analysis", "phân tích"),
                "interview": ("interview", "buổi phỏng vấn"),
                "report": ("interview", "buổi phỏng vấn"),
            }.get(slots.target, ("record", "hồ sơ"))
            qualifier = slots.when_expr or slots.jd_ref or slots.cv_ref or slots.free_ref
            if qualifier:
                message = (
                    f"I couldn’t find a {target_name[0]} matching {qualifier}. Here are nearby options you can open."
                    if language == "en"
                    else f"Không tìm thấy {target_name[1]} phù hợp với {qualifier}. Đây là các lựa chọn gần nhất để mở."
                )
            else:
                message = templates[language]["none"]
        else:
            message = templates[language][result.status]
        actions = []
        if result.status == "found" and result.targets:
            target = result.targets[0]
            # The API revalidates role and owner before dispatch.
            if user is not None:
                resolve_route(target.route_id, target.params, user.role)
            actions = [{"type": "navigate", "route_id": target.route_id, "params": target.params}]
        return AssistantResponse(
            message=message,
            intent="qa",
            route="navigate",
            cards=cards,
            chips=chips,
            ui_actions=actions,
        )

    def _classify(self, state: AssistantState) -> dict[str, Any]:
        return {"intent": "qa"}

    def _retrieve(self, state: AssistantState) -> dict[str, Any]:
        context = state["context"]
        emit_event("status", {"status": "searching"})
        try:
            # Reindex shares this lock so search never sees a partially replaced collection.
            with ASSISTANT_INDEX_LOCK:
                retriever = self._retriever or get_assistant_retriever()
                with provider_scope(mask_only=True) as scope:
                    # The masker escapes ampersands for wire/XML safety. Search
                    # keeps their original meaning, without restoring any PII.
                    query = scope.mask_text(state["message"]).replace("&amp;", "&")
                chunks = retriever.search(query, context.user_role, route=context.route)
        except (MaskingError, GatewayError):
            return {
                "sources": [],
                "confidence": "low",
                "response": AssistantResponse(
                    message="Trợ lý tạm thời chưa thể xử lý an toàn. Bạn vui lòng thử lại sau.",
                    intent=state["intent"],
                    actions=[],
                    sources=[],
                ),
            }
        except Exception as exc:
            logger.warning("Assistant retrieval unavailable (%s)", type(exc).__name__)
            return {"sources": [], "confidence": "low"}
        usable = [
            chunk
            for chunk in chunks
            if chunk.get("role") in (context.user_role, "all")
            and route_allowed(chunk.get("route", ""), context.user_role)
        ]
        selected = select_citation_chunks(usable)
        embedding = getattr(getattr(retriever, "vector_store", None), "embedding_service", None)
        embedding_id = getattr(embedding, "embedding_id", "")
        # E5 cosine confidence and the hashing fallback have different scales.
        # Gate only the top result here; leave citation ranking/cutoffs intact.
        if (
            isinstance(embedding_id, str)
            and embedding_id.startswith("e5:")
            and selected
            and selected[0].get("abstain_score", selected[0]["score"]) < get_settings().rag_semantic_abstain_threshold
        ):
            selected = []
        sources = [
            SourceCitation(
                chunk_id=chunk["chunk_id"],
                title=chunk["title"],
                route=chunk["route"],
                section=chunk["section"],
                snippet=clean_citation_snippet(chunk["content"])[:500],
                selector=chunk.get("selector"),
            )
            for chunk in selected
        ]
        corpus = getattr(retriever, "chunks", None)
        if not isinstance(corpus, list) or any(not isinstance(chunk, DocChunk) for chunk in corpus):
            corpus = [DocChunk.model_validate(chunk) for chunk in selected]
        return {
            "sources": sources,
            "confidence": "high" if sources else "low",
            "retrieved_chunks": selected,
            "masked_query": query,
            "docs_version": corpus_version(corpus),
        }

    def _target_route(self, state: AssistantState) -> str | None:
        text = normalized(state["message"])
        role = state["context"].user_role
        explicit = re.search(r"/(?:student|advisor)(?:/[\w-]+)*", text)
        if explicit:
            route = explicit.group(0)
            return route if route_allowed(route, role) else None
        if role == "student":
            if is_role_forbidden(text, role):
                return None
            choices = [
                (("lich su", "history", "tien bo"), "/student/history"),
                (("chia se", "sharing", "share"), "/student/share"),
                (("thu vien", "library", "them jd", "jd cua ban"), "/student/library"),
                (("phan tich", "analysis", "match score", "match-score", "khoang cach", "jd"), "/student/analysis"),
                (("phong van", "interview", "star"), "/student/interview"),
                (("cv", "ho so"), "/student/cv"),
                (("cai dat", "settings"), "/student/settings"),
            ]
        else:
            choices = [
                (("sinh vien", "students", "nguy co", "at-risk", "can chu y"), "/advisor/students"),
                (("nhan xet", "reviews"), "/advisor/reviews"),
                (("thong ke", "analytics"), "/advisor/analytics"),
                (("tong quan", "dashboard"), "/advisor/dashboard"),
                (("cai dat", "settings"), "/advisor/settings"),
            ]
        return next((route for words, route in choices if any(word in text for word in words)), None)

    def _fallback(self, state: AssistantState) -> AssistantResponse:
        context = state["context"]
        sources = state["sources"]
        chitchat, reply = is_chitchat(state["message"])
        if chitchat:
            return AssistantResponse(message=reply, intent="qa", actions=[], sources=[])
        if state["confidence"] != "high" or not sources or not has_careerv_topic(state["message"]):
            return AssistantResponse(
                message="Xin lỗi, tôi chưa tìm thấy tài liệu phù hợp để trả lời câu hỏi này trong hệ thống CareerV.",
                intent=state["intent"],
                actions=[],
                sources=[],
            )
        text = normalized(state["message"])
        route = self._target_route(state)
        actions: list[AgentAction] = []
        if state["intent"] != "qa" and route is not None:
            actions.append(NavigateAction(params={"route": route}, description_vi=f"Mở trang {route}"))
        if state["intent"] != "qa" and re.search(r"\b(?:dat lai|khoi phuc|reset)\b", text):
            actions.append(ResetAction(description_vi="Khôi phục bộ lọc và đóng các hộp thoại"))
        if state["intent"] != "qa" and "bat dau phan tich" in text and context.user_role == "student":
            jd_id = context.page_state.get("selected_jd_id") or context.page_state.get("jd_id")
            if context.selected_cv_id and isinstance(jd_id, str):
                actions.append(
                    AnalysisAction(
                        params={"cv_id": context.selected_cv_id, "jd_id": jd_id},
                        description_vi="Bắt đầu phân tích CV với JD đã chọn",
                    )
                )
        target_sources = [source for source in sources if source.selector and (route is None or source.route == route)]
        if target_sources and re.search(r"\b(?:nut|o dau|chi toi|highlight)\b", text):
            source = target_sources[0]
            if source.route != context.route and not any(a.action_type == "NAVIGATE_PAGE" for a in actions):
                actions.append(NavigateAction(params={"route": source.route}, description_vi="Mở trang có nút cần tìm"))
            actions.append(
                HighlightAction(params={"selector": source.selector}, description_vi="Chỉ vị trí nút trong hướng dẫn")
            )
        # Nguồn đã hiện riêng dưới câu trả lời ("Theo hướng dẫn: …"), nên chỉ trích hai đoạn sát nhất.
        message = "Theo tài liệu hướng dẫn:\n\n" + "\n\n".join(source.snippet for source in sources[:2])
        if any(action.action_type == "START_ANALYSIS" for action in actions):
            message += "\n\nVui lòng xác nhận trước khi bắt đầu phân tích."
        return AssistantResponse(message=message, intent=state["intent"], actions=actions, sources=sources)

    def _guard(self, response: AssistantResponse, state: AssistantState) -> AssistantResponse:
        if state.get("locate_fallback"):
            return response.model_copy(update={"actions": [], "ui_actions": [], "intent": "qa"})
        if is_refusal_response(response.message):
            return AssistantResponse(message=response.message, intent=state["intent"], actions=[], sources=[])
        context = state["context"]
        selectors = {_selector_key(source.selector) for source in state["sources"] if source.selector}
        filters = {
            "student": {"keyword", "type", "position", "date_range", "status", "active_tab"},
            "advisor": {"keyword", "status", "major", "cohort", "readiness", "score_max"},
        }
        modals = {
            "student": {"upload-cv-modal", "feedback-modal"},
            "advisor": {"feedback-modal", "student-review-modal"},
        }
        safe: list[AgentAction] = []
        for action in response.actions:
            if re.search(r"(?:^|[.!?;\n]\s*)(?:dung|khong duoc|khong can)\b", normalized(state["message"])):
                continue
            if action.action_type == "NAVIGATE_PAGE" and not route_allowed(action.params.route, context.user_role):
                continue
            if action.action_type in ("HIGHLIGHT_ELEMENT", "SCROLL_TO"):
                selector = action.params.selector
                if selector is not None and _selector_key(selector) not in selectors:
                    continue
            if action.action_type == "FILL_FILTER" and action.params.filter_name not in filters[context.user_role]:
                continue
            if action.action_type == "OPEN_MODAL" and action.params.modal_id not in modals[context.user_role]:
                continue
            if action.action_type == "SELECT_STUDENT":
                if context.user_role != "advisor" or action.params.student_id not in state["allowed_student_ids"]:
                    continue
            if action.action_type == "START_ANALYSIS":
                jd_id = context.page_state.get("selected_jd_id") or context.page_state.get("jd_id")
                if (
                    context.user_role != "student"
                    or state["intent"] == "qa"
                    or action.params.cv_id != context.selected_cv_id
                    or action.params.jd_id != jd_id
                ):
                    continue
            # IDs are generated by the server, never taken from model output/history.
            safe.append(action.model_copy(update={"id": str(uuid4())}))
        return AssistantResponse(
            message=response.message, intent=state["intent"], actions=safe, sources=response.sources
        )

    async def _generate_howto(self, state: AssistantState) -> AssistantResponse:
        context = state["context"]
        language = answer_language(state["message"])
        fallback = AssistantResponse(message=capability_menu(language, context.user_role), intent="qa")
        if state.get("response"):
            return state["response"]
        if not state["sources"]:
            return fallback
        key = answer_cache_key(state["masked_query"], context.user_role, language, state["docs_version"])
        cached = self.answer_cache.get(key)
        if cached is not None:
            return AssistantResponse(
                message=cached.message,
                intent="qa",
                sources=cached.sources,
                ui_actions=attached_actions(cached.attachment, context.user_role, context.route),
            )
        if self._llm is None and not llm_configured():
            # Keep the existing offline excerpt fallback, with no legacy actions.
            return self._fallback(state).model_copy(update={"intent": "qa", "actions": [], "ui_actions": []})
        client = self._llm if self._llm is not None else get_assistant_llm()
        stream = None
        text = ""
        try:
            with provider_scope(mask_only=True) as scope:
                data = scope.mask_payload(
                    {
                        "question": state["message"],
                        "history": json.dumps(state["history"][-4:], ensure_ascii=False),
                        "documents": [clean_citation_snippet(chunk["content"]) for chunk in state["retrieved_chunks"]],
                    }
                )
                prompt = (
                    f"<untrusted_user_query>{escape(data['question'], quote=False)}</untrusted_user_query>\n"
                    f"<untrusted_chat_history>{escape(data['history'], quote=False)}</untrusted_chat_history>\n"
                    + "\n".join(
                        f"<untrusted_document>{escape(doc, quote=False)}</untrusted_document>"
                        for doc in data["documents"]
                    )
                )
                messages = [
                    {
                        "role": "system",
                        "content": scope.mask_text(
                            HOWTO_SYSTEM_PROMPT.format(language="English" if language == "en" else "Vietnamese"),
                            wire=True,
                            detect_names=False,
                        ),
                    },
                    {"role": "user", "content": prompt},
                ]
                text, done = "", False
                stream = client.chat_stream(
                    scope.prepared(messages),
                    thinking=False,
                    model=get_settings().llm_model_agent,
                    temperature=0,
                    stream_text=_event_sink.get() is not None,
                )
                async for event in stream:
                    if isinstance(event, ContentDelta):
                        text += event.text
                        emit_event("token", {"text": event.text})
                    elif isinstance(event, Done):
                        if event.message.get("tool_calls"):
                            raise GatewayError("Unexpected how-to tool call")
                        done = True
                if not done:
                    raise GatewayError("Incomplete how-to response")
                text = scope.sanitize_output(text)
                if not safe_guide_output(text):
                    if _event_sink.get() is not None and text:
                        emit_event(
                            "notice",
                            {
                                "code": "grounding_advisory",
                                "message": "Please verify this answer against the cited guide.",
                            },
                        )
                        return AssistantResponse(
                            message=text,
                            intent="qa",
                            sources=state["sources"],
                            ui_actions=attached_actions(
                                AttachmentMetadata.model_validate(state["retrieved_chunks"][0]),
                                context.user_role,
                                context.route,
                            ),
                        )
                    return fallback
                if is_refusal_response(text):
                    return AssistantResponse(message=text, intent="qa")
                top = state["retrieved_chunks"][0]
                answer = GuideAnswer(
                    message=text,
                    sources=state["sources"],
                    attachment=AttachmentMetadata.model_validate(top),
                )
                self.answer_cache.put(key, answer)
                return AssistantResponse(
                    message=answer.message,
                    intent="qa",
                    sources=answer.sources,
                    ui_actions=attached_actions(answer.attachment, context.user_role, context.route),
                )
        except (MaskingError, GatewayError) as error:
            if _event_sink.get() is not None and text:
                raise
            if isinstance(error, MaskingError) or error.stage in {"mask", "egress", "response_mask"}:
                return AssistantResponse(
                    message="Trợ lý tạm thời chưa thể xử lý an toàn. Bạn vui lòng thử lại sau.", intent="qa"
                )
            return fallback
        except Exception:
            if _event_sink.get() is not None and text:
                raise
            logger.warning("Assistant how-to generation unavailable")
            return fallback
        finally:
            if stream is not None:
                await stream.aclose()
            if self._llm is None:
                await client.aclose()

    async def _generate(self, state: AssistantState) -> dict[str, Any]:
        if (state["intent"] == "qa" or state.get("howto")) and (self._llm is None or isinstance(self._llm, LlmClient)):
            return {"response": await self._generate_howto(state)}
        if not state.get("response") and not state["sources"] and state["intent"] == "qa":
            return {
                "response": AssistantResponse(
                    message=capability_menu(answer_language(state["message"]), state["context"].user_role),
                    intent="qa",
                )
            }
        response = state.get("response") or self._fallback(state)
        if not response.sources:
            return {"response": response}
        if state["confidence"] == "high" and state["sources"] and (self._llm is not None or llm_configured()):
            context = state["context"]
            system = SystemMessage(
                content=ASSISTANT_SYSTEM_PROMPT.format(
                    user_role=context.user_role,
                    allowed_routes=sorted(ROUTES[context.user_role]),
                    intent=state["intent"],
                )
            )
            # History remains quoted data, never replayed as privileged model roles.
            # Escape every value so embedded closing tags cannot break isolation.
            # Browser page_state is arbitrary input and can include CV/JD bodies
            # or transcripts. Only the validated page/role hint goes outbound.
            outbound_context = context.model_copy(
                update={
                    "user_id": None,
                    "selected_cv_id": None,
                    "page_state": {},
                    "current_url": urlsplit(context.current_url).path,
                }
            )
            prompt_data = {
                "untrusted_user_query": state["message"],
                "untrusted_chat_history": json.dumps(state["history"][-4:], ensure_ascii=False),
                "untrusted_page_context": json.dumps(outbound_context.model_dump(), ensure_ascii=False),
                "allowed_student_ids": json.dumps(state["allowed_student_ids"], ensure_ascii=False),
                "retrieved_documents": json.dumps(
                    [source.model_dump() for source in state["sources"]], ensure_ascii=False
                ),
            }
            try:
                with provider_scope(mask_only=True) as scope:
                    # Escape/render only after privacy masking, preserving XML's
                    # single encoding layer and literal-placeholder protection.
                    masked_data = scope.mask_payload(prompt_data)
                    messages = [
                        system,
                        HumanMessage(
                            content="\n".join(
                                f"<{tag}>{escape(value.replace('&amp;', '&'), quote=False)}</{tag}>"
                                for tag, value in masked_data.items()
                            )
                        ),
                    ]
                    if self._llm is None or isinstance(self._llm, LlmClient):
                        client = self._llm if self._llm is not None else get_assistant_llm()
                        try:
                            raw = await client.chat(
                                scope.prepared(
                                    [
                                        {
                                            "role": "system",
                                            "content": scope.mask_text(system.content, wire=True, detect_names=False)
                                            + "\nReturn your response using assistant_response.",
                                        },
                                        {"role": "user", "content": messages[1].content},
                                    ]
                                ),
                                tools=[
                                    {
                                        "type": "function",
                                        "function": {
                                            "name": "assistant_response",
                                            "description": "Return the grounded assistant response.",
                                            "parameters": AssistantLlmOutput.model_json_schema(),
                                        },
                                    }
                                ],
                                thinking=False,
                                temperature=0,
                            )
                            calls = raw.get("tool_calls", [])
                            if calls:
                                if len(calls) != 1 or calls[0]["function"]["name"] != "assistant_response":
                                    raise GatewayError("Unexpected assistant response tool")
                                result = client.parse_tool_arguments(raw)[calls[0]["id"]]
                            else:
                                result = json.loads(raw.get("content", ""))
                        finally:
                            if self._llm is None:
                                await client.aclose()
                    else:
                        # Preserve the existing injected recording-backend seam;
                        # production assistant generation uses LlmClient above.
                        structured = wrap_chat(
                            self._llm, timeout=get_settings().assistant_llm_timeout_seconds
                        ).with_structured_output(AssistantLlmOutput, method="function_calling")
                        result = await structured.ainvoke(scope.prepared(messages))
                    result = (
                        result if isinstance(result, AssistantLlmOutput) else AssistantLlmOutput.model_validate(result)
                    )
                    result = scope.sanitize_output(result)
                    response = AssistantResponse(
                        message=result.message,
                        intent=result.intent,
                        actions=[] if result.is_refusal else validate_llm_actions(result.actions),
                        sources=[] if result.is_refusal else state["sources"],
                    )
            except (MaskingError, GatewayError) as error:
                if isinstance(error, MaskingError) or error.stage in {"mask", "egress", "response_mask"}:
                    response = AssistantResponse(
                        message="Trợ lý tạm thời chưa thể xử lý an toàn. Bạn vui lòng thử lại sau.",
                        intent=state["intent"],
                        actions=[],
                        sources=[],
                    )
                else:
                    logger.warning("Assistant generation unavailable; using grounded fallback")
            except Exception:
                logger.warning("Assistant generation unavailable; using grounded fallback")
        # Structured backends can supply prose, but v2 accepts no model-authored
        # legacy actions or model-owned intent.
        response = response.model_copy(update={"actions": [], "intent": "qa"})
        return {"response": self._guard(response, state)}

    async def respond(
        self,
        message: str,
        context: ClientPageContext,
        history: list[dict[str, str]] | None = None,
        allowed_student_ids: list[str] | None = None,
        event_sink: Callable[[str, dict[str, Any]], None] | None = None,
        chip: AssistantChip | None = None,
        nav_db: Any = None,
        nav_user: Any = None,
        previous_targets: list[Any] | None = None,
    ) -> AssistantResponse:
        token = _event_sink.set(event_sink)
        try:
            return await self._respond_graph(
                message, context, history, allowed_student_ids, chip, nav_db, nav_user, previous_targets
            )
        finally:
            _event_sink.reset(token)

    async def _respond_graph(
        self,
        message: str,
        context: ClientPageContext,
        history: list[dict[str, str]] | None,
        allowed_student_ids: list[str] | None,
        chip: AssistantChip | None,
        nav_db: Any = None,
        nav_user: Any = None,
        previous_targets: list[Any] | None = None,
    ) -> AssistantResponse:
        with provider_scope(user_id=getattr(nav_user, "id", None), mask_only=True):
            result = await self.graph.ainvoke(
                {
                    "message": message,
                    "chip": chip,
                    "context": context,
                    "history": history or [],
                    "allowed_student_ids": allowed_student_ids or [],
                    "nav_db": nav_db,
                    "nav_user": nav_user,
                    "previous_targets": previous_targets or [],
                },
                config={"callbacks": []},
            )
        return result["response"].model_copy(update={"route": result["decision"].route})


@lru_cache(maxsize=1)
def get_assistant_agent() -> AssistantAgent:
    return AssistantAgent()
