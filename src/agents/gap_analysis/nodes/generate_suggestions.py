import uuid
from typing import Any

from src.agents.gap_analysis.state import GapAnalysisState
from src.services.cv_rewrite import check_rewrite, wrapped_line_nos
from src.services.fit_summary import compose_summary
from src.services.skill_matching import SECTION_LABELS, compute_score, is_descriptive

MAX_SUGGESTIONS = 5


def build_suggestions(
    raw_suggestions: list[dict[str, Any]],
    assessments: list[dict[str, Any]],
    lines: list[dict[str, Any]],
    cv_raw: str = "",
) -> list[dict[str, Any]]:
    """
    Chuẩn hoá gợi ý viết lại từ LLM. Chỉ giữ gợi ý trỏ tới một dòng mô tả việc đã làm có thật trong CV
    (bỏ dòng liệt kê kỹ năng, dòng tiêu đề), thuộc yêu cầu CV đã đáp ứng (Match > 0) — không bao giờ tạo câu mới cho
    kỹ năng CV chưa có (PRD mục 6.1). Bỏ gợi ý làm mất số thật, đổi ngôn ngữ dòng gốc hoặc nhắc công cụ / tổ chức
    không có trong mục CV của dòng đó.
    """
    by_id = {a["id"]: a for a in assessments}
    lines_by_no = {line["line_no"]: line for line in lines}
    # Gạch ý bị ngắt dòng khi trích PDF: không viết lại từng mẩu (Trình tối ưu viết lại cả gạch ý)
    wrapped = wrapped_line_nos(lines, cv_raw) if cv_raw else set()
    result: list[dict[str, Any]] = []
    used_lines: set[int] = set()
    for raw in raw_suggestions:
        requirement = by_id.get(str(raw.get("requirement_id", "")))
        try:
            line = lines_by_no[int(raw.get("line"))]
        except (KeyError, TypeError, ValueError):
            continue
        if (
            not requirement
            or requirement["match"] == 0
            or not is_descriptive(line)
            or line["line_no"] in used_lines
            or line["line_no"] in wrapped
        ):
            continue
        # Bỏ gợi ý trùng câu gốc, làm mất số thật, đổi ngôn ngữ dòng gốc hoặc nhắc công cụ ngoài mục CV của dòng
        rewrite = check_rewrite(line, str(raw.get("rewrite") or ""), lines_by_no)
        if rewrite is None:
            continue
        used_lines.add(line["line_no"])
        result.append(
            {
                "id": f"sg_{uuid.uuid4().hex[:12]}",
                "skill": requirement["skill"],
                "line_no": line["line_no"],
                "section_label": SECTION_LABELS.get(line["section"], line["section"]),
                # evidence_span/original_text: nguyên văn dòng CV; verify_grounding đối chiếu với CV gốc
                "evidence_span": line["text"],
                "original_text": line["text"],
                "suggested_revision": rewrite,
                "rationale": str(raw.get("reason") or "").strip(),
            }
        )
        if len(result) >= MAX_SUGGESTIONS:
            break
    return result


def fallback_summary(assessments: list[dict[str, Any]], score: float | None) -> str:
    matched = [a["skill"] for a in assessments if a["status"] == "matched"]
    partial = [a["skill"] for a in assessments if a["status"] == "partial"]
    missing = [a["skill"] for a in assessments if a["status"] == "missing"]
    parts = []
    if score is not None:
        parts.append(f"CV hiện đáp ứng {score:g}% tổng trọng số các yêu cầu được hệ thống trích xuất từ JD.")
    if matched:
        parts.append(f"Có bằng chứng cụ thể cho: {', '.join(matched)}.")
    if partial:
        parts.append(f"Mới chỉ liệt kê, chưa có mô tả sử dụng: {', '.join(partial)}.")
    if missing:
        parts.append(f"Chưa tìm thấy trong CV: {', '.join(missing)}.")
    if matched and not partial and not missing:
        parts.append("Ở vòng phỏng vấn, nhà tuyển dụng thường hỏi sâu cách bạn đã làm; nên chuẩn bị kể cụ thể.")
    elif missing and not matched and not partial:
        parts.append("Có thể bắt đầu từ một kỹ năng còn thiếu, làm một dự án nhỏ rồi cập nhật vào CV.")
    return " ".join(parts)


async def generate_suggestions_node(state: GapAnalysisState) -> dict[str, Any]:
    """
    Node 4: Generate — chuẩn hoá gợi ý diễn đạt lại (đã sinh cùng lệnh gọi LLM ở bước so sánh để giữ hạn mức
    2 lệnh gọi/lượt), tính CV–JD Matching Score và soạn khuyến nghị.
    """
    assessments = state.get("assessments", [])
    suggestions = build_suggestions(
        state.get("raw_suggestions", []), assessments, state.get("cv_lines", []), state.get("cv_raw", "")
    )
    score, breakdown = compute_score(assessments)

    missing = [a["skill"] for a in assessments if a["status"] == "missing"]
    partial = [a["skill"] for a in assessments if a["status"] == "partial"]
    recommendations = []
    if partial:
        recommendations.append(
            f"Bổ sung mô tả dự án hoặc kinh nghiệm thật cho các kỹ năng mới chỉ được liệt kê: {', '.join(partial)}."
        )
    if missing:
        # PRD 5.2: không khuyên thêm từ khoá còn thiếu vào CV; đây là kỹ năng cần học thêm nếu SV chưa có
        recommendations.append(
            f"Kỹ năng JD yêu cầu nhưng chưa thấy trong CV: {', '.join(missing)}. Nếu bạn thực sự đã làm, hãy bổ sung "
            "kèm bằng chứng; nếu chưa, đây là kỹ năng nên học thêm."
        )

    return {
        "suggestions": suggestions,
        "recommendations": recommendations,
        "match_score": score,
        "score_breakdown": breakdown,
        "gap_summary": compose_summary(assessments, state.get("cv_lines", [])) or fallback_summary(assessments, score),
    }
