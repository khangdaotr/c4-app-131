import pytest

from src.agents.gap_analysis.graph import gap_analysis_agent
from src.agents.gap_analysis.nodes import compare_gap, verify_grounding
from src.services import guardrails
from src.services.skill_matching import (
    assess_by_rules,
    compute_score,
    match_label,
    normalize_requirements,
    split_cv_lines,
)
from src.services.taxonomy import (
    STATIC_TAXONOMY,
    apply_taxonomy_matching,
    check_skill_match,
    get_parent_skill,
)


def test_static_taxonomy_mappings():
    """Kiểm tra các cặp mapping taxonomy bắt buộc theo yêu cầu đề bài."""
    expected_pairs = {
        "FastAPI": "Python",
        "Flask": "Python",
        "Django": "Python",
        "PyTorch": "Machine Learning",
        "TensorFlow": "Machine Learning",
        "React": "JavaScript",
        "Next.js": "JavaScript",
    }
    for child, parent in expected_pairs.items():
        assert STATIC_TAXONOMY.get(child) == parent
        assert get_parent_skill(child) == parent


def test_taxonomy_skill_match_logic():
    """Kiểm tra logic so khớp kỹ năng trực tiếp và qua taxonomy."""
    # Trực tiếp
    match, _ = check_skill_match("Python", "Python")
    assert match is True

    # Ứng viên có kỹ năng con (FastAPI) đáp ứng yêu cầu cha (Python)
    match, reason = check_skill_match("FastAPI", "Python")
    assert match is True
    assert reason is not None and "taxonomy" in reason.lower()

    # Ứng viên có PyTorch đáp ứng yêu cầu Machine Learning
    match, _ = check_skill_match("PyTorch", "Machine Learning")
    assert match is True

    # Kỹ năng không liên quan
    match, _ = check_skill_match("React", "Python")
    assert match is False


def test_apply_taxonomy_matching_list():
    """Kiểm tra hàm so khớp danh sách kỹ năng tổng thể."""
    cv_skills = ["Flask", "Django", "PyTorch", "Git"]
    jd_skills = ["Python", "Machine Learning", "Docker", "Git"]

    matched, missing, tax_notes = apply_taxonomy_matching(cv_skills, jd_skills)

    assert "Git" in matched  # Trùng khớp trực tiếp
    assert "Python" in matched  # Match qua Flask/Django -> Python
    assert "Machine Learning" in matched  # Match qua PyTorch -> Machine Learning
    assert "Docker" in missing  # Thiếu Docker
    assert len(tax_notes) > 0


@pytest.mark.asyncio
async def test_gap_analysis_graph_4_nodes_flow(monkeypatch):
    """
    Kiểm thử luồng chạy tuần tự 4 node của Gap Analysis Agent:
    parse -> retrieve -> compare -> generate
    """
    monkeypatch.setattr(compare_gap, "llm_configured", lambda: False)
    cv_text = """
    # Nguyễn Văn A - Software Engineer
    - Kỹ năng: Python, Flask, Django, Docker, PostgreSQL, Git
    - Kinh nghiệm: 2 năm làm Backend Developer với Flask và PostgreSQL.
    """
    jd_text = """
    Tuyển dụng Senior Python Backend Engineer:
    Yêu cầu: Python, FastAPI, PostgreSQL, Docker, Qdrant, Redis.
    Kinh nghiệm xây dựng REST API và triển khai hệ thống AI/Backend.
    """

    initial_state = {
        "cv_raw": cv_text,
        "jd_raw": jd_text,
    }

    result = await gap_analysis_agent.ainvoke(initial_state)

    # 1. Kiểm tra đầu ra matched_skills và missing_skills
    assert "matched_skills" in result
    assert "missing_skills" in result
    assert isinstance(result["matched_skills"], list)
    assert isinstance(result["missing_skills"], list)

    # Python, Docker, PostgreSQL là matched
    assert "Python" in result["matched_skills"]
    assert "PostgreSQL" in result["matched_skills"]
    assert "Docker" in result["matched_skills"]

    # Qdrant, Redis là missing
    assert "Qdrant" in result["missing_skills"]
    assert "Redis" in result["missing_skills"]

    # 2. Không có LLM: không sinh câu viết lại từ mẫu có sẵn (tránh thêm thông tin không có trong CV — PRD mục 6)
    assert result["llm_used"] is False
    assert result["suggestions"] == []

    # Mọi bằng chứng đều là nguyên văn một dòng trong CV gốc
    for item in result["assessments"]:
        if item["evidence"]:
            assert item["evidence"]["text"] in cv_text

    # 3. Kiểm tra ngữ cảnh retrieved_context từ RAG (top-k=3-5)
    assert "retrieved_context" in result
    retrieved = result["retrieved_context"]
    assert 3 <= len(retrieved) <= 5


# ---------- CV–JD Matching Score theo PRD mục 5.2 ----------

