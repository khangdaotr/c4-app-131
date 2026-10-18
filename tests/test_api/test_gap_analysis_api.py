from pathlib import Path

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from sqlalchemy import delete, select

from src.config import get_settings
from src.db.database import SessionLocal, init_db
from src.db.models import CvVersion, Feedback, GapAnalysis, JobDescription
from src.services import jd_store
from tests.helpers import ADVISOR, STUDENT, make_docx, upload_cv

CV_LINES = [
    "Nguyễn Minh Anh",
    "Sinh viên năm cuối ngành Kinh doanh Quốc tế",
    "Mục tiêu: Trở thành chuyên viên phân tích dữ liệu",
    "Kinh nghiệm",
    "Thực tập sinh tại Công ty ABC: xây dựng dashboard Power BI theo dõi doanh số hằng tuần",
    "Viết truy vấn SQL tổng hợp dữ liệu đơn hàng cho báo cáo tháng",
    "Kỹ năng",
    "Python, Excel, Tableau",
]
PASTED_JD = (
    "Công ty X tuyển thực tập sinh kỹ sư dữ liệu làm việc với đội phân tích. Mô tả công việc: xây dựng pipeline "
    "xử lý dữ liệu bán hàng, viết truy vấn tổng hợp và hỗ trợ đội kinh doanh khai thác số liệu hằng tuần. "
    "Yêu cầu ứng viên: thành thạo Python và SQL, biết Docker để đóng gói dịch vụ, có kinh nghiệm làm việc "
    "với Git trong nhóm. Ưu tiên ứng viên từng tham gia dự án thực tế và có tinh thần học hỏi."
)


@pytest.fixture(autouse=True)
def clean_data():
    init_db()
    with SessionLocal() as db:
        for model in (Feedback, GapAnalysis, CvVersion):
            db.execute(delete(model))
        db.execute(delete(JobDescription).where(JobDescription.source == "pasted"))
        db.commit()


async def create_cv(client) -> dict:
    return (await upload_cv(client, "CV_MinhAnh.docx", make_docx(CV_LINES))).json()


@pytest.fixture
def recommendation_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> jd_store.JDDocumentStore:
    """Exercise real Chroma/scoring with an isolated index and no model downloads."""
    monkeypatch.setattr(get_settings(), "chroma_persist_dir", str(tmp_path / "jd-index"))
    store = jd_store.JDDocumentStore(embeddings=DeterministicFakeEmbedding(size=384))
    monkeypatch.setattr(jd_store, "_jd_store_instance", store)
    store.index_from_fixtures()
    return store


async def analyze(client, **body) -> tuple[dict, dict]:
    """Tạo lượt phân tích; trong test, tác vụ nền chạy xong trước khi request trả về."""
    created = await client.post("/api/v1/gap-analysis", json=body, headers=STUDENT)
    assert created.status_code == 202, created.text
    result = await client.get(f"/api/v1/gap-analysis/{created.json()['id']}", headers=STUDENT)
    return created.json(), result.json()


@pytest.mark.asyncio
async def test_jd_library_has_seeded_jds_with_importance(client):
    response = await client.get("/api/v1/jd/library", headers=STUDENT)
    assert response.status_code == 200
    jds = {jd["id"]: jd for jd in response.json()}
    assert len(jds) == 8
    da = jds["jd-da-intern"]
    assert da["source"] == "library" and da["content"]
    assert ("Power BI", "required") in {(s["name"], s["importance"]) for s in da["skills"]}
    assert {s["importance"] for s in da["skills"]} == {"required", "preferred", "additional"}


@pytest.mark.asyncio
async def test_library_analysis_scores_by_prd_formula(client):
    cv = await create_cv(client)
    created, result = await analyze(client, cv_version_id=cv["id"], jd_id="jd-da-intern")

    assert created["status"] == "processing"
    assert created["current_step"] == "parse"
    assert result["status"] == "completed"
    assert result["current_step"] is None
    # Required: SQL 1, Excel 0.5, Power BI 1 · Preferred: Python 0.5, Trực quan hoá 1, Thống kê 0
    # Additional: Tableau 0.5, Google Analytics 0, Tiếng Anh 0 → 11 / 18
    assert result["match_score"] == 61.1
    assert result["match_label"] == "medium"
    assert result["counts"] == {"matched": 3, "partial": 3, "missing": 3}

    rows = {r["skill"]: r for r in result["requirements"]}
    assert rows["SQL"]["evidence"]["section_label"] == "Kinh nghiệm"
    assert rows["Excel"]["status"] == "partial"
    assert rows["Thống kê"]["evidence"] is None
    # Không có LLM → không sinh câu viết lại
    assert result["llm_used"] is False and result["suggestions"] == []
    assert result["jd"]["title"] == "Data Analyst Intern"

    # Thẻ CV hiển thị "Độ khớp JD gần nhất"
    [card] = (await client.get("/api/v1/cv", headers=STUDENT)).json()
    assert card["target_title"] == "Data Analyst Intern"
    assert card["match_score"] == 61
    assert card["latest_analysis_id"] == result["id"]


