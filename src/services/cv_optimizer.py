"""
Trình tối ưu CV (US-SV-03, US-SV-05, PRD mục 6).

- Gợi ý viết lại được soạn riêng khi mở Trình tối ưu lần đầu (một lần gọi LLM chỉ để viết lại, lưu lại cho các lần
  sau; xem services/cv_rewrite.py), qua cùng các bước kiểm tra và guardrail grounding như gợi ý của bước phân tích.
  Không có LLM, hoặc phiên đã có quyết định trước khi có bước này, thì dùng gợi ý của lượt phân tích.
- SV chấp nhận / sửa tay / bỏ qua từng gợi ý; mọi quyết định được gom vào bản nháp và ghi Audit Trail (PRD 6.5). Gợi ý
  đã bỏ qua không được đề xuất lại (AC3).
- Kỹ năng JD yêu cầu mà CV chưa có: SV tự xác nhận; AI không tự thêm vào CV. Kỹ năng SV ghi là đang học chỉ vào mục
  "Kỹ năng đang phát triển", không nằm trong nội dung được chấm khi phân tích lại.
- "Hoàn tất" tạo đúng một phiên bản mới trong cùng CV (số phụ +1, ví dụ v1.1 → v1.2; không ghi đè bản cũ) kèm file
  DOCX, sau đó phiên tối ưu bị khoá. CV đang dùng thì bản mới tự thành bản đang dùng (xem services/cv_versions.py).
"""

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.errors import AppError
from src.db.models import CvEditAudit, CvExport, CvOptimization, CvVersion, GapAnalysis, JobDescription, User
from src.services import cv_files, cv_rewrite, cv_versions, llm
from src.services.cv_layout import SECTION_LABELS_EN, cv_language, layout_lines
from src.services.fit_summary import entry_title
from src.services.providers.gateway import provider_scope
from src.services.roadmap import get_roadmap_info
from src.services.skill_matching import (
    BULLET_PREFIX,
    IMPORTANCE_LABELS,
    SECTION_LABELS,
    contains_term,
    match_label,
    split_cv_lines,
    strip_bullet,
)

MAX_EDIT_CHARS = 600
MAX_CONTEXT_CHARS = 500
MAX_LEARNING_NOTE_CHARS = 120
# Câu AI viết từ kinh nghiệm SV kể (kỹ năng còn thiếu, chọn "Có, đã dùng")
MAX_SKILL_LINE_CHARS = 300
# Mục có thể chèn câu kinh nghiệm mới
ENTRY_BLOCKS = ("projects", "experience", "activities")
IMPORTANCE_ORDER = {"required": 0, "preferred": 1, "additional": 2}
STATUS_OF_ACTION = {"accept": "accepted", "edit": "edited", "reject": "rejected"}
DEVELOPING_TITLE = "Kỹ năng đang phát triển"

logger = logging.getLogger(__name__)


# ---------- Nội dung CV ----------


def cv_document(cv: CvVersion) -> dict[str, Any]:
    """
    Tách văn bản CV thành phần đầu (họ tên, liên hệ) và các mục; mỗi dòng giữ số dòng như lúc phân tích
    và mang loại dòng (kind, date, cont) để trình bày theo mẫu CV (src/services/cv_layout.py).
    """
    header: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_key = "header"
    lines = split_cv_lines(cv.content_text)
    layout = layout_lines(cv.content_text)
    lang = cv_language(cv.content_text, lines)
    labels = SECTION_LABELS_EN if lang == "en" else SECTION_LABELS
    for line in lines:
        item = {
            "id": f"l{line['line_no']}",
            "line_no": line["line_no"],
            "text": line["text"],
            **layout[line["line_no"]],
        }
        if line["is_heading"]:
            current = {"id": f"s{line['line_no']}", "title": line["text"], "lines": []}
            sections.append(current)
            current_key = line["block"]
        elif line["block"] == "header":
            if item["kind"] != "heading":
                header.append(item)
        else:
            # Mục viết cùng dòng với nội dung ("Kỹ năng: Python, SQL") không có dòng tiêu đề riêng
            if current is None or line["block"] != current_key:
                title = labels.get(line["block"], line["block"])
                current = {"id": f"s{line['line_no']}", "title": title, "lines": []}
                sections.append(current)
                current_key = line["block"]
            current["lines"].append(item)
    return {"header": header, "sections": sections, "developing_skills": cv.developing_skills or [], "lang": lang}


