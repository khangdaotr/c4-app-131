from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

# Thời điểm lưu trong DB là UTC dạng naive; khi trả về luôn kèm múi giờ để trình duyệt hiểu đúng.
UtcDatetime = Annotated[
    datetime,
    PlainSerializer(lambda d: (d if d.tzinfo else d.replace(tzinfo=UTC)).isoformat(), return_type=str),
]

# ============================================================================
# 1. Health & Status Schemas
# ============================================================================


class HealthResponse(BaseModel):
    """Schema phản hồi kiểm tra sức khỏe hệ thống."""

    status: str = Field(default="ok", description="Trạng thái hệ thống (ok / healthy)")
    env: str = Field(default="development", description="Môi trường hiện tại (development / production)")
    version: str = Field(default="1.0.0", description="Phiên bản API")


class AgentStatusResponse(BaseModel):
    """Schema thông tin trạng thái Agent và LLM Provider."""

    status: str = Field(default="ready", description="Trạng thái agent")
    agent: str = Field(default="LangGraph Agent v1.0", description="Tên agent")
    llm_provider: str = Field(default="groq", description="Provider đang kích hoạt (groq / openrouter / openai)")
    model_name: str = Field(default="openai/gpt-oss-120b", description="Tên model đang dùng")
    langsmith_tracing: bool = Field(default=False, description="Trạng thái LangSmith tracing")


class UserProfile(BaseModel):
    """Hồ sơ người dùng đang đăng nhập (khớp UserProfile trong frontend/lib/types.ts)."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Mã người dùng")
    role: Literal["student", "advisor", "admin"] = Field(..., description="Vai trò")
    full_name: str = Field(..., description="Họ và tên")
    subtitle: str = Field(default="", description="Dòng phụ: email (SV) hoặc chức danh (cố vấn)")
    avatar_url: str | None = Field(default=None, description="Ảnh đại diện")
    must_change_password: bool = Field(
        default=False, description="Đang dùng mật khẩu tạm do quản trị viên đặt: phải đổi trước khi dùng tiếp"
    )

    @field_validator("must_change_password", mode="before")
    @classmethod
    def _flag(cls, value: bool | None) -> bool:
        return bool(value)


# ============================================================================
# 2. General Chat Schemas
# ============================================================================


class ChatRequest(BaseModel):
    """Schema gửi tin nhắn trò chuyện với Agent."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Tin nhắn từ người dùng",
        examples=["Cho tôi lời khuyên tối ưu CV ngành AI Engineer"],
    )
    conversation_id: str | None = Field(
        default=None,
        description="ID phiên hội thoại (tự tạo nếu None)",
    )
    stream: bool = Field(
        default=False,
        description="Bật chế độ phản hồi dạng stream",
    )


class ChatResponse(BaseModel):
    """Schema phản hồi tin nhắn từ Agent."""

    response: str = Field(..., description="Nội dung phản hồi từ AI Agent")
    conversation_id: str = Field(default="", description="ID phiên hội thoại")
    analysis: str = Field(default="", description="Phân tích nội bộ / suy luận của agent")
    sources: list[str] = Field(default_factory=list, description="Danh sách tài liệu trích dẫn nguồn")
    timestamp: datetime = Field(default_factory=datetime.now, description="Thời gian phản hồi")


# ============================================================================
# 3. CV Upload & Versioning Schemas (US-SV-01, US-SV-03)
# ============================================================================


class CvVersionResponse(BaseModel):
    """Một phiên bản CV (khớp CvVersion trong frontend/lib/types.ts)."""

    id: str = Field(..., description="Mã phiên bản CV")
    version: int = Field(..., description="Số thứ tự nội bộ, tăng dần trên mọi CV của SV, không ghi đè bản cũ")
    label: str = Field(
        ..., description="Nhãn trong CV: 'v1.0' bản tải lên, số phụ +1 mỗi lần tối ưu, số chính +1 khi khôi phục"
    )
    family_id: str = Field(..., description="Mã CV (các phiên bản cùng mã là một CV, một thẻ trong 'CV của tôi')")
    version_count: int = Field(default=1, description="Số phiên bản của CV này (có ở danh sách CV)")
    file_name: str = Field(..., description="Tên file gốc")
    file_type: Literal["pdf", "docx", "png", "jpg", "jpeg"] = Field(..., description="Định dạng file")
    size_bytes: int = Field(..., description="Dung lượng file (byte)")
    page_count: int | None = Field(default=None, description="Số trang (chỉ có với PDF)")
    read_by_ocr: bool = Field(
        default=False,
        description="Chữ được đọc bằng OCR vì file gốc là PDF scan (bản tối ưu / khôi phục thừa hưởng từ bản gốc)",
    )
    uploaded_at: UtcDatetime = Field(..., description="Thời điểm tải lên / tạo phiên bản")
    status: Literal["processing", "ready", "failed"] = Field(default="ready", description="Trạng thái xử lý")
    error_message: str | None = Field(default=None, description="Lý do khi status = failed")
    target_title: str | None = Field(default=None, description="Vị trí (JD) của lần phân tích gần nhất")
    match_score: int | None = Field(
        default=None, description="CV–JD Matching Score (0–100) của lần phân tích gần nhất — không phải điểm ATS"
    )
    origin: Literal["upload", "optimized", "restored"] = Field(default="upload", description="Nguồn tạo phiên bản")
    latest_analysis_id: str | None = Field(default=None, description="Lần phân tích gần nhất của phiên bản này")
    source_analysis_id: str | None = Field(
        default=None, description="Lượt phân tích đã dùng để tối ưu ra phiên bản này (origin = 'optimized')"
    )
    source_jd_title: str | None = Field(
        default=None, description="Vị trí của JD đã dùng để tối ưu ra phiên bản này (có ở lịch sử phiên bản)"
    )
    restored_from_label: str | None = Field(
        default=None, description="Nhãn phiên bản cũ được khôi phục thành bản này (origin = 'restored')"
    )
    is_active: bool = Field(default=False, description="Phiên bản đang dùng")
    is_draft: bool = Field(default=False, description="Bản nháp")


class CvTextResponse(BaseModel):
    """Văn bản đã trích từ CV (dùng cho xem nhanh file DOCX)."""

    text: str = Field(..., description="Nội dung văn bản của CV")


# ============================================================================
# 4. JD & Gap Analysis Schemas (CV vs JD) (US-SV-02, US-SV-05, PRD mục 5.2)
# ============================================================================

Importance = Literal["required", "preferred", "additional"]


class JdSkill(BaseModel):
    """Một yêu cầu kỹ năng trong JD kèm mức độ quan trọng (trọng số 3 / 2 / 1)."""

    name: str = Field(..., description="Tên kỹ năng / yêu cầu")
    importance: Importance = Field(..., description="Required (3) / Preferred (2) / Additional (1)")
    aliases: list[str] = Field(default_factory=list, description="Tên gọi khác")


JobLevel = Literal["intern", "fresher", "junior"]
EmploymentType = Literal["full_time", "part_time", "internship"]
WorkMode = Literal["onsite", "remote", "hybrid"]
ExperienceLevel = Literal["none", "under_1", "1_2", "2_plus"]


class JdFields(BaseModel):
    """Các trường của cấu trúc chung (đều không bắt buộc ở mức schema; service kiểm tra theo loại JD)."""

    title: str | None = None
    company: str | None = None
    level: JobLevel | None = None
    industry: str | None = None
    employment_type: EmploymentType | None = None
    work_mode: WorkMode | None = None
    location: str | None = None
    salary: str | None = Field(default=None, description="Chữ tự do: 12 – 15 triệu, Thoả thuận")
    deadline: date | None = None
    experience: ExperienceLevel | None = None
    majors: list[str] | None = None
    description: str | None = Field(default=None, description="Mô tả công việc")
    requirements: str | None = Field(default=None, description="Yêu cầu ứng viên")
    benefits: str | None = None
    how_to_apply: str | None = None