CV_DATA_ANALYST = """Nguyễn Minh Anh
Mục tiêu: Trở thành chuyên viên phân tích dữ liệu
KINH NGHIỆM
Thực tập sinh tại Công ty ABC: xây dựng dashboard Power BI theo dõi doanh số hằng tuần
Viết truy vấn SQL tổng hợp dữ liệu đơn hàng cho báo cáo tháng
KỸ NĂNG
Python, Excel, Tableau"""


def test_split_cv_lines_assigns_sections():
    lines = split_cv_lines(CV_DATA_ANALYST)
    by_text = {line["text"]: line for line in lines}
    assert by_text["Nguyễn Minh Anh"]["section"] == "header"
    assert by_text["Mục tiêu: Trở thành chuyên viên phân tích dữ liệu"]["section"] == "summary"
    assert by_text["KINH NGHIỆM"]["is_heading"] is True
    assert by_text["Viết truy vấn SQL tổng hợp dữ liệu đơn hàng cho báo cáo tháng"]["section"] == "experience"
    assert by_text["Python, Excel, Tableau"]["section"] == "skills"


def test_inline_listing_inside_entry_keeps_section():
    """'Technologies: ...' trong mục Kinh nghiệm không biến các dòng mô tả phía sau thành mục Kỹ năng."""
    lines = split_cv_lines(
        "EXPERIENCE\nWeb Developer Intern\nTechnologies: React.js, Git\nXây dựng API CRUD bằng Python FastAPI.\n"
        "KỸ NĂNG\nPython, SQL\nCông cụ: Git, Docker"
    )
    by_text = {line["text"]: line for line in lines}
    listing = by_text["Technologies: React.js, Git"]
    assert (listing["section"], listing["block"]) == ("skills", "experience")
    described = by_text["Xây dựng API CRUD bằng Python FastAPI."]
    assert (described["section"], described["block"]) == ("experience", "experience")
    assert by_text["Công cụ: Git, Docker"]["block"] == "skills"
    [python] = normalize_requirements([{"name": "Python", "importance": "required"}])
    assert assess_by_rules(python, lines)["match"] == 1


def test_listing_note_says_where_the_skill_is_listed():
    """Mức 0,5: ghi chú nói rõ kỹ năng nằm ở dòng công nghệ của mục nào và cần thêm câu mô tả gì."""
    lines = split_cv_lines(
        "PROJECTS\nMaintenance Platform\nTechnologies: Python, FastAPI, Redis\n"
        "Sử dụng Redis để cache dữ liệu trạng thái thiết bị.\nSKILLS\nPython, FastAPI, Git"
    )
    fastapi, git = (
        assess_by_rules(r, lines)
        for r in normalize_requirements([{"name": "FastAPI", "importance": "preferred"}, {"name": "Git"}])
    )
    assert fastapi["match"] == 0.5
    # Dòng công nghệ của dự án hiện "Mục Dự án", không phải "Mục Kỹ năng"
    assert fastapi["evidence"]["section_label"] == "Dự án"
    assert fastapi["note"] == "Có trong dòng công nghệ nhưng chưa có câu mô tả bạn đã dùng FastAPI làm gì"
    assert git["match"] == 0.5 and git["evidence"]["section_label"] == "Kỹ năng"
    assert git["note"].startswith("Chỉ có trong danh sách kỹ năng")


def test_rule_anchor_levels():
    lines = split_cv_lines(CV_DATA_ANALYST)
    reqs = normalize_requirements(
        [
            {"name": "SQL", "importance": "required"},
            {"name": "Excel", "importance": "required"},
            {"name": "Thống kê", "importance": "preferred"},
        ]
    )
    sql, excel, stats = (assess_by_rules(r, lines) for r in reqs)
    assert (sql["match"], sql["evidence"]["section"]) == (1, "experience")
    assert (excel["match"], excel["evidence"]["section"]) == (0.5, "skills")
    assert (stats["match"], stats["evidence"]) == (0, None)


def test_rule_taxonomy_child_counts_as_parent():
    lines = split_cv_lines("KINH NGHIỆM\nXây dựng REST API cho hệ thống đặt lịch bằng FastAPI")
    [python] = normalize_requirements([{"name": "Python", "importance": "required"}])
    result = assess_by_rules(python, lines)
    assert result["match"] == 1
    assert "taxonomy" in result["note"]


def test_score_formula_matches_prd_example():
    """Ví dụ trong PRD mục 5.2: (3 + 3 + 1.5 + 0 + 0 + 1) / 14 × 100% = 60.7%."""
    rows = [("SQL", "required", 1), ("Python", "required", 1), ("Excel", "required", 0.5)]
    rows += [("Power BI", "preferred", 0), ("Tableau", "preferred", 0), ("Git", "additional", 1)]
    items = [
        {"importance": imp, "match": m, "status": {1: "matched", 0.5: "partial", 0: "missing"}[m]} for _, imp, m in rows
    ]
    score, breakdown = compute_score(items)
    assert score == 60.7
    assert match_label(score) == "medium"
    assert [b["weight"] for b in breakdown] == [3, 2, 1]


