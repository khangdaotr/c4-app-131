"""Thư viện JD và phân tích khoảng cách CV–JD (US-SV-02, US-SV-05)."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Query, status
from sqlalchemy import select

from src.api.deps import CurrentStudent, CurrentUser, DbSession
from src.api.errors import AppError
from src.db.models import CvVersion, GapAnalysis, JobComparisonHistory, JobDescription, utcnow
from src.models.schemas import (
    CareerAdvice,
    CompareJDsRequest,
    CompareJDsResponse,
    CreateGapAnalysisRequest,
    CreatePastedJdRequest,
    GapAnalysisResponse,
    JdDraftResponse,
    JdFields,
    JobDescriptionResponse,
    ParseJdRequest,
    RecommendJDsRequest,
    RecommendJDsResponse,
    SavedJdResponse,
    SkillRoadmapResponse,
)
from src.services import gap_analysis, jd_parser, jds
from src.services.jd_recommendation import (
    compare_selected_jds_with_llm,
    generate_career_advice_with_llm,
    recommend_top_jds_from_cv,
)
from src.services.privacy.types import Identity
from src.services.providers.gateway import provider_scope
from src.services.roadmap import get_roadmap_info

router = APIRouter()


def _latest_analysis_scores(db: DbSession, owner_id: str, cv_version_id: str) -> dict[str, dict]:
    """Lượt phân tích hoàn tất mới nhất của CV này với từng JD, để gợi ý JD dùng đúng điểm sinh viên đã xem."""
    rows = db.scalars(
        select(GapAnalysis)
        .where(
            GapAnalysis.owner_id == owner_id,
            GapAnalysis.cv_version_id == cv_version_id,
            GapAnalysis.status == "completed",
        )
        .order_by(GapAnalysis.created_at.desc())
    )
    known: dict[str, dict] = {}
    for analysis in rows:
        if analysis.jd_id in known or analysis.match_score is None:
            continue
        result = analysis.result or {}
        known[analysis.jd_id] = {
            "match_score": analysis.match_score,
            "requirements": result.get("requirements", []),
            "breakdown": result.get("breakdown", []),
            "analysis_id": analysis.id,
        }
    return known


def _roadmaps(skills: list[str]) -> dict[str, str]:
    """Link roadmap.sh cho các kỹ năng có lộ trình riêng (bỏ qua kỹ năng ngoài CNTT)."""
    infos = {skill: get_roadmap_info(skill) for skill in skills}
    return {skill: info["roadmap_url"] for skill, info in infos.items() if info["is_it_supported"]}


@router.post(
    "/jd/compare",
    response_model=CompareJDsResponse,
    tags=["Gap Analysis"],
)
@router.post(
    "/gap-analysis/compare",
    response_model=CompareJDsResponse,
    tags=["Gap Analysis"],
    include_in_schema=False,
)
async def compare_jds(
    body: CompareJDsRequest,
    user: CurrentStudent,
    db: DbSession,
) -> CompareJDsResponse:
    """
    So sánh các JD được chọn (2-3 JD) với CV của sinh viên bằng LLM:
    - Sinh viên chọn 2-3 vị trí JD mục tiêu.
    - Gọi LLM phân tích ngữ nghĩa sâu từng JD đối chiếu với CV theo bảng rubric PRD 5.2.
    - Sắp xếp kết quả theo điểm match_score (%) giảm dần.
    - Hiển thị bảng so sánh chi tiết: kỹ năng đã đáp ứng, kỹ năng chỉ mới liệt kê, kỹ năng còn thiếu, nhận xét của LLM.
    - Tổng hợp danh sách kỹ năng còn thiếu chung (common missing skills) ở tất cả các JD.
    """
    cv_text = ""
    cv_label = None
    cv_name = None
    if body.cv_version_id:
        cv = db.get(CvVersion, body.cv_version_id)
        if cv is None or cv.owner_id != user.id:
            raise AppError(404, "Không tìm thấy CV.", "cv_not_found")
        cv_text = cv.content_text
        cv_label = f"v{cv.major}.{cv.minor}" if cv.major is not None and cv.minor is not None else None
        cv_name = cv.file_name
    elif body.cv_text and body.cv_text.strip():
        cv_text = body.cv_text
    else:
        raise AppError(400, "Vui lòng cung cấp cv_version_id hoặc cv_text.", "cv_required")

    unique_jd_ids = list(dict.fromkeys(body.jd_ids))
    if len(unique_jd_ids) < 2 or len(unique_jd_ids) > 5:
        raise AppError(400, "Vui lòng chọn từ 2 đến 5 vị trí JD khác nhau để so sánh.", "invalid_jd_selection")

    # Kiểm tra bảo mật: nếu là JD tự dán, phải thuộc quyền sở hữu của chính sinh viên
    pasted_jds = db.scalars(
        select(JobDescription).where(
            JobDescription.id.in_(unique_jd_ids),
            JobDescription.source == "pasted",
        )
    ).all()
    for pjd in pasted_jds:
        if pjd.owner_id != user.id:
            raise AppError(403, "Bạn không có quyền truy cập vị trí JD này.", "jd_forbidden")

    with provider_scope(user_id=user.id, identities=(Identity(name=user.full_name, email=user.email),)):
        result = await compare_selected_jds_with_llm(
            cv_text=cv_text,
            jd_ids=unique_jd_ids,
            db=db,
        )

    found_ids = {c["jd_id"] for c in result.get("comparisons", [])}
    missing_ids = [jid for jid in unique_jd_ids if jid not in found_ids]
    if missing_ids:
        raise AppError(404, f"Không tìm thấy thông tin JD: {', '.join(missing_ids)}.", "jd_not_found")

    # Lưu lịch sử so sánh vào cơ sở dữ liệu
    history_id = f"cmp-{uuid.uuid4().hex[:12]}"
    history_record = JobComparisonHistory(
        id=history_id,
        owner_id=user.id,
        cv_version_id=body.cv_version_id,
        cv_label=cv_label,
        cv_name=cv_name,
        jd_ids=unique_jd_ids,
        total_compared=len(result["comparisons"]),
        comparisons=result["comparisons"],
        common_missing_skills=result["common_missing_skills"],
        created_at=utcnow(),
    )
    db.add(history_record)
    db.commit()

    return CompareJDsResponse(
        id=history_id,
        cv_version_id=body.cv_version_id,
        cv_label=cv_label,
        cv_name=cv_name,
        total_compared=len(result["comparisons"]),
        comparisons=result["comparisons"],
        common_missing_skills=result["common_missing_skills"],
        common_missing_roadmaps=_roadmaps(result["common_missing_skills"]),
        created_at=history_record.created_at,
    )


@router.get(
    "/jd/compare/history",
    response_model=list[CompareJDsResponse],
    tags=["Gap Analysis"],
)
def list_comparison_history(
    user: CurrentStudent,
    db: DbSession,
    limit: int = Query(default=10, ge=1, le=50, description="Số lượng lượt so sánh gần nhất"),
) -> list[CompareJDsResponse]:
    """Lấy danh sách các lượt so sánh JD của sinh viên (mới nhất trước)."""
    records = db.scalars(
        select(JobComparisonHistory)
        .where(JobComparisonHistory.owner_id == user.id)
        .order_by(JobComparisonHistory.created_at.desc())
        .limit(limit)
    ).all()

    return [
        CompareJDsResponse(
            id=r.id,
            cv_version_id=r.cv_version_id,
            cv_label=r.cv_label,
            cv_name=r.cv_name,
            total_compared=r.total_compared,
            comparisons=r.comparisons,
            common_missing_skills=r.common_missing_skills,
            common_missing_roadmaps=_roadmaps(r.common_missing_skills),
            created_at=r.created_at,
        )
        for r in records
    ]


@router.delete(
    "/jd/compare/history/{history_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Gap Analysis"],
)
def delete_comparison_history(
    history_id: str,
    user: CurrentStudent,
    db: DbSession,
) -> None:
    """Xóa một lượt so sánh khỏi lịch sử."""
    record = db.get(JobComparisonHistory, history_id)
    if record and record.owner_id == user.id:
        db.delete(record)
        db.commit()


@router.post(
    "/jd/recommend",
    response_model=RecommendJDsResponse,
    tags=["Gap Analysis"],
)
async def recommend_jds(
    body: RecommendJDsRequest,
    user: CurrentStudent,
    db: DbSession,
) -> RecommendJDsResponse:
    """
    (Task A3) Gợi ý Top-N JD phù hợp nhất với CV đã chọn kèm Matching Score từng JD (Full RAG):
    - Stage 1: Dense Retrieval tìm ứng viên qua Chroma Vector Store.
    - Stage 2: ATS Rule Scorer chấm điểm và sắp xếp theo Matching Score (PRD 5.2).
    - Stage 3: LLM Generation sinh lời khuyên nghề nghiệp và kế hoạch hành động cá nhân hóa.
    Sinh viên có thể truyền cv_version_id hoặc cv_text trực tiếp.
    """
    cv_text = ""
    if body.cv_version_id:
        cv = db.get(CvVersion, body.cv_version_id)
        if cv is None or cv.owner_id != user.id:
            raise AppError(404, "Không tìm thấy CV.", "cv_not_found")
        cv_text = cv.content_text
    elif body.cv_text and body.cv_text.strip():
        cv_text = body.cv_text
    else:
        raise AppError(400, "Vui lòng cung cấp cv_version_id hoặc cv_text.", "cv_required")

    with provider_scope(user_id=user.id, identities=(Identity(name=user.full_name, email=user.email),)) as scope:
        scope.prime(cv_text, "message", document_type="cv")
        results = recommend_top_jds_from_cv(
            cv_text=cv_text,
            db=db,
            top_n=body.top_n,
            known_scores=_latest_analysis_scores(db, user.id, body.cv_version_id) if body.cv_version_id else None,
        )

        advice = None
        if body.generate_advice:
            advice_data = await generate_career_advice_with_llm(
                cv_summary=cv_text[:800],
                recommendations=results,
            )
            advice = CareerAdvice(**advice_data)

    return RecommendJDsResponse(
        cv_version_id=body.cv_version_id,
        recommendations=results,
        advice=advice,
    )


@router.get("/jd/library", response_model=list[JobDescriptionResponse], tags=["Gap Analysis"])
def list_jd_library(user: CurrentUser, db: DbSession) -> list[JobDescription]:
    """Thư viện JD đang hiển thị, theo cấu trúc chung; kỹ năng theo mức Required / Preferred / Additional."""
    return jds.published_library(db)


@router.get("/jd", response_model=list[JobDescriptionResponse], tags=["Gap Analysis"])
def list_my_jds(user: CurrentStudent, db: DbSession) -> list[JobDescription]:
    """Các vị trí SV chọn được: thư viện JD đang hiển thị và các JD SV đã tự dán (mới nhất trước)."""
    return [*jds.published_library(db), *jds.list_pasted(db, user)]


@router.post("/jd", response_model=JobDescriptionResponse, status_code=status.HTTP_201_CREATED, tags=["Gap Analysis"])
def create_pasted_jd(body: CreatePastedJdRequest, user: CurrentStudent, db: DbSession) -> JobDescription:
    """
    Lưu JD tự dán theo cấu trúc chung. reviewed=true (hộp Thêm JD, bước xem lại): bắt buộc tên vị trí, cấp bậc, mô tả,
    yêu cầu. Không gửi các trường (màn So sánh): chỉ cần tên vị trí, phần còn lại tự tách bằng quy tắc.
    """
    fields = body.model_dump(exclude_unset=True, exclude={"text", "reviewed"})
    return jds.create_pasted(db, user, body.text, fields, reviewed=body.reviewed)


@router.post("/jd/parse", response_model=JdDraftResponse, tags=["Gap Analysis"])
async def parse_jd(body: ParseJdRequest, user: CurrentUser, db: DbSession) -> dict:
    """
    Tách toàn văn JD thành cấu trúc chung (chưa lưu): quy tắc trước, chỉ gọi AI khi còn thiếu tên vị trí, mô tả hoặc
    yêu cầu. Dùng cho hộp Thêm JD của sinh viên và form Thêm JD vào thư viện của quản trị viên.
    """
    if user.role not in ("student", "admin"):
        raise AppError(403, "Chức năng này dành cho sinh viên và quản trị viên.", "forbidden")
    if len(body.text.split()) < jds.JD_MIN_WORDS:
        raise AppError(422, f"Nội dung JD quá ngắn. Hãy dán tối thiểu {jds.JD_MIN_WORDS} từ.", "jd_too_short")
    draft = await jd_parser.parse(db, body.text)
    return {**draft, "word_count": jds.word_count(body.text)}


@router.get("/jd/mine", response_model=list[JobDescriptionResponse], tags=["Gap Analysis"])
def list_pasted_jds(user: CurrentStudent, db: DbSession) -> list[JobDescription]:
    """JD của bạn: các JD sinh viên tự dán (chỉ người dán thấy), mới nhất trước."""
    return jds.list_pasted(db, user)


@router.patch("/jd/{jd_id}", response_model=JobDescriptionResponse, tags=["Gap Analysis"])
def update_pasted_jd(jd_id: str, body: JdFields, user: CurrentStudent, db: DbSession) -> JobDescription:
    """Sửa JD tự dán (không tách lại toàn văn, kỹ năng giữ nguyên)."""
    return jds.update_pasted(db, user, jd_id, body.model_dump(exclude_unset=True))


@router.delete("/jd/{jd_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Gap Analysis"])
def delete_pasted_jd(jd_id: str, user: CurrentStudent, db: DbSession) -> None:
    """Xoá JD tự dán khỏi danh sách; các lượt phân tích, phỏng vấn đã làm với JD này vẫn mở được."""
    jds.delete_pasted(db, user, jd_id)


@router.get("/jd/saved", response_model=list[SavedJdResponse], tags=["Gap Analysis"])
def list_saved_jds(user: CurrentStudent, db: DbSession) -> list[dict]:
    """Vị trí SV đã lưu (♥), mới lưu trước."""
    return [jds.saved_out(s) for s in jds.list_saved(db, user)]


@router.put("/jd/{jd_id}/saved", response_model=SavedJdResponse, tags=["Gap Analysis"])
def save_jd(jd_id: str, user: CurrentStudent, db: DbSession) -> dict:
    return jds.saved_out(jds.save(db, user, jd_id))


@router.delete("/jd/{jd_id}/saved", status_code=status.HTTP_204_NO_CONTENT, tags=["Gap Analysis"])
def unsave_jd(jd_id: str, user: CurrentStudent, db: DbSession) -> None:
    jds.unsave(db, user, jd_id)


@router.post(
    "/gap-analysis",
    response_model=GapAnalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Gap Analysis"],
)
def create_gap_analysis(
    body: CreateGapAnalysisRequest,
    user: CurrentStudent,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> GapAnalysisResponse:
    """
    Tạo lượt phân tích CV–JD và chạy nền. Trả về ngay với status "processing";
    frontend hỏi lại GET /gap-analysis/{id} để theo dõi current_step cho tới khi xong.
    """
    analysis = gap_analysis.create_analysis(db, user, body)
    background_tasks.add_task(gap_analysis.run_analysis, analysis.id)
    return gap_analysis.to_response(analysis, db.get(JobDescription, analysis.jd_id))


@router.get("/gap-analysis/{analysis_id}", response_model=GapAnalysisResponse, tags=["Gap Analysis"])
def get_gap_analysis(analysis_id: str, user: CurrentStudent, db: DbSession) -> GapAnalysisResponse:
    """Tiến độ hoặc kết quả của một lượt phân tích (chỉ chủ sở hữu xem được)."""
    analysis = db.get(GapAnalysis, analysis_id)
    if analysis is None or analysis.owner_id != user.id:
        raise AppError(404, "Không tìm thấy kết quả phân tích.", "analysis_not_found")
    return gap_analysis.to_response(analysis, db.get(JobDescription, analysis.jd_id))


@router.get("/skills/roadmap", response_model=SkillRoadmapResponse, tags=["Gap Analysis"])
def get_skill_roadmap(
    user: CurrentUser,
    skill: str = Query(..., min_length=1, description="Tên kỹ năng cần tra cứu lộ trình học trên roadmap.sh"),
) -> SkillRoadmapResponse:
    """Tra cứu đường dẫn lộ trình học tập roadmap.sh cho một kỹ năng bất kỳ."""
    info = get_roadmap_info(skill)
    return SkillRoadmapResponse(**info)
