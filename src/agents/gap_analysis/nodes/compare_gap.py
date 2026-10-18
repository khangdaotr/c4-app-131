import logging
import re
from typing import Any

from src.agents.gap_analysis.state import GapAnalysisState
from src.services.llm import invoke_json, llm_configured
from src.services.providers.gateway import provider_scope
from src.services.skill_matching import (
    IMPORTANCE_LABELS,
    MATCH_LEVELS,
    SECTION_LABELS,
    assess_by_rules,
    assessment,
    contains_term,
    evidence_level,
    lift_parents,
    listing_note,
    metric_note,
)

logger = logging.getLogger(__name__)

# PRD mục 5.2: tối đa 2 lệnh gọi LLM cho một lượt phân tích
MAX_LLM_CALLS = 2
# Giới hạn độ dài CV gửi cho LLM (CV 1–2 trang thường chỉ 3.000–6.000 ký tự)
MAX_CV_CHARS = 12_000
MAX_SUGGESTIONS = 5


def _cv_block(lines: list[dict[str, Any]]) -> str:
    out, total = [], 0
    for line in lines:
        row = f"[{line['line_no']}|{SECTION_LABELS.get(line['section'], line['section'])}] {line['text']}"
        total += len(row)
        if total > MAX_CV_CHARS:
            break
        out.append(row)
    return "\n".join(out)


def _requirements_block(requirements: list[dict[str, Any]]) -> str:
    rows = []
    for r in requirements:
        aliases = f" — tên tương đương: {', '.join(r['aliases'])}" if r.get("aliases") else ""
        rows.append(f"{r['id']}. {r['name']} ({IMPORTANCE_LABELS[r['importance']]}){aliases}")
    return "\n".join(rows)


def _score_prompt(
    lines: list[dict[str, Any]],
    requirements: list[dict[str, Any]],
    retrieved_context: list[dict[str, Any]],
) -> str:
    """
    LLM call #2 (PRD 5.2): Chấm Match cho TOÀN BỘ yêu cầu trong một lần gọi (batch) theo bảng 4 mức, kèm dòng bằng
    chứng, gợi ý diễn đạt lại và một chủ đề nên chuẩn bị phỏng vấn.
    """
    context = "\n".join(f"- {doc.get('title', '')}: {doc.get('content', '')}" for doc in retrieved_context[:4])
    return (
        "Bạn là chuyên gia tuyển dụng, chấm mức độ đáp ứng yêu cầu JD của một CV sinh viên theo bảng chấm cố định. "
        "Nhà tuyển dụng nhìn vào việc ứng viên đã làm, không nhìn số lần nhắc từ khoá.\n\n"
        "=== CV (mỗi dòng: [số dòng|mục] nội dung) ===\n"
        f"{_cv_block(lines)}\n\n"
        "=== YÊU CẦU CỦA JD ===\n"
        f"{_requirements_block(requirements)}\n\n"
        "=== BẢNG CHẤM MATCH (bắt buộc tuân theo, chỉ dùng đúng 4 giá trị) ===\n"
        "- 0: không xuất hiện ở bất kỳ đâu trong CV (khoảng cách năng lực: cần học thêm, không viết câu sửa CV).\n"
        "- 0.5: chỉ xuất hiện dạng liệt kê (mục Kỹ năng, Giới thiệu, Chứng chỉ..., hoặc dòng 'Technologies: ...' / "
        "'Công nghệ: ...' của một dự án), chưa có câu mô tả đã dùng để làm gì (khoảng cách trình bày: cần viết rõ).\n"
        "- 0.75: có câu mô tả cụ thể đã dùng kỹ năng để làm gì (thường là đồ án, bài tập lớn, dự án cá nhân) nhưng "
        "chưa có số liệu kết quả.\n"
        "- 1: có câu mô tả kèm số liệu kết quả (thời gian, %, số người dùng, quy mô...) hoặc là kinh nghiệm làm việc "
        "thực tế tại doanh nghiệp.\n"
        "Không cho điểm cao dễ dãi: nhắc tên công nghệ chưa phải là đã dùng thành thạo.\n"
        "Taxonomy: FastAPI/Flask/Django tính là Python; PyTorch/TensorFlow tính là Machine Learning; "
        "React/Next.js/Vue/Angular tính là JavaScript; Spring Boot tính là Java.\n\n"
        "=== TIÊU CHUẨN THAM KHẢO ===\n"
        f"{context or '- Chỉ công nhận kỹ năng có bằng chứng thật trong CV.'}\n\n"
        "=== NHIỆM VỤ ===\n"
        "1. Chấm match cho TỪNG yêu cầu, kèm evidence_lines là số dòng CV làm bằng chứng (match = 0 thì "
        "evidence_lines = []). note: 1 câu tiếng Việt cho sinh viên, nói rõ còn thiếu gì (không ghi số điểm match).\n"
        f"2. Viết tối đa {MAX_SUGGESTIONS} gợi ý diễn đạt lại cho các câu mô tả việc đã làm thuộc mục Kinh nghiệm / "
        "Dự án / Học vấn / Hoạt động (không viết lại dòng chỉ liệt kê kỹ năng / công nghệ hay dòng tiêu đề), ưu tiên "
        "câu chưa có số liệu; mỗi dòng tối đa 1 gợi ý; requirement_id là yêu cầu có match > 0 mà gợi ý làm rõ. "
        "Viết bằng ngôn ngữ của CHÍNH dòng gốc (dòng tiếng Anh thì viết tiếng Anh, dòng tiếng Việt không dấu thì "
        "viết không dấu), không theo tên mục hay phần còn lại của CV. "
        "Cách viết: động từ hành động + việc / bài toán cụ thể + kỹ năng hoặc công cụ JD cần; chỉ nhắc công cụ có "
        "trong chính dòng đó hoặc cùng dự án / nơi làm việc, KHÔNG lấy từ mục Kỹ năng hay dự án khác. "
        "RÀNG BUỘC: giữ đúng sự thật của dòng gốc; giữ nguyên mọi con số đã có; KHÔNG thêm việc, số liệu, công cụ, "
        "thành tích, quy mô, đối tượng, tên dự án không có trong CV; không tự khẳng định kết quả (tăng, giảm, "
        "cải thiện...). Dòng chưa có số liệu thì có thể thêm đúng MỘT chỗ trống ở cuối câu để sinh viên tự điền: "
        '\"[kết quả đo được]\" (câu tiếng Anh: \"[measurable result]\"; câu không dấu: \"[ket qua do duoc]\").\n'
        "3. interview_focus: 1 câu tiếng Việt nêu MỘT kỹ năng của JD mà bạn chấm match từ 0.75 trở lên, nhà tuyển "
        "dụng nhiều khả năng sẽ hỏi sâu, và sinh viên nên chuẩn bị kể gì về nó. Chỉ nhắc việc có ghi trong CV, không nhắc điểm chấm. "
        "Có thể để chuỗi rỗng.\n"
        "CHỈ trả về JSON hợp lệ đúng các trường sau, không giải thích:\n"
        '{\"requirements\": [{\"id\": \"r1\", \"match\": 0.75, \"evidence_lines\": [5], \"note\": \"...\"}], '
        '\"suggestions\": [{\"requirement_id\": \"r1\", \"line\": 5, \"rewrite\": \"...\", \"reason\": \"...\"}], '
        '\"interview_focus\": \"...\"}'
    )