def test_score_can_reach_zero_and_hundred_unclamped():
    """Kiểm tra điểm phản ánh 100% đánh giá thực tế (có thể đạt 100.0 hoặc 0.0, không bị clamp cố định)."""
    # 1. Trường hợp CV hoàn hảo (match = 1 cho tất cả) -> đạt 100.0%
    perfect_rows = [("SQL", "required", 1), ("Python", "required", 1), ("Git", "additional", 1)]
    perfect_items = [{"importance": imp, "match": m, "status": "matched"} for _, imp, m in perfect_rows]
    perf_score, _ = compute_score(perfect_items)
    assert perf_score == 100.0

    # 2. Trường hợp CV không khớp kỹ năng nào (match = 0 cho tất cả) -> đạt 0.0%
    zero_rows = [("SQL", "required", 0), ("Python", "required", 0), ("Git", "additional", 0)]
    zero_items = [{"importance": imp, "match": m, "status": "missing"} for _, imp, m in zero_rows]
    zero_score, _ = compute_score(zero_items)
    assert zero_score == 0.0


@pytest.mark.asyncio
async def test_llm_batch_scoring_is_cross_checked(monkeypatch, tmp_path):
    """Kết quả LLM được kiểm tra chéo bằng quy tắc anchor và guardrail trước khi hiển thị."""
    requirements = [
        {"name": "Power BI", "importance": "required"},
        {"name": "Excel", "importance": "required"},
        {"name": "Thống kê", "importance": "preferred"},
    ]
    calls = []

    async def fake_score(lines, reqs, context):
        calls.append(1)
        return {
            "requirements": [
                {"id": "r1", "match": 1, "evidence_lines": [4], "note": ""},
                # Excel chỉ nằm ở mục Kỹ năng → phải hạ xuống 0.5 dù LLM chấm 1
                {"id": "r2", "match": 1, "evidence_lines": [7], "note": ""},
                # LLM khẳng định có nhưng không chỉ ra dòng bằng chứng → bỏ, dùng kết quả quy tắc (0)
                {"id": "r3", "match": 1, "evidence_lines": [], "note": ""},
            ],
            "suggestions": [
                {
                    "requirement_id": "r1",
                    "line": 4,
                    "rewrite": "Xây dựng dashboard Power BI theo dõi doanh số hằng tuần cho Công ty ABC",
                    "reason": "Nêu rõ công cụ",
                },
                # Thêm số liệu không có trong CV → guardrail chặn, chờ cố vấn xem lại
                {
                    "requirement_id": "r1",
                    "line": 5,
                    "rewrite": "Viết truy vấn SQL tổng hợp dữ liệu đơn hàng cho báo cáo tháng, giúp giảm 30% thời gian làm báo cáo",
                    "reason": "Định lượng",
                },
                # Dòng chỉ liệt kê kỹ năng → không viết lại
                {"requirement_id": "r2", "line": 7, "rewrite": "Kỹ năng: Microsoft Excel", "reason": "Chuẩn hoá tên"},
                # Kỹ năng CV chưa có → không được sinh câu mới
                {
                    "requirement_id": "r3",
                    "line": 4,
                    "rewrite": "Áp dụng thống kê để phân tích doanh số",
                    "reason": "Bổ sung",
                },
            ],
            "summary": "CV có bằng chứng tốt cho Power BI.",
        }

    monkeypatch.setattr(compare_gap, "llm_configured", lambda: True)
    monkeypatch.setattr(compare_gap, "score_with_llm", fake_score)
    audit_db = tmp_path / "audit.db"
    monkeypatch.setattr(
        verify_grounding,
        "check_output_grounding",
        lambda **kw: guardrails.check_output_grounding(**kw, db_path=audit_db),
    )

    result = await gap_analysis_agent.ainvoke(
        {"cv_raw": CV_DATA_ANALYST, "jd_raw": "JD Data Analyst", "requirements": requirements}
    )

    by_skill = {a["skill"]: a for a in result["assessments"]}
    assert by_skill["Power BI"]["match"] == 1
    assert (by_skill["Excel"]["match"], by_skill["Excel"]["source"]) == (0.5, "llm")
    assert (by_skill["Thống kê"]["match"], by_skill["Thống kê"]["source"]) == (0, "rule")
    assert [s["skill"] for s in result["suggestions"]] == ["Power BI"]
    assert len(result["manual_review_items"]) == 1
    assert result["match_score"] == round((3 * 1 + 3 * 0.5 + 0) / 8 * 100, 1)
    # Nhận xét ghép từ bảng cuối, không lấy lời LLM: Thống kê (Ưu tiên) thiếu, Excel mới liệt kê, Power BI đáp ứng
    assert result["gap_summary"] == (
        "Đáp ứng tốt: Power BI. Excel mới được liệt kê: thêm một câu mô tả bạn đã dùng kỹ năng này làm gì. "
        "Còn thiếu yêu cầu Ưu tiên: Thống kê. Nên học và thực hành các kỹ năng này, ví dụ qua một dự án nhỏ, "
        "trước khi ứng tuyển."
    )
    assert len(calls) == 1 and result["llm_calls"] == 1