def apply_changes(
    text: str,
    replacements: dict[int, str],
    insertions: dict[int, list[str]] | None = None,
    removals: set[int] | None = None,
) -> str:
    """
    Thay các dòng theo số dòng (đếm như split_cv_lines), giữ nguyên ký tự đầu dòng và các dòng còn lại.
    insertions: thêm dòng mới ngay sau một dòng (câu kinh nghiệm SV xác nhận), cùng ký tự đầu dòng với dòng đó.
    removals: dòng nối của gạch ý bị ngắt dòng mà câu thay thế đã gộp vào (bỏ khỏi bản mới).
    """
    insertions = insertions or {}
    removals = removals or set()
    out: list[str] = []
    line_no = 0
    for raw in text.splitlines():
        if not strip_bullet(raw):
            out.append(raw)
            continue
        line_no += 1
        prefix = BULLET_PREFIX.match(raw)
        if line_no in removals:
            out.extend((prefix.group(0) if prefix else "") + extra for extra in insertions.get(line_no, []))
            continue
        out.append((prefix.group(0) if prefix else "") + replacements[line_no] if line_no in replacements else raw)
        # Câu mới theo đúng kiểu đầu dòng của dòng phía trên (có gạch đầu dòng hay không)
        out.extend((prefix.group(0) if prefix else "") + extra for extra in insertions.get(line_no, []))
    return "\n".join(out)