@pytest.mark.asyncio
async def test_pasted_jd_requirements_are_extracted_and_saved(client):
    cv = await create_cv(client)
    _, result = await analyze(client, cv_version_id=cv["id"], jd_text=PASTED_JD, jd_title="Data Engineer Intern")

    assert result["status"] == "completed"
    assert result["jd"]["source"] == "pasted"
    skills = {r["skill"] for r in result["requirements"]}
    assert {"Python", "SQL", "Docker", "Git"} <= skills
    with SessionLocal() as db:
        jd = db.get(JobDescription, result["jd"]["id"])
        assert {s["name"] for s in jd.skills} == skills
        # Test không có LLM: yêu cầu chỉ từ từ điển, giữ "dictionary" để lần sau AI trích lại
        assert jd.skills_source == "dictionary"


@pytest.mark.asyncio
async def test_pasted_jd_without_requirements_fails_clearly(client):
    cv = await create_cv(client)
    text = " ".join(["Công ty chúng tôi đang tìm kiếm những bạn trẻ năng động và nhiệt huyết."] * 6)
    _, result = await analyze(client, cv_version_id=cv["id"], jd_text=text, jd_title="Vị trí X")
    assert result["status"] == "failed"
    assert "Không trích xuất được yêu cầu" in result["error_message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({}, 422, "jd_required"),
        ({"jd_text": "JD quá ngắn", "jd_title": "X"}, 422, "jd_too_short"),
        ({"jd_text": PASTED_JD}, 422, "jd_title_required"),
        ({"jd_id": "jd-khong-ton-tai"}, 404, "jd_not_found"),
        ({"jd_id": "jd-da-intern", "jd_text": PASTED_JD, "jd_title": "X"}, 422, "jd_source_conflict"),
    ],
    ids=["no-jd", "short-jd", "no-title", "unknown-jd", "both-sources"],
)
async def test_create_analysis_validation(client, body, status, code):
    cv = await create_cv(client)
    response = await client.post("/api/v1/gap-analysis", json={"cv_version_id": cv["id"], **body}, headers=STUDENT)
    assert response.status_code == status
    assert response.json()["code"] == code


@pytest.mark.asyncio
async def test_unknown_cv_and_analysis_are_not_found(client):
    response = await client.post(
        "/api/v1/gap-analysis", json={"cv_version_id": "cv_khong_co", "jd_id": "jd-da-intern"}, headers=STUDENT
    )
    assert response.json()["code"] == "cv_not_found"
    response = await client.get("/api/v1/gap-analysis/ga_khong_co", headers=STUDENT)
    assert response.json()["code"] == "analysis_not_found"