async def score_with_llm(
    lines: list[dict[str, Any]],
    requirements: list[dict[str, Any]],
    retrieved_context: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    LLM call #2 (PRD 5.2): chấm Match cho TOÀN BỘ yêu cầu trong một lần gọi (batch) theo bảng 4 mức, kèm dòng bằng
    chứng, gợi ý diễn đạt lại và một chủ đề nên chuẩn bị phỏng vấn. Kết quả được kiểm tra chéo bằng quy tắc (_merge);
    nhận xét tổng quan ghép bằng quy tắc từ bảng cuối (fit_summary) để luôn khớp với bảng.
    """
    with provider_scope() as scope:
        scope.prime("\n".join(line["text"] for line in lines), "message", document_type="cv")
        fields = scope.mask_payload(
            {"lines": lines, "requirements": requirements, "retrieved_context": retrieved_context}
        )
        prompt = _score_prompt(**fields)
        return await invoke_json(scope.prepared(prompt), temperature=0.0, timeout=60.0)


def _merge(
    requirement: dict[str, Any],
    rule: dict[str, Any],
    llm_item: dict[str, Any] | None,
    lines_by_no: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Kết hợp chấm của LLM với chấm theo quy tắc; quy tắc cưỡng chế bảng anchor để điểm nhất quán giữa các lần chạy."""
    if llm_item is None:
        return rule
    try:
        match = float(llm_item.get("match", 0))
    except (TypeError, ValueError):
        return rule
    if match not in MATCH_LEVELS:
        return rule

    evidence_lines = []
    for n in llm_item.get("evidence_lines") or []:
        try:
            evidence_lines.append(lines_by_no[int(n)])
        except (KeyError, TypeError, ValueError):
            continue
    evidence_lines = [line for line in evidence_lines if not line.get("is_heading")]
    note = str(llm_item.get("note") or "").strip() or None

    if match == 0:
        # CV có ghi rõ tên kỹ năng → không để LLM đánh "Thiếu" (tránh kết luận sai bất lợi cho SV)
        return rule if rule["match"] > 0 else assessment(requirement, 0, None, note or rule["note"], "llm")
    if not evidence_lines:
        # LLM khẳng định có nhưng không chỉ ra được dòng bằng chứng → không tin, dùng kết quả quy tắc
        return rule
    # Anchor: LLM chỉ quyết định dòng bằng chứng có thật sự mô tả việc đã làm hay không (0,5 hay từ 0,75); mức
    # 0,75 / 1 do dòng bằng chứng quyết định (có số liệu hoặc là kinh nghiệm làm việc → 1), để chấm lại vẫn ra cùng điểm
    line = max(evidence_lines, key=evidence_level)
    match = 0.5 if match == 0.5 else evidence_level(line)
    if match == 0.5:
        # Ghi chú cố định thay cho lời của LLM: nói rõ kỹ năng mới được liệt kê ở đâu và cần thêm gì
        note = listing_note(requirement["name"], line)
    elif match == 0.75:
        note = metric_note(requirement["name"])
    return assessment(requirement, match, line, note or rule["note"], "llm")


def _interview_focus(raw: Any, requirements: list[dict[str, Any]], assessments: list[dict[str, Any]]) -> str | None:
    """
    Chủ đề nên chuẩn bị phỏng vấn: chỉ nhận khi nhắc đúng một kỹ năng của JD mà CV đã có câu mô tả (Match ≥ 0,75),
    để không gợi ý kể về kỹ năng CV mới liệt kê tên.
    """
    # Bỏ markdown và mã yêu cầu nội bộ ("(r5)") mà LLM đôi khi chép từ prompt
    text = " ".join(re.sub(r"\*\*|`|\s*\(r\d+\)", "", str(raw or "")).split())
    # Câu nhắc điểm chấm nội bộ ("được chấm 0.75", "match") không dành cho sinh viên đọc
    if not text or len(text) > 240 or re.search(r"\b0[.,]\d+\b|\bmatch\b", text, re.IGNORECASE):
        return None
    described = {a["id"] for a in assessments if a["match"] >= 0.75}
    for r in requirements:
        if r["id"] in described and any(contains_term(t, text) for t in [r["name"], *r.get("aliases", [])]):
            return text
    return None


async def compare_gap_node(state: GapAnalysisState) -> dict[str, Any]:
    """
    Node 3: Compare — chấm Match từng yêu cầu JD với bằng chứng trong CV (PRD 5.2).
    Dùng LLM một lần cho cả danh sách (batch), kiểm tra chéo bằng quy tắc; không có LLM thì chấm hoàn toàn bằng quy tắc.
    """
    lines = state.get("cv_lines", [])
    requirements = state.get("requirements", [])
    llm_calls = state.get("llm_calls", 0)
    rule_results = {r["id"]: assess_by_rules(r, lines) for r in requirements}

    llm_data: dict[str, Any] | None = None
    if requirements and llm_configured():
        # Thử lại một lần nếu còn trong hạn mức 2 lệnh gọi
        while llm_data is None and llm_calls < MAX_LLM_CALLS:
            llm_calls += 1
            try:
                llm_data = await score_with_llm(lines, requirements, state.get("retrieved_context", []))
            except Exception:
                logger.warning("Chấm Match bằng LLM thất bại (lần %d)", llm_calls)

    llm_items = {}
    if llm_data:
        for item in llm_data.get("requirements") or []:
            if isinstance(item, dict) and item.get("id"):
                llm_items[str(item["id"])] = item

    lines_by_no = {line["line_no"]: line for line in lines}
    assessments = [_merge(r, rule_results[r["id"]], llm_items.get(r["id"]), lines_by_no) for r in requirements]
    assessments = lift_parents(requirements, assessments, lines_by_no)

    matched = [a["skill"] for a in assessments if a["match"] > 0]
    missing = [a["skill"] for a in assessments if a["match"] == 0]
    taxonomy_matches = {a["skill"]: a["note"] for a in assessments if a["note"] and "taxonomy" in a["note"]}
    raw_suggestions = [s for s in (llm_data or {}).get("suggestions") or [] if isinstance(s, dict)]
    interview_focus = _interview_focus((llm_data or {}).get("interview_focus"), requirements, assessments)

    return {
        "assessments": assessments,
        "raw_suggestions": raw_suggestions,
        "interview_focus": interview_focus,
        "llm_used": llm_data is not None,
        "llm_calls": llm_calls,
        # Giữ các trường cũ cho script demo và báo cáo eval
        "matched_skills": matched,
        "missing_skills": missing,
        "taxonomy_matches": taxonomy_matches,
    }