def cv_entries(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Chỗ có thể thêm câu kinh nghiệm mới: từng dự án / công việc (dòng tiêu đề có ngày tháng) trong các mục Dự án,
    Kinh nghiệm, Hoạt động; mục không có dòng tiêu đề như vậy thì thêm vào cuối mục. after_line_no = dòng cuối của
    phần đó (câu mới chèn ngay sau).
    """
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        block = line.get("block")
        if line["is_heading"] or block not in ENTRY_BLOCKS:
            current = None
            continue
        title = entry_title(line["text"]) if line["section"] == block else None
        if title or current is None or current["block"] != block:
            label = SECTION_LABELS.get(block, block)
            current = {
                "id": f"l{line['line_no']}",
                "label": f"{label} · {title}" if title else f"{label} (cuối mục)",
                "block": block,
                "after_line_no": line["line_no"],
            }
            entries.append(current)
        else:
            current["after_line_no"] = line["line_no"]
    return entries


def _optimized_file_name(file_name: str, version_label: str) -> str:
    stem = re.sub(r"_v\d+(\.\d+)?$", "", Path(file_name).stem) or "CV"
    return f"{stem}_{version_label}.docx"


# ---------- Gợi ý & kiểm tra kỹ năng ----------


def suggestions_state(optimization: CvOptimization) -> str:
    """
    pending: chưa soạn gợi ý riêng (frontend gọi prepare_suggestions); failed: soạn lỗi, chờ SV thử lại; ready: có gợi
    ý để duyệt. Phiên đã hoàn tất, không có LLM, hoặc đã có quyết định trên gợi ý của lượt phân tích (phiên tạo trước
    khi có bước soạn riêng) thì giữ nguyên gợi ý đang có.
    """
    if optimization.status != "draft" or not llm.llm_configured():
        return "ready"
    if optimization.rewrites is None:
        return "ready" if optimization.decisions or optimization.contexts else "pending"
    return "failed" if optimization.rewrites.get("status") == "failed" else "ready"


def _suggestions(analysis: GapAnalysis, cv: CvVersion, optimization: CvOptimization) -> list[dict[str, Any]]:
    """
    Gợi ý của phiên (soạn riêng nếu đã có, không thì của lượt phân tích) kèm dòng CV được thay; bỏ gợi ý không còn
    khớp nguyên văn dòng nào trong CV. Gợi ý soạn riêng thay cả gạch ý bị ngắt dòng (extra_line_nos: các dòng nối).
    """
    lines = split_cv_lines(cv.content_text)
    rewrites = optimization.rewrites or {}
    source = (
        rewrites.get("items", [])
        if rewrites.get("status") == "ready"
        else (analysis.result or {}).get("suggestions", [])
    )
    by_no = {line["line_no"]: line for line in lines}
    units = {u["line_no"]: u for u in cv_rewrite.merge_wrapped(lines, cv.content_text)}
    result = []
    for s in source:
        if "extra_line_nos" in s:
            unit = units.get(s["line_no"])
            if unit is not None and unit["text"] == s["original_text"]:
                result.append({**s, "extra_line_nos": unit["extra_line_nos"]})
            continue
        line = by_no.get(s.get("line_no"))
        if line is None or line["text"] != s["original_text"]:
            # Lượt phân tích cũ chưa lưu số dòng: tìm theo nguyên văn
            line = next((x for x in lines if not x["is_heading"] and x["text"] == s["original_text"]), None)
        if line is not None:
            result.append({**s, "line_no": line["line_no"], "extra_line_nos": []})
    return result


_PLACEHOLDER = re.compile(r"\[[^\]]{1,40}\]")
CONTEXT_QUESTION = "Câu này cần số liệu thật. Bạn đã làm được bao nhiêu (số lượng, tỷ lệ, thời gian…)?"


def _with_context(suggestions: list[dict[str, Any]], optimization: CvOptimization) -> list[dict[str, Any]]:
    """
    Gợi ý còn chỗ trống [ ] cần SV bổ sung số liệu thật (US-SV-03 AC2). Đã bổ sung thì dùng câu đã điền số
    thay cho câu AI đề xuất ban đầu; AI không bao giờ tự đặt số liệu.
    """
    contexts = optimization.contexts or {}
    out = []
    for s in suggestions:
        ctx = contexts.get(s["id"])
        text = ctx["proposed_text"] if ctx else s["suggested_text"]
        out.append({**s, "suggested_text": text, "needs_context": ctx is None and bool(_PLACEHOLDER.search(text))})
    return out


def _fill_by_rules(proposed: str, answer: str) -> str:
    """Điền lần lượt các số trong câu trả lời vào chỗ trống; không đủ số thì nối câu trả lời vào cuối câu."""
    numbers = re.findall(r"\d+(?:[.,]\d+)?\s*%?", answer)
    holes = _PLACEHOLDER.findall(proposed)
    if numbers and len(numbers) >= len(holes):
        filled = proposed
        for number in numbers[: len(holes)]:
            filled = _PLACEHOLDER.sub(number.strip(), filled, count=1)
        return filled
    return f"{_PLACEHOLDER.sub('', proposed).rstrip(' .')} – {answer.rstrip('.')}."


async def _fill_with_llm(original: str, proposed: str, answer: str) -> str | None:
    prompt = (
        "Bạn sửa một câu trong CV. Câu đề xuất có chỗ trống dạng [ ] cần số liệu thật.\n"
        f"Câu gốc: {original}\nCâu đề xuất: {proposed}\nSinh viên cung cấp: {answer}\n"
        "Điền chỗ trống CHỈ bằng thông tin sinh viên cung cấp; không thêm số, kỹ năng hay thành tích khác. "
        "Thông tin không đủ cho chỗ trống nào thì bỏ cụm có chỗ trống đó. Giữ câu ngắn gọn, cùng giọng văn.\n"
        'Trả về JSON: {"text": "<câu hoàn chỉnh>"}'
    )
    try:
        data = await llm.invoke_json(prompt, timeout=30.0)
    except Exception:
        return None
    text = " ".join(str(data.get("text", "")).split())
    if not text or _PLACEHOLDER.search(text) or len(text) > MAX_EDIT_CHARS:
        return None
    # Chống bịa số: mọi số trong câu mới phải có trong câu gốc hoặc câu trả lời của SV
    allowed = set(re.findall(r"\d+", f"{original} {answer}"))
    if any(n not in allowed for n in re.findall(r"\d+", text)):
        return None
    return text


async def provide_context(
    db: Session, user: User, analysis_id: str, suggestion_id: str, answer: str, now: datetime
) -> None:
    """SV bổ sung số liệu cho gợi ý còn chỗ trống; câu đề xuất được điền lại và quyết định cũ (nếu có) bị bỏ."""
    analysis, cv, optimization = _load(db, user, analysis_id)
    _require_draft(optimization)
    text = " ".join(answer.split())
    if not text:
        raise AppError(422, "Hãy nhập ngữ cảnh trước khi gửi.", "context_required")
    if len(text) > MAX_CONTEXT_CHARS:
        raise AppError(422, f"Ngữ cảnh tối đa {MAX_CONTEXT_CHARS} ký tự.", "context_too_long")
    base = next(
        (s for s in _suggestions(analysis, cv, optimization) if s["id"] == suggestion_id),
        None,
    )
    if base is None:
        raise AppError(404, "Không tìm thấy gợi ý.", "suggestion_not_found")
    proposed = None
    if llm.llm_configured():
        proposed = await _fill_with_llm(base["original_text"], base["suggested_text"], text)
    proposed = proposed or _fill_by_rules(base["suggested_text"], text)
    contexts = dict(optimization.contexts or {})
    contexts[suggestion_id] = {"answer": text, "proposed_text": proposed, "answered_at": now.isoformat()}
    optimization.contexts = contexts
    decisions = dict(optimization.decisions or {})
    decisions.pop(suggestion_id, None)
    optimization.decisions = decisions
    db.commit()


def _kind(skill: str, original: str, proposed: str) -> str:
    """ats_keyword: câu mới dùng đúng tên kỹ năng trong JD mà câu gốc chưa có; còn lại là diễn đạt lại."""
    return "ats_keyword" if contains_term(skill, proposed) and not contains_term(skill, original) else "rephrase"


def _suggestion_out(s: dict[str, Any], decision: dict[str, Any] | None) -> dict[str, Any]:
    status = STATUS_OF_ACTION.get(decision["action"], "pending") if decision else "pending"
    return {
        "id": s["id"],
        "kind": _kind(s["skill"], s["original_text"], s["suggested_text"]),
        "skill": s["skill"],
        "line_id": f"l{s['line_no']}",
        "extra_line_ids": [f"l{n}" for n in s.get("extra_line_nos", [])],
        "original_text": s["original_text"],
        "proposed_text": s["suggested_text"],
        "final_text": decision["final_text"] if status in ("accepted", "edited") else None,
        "rationale": s.get("reason", ""),
        "evidence_span": {"text": s["original_text"], "line_start": s["line_no"], "line_end": s["line_no"]},
        "status": status,
        "needs_context": s.get("needs_context", False),
        "context_question": CONTEXT_QUESTION if s.get("needs_context") else None,
    }


def _missing(analysis: GapAnalysis) -> list[dict[str, Any]]:
    """Yêu cầu JD mà CV chưa có (Match = 0), nhóm Bắt buộc trước."""
    missing = [r for r in (analysis.result or {}).get("requirements", []) if r["status"] == "missing"]
    return sorted(missing, key=lambda r: IMPORTANCE_ORDER.get(r["importance"], 3))


def _check_out(requirement: dict[str, Any], jd: JobDescription, answer: dict[str, Any] | None) -> dict[str, Any]:
    status = "pending"
    if answer:
        status = "has_experience" if answer["has_experience"] else "no_experience"
    level = IMPORTANCE_LABELS.get(requirement["importance"], "").lower()
    roadmap = get_roadmap_info(requirement["skill"])
    decision = (answer or {}).get("decision")
    return {
        "entry_id": (answer or {}).get("entry_id"),
        "draft_text": (answer or {}).get("draft_text"),
        "final_text": (answer or {}).get("final_text"),
        "line_status": {"accept": "accepted", "edit": "edited", "reject": "rejected"}.get(decision or "", "pending"),
        "roadmap_url": roadmap["roadmap_url"] if roadmap["is_it_supported"] else None,
        "id": requirement["id"],
        "skill": requirement["skill"],
        "importance": requirement["importance"],
        "jd_requirement": f"Vị trí {jd.title} yêu cầu {requirement['skill']} (mức {level}), "
        "nhưng CV chưa thể hiện kỹ năng này.",
        "status": status,
        "context": answer.get("context") if answer else None,
        "learning_note": answer.get("learning_note") if answer else None,
    }


# ---------- Phiên tối ưu ----------


def _load(db: Session, user: User, analysis_id: str) -> tuple[GapAnalysis, CvVersion, CvOptimization]:
    analysis = db.get(GapAnalysis, analysis_id)
    if analysis is None or analysis.owner_id != user.id:
        raise AppError(404, "Không tìm thấy kết quả phân tích.", "analysis_not_found")
    if analysis.status != "completed":
        raise AppError(409, "Lượt phân tích chưa hoàn tất nên chưa mở được trình tối ưu.", "analysis_not_ready")
    cv = db.get(CvVersion, analysis.cv_version_id)
    if cv is None:
        raise AppError(
            409, "Phiên bản CV của lượt phân tích này đã bị xoá nên không mở được trình tối ưu.", "cv_deleted"
        )
    optimization = db.scalar(select(CvOptimization).where(CvOptimization.analysis_id == analysis.id))
    if optimization is None:
        optimization = CvOptimization(
            id=f"op_{uuid.uuid4().hex[:12]}",
            analysis_id=analysis.id,
            owner_id=user.id,
            decisions={},
            capability_answers={},
        )
        db.add(optimization)
        db.commit()
    return analysis, cv, optimization


def _require_draft(optimization: CvOptimization) -> None:
    if optimization.status != "draft":
        raise AppError(
            409,
            "Bạn đã hoàn tất phiên tối ưu này. Hãy phân tích lại phiên bản mới để tiếp tục tối ưu.",
            "optimization_finalized",
        )


def session(db: Session, user: User, analysis_id: str) -> dict[str, Any]:
    """Trạng thái Trình tối ưu; phiên bản CV trả về dạng ORM để router chuyển sang CvVersionResponse."""
    analysis, cv, optimization = _load(db, user, analysis_id)
    jd = db.get(JobDescription, analysis.jd_id)
    result = analysis.result or {}
    lines = split_cv_lines(cv.content_text)
    result_cv = db.get(CvVersion, optimization.result_cv_version_id) if optimization.result_cv_version_id else None
    answers = optimization.capability_answers or {}
    state = suggestions_state(optimization)
    rewrites = optimization.rewrites or {}
    suggestions = (
        [
            _suggestion_out(s, (optimization.decisions or {}).get(s["id"]))
            for s in _with_context(_suggestions(analysis, cv, optimization), optimization)
        ]
        if state == "ready"
        else []
    )
    return {
        "analysis_id": analysis.id,
        "status": optimization.status,
        "jd": {
            "id": jd.id,
            "title": jd.title,
            "company": jd.company,
            "industry": jd.industry,
            "level": jd.level,
            "source": jd.source,
        },
        "match_score": analysis.match_score,
        "match_label": match_label(analysis.match_score),
        "llm_used": bool(result.get("llm_used")),
        "pending_review_count": result.get("pending_review_count", 0),
        "cv": cv,
        "result_cv": result_cv,
        "document": cv_document(cv),
        "result_document": cv_document(result_cv) if result_cv else None,
        "suggestions": suggestions,
        "suggestions_state": state,
        "kept_count": rewrites.get("kept", 0) if rewrites.get("status") == "ready" else 0,
        "suggestions_attempted_at": datetime.fromisoformat(rewrites["attempted_at"])
        if rewrites.get("attempted_at")
        else None,
        "capability_checks": [_check_out(r, jd, answers.get(r["id"])) for r in _missing(analysis)],
        "entries": [
            {"id": e["id"], "label": e["label"], "after_line_id": f"l{e['after_line_no']}"} for e in cv_entries(lines)
        ],
        "finalized_at": optimization.finalized_at,
    }


async def prepare_suggestions(db: Session, user: User, analysis_id: str, now: datetime) -> None:
    """
    Soạn gợi ý viết lại riêng cho phiên (lần đầu mở Trình tối ưu, hoặc SV bấm Thử lại sau khi lỗi). Đã có gợi ý thì
    không gọi lại LLM. Lỗi LLM (bận, hết lượt) thì ghi "failed"; CV và các phần khác của phiên không bị ảnh hưởng.
    """
    analysis, cv, optimization = _load(db, user, analysis_id)
    if suggestions_state(optimization) not in ("pending", "failed"):
        return
    jd = db.get(JobDescription, analysis.jd_id)
    requirements = (analysis.result or {}).get("requirements", [])
    try:
        with provider_scope(user_id=user.id):
            drafted = await cv_rewrite.draft_rewrites(
                split_cv_lines(cv.content_text), requirements, jd.title if jd else "", cv.content_text
            )
        rewrites = {"status": "ready", **drafted, "attempted_at": now.isoformat()}
    except Exception as e:
        logger.warning("Soạn gợi ý viết lại cho %s thất bại: %s", analysis_id, e)
        rewrites = {"status": "failed", "items": [], "kept": 0, "attempted_at": now.isoformat()}
    # Mở ở hai tab cùng lúc: tab kia đã soạn xong (SV có thể đã duyệt gợi ý) thì giữ, không ghi đè
    db.refresh(optimization)
    if suggestions_state(optimization) in ("pending", "failed"):
        optimization.rewrites = rewrites
        db.commit()


def decide(
    db: Session,
    user: User,
    analysis_id: str,
    suggestion_id: str,
    decision: str,
    edited_text: str | None,
    now: datetime,
) -> None:
    """Ghi quyết định của SV vào bản nháp và Audit Trail. undo đưa gợi ý về chờ duyệt."""
    analysis, cv, optimization = _load(db, user, analysis_id)
    _require_draft(optimization)
    suggestion = next(
        (s for s in _with_context(_suggestions(analysis, cv, optimization), optimization) if s["id"] == suggestion_id),
        None,
    )
    if suggestion is None:
        raise AppError(404, "Không tìm thấy gợi ý.", "suggestion_not_found")

    decisions = dict(optimization.decisions or {})
    if decision == "undo":
        if suggestion_id not in decisions:
            return
        del decisions[suggestion_id]
        final = suggestion["original_text"]
    elif decision == "edit":
        # Mỗi gợi ý thay một dòng CV nên nội dung sửa được gộp thành một dòng
        final = " ".join((edited_text or "").split())
        if not final:
            raise AppError(422, "Hãy nhập nội dung chỉnh sửa.", "edited_text_required")
        if len(final) > MAX_EDIT_CHARS:
            raise AppError(422, f"Nội dung chỉnh sửa tối đa {MAX_EDIT_CHARS} ký tự.", "edited_text_too_long")
        if final == suggestion["original_text"]:
            raise AppError(
                422,
                "Nội dung chỉnh sửa đang giống câu gốc. Nếu không muốn thay đổi, hãy chọn Bỏ qua.",
                "edit_unchanged",
            )
    else:
        final = suggestion["suggested_text"] if decision == "accept" else suggestion["original_text"]
    if decision in ("accept", "edit") and _PLACEHOLDER.search(final):
        # Chỗ trống [ ] không bao giờ được vào CV: SV điền số thật hoặc xoá chỗ trống trước
        raise AppError(
            422,
            "Câu còn chỗ trống [ ]. Hãy điền số liệu thật của bạn hoặc xoá chỗ trống trước khi áp dụng.",
            "placeholder_left",
        )
    if decision != "undo":
        decisions[suggestion_id] = {"action": decision, "final_text": final}

    optimization.decisions = decisions
    db.add(
        CvEditAudit(
            id=f"au_{uuid.uuid4().hex[:12]}",
            owner_id=user.id,
            analysis_id=analysis.id,
            suggestion_id=suggestion_id,
            cv_version_id=cv.id,
            original_content=suggestion["original_text"],
            ai_suggestion=suggestion["suggested_text"],
            evidence_line_no=suggestion["line_no"],
            evidence_text=suggestion["original_text"],
            reason=suggestion.get("reason", ""),
            action=decision,
            final_content=final,
            created_at=now,
        )
    )
    db.commit()


def answer_check(
    db: Session,
    user: User,
    analysis_id: str,
    requirement_id: str,
    has_experience: bool,
    context: str | None,
    learning_note: str | None,
    now: datetime,
) -> None:
    """Ghi câu trả lời kiểm tra kỹ năng thiếu (được đổi lại cho tới khi "Hoàn tất")."""
    analysis, _, optimization = _load(db, user, analysis_id)
    _require_draft(optimization)
    if requirement_id not in {r["id"] for r in _missing(analysis)}:
        raise AppError(404, "Không tìm thấy kỹ năng cần xác nhận.", "check_not_found")

    if has_experience:
        text = (context or "").strip()
        if not text:
            raise AppError(422, "Hãy mô tả ngắn kinh nghiệm của bạn với kỹ năng này.", "context_required")
        if len(text) > MAX_CONTEXT_CHARS:
            raise AppError(422, f"Mô tả kinh nghiệm tối đa {MAX_CONTEXT_CHARS} ký tự.", "context_too_long")
        answer = {"has_experience": True, "context": text, "learning_note": None}
    else:
        note = " ".join((learning_note or "").split()) or None
        if note and len(note) > MAX_LEARNING_NOTE_CHARS:
            raise AppError(422, f"Ghi chú đang học tối đa {MAX_LEARNING_NOTE_CHARS} ký tự.", "learning_note_too_long")
        answer = {"has_experience": False, "context": None, "learning_note": note}
    answer["answered_at"] = now.isoformat()
    optimization.capability_answers = {**(optimization.capability_answers or {}), requirement_id: answer}
    db.commit()


def _line_from_context(context: str) -> str:
    """Không có AI: câu SV kể (bỏ khoảng trắng thừa, viết hoa chữ đầu, có dấu chấm), cắt gọn nếu quá dài."""
    text = " ".join(context.split())[:MAX_SKILL_LINE_CHARS].rstrip(" ,;")
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else f"{text}."


async def _line_with_llm(skill: str, context: str, entry_label: str, sample: list[str], lang: str = "vi") -> str | None:
    """Câu CV viết từ đúng lời SV kể; trả None nếu câu thêm số / không nhắc kỹ năng / quá dài (dùng câu của SV)."""
    examples = "\n".join(f"- {line}" for line in sample[:4]) or "- (chưa có)"
    prompt = (
        "Bạn viết MỘT gạch đầu dòng cho CV của sinh viên, đặt trong phần: " + entry_label + ".\n"
        f"Kỹ năng cần thể hiện: {skill}\n"
        f"Sinh viên kể: {context}\n"
        f"Các gạch đầu dòng hiện có trong CV (để viết cùng giọng văn, cùng ngôn ngữ):\n{examples}\n\n"
        "Quy tắc: CHỈ dùng thông tin sinh viên kể; không thêm số liệu, công cụ, thành tích hay quy mô không có trong lời "
        "kể. Bắt đầu bằng động từ, nêu rõ đã dùng kỹ năng để làm gì, kết quả nếu sinh viên có nói. "
        f'Tối đa khoảng 35 từ, phải nhắc tên kỹ năng {skill}. Không dùng ngôi "tôi", "em", "mình".\n'
        # CV tiếng Anh thì câu mới cũng bằng tiếng Anh, dù SV kể bằng tiếng Việt
        f"Viết bằng {'tiếng Anh' if lang == 'en' else 'tiếng Việt'}, cùng ngôn ngữ với CV.\n"
        'Trả về JSON: {"text": "<câu cho CV>"}'
    )
    try:
        data = await llm.invoke_json(prompt, temperature=0.0, timeout=30.0)
    except Exception:
        return None
    text = " ".join(str(data.get("text", "")).split()).lstrip("-•* ").strip()
    if not text or len(text) > MAX_SKILL_LINE_CHARS or _PLACEHOLDER.search(text):
        return None
    # Chống bịa: số trong câu phải có trong lời kể; câu phải nói tới đúng kỹ năng
    allowed = set(re.findall(r"\d+", context))
    if any(n not in allowed for n in re.findall(r"\d+", text)) or not contains_term(skill, text):
        return None
    # Cùng cách kết câu với các dòng khác trong mục
    if sample and sum(line.endswith(".") for line in sample) * 2 > len(sample) and not text.endswith((".", "!", "?")):
        text += "."
    return text


async def draft_capability_line(
    db: Session, user: User, analysis_id: str, requirement_id: str, context: str, entry_id: str, now: datetime
) -> None:
    """SV chọn "Có, đã dùng", kể kinh nghiệm và chọn chỗ thêm: AI viết thành một câu cho CV để SV duyệt."""
    analysis, cv, optimization = _load(db, user, analysis_id)
    _require_draft(optimization)
    requirement = next((r for r in _missing(analysis) if r["id"] == requirement_id), None)
    if requirement is None:
        raise AppError(404, "Không tìm thấy kỹ năng cần xác nhận.", "check_not_found")
    text = " ".join(context.split())
    if not text:
        raise AppError(422, "Hãy kể ngắn bạn đã dùng kỹ năng này ở đâu, làm những gì.", "context_required")
    if len(text) > MAX_CONTEXT_CHARS:
        raise AppError(422, f"Mô tả kinh nghiệm tối đa {MAX_CONTEXT_CHARS} ký tự.", "context_too_long")
    lines = split_cv_lines(cv.content_text)
    entry = next((e for e in cv_entries(lines) if e["id"] == entry_id), None)
    if entry is None:
        raise AppError(422, "Hãy chọn phần của CV để thêm câu này.", "entry_required")
    sample = [x["text"] for x in lines if x["block"] == entry["block"] and x["section"] == entry["block"]]
    lang = cv_language(cv.content_text, lines)
    drafted = (
        await _line_with_llm(requirement["skill"], text, entry["label"], sample, lang) if llm.llm_configured() else None
    )
    answers = dict(optimization.capability_answers or {})
    answers[requirement_id] = {
        "has_experience": True,
        "context": text,
        "learning_note": None,
        "entry_id": entry_id,
        "draft_text": drafted or _line_from_context(text),
        "draft_source": "ai" if drafted else "student",
        "decision": None,
        "final_text": None,
        "answered_at": now.isoformat(),
    }
    optimization.capability_answers = answers
    db.commit()


def decide_capability_line(
    db: Session,
    user: User,
    analysis_id: str,
    requirement_id: str,
    decision: str,
    edited_text: str | None,
    now: datetime,
) -> None:
    """Áp dụng / sửa / bỏ qua câu kinh nghiệm cho kỹ năng còn thiếu, hoặc hoàn tác; ghi Audit Trail như gợi ý AI."""
    analysis, cv, optimization = _load(db, user, analysis_id)
    _require_draft(optimization)
    answers = dict(optimization.capability_answers or {})
    answer = answers.get(requirement_id)
    if not answer or not answer.get("draft_text"):
        raise AppError(404, "Chưa có câu đề xuất cho kỹ năng này.", "draft_not_found")
    if decision == "edit":
        final = " ".join((edited_text or "").split())
        if not final:
            raise AppError(422, "Hãy nhập nội dung chỉnh sửa.", "edited_text_required")
        if len(final) > MAX_EDIT_CHARS:
            raise AppError(422, f"Nội dung chỉnh sửa tối đa {MAX_EDIT_CHARS} ký tự.", "edited_text_too_long")
    else:
        final = answer["draft_text"] if decision == "accept" else None
    answers[requirement_id] = {
        **answer,
        "decision": None if decision == "undo" else decision,
        "final_text": final if decision in ("accept", "edit") else None,
    }
    optimization.capability_answers = answers
    entry = next((e for e in cv_entries(split_cv_lines(cv.content_text)) if e["id"] == answer.get("entry_id")), None)
    db.add(
        CvEditAudit(
            id=f"au_{uuid.uuid4().hex[:12]}",
            owner_id=user.id,
            analysis_id=analysis.id,
            suggestion_id=f"cap:{requirement_id}",
            cv_version_id=cv.id,
            original_content="",
            ai_suggestion=answer["draft_text"],
            evidence_line_no=entry["after_line_no"] if entry else 0,
            evidence_text=answer.get("context") or "",
            reason="Kỹ năng JD cần, SV xác nhận đã có kinh nghiệm (câu thêm mới vào CV)",
            action=decision,
            final_content=final or "",
            created_at=now,
        )
    )
    db.commit()


def finalize(db: Session, user: User, analysis_id: str, now: datetime) -> None:
    """Tạo một phiên bản CV mới từ bản nháp (câu đã chấp nhận / sửa tay, kỹ năng đang học) rồi khoá phiên."""
    analysis, cv, optimization = _load(db, user, analysis_id)
    _require_draft(optimization)

    suggestions = {s["id"]: s for s in _suggestions(analysis, cv, optimization)}
    applied = [
        (suggestions[sid], d["final_text"])
        for sid, d in (optimization.decisions or {}).items()
        if d["action"] in ("accept", "edit") and sid in suggestions
    ]
    replacements = {s["line_no"]: final for s, final in applied}
    # Câu thay thế đã gộp các dòng nối của gạch ý bị ngắt dòng
    removals = {n for s, _ in applied for n in s.get("extra_line_nos", [])}
    missing = {r["id"]: r for r in _missing(analysis)}
    learning = [
        {"name": missing[rid]["skill"], "note": a["learning_note"]}
        for rid, a in (optimization.capability_answers or {}).items()
        if rid in missing and not a["has_experience"] and a.get("learning_note")
    ]
    entries = {e["id"]: e for e in cv_entries(split_cv_lines(cv.content_text))}
    insertions: dict[int, list[str]] = {}
    for rid, a in (optimization.capability_answers or {}).items():
        entry = entries.get(a.get("entry_id") or "")
        if rid in missing and a.get("final_text") and entry:
            insertions.setdefault(entry["after_line_no"], []).append(a["final_text"])
    if not replacements and not learning and not insertions:
        raise AppError(
            422,
            "Chưa có thay đổi nào để lưu. Hãy áp dụng ít nhất một gợi ý hoặc ghi một kỹ năng bạn đang học.",
            "no_changes",
        )

    developing = {s["name"].lower(): s for s in cv.developing_skills or []}
    developing.update({s["name"].lower(): s for s in learning})
    new_cv = CvVersion(
        id=f"cv_{uuid.uuid4().hex[:12]}",
        owner_id=user.id,
        file_type="docx",
        size_bytes=0,
        page_count=None,
        content_text=apply_changes(cv.content_text, replacements, insertions, removals),
        origin="optimized",
        is_active=False,
        is_draft=False,
        uploaded_at=now,
        developing_skills=list(developing.values()) or None,
        source_analysis_id=analysis.id,
        # Chữ vẫn đến từ bản gốc: bản đọc bằng OCR thì bản tối ưu cũng cần sinh viên kiểm tra
        read_by_ocr=cv.read_by_ocr,
    )
    cv_versions.append(db, cv, new_cv, new_major=False)
    new_cv.file_name = _optimized_file_name(cv.file_name, cv_versions.label(new_cv))
    data = cv_files.build_docx(cv_document(new_cv))
    new_cv.size_bytes = len(data)
    cv_files.save_file(user.id, new_cv.id, "docx", data)
    db.add(new_cv)
    optimization.status = "finalized"
    optimization.result_cv_version_id = new_cv.id
    optimization.finalized_at = now
    try:
        db.commit()
    except Exception:
        cv_files.delete_file(user.id, new_cv.id, "docx")
        raise


# ---------- Xuất CV ----------


def record_export(db: Session, user: User, cv: CvVersion, format_: str, integrity_confirmed: bool) -> CvExport:
    """Ghi nhận một lần xuất CV; bắt buộc SV đã xác nhận cam kết liêm chính."""
    if not integrity_confirmed:
        raise AppError(422, "Hãy xác nhận cam kết liêm chính trước khi xuất CV.", "integrity_required")
    export = CvExport(id=f"ex_{uuid.uuid4().hex[:12]}", owner_id=user.id, cv_version_id=cv.id, format=format_)
    db.add(export)
    db.commit()
    return export


def cv_preview(cv: CvVersion) -> dict[str, Any]:
    """Xem CV trong app: PDF gốc còn file → ảnh từng trang; còn lại (DOCX, bản đã tối ưu) → nội dung theo mẫu CV."""
    path = cv_files.stored_path(cv.owner_id, cv.id, cv.file_type)
    if cv.file_type == "pdf" and path.exists():
        try:
            pages = cv_files.pdf_page_count(path)
        except Exception:
            pages = 0
        if pages:
            return {"kind": "pages", "page_count": min(pages, cv_files.MAX_PREVIEW_PAGES)}
    return {"kind": "document", "document": cv_document(cv)}


def page_image(cv: CvVersion, page: int) -> bytes:
    path = cv_files.stored_path(cv.owner_id, cv.id, cv.file_type)
    if cv.file_type != "pdf" or not path.exists():
        raise AppError(404, "Không tìm thấy file gốc của CV này.", "cv_file_missing")
    return cv_files.render_pdf_page(path, page)


def display_text(cv: CvVersion) -> str:
    """Văn bản CV để xem nhanh, kèm mục kỹ năng đang phát triển (không thuộc nội dung được chấm)."""
    if not cv.developing_skills:
        return cv.content_text
    skills = "\n".join(f"- {s['name']}: {s['note']}" for s in cv.developing_skills)
    return f"{cv.content_text}\n\n{DEVELOPING_TITLE}\n{skills}"