@pytest.mark.asyncio
async def test_advisor_cannot_create_analysis(client):
    response = await client.post("/api/v1/gap-analysis", json={"cv_version_id": "x", "jd_id": "y"}, headers=ADVISOR)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_feedback_csat_once_thumb_changeable(client):
    url = "/api/v1/feedback"
    csat = {"response_id": "ga_1", "kind": "csat", "value": 4, "activity": "gap_analysis"}
    assert (await client.post(url, json=csat, headers=STUDENT)).json()["already_submitted"] is False
    again = await client.post(url, json={**csat, "value": 1}, headers=STUDENT)
    assert again.json() == {**again.json(), "already_submitted": True, "value": 4}

    # Like / dislike: bấm nút kia thì đổi, bấm lại nút đang chọn (DELETE) thì huỷ
    thumb = {"response_id": "sg_1", "kind": "thumb", "value": 1, "activity": "gap_suggestion"}
    assert (await client.post(url, json=thumb, headers=STUDENT)).json()["value"] == 1
    changed = await client.post(url, json={**thumb, "value": -1}, headers=STUDENT)
    assert changed.json() == {**changed.json(), "already_submitted": False, "value": -1}
    params = {"response_id": "sg_1", "kind": "thumb"}
    assert (await client.get(url, params=params, headers=STUDENT)).json() == {"kind": "thumb", "value": -1}
    assert (await client.delete(url, params={"response_id": "sg_1"}, headers=STUDENT)).status_code == 204
    assert (await client.get(url, params=params, headers=STUDENT)).json() == {"kind": "thumb", "value": None}
    assert (await client.delete(url, params={"response_id": "sg_1"}, headers=STUDENT)).status_code == 204
    # CSAT không huỷ được
    csat_delete = await client.delete(url, params={"response_id": "ga_1", "kind": "csat"}, headers=STUDENT)
    assert csat_delete.status_code == 422
    empty = await client.get(url, params={"response_id": "ga_2", "kind": "csat"}, headers=STUDENT)
    assert empty.json() == {"kind": "csat", "value": None}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"response_id": "ga_1", "kind": "csat", "value": 6, "activity": "gap_analysis"},
        {"response_id": "ga_1", "kind": "csat", "value": 5},
        {"response_id": "sg_1", "kind": "thumb", "value": 2},
    ],
    ids=["csat-out-of-range", "csat-no-activity", "thumb-invalid"],
)
async def test_feedback_validation(client, body):
    response = await client.post("/api/v1/feedback", json=body, headers=STUDENT)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_recommend_jds_by_cv_version_id(client, recommendation_store):
    """Test API POST /api/v1/jd/recommend gợi ý JD từ cv_version_id đã lưu."""
    cv = await create_cv(client)
    cv_version_id = cv["id"]

    response = await client.post(
        "/api/v1/jd/recommend",
        json={"cv_version_id": cv_version_id, "top_n": 3},
        headers=STUDENT,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["cv_version_id"] == cv_version_id
    assert "recommendations" in data
    assert len(data["recommendations"]) > 0

    top_rec = data["recommendations"][0]
    assert "title" in top_rec
    assert "match_score" in top_rec
    assert "semantic_score" in top_rec


@pytest.mark.asyncio
async def test_recommend_jds_by_cv_text(client, recommendation_store):
    """Test API POST /api/v1/jd/recommend gợi ý trực tiếp từ văn bản cv_text."""
    response = await client.post(
        "/api/v1/jd/recommend",
        json={"cv_text": "Kỹ sư Backend Python thành thạo FastAPI, PostgreSQL, Docker", "top_n": 2},
        headers=STUDENT,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["recommendations"]) <= 2
    assert "Backend" in data["recommendations"][0]["title"]


@pytest.mark.asyncio
async def test_recommend_jds_errors(client, recommendation_store):
    """Kiểm tra các trường hợp lỗi: thiếu CV hoặc không tìm thấy CV."""
    # Thiếu cả cv_version_id và cv_text
    res_missing = await client.post("/api/v1/jd/recommend", json={}, headers=STUDENT)
    assert res_missing.status_code == 400

    # ID không tồn tại
    res_not_found = await client.post(
        "/api/v1/jd/recommend", json={"cv_version_id": "non-existent-id"}, headers=STUDENT
    )
    assert res_not_found.status_code == 404

    # Cố vấn không được gọi endpoint dành riêng cho sinh viên
    res_advisor = await client.post("/api/v1/jd/recommend", json={"cv_text": "Python Developer"}, headers=ADVISOR)
    assert res_advisor.status_code == 403


@pytest.mark.asyncio
async def test_recommend_scores_every_visible_library_jd(client, recommendation_store):
    """Thư viện nhỏ: mọi JD đang hiển thị đều được chấm, không bị loại trước bởi bước tìm theo vector."""
    with SessionLocal() as db:
        visible = db.scalars(
            select(JobDescription.id).where(
                JobDescription.source == "library",
                (JobDescription.status.is_(None)) | (JobDescription.status == "published"),
            )
        ).all()
    response = await client.post(
        "/api/v1/jd/recommend",
        json={
            "cv_text": "Sinh viên Kinh tế, thành thạo Excel và SQL, làm báo cáo doanh số.",
            "top_n": 10,
            "generate_advice": False,
        },
        headers=STUDENT,
    )
    assert response.status_code == 200
    ids = [r["jd_id"] for r in response.json()["recommendations"]]
    assert sorted(ids) == sorted(visible[:10])
    assert {r["score_source"] for r in response.json()["recommendations"]} == {"estimate"}


@pytest.mark.asyncio
async def test_recommend_uses_score_of_existing_analysis(client, recommendation_store):
    """CV đã phân tích với một JD: gợi ý dùng đúng điểm và nhãn của lượt phân tích đó."""
    cv = await create_cv(client)
    _, analysis = await analyze(client, cv_version_id=cv["id"], jd_id="jd-da-intern")
    assert analysis["status"] == "completed"

    response = await client.post(
        "/api/v1/jd/recommend",
        json={"cv_version_id": cv["id"], "top_n": 10, "generate_advice": False},
        headers=STUDENT,
    )
    by_id = {r["jd_id"]: r for r in response.json()["recommendations"]}
    da = by_id["jd-da-intern"]
    assert (da["score_source"], da["analysis_id"]) == ("analysis", analysis["id"])
    assert da["match_score"] == analysis["match_score"]
    assert all(r["score_source"] == "estimate" for jd_id, r in by_id.items() if jd_id != "jd-da-intern")