class JobDescriptionResponse(JdFields):
    """JD trong thư viện hoặc JD sinh viên tự dán, theo cấu trúc chung."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    content: str = Field(..., description="Toàn văn JD")
    skills: list[JdSkill] = Field(default_factory=list, description="Yêu cầu kỹ năng theo mức độ")
    skills_source: str | None = Field(default=None, description="dictionary / sections / ai / analysis / admin")
    source: Literal["library", "pasted"]
    created_at: UtcDatetime | None = None


class JdSkillInput(BaseModel):
    name: str
    importance: Importance
    aliases: list[str] = Field(default_factory=list)


class ParseJdRequest(BaseModel):
    text: str = Field(..., max_length=20000, description="Toàn văn JD")


class JdDraftResponse(JdFields):
    """Bản nháp tách từ toàn văn (chưa lưu)."""

    skills: list[JdSkill] = Field(default_factory=list)
    skills_source: str
    used_ai: bool = Field(..., description="Có dùng AI để tách (khi quy tắc còn thiếu trường chính)")
    word_count: int


class JDRecommendationItem(BaseModel):
    """Một vị trí JD được đề xuất dựa trên CV (Task A3)."""

    jd_id: str
    title: str
    company: str | None = None
    industry: str | None = None
    level: str | None = None
    semantic_score: float = Field(..., description="Độ tương đồng ngữ nghĩa từ Vector Store (0-1)")
    match_score: float | None = Field(default=None, description="Điểm phù hợp CV–JD theo trọng số PRD 5.2 (0-100)")
    match_label: Literal["low", "medium", "high"] | None = Field(
        default=None, description="Thấp (< 50) / Trung bình (50–74) / Cao (≥ 75)"
    )
    matched_skills: list[str] = Field(default_factory=list, description="Kỹ năng sinh viên đã đáp ứng có bằng chứng")
    partial_skills: list[str] = Field(default_factory=list, description="Kỹ năng chỉ được liệt kê trong CV")
    missing_skills: list[str] = Field(default_factory=list, description="Kỹ năng còn thiếu theo yêu cầu JD")
    breakdown: list[dict[str, Any]] = Field(
        default_factory=list, description="Phân rã điểm theo Required/Preferred/Additional"
    )
    score_source: Literal["analysis", "estimate"] = Field(
        default="estimate",
        description="analysis: lấy từ lượt phân tích đã có của CV này; estimate: ước tính nhanh bằng quy tắc",
    )
    analysis_id: str | None = Field(
        default=None, description="Lượt phân tích dùng làm điểm khi score_source = analysis"
    )


class CareerAdvice(BaseModel):
    """Lời khuyên tư vấn nghề nghiệp từ AI dựa trên kết quả đối sánh (RAG Generation)."""

    summary: str = Field(..., description="Nhận xét tổng quan về mức độ phù hợp nghề nghiệp")
    top_position_advice: str = Field(..., description="Lời khuyên chi tiết cho vị trí phù hợp nhất")
    action_plan: list[str] = Field(default_factory=list, description="Kế hoạch hành động cải thiện kỹ năng còn thiếu")


class RecommendJDsRequest(BaseModel):
    """Yêu cầu gợi ý Top-N JD phù hợp từ CV."""

    cv_version_id: str | None = Field(default=None, description="Mã phiên bản CV của sinh viên")
    cv_text: str | None = Field(default=None, description="Hoặc văn bản CV trực tiếp")
    top_n: int = Field(default=3, ge=1, le=10, description="Số lượng JD tối đa cần gợi ý (1–10)")
    generate_advice: bool = Field(default=True, description="Có gọi LLM sinh lời khuyên nghề nghiệp hay không")


class RecommendJDsResponse(BaseModel):
    """Phản hồi danh sách các JD được gợi ý phù hợp nhất."""

    cv_version_id: str | None = None
    recommendations: list[JDRecommendationItem]
    advice: CareerAdvice | None = Field(default=None, description="Lời khuyên tư vấn nghề nghiệp được sinh bởi LLM")


class JDComparisonItem(BaseModel):
    """Kết quả đối sánh của 1 JD trong bảng so sánh đa JD sau khi phân tích qua LLM."""

    rank: int = Field(..., description="Thứ hạng phù hợp (1 là cao nhất)")
    jd_id: str
    title: str
    company: str | None = None
    industry: str | None = None
    level: str | None = None
    match_score: float = Field(..., description="Điểm phù hợp CV–JD theo trọng số PRD 5.2 (0-100)")
    match_label: Literal["low", "medium", "high"] = Field(
        ..., description="Thấp (< 50) / Trung bình (50–74) / Cao (≥ 75)"
    )
    matched_skills: list[str] = Field(default_factory=list, description="Kỹ năng sinh viên đã đáp ứng có bằng chứng")
    partial_skills: list[str] = Field(default_factory=list, description="Kỹ năng chỉ được liệt kê trong CV")
    missing_skills: list[str] = Field(default_factory=list, description="Kỹ năng còn thiếu theo yêu cầu JD")
    breakdown: list[dict[str, Any]] = Field(
        default_factory=list, description="Phân rã điểm theo Required/Preferred/Additional"
    )
    llm_summary: str | None = Field(default=None, description="Nhận xét tổng quan của LLM cho vị trí này")
    llm_used: bool = Field(default=False, description="Xác nhận đối soát kỹ năng đã gọi qua LLM")
    requirement_count: int = Field(default=0, description="Số yêu cầu kỹ năng trích được từ JD")
    requirements_source: Literal["given", "llm", "dictionary"] = Field(
        default="given",
        description="given: có sẵn; llm: vừa trích bằng AI; dictionary: AI lỗi, chỉ có kỹ năng theo từ điển",
    )


class CompareJDsRequest(BaseModel):
    """Yêu cầu so sánh CV với 2-3 JD do sinh viên chủ động chọn."""

    cv_version_id: str | None = Field(default=None, description="Mã phiên bản CV của sinh viên")
    cv_text: str | None = Field(default=None, description="Hoặc văn bản CV trực tiếp")
    jd_ids: list[str] = Field(..., min_length=2, max_length=5, description="Danh sách 2 đến 5 JD ID cần so sánh")


class CompareJDsResponse(BaseModel):
    """Kết quả bảng so sánh các JD sau khi phân tích qua LLM, sắp xếp theo điểm match giảm dần."""

    id: str | None = Field(default=None, description="Mã bản ghi lịch sử so sánh")
    cv_version_id: str | None = None
    cv_label: str | None = None
    cv_name: str | None = None
    total_compared: int = Field(default=0, description="Số lượng JD đã so sánh")
    comparisons: list[JDComparisonItem] = Field(
        ..., description="Danh sách kết quả đối soát các JD, sắp xếp giảm dần theo match_score"
    )
    common_missing_skills: list[str] = Field(
        default_factory=list, description="Các kỹ năng còn thiếu chung ở tất cả các JD được chọn"
    )
    common_missing_roadmaps: dict[str, str] = Field(
        default_factory=dict, description="Kỹ năng thiếu chung → link roadmap.sh (chỉ kỹ năng có lộ trình riêng)"
    )
    created_at: UtcDatetime | None = Field(default=None, description="Thời gian thực hiện so sánh")


class CreateGapAnalysisRequest(BaseModel):
    """Tạo lượt phân tích: chọn một phiên bản CV và một JD (từ thư viện hoặc dán nội dung)."""

    cv_version_id: str = Field(..., description="Phiên bản CV trong 'CV của tôi'")
    jd_id: str | None = Field(default=None, description="JD trong thư viện")
    jd_text: str | None = Field(default=None, description="Nội dung JD tự dán (tối thiểu 50 từ)")
    jd_title: str | None = Field(default=None, description="Tiêu đề vị trí (bắt buộc khi dán JD)")
    jd_company: str | None = Field(default=None, description="Tên công ty (tuỳ chọn)")


class AnalysisJd(BaseModel):
    id: str
    title: str
    company: str | None = None
    industry: str | None = None
    level: Literal["intern", "fresher", "junior"] | None = None
    source: Literal["library", "pasted"]


class Evidence(BaseModel):
    """Câu trích nguyên văn từ CV làm bằng chứng."""

    line_no: int = Field(..., description="Số dòng trong CV (đếm các dòng không rỗng)")
    text: str = Field(..., description="Nguyên văn dòng CV")
    section: str | None = Field(default=None, description="Mã mục: experience, projects, skills...")
    section_label: str = Field(..., description="Tên mục hiển thị, ví dụ 'Kinh nghiệm'")


class RequirementAssessment(BaseModel):
    """Một dòng bảng Evidence: yêu cầu JD, mức độ, Match và bằng chứng trong CV."""

    id: str
    skill: str
    importance: Importance
    weight: int = Field(..., description="Trọng số 3 / 2 / 1")
    match: float = Field(..., description="0 (thiếu), 0.5 (chỉ liệt kê), 1 (có bằng chứng cụ thể)")
    status: Literal["matched", "partial", "missing"]
    evidence: Evidence | None = Field(default=None, description="None khi không tìm thấy trong CV — không tự điền")
    note: str | None = Field(default=None, description="Ghi chú, ví dụ 'FastAPI → tính là Python (taxonomy)'")
    roadmap_url: str | None = Field(
        default=None,
        description="Đường dẫn lộ trình học kỹ năng trên roadmap.sh",
    )
    is_it_supported: bool = Field(
        default=True,
        description="Đánh dấu kỹ năng có thuộc lĩnh vực IT được roadmap.sh hỗ trợ hay không",
    )
    roadmap_message: str | None = Field(
        default=None,
        description="Thông báo cho người dùng nếu kỹ năng không thuộc IT hoặc chưa có roadmap",
    )


class SkillRoadmapResponse(BaseModel):
    """Thông tin đường dẫn lộ trình học tập roadmap.sh cho một kỹ năng."""

    skill: str
    roadmap_url: str
    is_matched: bool
    is_it_supported: bool = Field(
        default=True,
        description="Chỉ hỗ trợ các lĩnh vực liên quan đến Công nghệ thông tin (IT)",
    )
    message: str | None = Field(
        default=None,
        description="Thông báo cho người dùng nếu kỹ năng không thuộc IT hoặc chưa có roadmap",
    )


class ScoreBreakdown(BaseModel):
    """Phân rã điểm theo mức độ yêu cầu (hiển thị khi SV bấm 'Xem thêm')."""

    importance: Importance
    label: str
    weight: int
    total: int
    matched: int
    partial: int
    missing: int
    earned: float = Field(..., description="Σ(w × Match) của nhóm")
    possible: float = Field(..., description="Σw của nhóm")


class AnalysisSuggestion(BaseModel):
    """Gợi ý diễn đạt lại một dòng CV, đã qua kiểm tra grounding."""

    id: str = Field(..., description="Dùng làm response_id cho like/dislike")
    skill: str
    line_no: int | None = Field(default=None, description="Dòng CV được thay (None với lượt phân tích cũ)")
    section_label: str | None = None
    original_text: str = Field(..., description="Nguyên văn dòng CV")
    suggested_text: str = Field(..., description="Đề xuất diễn đạt lại (không thêm thông tin mới)")
    reason: str = ""


class MatchCounts(BaseModel):
    matched: int = 0
    partial: int = 0
    missing: int = 0


class GapAnalysisResponse(BaseModel):
    """Kết quả (hoặc tiến độ) một lượt phân tích. Frontend hỏi lại endpoint này cho tới khi status khác 'processing'."""

    id: str
    response_id: str = Field(..., description="Dùng cho khảo sát CSAT")
    status: Literal["processing", "completed", "failed"]
    current_step: Literal["parse", "retrieve", "compare", "generate", "verify_grounding"] | None = None
    error_message: str | None = None
    cv_version_id: str
    cv_file_name: str
    cv_label: str
    jd: AnalysisJd
    created_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    match_score: float | None = Field(default=None, description="CV–JD Matching Score 0–100")
    match_label: Literal["low", "medium", "high"] | None = Field(
        default=None, description="Thấp (< 50) / Trung bình (50–74) / Cao (≥ 75)"
    )
    counts: MatchCounts = Field(default_factory=MatchCounts)
    breakdown: list[ScoreBreakdown] = Field(default_factory=list)
    requirements: list[RequirementAssessment] = Field(default_factory=list)
    suggestions: list[AnalysisSuggestion] = Field(default_factory=list)
    pending_review_count: int = Field(default=0, description="Số gợi ý không qua guardrail, chờ cố vấn xem lại")
    summary: str | None = None
    interview_focus: str | None = Field(
        default=None, description="Một kỹ năng của JD có trong CV mà nhà tuyển dụng nhiều khả năng hỏi sâu"
    )
    llm_used: bool = Field(default=False, description="False khi chấm bằng quy tắc dự phòng (không có LLM)")


# ============================================================================
# 5. Trình tối ưu CV & Xuất CV (US-SV-03, US-SV-05, PRD mục 6)
# ============================================================================


class DevelopingSkill(BaseModel):
    """Kỹ năng SV tự ghi là đang học; không bao giờ ghi là thành thạo."""

    name: str
    note: str


class CvDocLine(BaseModel):
    id: str = Field(..., description="Mã dòng, dạng 'l{line_no}'")
    line_no: int = Field(..., description="Số dòng trong CV (đếm các dòng không rỗng), khớp Evidence.line_no")
    text: str
    kind: Literal["name", "contact", "text", "entry", "role", "tech", "label", "bullet"] = Field(
        default="bullet", description="Cách trình bày dòng trong mẫu CV (src/services/cv_layout.py)"
    )
    date: str | None = Field(default=None, description="Thời gian của dòng entry, căn phải; tên là phần còn lại")
    cont: bool = Field(
        default=False, description="Nửa sau của câu bị xuống dòng khi trích PDF/OCR, ghép vào dòng trước"
    )


class CvDocSection(BaseModel):
    id: str
    title: str = Field(..., description="Tiêu đề mục như trong CV, ví dụ 'KINH NGHIỆM LÀM VIỆC'")
    lines: list[CvDocLine]


class CvDocument(BaseModel):
    """Nội dung CV tách theo mục từ văn bản đã trích, dùng để hiển thị ở Trình tối ưu và Xuất CV."""

    header: list[CvDocLine] = Field(default_factory=list, description="Các dòng trước mục đầu tiên (họ tên, liên hệ)")
    sections: list[CvDocSection] = Field(default_factory=list)
    developing_skills: list[DevelopingSkill] = Field(default_factory=list)
    lang: Literal["vi", "en"] = Field(default="vi", description="Ngôn ngữ CV, đặt tiêu đề mục do hệ thống thêm")


class CvPreviewResponse(BaseModel):
    """
    Cách xem một phiên bản CV: "pages" = PDF gốc, tải từng trang dạng ảnh (GET .../pages/{n});
    "document" = DOCX / bản đã tối ưu, trình bày theo mẫu CV (giống trang Xuất CV và file DOCX).
    """

    kind: Literal["pages", "document"]
    page_count: int | None = Field(default=None, description="Số trang hiển thị (kind = pages)")
    document: CvDocument | None = None


class EvidenceSpan(BaseModel):
    """Vị trí trong CV gốc làm căn cứ cho gợi ý."""

    text: str
    line_start: int
    line_end: int


class OptimizerSuggestion(BaseModel):
    """Một gợi ý diễn đạt lại trong Trình tối ưu kèm quyết định hiện tại của SV."""

    id: str
    kind: Literal["rephrase", "ats_keyword", "star_quantify"] = Field(
        ..., description="ats_keyword: câu mới dùng đúng tên kỹ năng trong JD mà câu gốc chưa có"
    )
    skill: str
    line_id: str = Field(..., description="Dòng trong CvDocument mà gợi ý thay thế")
    extra_line_ids: list[str] = Field(
        default_factory=list, description="Dòng nối của gạch ý bị ngắt dòng; câu thay thế gộp luôn các dòng này"
    )
    original_text: str
    proposed_text: str = Field(..., description="Nội dung AI đề xuất")
    final_text: str | None = Field(
        default=None, description="Nội dung sẽ vào CV sau quyết định; None khi chưa quyết định hoặc đã bỏ qua"
    )
    rationale: str = ""
    evidence_span: EvidenceSpan
    status: Literal["pending", "accepted", "edited", "rejected"]
    needs_context: bool = Field(
        default=False, description="US-SV-03 AC2: câu đề xuất còn chỗ trống [ ] cần SV bổ sung số liệu thật"
    )
    context_question: str | None = None


class CapabilityCheck(BaseModel):
    """Kỹ năng JD yêu cầu mà CV chưa có (US-SV-05): SV tự xác nhận, AI không tự thêm vào CV."""

    id: str = Field(..., description="Mã yêu cầu JD trong lượt phân tích")
    skill: str
    importance: Importance
    jd_requirement: str
    status: Literal["pending", "has_experience", "no_experience"]
    context: str | None = Field(default=None, description="Mô tả kinh nghiệm SV cung cấp khi chọn 'đã có'")
    learning_note: str | None = Field(default=None, description="Ghi chú đang học khi chọn 'chưa có'")
    entry_id: str | None = Field(default=None, description="Phần CV sẽ thêm câu kinh nghiệm (một mục trong entries)")
    draft_text: str | None = Field(default=None, description="Câu cho CV viết từ lời kể của SV, chờ SV duyệt")
    final_text: str | None = Field(default=None, description="Câu sẽ thêm vào CV khi Hoàn tất (đã áp dụng / sửa)")
    line_status: Literal["pending", "accepted", "edited", "rejected"] = "pending"
    roadmap_url: str | None = Field(default=None, description="Lộ trình học trên roadmap.sh (kỹ năng CNTT)")


class CvEntry(BaseModel):
    """Một chỗ có thể thêm câu kinh nghiệm mới: dự án / công việc trong CV, hoặc cuối một mục."""

    id: str
    label: str
    after_line_id: str = Field(..., description="Câu mới chèn ngay sau dòng này (id dòng trong document)")


class OptimizerSessionResponse(BaseModel):
    """Trạng thái Trình tối ưu của một lượt phân tích."""

    analysis_id: str
    status: Literal["draft", "finalized"] = Field(
        ..., description="finalized: đã tạo phiên bản mới, không sửa được nữa"
    )
    jd: AnalysisJd
    match_score: float | None = Field(default=None, description="CV–JD Matching Score của lượt phân tích")
    match_label: Literal["low", "medium", "high"] | None = None
    llm_used: bool = Field(..., description="False: lượt phân tích chấm bằng quy tắc dự phòng nên không có gợi ý")
    pending_review_count: int = Field(default=0, description="Gợi ý không qua guardrail, chờ cố vấn xem lại")
    cv: CvVersionResponse = Field(..., description="Phiên bản CV được tối ưu")
    result_cv: CvVersionResponse | None = Field(default=None, description="Phiên bản tạo ra khi 'Hoàn tất'")
    document: CvDocument = Field(..., description="Nội dung phiên bản được tối ưu (chưa áp gợi ý)")
    result_document: CvDocument | None = Field(
        default=None, description="Nội dung phiên bản tạo ra khi 'Hoàn tất' (đúng như file DOCX)"
    )
    suggestions: list[OptimizerSuggestion]
    suggestions_state: Literal["pending", "ready", "failed"] = Field(
        default="ready",
        description="pending: chưa soạn gợi ý riêng (gọi POST .../prepare); failed: soạn lỗi, SV bấm Thử lại",
    )
    kept_count: int = Field(default=0, description="Số câu AI xem xét và cho là đã rõ, không cần sửa")
    suggestions_attempted_at: UtcDatetime | None = Field(default=None, description="Lần soạn gợi ý gần nhất")
    capability_checks: list[CapabilityCheck]
    entries: list[CvEntry] = Field(default_factory=list, description="Chỗ có thể thêm câu kinh nghiệm mới")
    finalized_at: UtcDatetime | None = None


class SuggestionDecisionRequest(BaseModel):
    """accept / edit (kèm edited_text) / reject; undo đưa gợi ý về chờ duyệt (chỉ khi chưa 'Hoàn tất')."""

    decision: Literal["accept", "edit", "reject", "undo"]
    edited_text: str | None = None


class CapabilityDraftRequest(BaseModel):
    context: str = Field(..., description="SV kể đã dùng kỹ năng ở đâu, làm những gì")
    entry_id: str = Field(..., description="Phần CV sẽ thêm câu (id trong entries)")


class CapabilityLineDecisionRequest(BaseModel):
    decision: Literal["accept", "edit", "reject", "undo"]
    edited_text: str | None = Field(default=None, description="Bắt buộc khi decision = edit")


class CapabilityAnswerRequest(BaseModel):
    has_experience: bool
    context: str | None = Field(default=None, description="Bắt buộc khi has_experience = true")
    learning_note: str | None = Field(default=None, description="Tuỳ chọn khi has_experience = false")


class ExportCvRequest(BaseModel):
    format: Literal["docx", "print", "text"] = Field(
        ..., description="docx: tải file; print: in / lưu PDF từ trình duyệt; text: sao chép các câu đã sửa"
    )
    integrity_confirmed: bool = Field(..., description="SV đã tick cam kết liêm chính")


class ExportCvResponse(BaseModel):
    id: str
    format: Literal["docx", "print", "text"]
    confirmed_at: UtcDatetime


# ============================================================================
# 6. Mock Interview Schemas (STAR Rubric 0–5, PRD mục 5.1) (US-SV-04)
# ============================================================================


StarCriterion = Literal["situation", "task", "action", "result"]


class StarScores(BaseModel):
    """Điểm 4 tiêu chí STAR, thang 0–5 (PRD mục 5.1)."""

    situation: float = Field(..., ge=0.0, le=5.0)
    task: float = Field(..., ge=0.0, le=5.0)
    action: float = Field(..., ge=0.0, le=5.0)
    result: float = Field(..., ge=0.0, le=5.0)


class InterviewJd(BaseModel):
    id: str
    title: str
    company: str | None = None
    source: Literal["library", "pasted"]


class InterviewQuestion(BaseModel):
    """Câu hỏi đang chờ trả lời."""

    index: int = Field(..., description="Số thứ tự câu, bắt đầu từ 1")
    theme: str = Field(..., description="Chủ đề câu hỏi, ví dụ 'Làm việc nhóm'")
    text: str


class InterviewTurnOut(BaseModel):
    """Một câu đã trả lời (hoặc hết giờ) kèm điểm S/T/A/R và nhận xét ngắn."""

    id: str = Field(..., description="Dùng làm response_id cho like/dislike nhận xét")
    index: int
    theme: str
    question: str
    answer: str | None = Field(default=None, description="None khi hết giờ mà chưa có câu trả lời")
    timed_out: bool = False
    star: StarScores | None = None
    score: float | None = Field(default=None, description="Trung bình 4 tiêu chí (0–5)")
    feedback: str | None = None


class InterviewSessionResponse(BaseModel):
    """Trạng thái buổi phỏng vấn: các câu đã trả lời, câu hiện tại và thời gian còn lại."""

    id: str
    status: Literal["in_progress", "completed"]
    jd: InterviewJd
    cv_version_id: str | None = None
    cv_file_name: str | None = None
    interview_mode: Literal["jd_only", "with_cv"] = "with_cv"
    question_count: int
    seconds_per_question: int
    current_question: InterviewQuestion | None = Field(default=None, description="None khi đã hoàn thành")
    seconds_left: int | None = Field(default=None, description="Thời gian còn lại của câu hiện tại (giây)")
    paused: bool = False
    pause_used: bool = False
    pause_seconds_left: int | None = Field(default=None, description="Thời gian tạm dừng còn lại (giây)")
    turns: list[InterviewTurnOut] = Field(default_factory=list, description="Các câu đã trả lời, theo thứ tự")
    created_at: UtcDatetime
    voice_input: bool = Field(default=True, description="PhoWhisper trên thiết bị; trình duyệt kiểm tra khả năng hỗ trợ")


class CreateInterviewRequest(BaseModel):
    """Bắt đầu buổi phỏng vấn mới cho một vị trí (JD) và tùy chọn phiên bản CV."""

    jd_id: str
    cv_version_id: str | None = None
    interview_mode: Literal["jd_only", "with_cv"] | None = None


class SubmitAnswerRequest(BaseModel):
    """Nộp câu trả lời cho câu hiện tại. timed_out = True khi frontend tự nộp lúc hết giờ."""

    question_index: int = Field(..., ge=1)
    text: str = Field(default="", max_length=5000)
    timed_out: bool = False


class SubmitAnswerResponse(BaseModel):
    """
    allowed = False: câu trả lời bị guardrail chặn (lạc đề, quá ngắn...), không tính câu, đồng hồ vẫn chạy.
    allowed = True: câu đã được chấm; next_question là câu tiếp theo hoặc None khi buổi đã xong (finished).
    """

    allowed: bool
    reason: str | None = None
    turn: InterviewTurnOut | None = None
    next_question: InterviewQuestion | None = None
    seconds_left: int | None = None
    finished: bool = False


class InterviewComparison(BaseModel):
    """So sánh với buổi đầu tiên của cùng vị trí (từ buổi thứ 2 trở đi)."""

    first_session_id: str
    first_score: float
    first_completed_at: UtcDatetime
    delta: float


class InterviewReportResponse(BaseModel):
    """Kết quả buổi phỏng vấn (S7): điểm STAR 0–5, chi tiết từng câu và hướng dẫn cải thiện."""

    id: str
    response_id: str = Field(..., description="Dùng cho khảo sát CSAT")
    jd: InterviewJd
    cv_file_name: str | None = None
    interview_mode: Literal["jd_only", "with_cv"] = "with_cv"
    created_at: UtcDatetime
    completed_at: UtcDatetime
    duration_seconds: int
    overall_score: float = Field(..., ge=0.0, le=5.0)
    label: Literal["weak", "basic", "fair", "good"] = Field(
        ..., description="Cần luyện thêm (< 2) / Đạt cơ bản (< 3) / Khá (< 4) / Tốt (≥ 4)"
    )
    star: StarScores
    weakest: StarCriterion
    turns: list[InterviewTurnOut]
    timed_out_count: int
    # Chỉ gợi ý khung trả lời, không viết sẵn câu trả lời chứa thành tích SV chưa nêu
    guidance: list[str]
    comparison: InterviewComparison | None = None


class InterviewSummary(BaseModel):
    """Một buổi đã hoàn thành trong danh sách gần đây."""

    id: str
    jd: InterviewJd
    completed_at: UtcDatetime
    overall_score: float
    star: StarScores


class InterviewQuota(BaseModel):
    """Hạn mức buổi phỏng vấn có chấm điểm theo vị trí trong tuần (PRD: 3 buổi / vị trí / tuần)."""

    jd_id: str
    used: int
    limit: int
    remaining: int
    resets_at: UtcDatetime


# ============================================================================
# 7. Feedback Schemas: like/dislike & CSAT (US-SV-06)
# ============================================================================


class FeedbackRequest(BaseModel):
    """Phản hồi cho một phản hồi AI: like/dislike (thumb: 1 / -1) hoặc CSAT (csat: 1–5 sao)."""

    response_id: str = Field(..., description="Id gợi ý (thumb) hoặc id lượt phân tích / phỏng vấn (csat)")
    kind: Literal["thumb", "csat"]
    value: int
    activity: (
        Literal[
            "gap_analysis",
            "optimizer",
            "interview",
            "gap_suggestion",
            "interview_turn",
            "job_recommendation",
            "jd_compare",
        ]
        | None
    ) = Field(default=None, description="Bắt buộc với csat (gap_analysis / optimizer / interview)")
    comment: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=5, description="Chỉ với csat 1–3 sao: mã lý do")
    would_reuse: bool | None = Field(default=None, description="Chỉ với csat: 'Bạn có dùng lại không?'")


class FeedbackResponse(BaseModel):
    id: str
    already_submitted: bool = Field(..., description="Đã có phản hồi trước đó cho cùng response_id (US-SV-06 AC3)")
    value: int = Field(..., description="Giá trị đang lưu (giá trị cũ nếu already_submitted)")


class FeedbackStatus(BaseModel):
    kind: Literal["thumb", "csat"]
    value: int | None = Field(default=None, description="None nếu chưa gửi")


# ============================================================================
# 8. Tổng quan (S1) & Lịch sử – Tiến bộ (S8) của sinh viên
# ============================================================================

InterviewLabel = Literal["weak", "basic", "fair", "good"]
MatchLabel = Literal["low", "medium", "high"]


class AnalysisRow(BaseModel):
    """Một lượt phân tích trong danh sách (mọi trạng thái)."""

    id: str
    jd: InterviewJd
    cv_version_id: str
    cv_label: str
    cv_file_name: str
    status: Literal["processing", "completed", "failed"]
    current_step: Literal["parse", "retrieve", "compare", "generate", "verify_grounding"] | None = None
    match_score: float | None = Field(default=None, description="CV–JD Matching Score 0–100")
    match_label: MatchLabel | None = None
    created_at: UtcDatetime
    completed_at: UtcDatetime | None = None


class InterviewRow(BaseModel):
    """Một buổi phỏng vấn đã hoàn thành trong danh sách."""

    id: str
    jd: InterviewJd
    completed_at: UtcDatetime
    duration_seconds: int
    overall_score: float = Field(..., ge=0.0, le=5.0)
    label: InterviewLabel
    star: StarScores
    timed_out_count: int
    interview_mode: Literal["jd_only", "with_cv"] = Field(default="with_cv", description="Có dùng CV khi hỏi không")
    cv_file_name: str | None = Field(default=None, description="Tên file CV đã dùng (with_cv)")
    cv_label: str | None = Field(
        default=None, description="Phiên bản CV đã dùng, ví dụ 'v1.0'; null nếu bản đó đã bị xoá"
    )


class ScorePoint(BaseModel):
    """Điểm một buổi phỏng vấn (0–5) để vẽ biểu đồ."""

    id: str = Field(..., description="Mã buổi phỏng vấn")
    completed_at: UtcDatetime
    score: float


class LatestMatch(BaseModel):
    """Độ khớp CV–JD của lượt phân tích hoàn thành gần nhất."""

    analysis_id: str
    jd: InterviewJd
    cv_label: str
    score: float | None
    label: MatchLabel | None
    completed_at: UtcDatetime


class LatestInterview(BaseModel):
    """Buổi phỏng vấn gần nhất, so với buổi đầu tiên của cùng vị trí."""

    id: str
    jd: InterviewJd
    completed_at: UtcDatetime
    score: float
    label: InterviewLabel
    first_score: float | None = Field(default=None, description="None khi đây là buổi đầu tiên của vị trí")
    delta: float | None = Field(default=None, description="score − first_score")
    session_count: int = Field(..., description="Số buổi đã hoàn thành của vị trí này")
    trend: list[ScorePoint] = Field(default_factory=list, description="Tối đa 5 buổi gần nhất của vị trí, cũ → mới")


class StarSummary(BaseModel):
    """Điểm trung bình từng tiêu chí của các buổi gần nhất (tối đa 5 buổi)."""

    average: StarScores
    weakest: StarCriterion
    session_count: int


class InProgressInterview(BaseModel):
    """Buổi phỏng vấn đang dở, còn quay lại phòng được."""

    id: str
    jd: InterviewJd
    current_index: int
    question_count: int
    seconds_left: int | None = None
    paused: bool = False


class OverviewInProgress(BaseModel):
    analyses: list[AnalysisRow] = Field(default_factory=list, description="Lượt phân tích đang chạy")
    interview: InProgressInterview | None = None


class NextStep(BaseModel):
    """
    Việc nên làm tiếp theo: upload_cv (chưa có CV) → analyze (chưa phân tích) → interview (chưa luyện vị trí
    vừa phân tích) → improve (luyện tiếp để cải thiện tiêu chí yếu nhất của buổi gần nhất).
    """

    kind: Literal["upload_cv", "analyze", "interview", "improve"]
    cv_version_id: str | None = None
    cv_label: str | None = None
    jd: InterviewJd | None = None
    analysis_id: str | None = None
    match_score: float | None = None
    session_id: str | None = None
    criterion: StarCriterion | None = None
    criterion_score: float | None = None
    guidance: str | None = None
    quota_remaining: int | None = Field(default=None, description="Số buổi còn lại của vị trí trong tuần")
    quota_resets_at: UtcDatetime | None = None


class SkillToLearn(BaseModel):
    name: str
    importance: Importance
    roadmap_url: str | None = Field(default=None, description="Lộ trình học trên roadmap.sh (chỉ kỹ năng CNTT)")


class SkillsToLearn(BaseModel):
    """Kỹ năng "Thiếu" trong lần phân tích gần nhất, nhóm Bắt buộc trước (tối đa 6)."""

    analysis_id: str
    jd: InterviewJd
    skills: list[SkillToLearn]
    total_missing: int


class StudentOverviewResponse(BaseModel):
    """Trang Tổng quan (S1)."""

    cv_count: int
    cv_latest_at: UtcDatetime | None = None
    interview_count: int = Field(..., description="Số buổi đã hoàn thành")
    interview_week_count: int = Field(..., description="Số buổi hoàn thành trong tuần này (mọi vị trí)")
    latest_match: LatestMatch | None = None
    latest_interview: LatestInterview | None = None
    star: StarSummary | None = None
    in_progress: OverviewInProgress
    next_step: NextStep
    skills_to_learn: SkillsToLearn | None = None
    recent_analyses: list[AnalysisRow] = Field(default_factory=list, description="Tối đa 5, mới nhất trước")
    recent_interviews: list[InterviewRow] = Field(default_factory=list, description="Tối đa 5, mới nhất trước")


ProgressRange = Literal["30d", "90d", "all"]


class PositionOption(BaseModel):
    """Một vị trí SV đã luyện phỏng vấn hoặc phân tích (dùng cho bộ lọc)."""

    jd: InterviewJd
    interview_count: int
    analysis_count: int
    last_activity_at: UtcDatetime


class InterviewProgress(BaseModel):
    """
    Tiến bộ phỏng vấn của một vị trí (PRD mục 5.1): lớp 1 là điểm tổng qua các buổi,
    lớp 2 là S/T/A/R của buổi trước so với buổi gần nhất.
    """

    jd: InterviewJd
    session_count: int
    points: list[ScorePoint] = Field(..., description="Các buổi trong khoảng thời gian, cũ → mới")
    first_score: float
    latest_score: float
    delta_from_first: float | None = Field(default=None, description="None khi mới có 1 buổi")
    delta_from_previous: float | None = Field(default=None, description="None khi mới có 1 buổi")
    latest_session_id: str
    previous_session_id: str | None = None
    star_latest: StarScores
    star_previous: StarScores | None = None


class CvPoint(BaseModel):
    analysis_id: str
    cv_version_id: str
    cv_label: str
    match_score: float
    completed_at: UtcDatetime


class CvProgress(BaseModel):
    """Độ khớp với một JD qua các phiên bản CV (mỗi phiên bản lấy lần phân tích gần nhất), theo số phiên bản."""

    jd: InterviewJd
    points: list[CvPoint]
    delta: float | None = Field(default=None, description="Điểm phiên bản mới nhất − phiên bản đầu; None nếu 1 bản")


class StudentProgressResponse(BaseModel):
    """Trang Lịch sử & Tiến bộ (S8), lọc theo khoảng thời gian và vị trí."""

    range: ProgressRange
    jd_id: str | None = None
    last_activity_at: UtcDatetime | None = None
    positions: list[PositionOption] = Field(
        default_factory=list, description="Mọi vị trí đã có hoạt động (không phụ thuộc bộ lọc)"
    )
    interview_progress: list[InterviewProgress] = Field(default_factory=list, description="Hoạt động gần nhất trước")
    cv_progress: list[CvProgress] = Field(default_factory=list, description="Hoạt động gần nhất trước")
    interviews: list[InterviewRow] = Field(default_factory=list, description="Mới nhất trước")
    analyses: list[AnalysisRow] = Field(default_factory=list, description="Mới nhất trước")


# ============================================================================
# 9. Chia sẻ với cố vấn (phía SV)
# ============================================================================


class AdvisorContact(BaseModel):
    """Cố vấn phụ trách hiện ở trang Chia sẻ với cố vấn."""

    id: str
    full_name: str
    title: str
    email: str
    office: str | None = None
    office_hours: str | None = None
    avatar_url: str | None = None


class SharedItem(BaseModel):
    """Một tài liệu SV có thể bật / tắt chia sẻ. Mặc định riêng tư."""

    id: str = Field(..., description="Mã phiên bản CV hoặc mã buổi phỏng vấn")
    kind: Literal["cv", "interview_report"]
    title: str
    subtitle: str | None = None
    tag: Literal["primary", "draft"] | None = Field(default=None, description="primary: CV đang dùng")
    created_at: UtcDatetime
    score: float | None = Field(
        default=None, description="CV: độ khớp JD gần nhất (0–100); báo cáo phỏng vấn: điểm STAR (0–5)"
    )
    shared: bool
    advisor_viewed_at: UtcDatetime | None = Field(default=None, description="Lần gần nhất cố vấn mở tài liệu")
    has_advisor_comment: bool = False


class AdvisorFeedbackTarget(BaseModel):
    kind: Literal["interview_report"]
    id: str
    label: str


class AdvisorFeedbackItem(BaseModel):
    """Nhận xét của cố vấn cho một báo cáo của SV."""

    id: str
    advisor_name: str
    comment: str
    created_at: UtcDatetime = Field(..., description="Lần cập nhật gần nhất của nhận xét")
    read: bool
    target: AdvisorFeedbackTarget


class SharingResponse(BaseModel):
    advisor: AdvisorContact | None = Field(default=None, description="None khi SV chưa được phân công cố vấn")
    items: list[SharedItem]
    feedback: list[AdvisorFeedbackItem]


class UpdateSharingRequest(BaseModel):
    item_ids: list[str] = Field(..., min_length=1)
    shared: bool


class ReportAdvisorReview(BaseModel):
    """Nhận xét của cố vấn hiện trên trang báo cáo phỏng vấn của SV."""

    id: str
    advisor_name: str
    comment: str
    updated_at: UtcDatetime
    read: bool


class StudentReportResponse(InterviewReportResponse):
    """Báo cáo phỏng vấn phía SV, kèm nhận xét của cố vấn (nếu có)."""

    advisor_review: ReportAdvisorReview | None = None


# ============================================================================
# 10. Cố vấn (US-ADV-01, US-ADV-02, US-ADV-03)
# ============================================================================


class StudentFlag(BaseModel):
    """Cờ "Cần chú ý": 2 vòng liên tiếp không tăng điểm ở vị trí đang luyện (US-ADV-02 AC1)."""

    jd: InterviewJd
    rounds: list[int] = Field(..., description="Số thứ tự các buổi liên quan trong vị trí, ví dụ [2, 3, 4]")
    scores: list[float]
    flagged_at: UtcDatetime


class AssignedStudentResponse(BaseModel):
    """Một SV trong danh sách phụ trách. Số liệu luôn xem được; chi tiết kỹ năng cần SV chia sẻ CV."""

    id: str
    full_name: str
    subtitle: str
    email: str
    phone: str | None = None
    avatar_url: str | None = None
    target: InterviewJd | None = Field(default=None, description="Vị trí của buổi gần nhất (hoặc lần phân tích)")
    interview_count: int
    focus_session_count: int = Field(..., description="Số buổi của vị trí đang luyện")
    first_score: float | None = None
    latest_score: float | None = None
    score_delta: float | None = Field(default=None, description="None khi vị trí đang luyện mới có < 2 buổi (AC2)")
    trend: Literal["improving", "stable", "declining", "insufficient"]
    flag: StudentFlag | None = None
    latest_match: float | None = Field(default=None, description="Độ khớp CV–JD của lần phân tích gần nhất")
    missing_required: list[str] = Field(default_factory=list, description="Rỗng khi SV chưa chia sẻ CV của lần đó")
    last_active_at: UtcDatetime | None = None
    shared_items: int
    total_items: int
    pending_reviews: int = Field(..., description="Báo cáo đã chia sẻ, chưa có nhận xét của bạn")


class AdvisorStudentProgress(BaseModel):
    """Dòng mở rộng ở danh sách SV phụ trách."""

    interview_progress: list[InterviewProgress]
    cv_progress: list[CvProgress]
    star: StarSummary | None = None
    insight: str | None = Field(default=None, description="Câu nhận xét ghép theo quy tắc từ tiêu chí yếu nhất")
    suggestions: list[str] = Field(default_factory=list, description="Gợi ý cho buổi tư vấn tới (theo quy tắc)")


class AdvisorCv(CvVersionResponse):
    shared: bool


class AdvisorGap(BaseModel):
    """Kết quả phân tích gần nhất (US-ADV-03 AC1); danh sách kỹ năng rỗng khi SV chưa chia sẻ CV của lần đó."""

    analysis_id: str
    created_at: UtcDatetime
    cv_version_id: str
    cv_label: str
    jd: InterviewJd
    match_score: float | None = None
    match_label: MatchLabel | None = None
    shared: bool
    matched: list[str] = Field(default_factory=list)
    partial: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class AdvisorReviewResponse(BaseModel):
    id: str
    comment: str
    created_at: UtcDatetime
    updated_at: UtcDatetime
    seen_at: UtcDatetime | None = Field(default=None, description="Lúc SV xem bản nhận xét hiện tại")


class AdvisorInterviewRow(InterviewRow):
    shared: bool
    summary: str = Field(..., description="Tóm tắt ghép từ điểm số")
    review: AdvisorReviewResponse | None = None


NoteTag = Literal["behavior", "soft_skill", "technical", "watch"]


class AdvisorNoteResponse(BaseModel):
    id: str
    body: str
    tags: list[NoteTag]
    pinned: bool
    created_at: UtcDatetime
    updated_at: UtcDatetime


class AdvisorStudentDetail(AdvisorStudentProgress):
    """Hồ sơ SV (US-ADV-03)."""

    student: AssignedStudentResponse
    cvs: list[AdvisorCv] = Field(..., description="Mọi phiên bản CV, mới nhất trước (AC2); mở được khi đã chia sẻ")
    target_jd: JobDescriptionResponse | None = Field(
        default=None, description="None → 'SV chưa chọn vị trí ứng tuyển' (AC3)"
    )
    latest_gap: AdvisorGap | None = None
    interviews: list[AdvisorInterviewRow]
    notes: list[AdvisorNoteResponse]


class AdvisorReportResponse(InterviewReportResponse):
    """Báo cáo phỏng vấn SV đã chia sẻ, kèm nhận xét của bạn."""

    review: AdvisorReviewResponse | None = None


class WeeklyScore(BaseModel):
    week_start: UtcDatetime = Field(..., description="Thứ Hai 00:00 giờ Việt Nam")
    average: float = Field(..., description="TB điểm buổi gần nhất của mỗi SV tính đến cuối tuần, thang 0–5")
    student_count: int


class StatusCounts(BaseModel):
    """Số SV theo trạng thái như nhãn ở danh sách: cờ "Cần chú ý" trước, sau đó là xu hướng điểm."""

    flagged: int
    declining: int
    insufficient: int
    stable: int
    improving: int


class CohortStar(BaseModel):
    """S/T/A/R trung bình của nhóm (mỗi SV lấy TB tối đa 5 buổi gần nhất)."""

    average: StarScores
    weakest: StarCriterion
    weakest_count: int = Field(..., description="Số SV có tiêu chí yếu nhất trùng với tiêu chí yếu nhất của nhóm")
    student_count: int


class RecentReview(AdvisorReviewResponse):
    student_id: str
    student_name: str
    avatar_url: str | None = None
    session_id: str
    jd: InterviewJd


class AdvisorOverviewResponse(BaseModel):
    """Tổng quan cả nhóm SV phụ trách (chỉ số liệu tổng hợp). Mục tiêu theo PRD mục 9."""

    advisor_name: str
    student_count: int
    sharing_count: int = Field(..., description="Số SV đang chia sẻ ít nhất một tài liệu")
    pending_reviews: int
    active_count: int = Field(..., description="Số SV có lượt phân tích / buổi phỏng vấn hoàn thành trong active_days")
    active_days: int
    active_target: int = Field(..., description="Mục tiêu tỷ lệ SV hoạt động (%)")
    average_score: float | None = Field(default=None, description="TB điểm buổi gần nhất của các SV đã phỏng vấn")
    scored_count: int
    average_delta: float | None = Field(default=None, description="TB chênh lệch gần nhất − buổi đầu của từng SV")
    delta_count: int
    weekly_scores: list[WeeklyScore]
    status_counts: StatusCounts
    star: CohortStar | None = None
    insight: str | None = Field(default=None, description="Câu nhận xét ghép theo quy tắc từ tiêu chí yếu nhất")
    flagged_students: list[AssignedStudentResponse]
    top_improvers: list[AssignedStudentResponse]
    recent_reviews: list[RecentReview]
    pending_sessions: list["PendingReviewSession"] = Field(
        default_factory=list, description="Buổi SV đã chia sẻ mà bạn chưa nhận xét, cũ nhất trước (tối đa 10)"
    )


class ReviewRequest(BaseModel):
    comment: str


class NoteRequest(BaseModel):
    body: str
    tags: list[NoteTag] = Field(default_factory=list)


class NoteUpdateRequest(BaseModel):
    body: str | None = None
    tags: list[NoteTag] | None = None
    pinned: bool | None = None


# ============================================================================
# 11. Tin nhắn SV ↔ cố vấn phụ trách
# ============================================================================


class ChatParticipant(BaseModel):
    """Người ở phía bên kia hội thoại."""

    id: str
    full_name: str
    role: Literal["student", "advisor"]
    subtitle: str = Field(..., description="SV: email; cố vấn: chức danh")
    avatar_url: str | None = None
    office_hours: str | None = Field(default=None, description="Giờ tư vấn (chỉ với cố vấn)")


class ChatMessage(BaseModel):
    id: str
    body: str
    created_at: UtcDatetime
    mine: bool = Field(..., description="Tin do người đang xem gửi")
    read_at: UtcDatetime | None = Field(default=None, description="Lúc người nhận đọc")


class ConversationSummary(BaseModel):
    student_id: str = Field(..., description="Mã hội thoại (mã SV)")
    counterpart: ChatParticipant
    last_message: ChatMessage | None = None
    unread_count: int


class ConversationResponse(BaseModel):
    student_id: str
    counterpart: ChatParticipant
    messages: list[ChatMessage] = Field(..., description="Tối đa 200 tin gần nhất, cũ → mới")


class SendMessageRequest(BaseModel):
    body: str


class UnreadCountResponse(BaseModel):
    count: int


# ============================================================================
# Tài khoản: đăng nhập, đăng ký, quên / đổi mật khẩu
# ============================================================================


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    role: Literal["student", "advisor", "admin"]
    profile: UserProfile
    must_change_password: bool = False


class RegisterRequest(BaseModel):
    """Chỉ sinh viên tự đăng ký. Email là email cá nhân."""

    full_name: str
    date_of_birth: date
    phone: str
    email: str
    password: str
    consent: bool = Field(..., description="Đồng ý xử lý CV và câu trả lời phỏng vấn")
    integrity_pledge: bool = Field(..., description="Cam kết chỉ đưa vào CV kinh nghiệm có thật")


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ChangePasswordResponse(BaseModel):
    password_updated_at: UtcDatetime


# ============================================================================
# Cài đặt & hồ sơ sinh viên
# ============================================================================


class StorageInfo(BaseModel):
    used_bytes: int
    limit_bytes: int
    allocated_by: str


class PrivacySettings(BaseModel):
    anonymous_contribution: bool = False


class NotificationSettings(BaseModel):
    advisor_comment: bool = True
    report_ready: bool = True
    weekly_reminder: bool = False
    email: bool = False


class StudentSettingsResponse(BaseModel):
    """Khớp StudentSettings trong frontend/lib/types.ts."""

    full_name: str
    email: str
    phone: str | None = None
    date_of_birth: date | None = None
    password_updated_at: UtcDatetime | None = None
    consent_accepted_at: UtcDatetime | None = None
    storage: StorageInfo
    privacy: PrivacySettings
    notifications: NotificationSettings


class UpdateSettingsRequest(BaseModel):
    privacy: dict[str, bool] | None = None
    notifications: dict[str, bool] | None = None


class UpdateProfileRequest(BaseModel):
    """Sửa hồ sơ cá nhân; trường bỏ trống (None) giữ nguyên."""

    full_name: str | None = None
    phone: str | None = None
    date_of_birth: date | None = None


class DataExportResponse(BaseModel):
    download_url: str | None = Field(default=None, description="Đường dẫn tải file JSON toàn bộ dữ liệu")


# ============================================================================
# Thông báo
# ============================================================================


class NotificationResponse(BaseModel):
    id: str
    kind: Literal[
        "advisor_comment",
        "interview_report",
        "gap_analysis",
        "integrity_alert",
        "student_activity",
        "student_inactive",
        "advisor_assigned",
        "student_registered",
    ]
    title: str
    body: str
    created_at: UtcDatetime
    read: bool
    action_label: str | None = None
    action_href: str | None = None


# ============================================================================
# JD đã lưu, JD tự dán
# ============================================================================


class SavedJdResponse(BaseModel):
    jd_id: str
    saved_at: UtcDatetime


class CreatePastedJdRequest(JdFields):
    text: str = Field(..., max_length=20000, description="Toàn văn JD (tối thiểu 50 từ)")
    skills: list[JdSkillInput] | None = Field(default=None, description="Kỹ năng từ bước tách (POST /jd/parse)")
    skills_source: Literal["dictionary", "sections", "ai"] | None = None
    reviewed: bool = Field(False, description="Sinh viên đã xem lại các trường: bắt buộc đủ trường chính")


class AdminJdRow(BaseModel):
    id: str
    title: str
    company: str | None = None
    industry: str | None = None
    level: JobLevel | None = None
    skills: list[JdSkill]
    status: Literal["published", "hidden"]
    usage_30d: int = Field(..., description="Lượt phân tích CV + buổi phỏng vấn hoàn thành trong 30 ngày")
    updated_at: UtcDatetime


class AdminUploadedJd(BaseModel):
    """JD sinh viên tự dán, gộp theo vị trí – công ty (không kèm tên sinh viên)."""

    sample_jd_id: str
    title: str
    company: str | None = None
    level: JobLevel | None = None
    skills: list[JdSkill]
    student_count: int
    last_added_at: UtcDatetime
    library_jd_id: str | None = Field(default=None, description="JD thư viện tương ứng (nếu đã có)")


class AdminJdDetail(JobDescriptionResponse):
    status: str | None = None
    source_jd_id: str | None = None
    updated_at: UtcDatetime | None = None


class AdminJdUpsert(JdFields):
    skills: list[JdSkillInput] | None = None
    text: str | None = Field(default=None, max_length=20000, description="Toàn văn đã dán (không có thì dựng từ mục)")
    source_jd_id: str | None = Field(default=None, description="JD sinh viên tải lên được đưa vào thư viện")
    status: Literal["published", "hidden"] | None = None


class SuggestionContextRequest(BaseModel):
    answer: str


# ============================================================================
# Cố vấn: buổi chờ nhận xét (Tổng quan)
# ============================================================================


class PendingReviewSession(BaseModel):
    session_id: str
    student_id: str
    student_name: str
    avatar_url: str | None = None
    jd: InterviewJd
    completed_at: UtcDatetime
    overall_score: float | None = None


AdvisorOverviewResponse.model_rebuild()


# ============================================================================
# Quản trị: thống kê toàn hệ thống, tài khoản cố vấn, phân công sinh viên
# ============================================================================


class AdminUserStats(BaseModel):
    student_count: int
    new_students_week: int = Field(..., description="SV tạo tài khoản trong 7 ngày qua")
    student_series: list[int] = Field(..., description="Tổng số SV ở cuối mỗi tuần (cũ → mới), để vẽ đường mảnh")
    active_count: int = Field(..., description="SV có lượt phân tích / buổi phỏng vấn hoàn thành trong kỳ")
    active_series: list[int] = Field(..., description="Số SV hoạt động trong kỳ tính tới cuối mỗi tuần")
    advisor_count: int = Field(..., description="Cố vấn đang hoạt động (không tính tài khoản tạm khoá)")
    assigned_count: int
    unassigned_count: int


class AdminWeeklyUsage(BaseModel):
    week_start: date
    analyses: int
    interviews: int


class AdminUsageStats(BaseModel):
    weekly: list[AdminWeeklyUsage]
    analyses: int
    analyses_change: float | None = Field(default=None, description="% thay đổi so với kỳ trước; None nếu kỳ trước = 0")
    interviews: int
    interviews_change: float | None = None
    optimized_cvs: int = Field(..., description="Phiên bản CV tạo từ Trình tối ưu trong kỳ")


class AdminReasonLabel(BaseModel):
    reason: str
    label: str


class AdminReasonCount(BaseModel):
    reason: str
    label: str
    activities: list[str] = Field(..., description="Các hoạt động có lý do này (gap_analysis / optimizer / interview)")
    count: int


class AdminHelpfulness(BaseModel):
    activity: str = Field(..., description="gap_suggestion / interview_turn / job_recommendation / jd_compare")
    label: str
    likes: int
    total: int


class AdminSatisfaction(BaseModel):
    csat: float | None = None
    count: int
    target: float
    distribution: dict[str, int] = Field(..., description='Số lượt theo số sao: {"1": .., ..., "5": ..}')
    low_count: int = Field(0, description="Số lượt chấm 1–3 sao trong kỳ")
    reasons: list[AdminReasonCount] = Field(default_factory=list, description="Lý do chưa hài lòng, nhiều nhất trước")
    helpful: list[AdminHelpfulness] = Field(default_factory=list, description="Like / dislike theo từng phần")


class AdminComment(BaseModel):
    """Đánh giá CSAT có nhận xét bằng chữ hoặc lý do; không có tên SV."""

    id: str
    value: int
    activity: str | None = None
    comment: str | None = None
    tags: list[AdminReasonLabel] = Field(default_factory=list)
    created_at: UtcDatetime


class AdminStatsResponse(BaseModel):
    days: int
    users: AdminUserStats
    usage: AdminUsageStats
    satisfaction: AdminSatisfaction
    recent_comments: list[AdminComment]


class AdminCommentsResponse(BaseModel):
    total: int = Field(..., description="Tổng số nhận xét khớp bộ lọc")
    items: list[AdminComment]


AdvisorAccountStatus = Literal["active", "password_pending", "disabled"]


class AdminAdvisorResponse(BaseModel):
    id: str
    full_name: str
    email: str
    title: str
    avatar_url: str | None = None
    student_count: int
    pending_reviews: int = Field(..., description="Buổi SV đã chia sẻ mà cố vấn chưa nhận xét")
    status: AdvisorAccountStatus
    last_active_at: UtcDatetime | None = None
    created_at: UtcDatetime


class CreateAdvisorRequest(BaseModel):
    full_name: str
    email: str
    title: str
    temporary_password: str


class UpdateAdvisorRequest(BaseModel):
    full_name: str | None = None
    email: str | None = None
    title: str | None = None
    disabled: bool | None = Field(default=None, description="true = tạm khoá, false = mở khoá")


class ResetAdvisorPasswordRequest(BaseModel):
    temporary_password: str


class AdminStudentAdvisor(BaseModel):
    id: str
    full_name: str
    disabled: bool


class AdminStudentResponse(BaseModel):
    id: str
    full_name: str
    email: str
    phone: str | None = None
    avatar_url: str | None = None
    advisor: AdminStudentAdvisor | None = None
    created_at: UtcDatetime
    last_active_at: UtcDatetime | None = None


class AssignAdvisorRequest(BaseModel):
    student_ids: list[str] = Field(..., min_length=1, max_length=200)
    advisor_id: str


class AssignAdvisorResponse(BaseModel):
    assigned: int = Field(..., description="Số SV được gán hoặc đổi sang cố vấn này")
    unchanged: int = Field(..., description="Số SV vốn đã thuộc cố vấn này")
