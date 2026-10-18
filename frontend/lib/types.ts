// Hợp đồng dữ liệu frontend ↔ backend (bản nháp do frontend đề xuất).
// Tên field dùng snake_case để khớp trực tiếp với Pydantic schema ở src/models/schemas.py.
// Khi backend chốt schema, sửa file này cho khớp; các trang chỉ phụ thuộc vào đây và lib/api.ts.

export type Role = "student" | "advisor" | "admin"

export type ISODateString = string

// ---------- Người dùng & hạn mức ----------

export interface UserProfile {
  id: string
  role: Role
  full_name: string
  /** SV: email; cố vấn: chức danh. */
  subtitle: string
  avatar_url: string | null
  /** Cố vấn đang dùng mật khẩu tạm do quản trị viên đặt: phải đổi trước khi dùng tiếp. */
  must_change_password?: boolean
}

// ---------- CV (US-SV-01) ----------

export type CvFileType = "pdf" | "docx"
export type CvStatus = "processing" | "ready" | "failed"

/**
 * Một phiên bản CV. Các phiên bản cùng family_id là một CV (một thẻ trong "CV của tôi"): tải file lên tạo CV mới v1.0,
 * "Hoàn tất" ở Trình tối ưu thêm số phụ (v1.1), khôi phục một bản cũ thêm số chính (v2.0). Bản mới nhất hiển thị
 * trên thẻ; các bản trước xem ở trang Chi tiết CV (src/services/cv_versions.py).
 */
export interface CvVersion {
  id: string
  /** Số thứ tự nội bộ, tăng dần trên mọi CV của SV; không dùng để hiển thị. */
  version: number
  /** "v1.0", "v1.1", "v2.0"... đánh số riêng trong từng CV. */
  label: string
  /** Mã CV = id phiên bản đầu tiên; dùng cho trang Chi tiết CV và chia sẻ với cố vấn. */
  family_id: string
  /** Số phiên bản của CV này (có ở danh sách CV). */
  version_count: number
  file_name: string
  file_type: CvFileType
  size_bytes: number
  page_count: number | null
  /** Chỉ có ở phản hồi tải lên: file là PDF scan, chữ được đọc bằng OCR nên có thể sai sót. */
  read_by_ocr?: boolean
  uploaded_at: ISODateString
  status: CvStatus
  /** Lý do khi status = "failed", ví dụ file scan không có lớp văn bản (US-SV-01 AC2). */
  error_message: string | null
  /** Vị trí (JD) của lần phân tích gần nhất. */
  target_title: string | null
  /** CV–JD Matching Score (0–100) của lần phân tích gần nhất; không phải điểm ATS (PRD mục 8). */
  match_score: number | null
  /** "upload": SV tự tải lên; "optimized": tạo ra khi "Hoàn tất" trong Trình tối ưu (US-SV-03);
   * "restored": bản sao của một phiên bản cũ khi SV khôi phục. */
  origin: "upload" | "optimized" | "restored"
  /** Lần phân tích gần nhất của phiên bản này; dùng cho nút "Tối ưu". */
  latest_analysis_id: string | null
  /** Lượt phân tích đã dùng để tối ưu ra phiên bản này (origin = "optimized"); dùng cho "Xem thay đổi". */
  source_analysis_id: string | null
  /** Vị trí của JD đã dùng để tối ưu ra phiên bản này (có ở lịch sử phiên bản). */
  source_jd_title: string | null
  /** Nhãn phiên bản cũ được khôi phục thành bản này (origin = "restored"). */
  restored_from_label: string | null
  is_active: boolean
  is_draft: boolean
}

// ---------- JD (US-SV-02) ----------

export type JobLevel = "intern" | "fresher" | "junior"

/** Mức độ yêu cầu trong JD; trọng số Required 3 / Preferred 2 / Additional 1 (PRD mục 5.2). */
export type RequirementImportance = "required" | "preferred" | "additional"

export interface JdSkill {
  name: string
  importance: RequirementImportance
  /** Tên gọi khác (để nhận ra kỹ năng khi CV / JD viết khác chữ). */
  aliases?: string[]
}

/** Kỹ năng nên học thêm ở Tổng quan; roadmap_url chỉ có với kỹ năng roadmap.sh có lộ trình riêng. */
export interface SkillToLearn extends JdSkill {
  roadmap_url?: string | null
}

export type EmploymentType = "full_time" | "part_time" | "internship"
export type WorkMode = "onsite" | "remote" | "hybrid"
export type ExperienceLevel = "none" | "under_1" | "1_2" | "2_plus"

/**
 * Cấu trúc chung của mọi JD (thư viện và JD sinh viên tự dán). Bắt buộc với JD tự dán: tên vị trí, cấp bậc, mô tả,
 * yêu cầu; JD thư viện bắt buộc thêm công ty, ngành, hình thức, nơi làm việc, địa điểm, kinh nghiệm.
 */
export interface JdFields {
  title?: string | null
  company?: string | null
  level?: JobLevel | null
  /** Một trong JD_INDUSTRIES (lib/jd.ts). */
  industry?: string | null
  employment_type?: EmploymentType | null
  work_mode?: WorkMode | null
  location?: string | null
  /** Chữ tự do: "12 – 15 triệu", "Thoả thuận". */
  salary?: string | null
  /** YYYY-MM-DD */
  deadline?: string | null
  experience?: ExperienceLevel | null
  majors?: string[] | null
  /** Mô tả công việc (gạch đầu dòng, có thể có đoạn giới thiệu ở đầu). */
  description?: string | null
  /** Yêu cầu ứng viên; có thể có dòng "Ưu tiên:" / "Điểm cộng:". */
  requirements?: string | null
  benefits?: string | null
  how_to_apply?: string | null
}

/** Kết quả tách toàn văn JD (POST /jd/parse), chưa lưu. */
export interface JdDraft extends JdFields {
  skills: JdSkill[]
  skills_source: "dictionary" | "sections" | "ai"
  /** Có dùng AI (khi quy tắc còn thiếu tên vị trí, mô tả hoặc yêu cầu). */
  used_ai: boolean
  word_count: number
}

export interface JobDescription extends JdFields {
  id: string
  title: string
  company: string | null
  industry: string | null
  /** null với JD sinh viên tự dán. */
  level: JobLevel | null
  skills: JdSkill[]
  /** Toàn văn JD. */
  content: string
  source: "library" | "pasted"
  /** Nguồn mức quan trọng của kỹ năng; "dictionary" / "sections": mức chính xác có sau lần phân tích đầu tiên. */
  skills_source?: "dictionary" | "sections" | "ai" | "analysis" | "admin" | null
  created_at?: ISODateString | null
}

/** Ngưỡng JD tối thiểu khi dán text (US-SV-02 AC2). */
export const JD_MIN_WORDS = 50

export interface CreateGapAnalysisRequest {
  cv_version_id: string
  /** Chọn từ thư viện... */
  jd_id?: string
  /** ...hoặc dán nội dung (≥ JD_MIN_WORDS từ). */
  jd_text?: string
  jd_title?: string
  jd_company?: string
}

// ---------- Gợi ý vị trí & JD đã lưu (Thư viện JD) ----------

/** POST /jd/recommend (RecommendJDsRequest). Backend cho top_n 1–10; giao diện dùng tối đa 6. */
export interface RecommendJdsRequest {
  cv_version_id?: string
  cv_text?: string
  top_n?: number
  generate_advice?: boolean
}

/**
 * Một vị trí được gợi ý (JDRecommendationItem). Ước tính nhanh theo quy tắc, không qua LLM; JD đã có lượt phân tích
 * của đúng CV này thì dùng điểm của lượt phân tích. Giao diện chỉ hiện match_label, không hiện match_score (DESIGN.md 8.1).
 */
export interface JdRecommendationItem {
  jd_id: string
  title: string
  company: string | null
  industry: string | null
  level: string | null
  /** Độ tương đồng ngữ nghĩa từ vector store (0–1). */
  semantic_score: number
  match_score: number | null
  match_label: MatchLabel | null
  /** Có bằng chứng sử dụng trong CV. */
  matched_skills: string[]
  /** Chỉ được liệt kê trong CV. */
  partial_skills: string[]
  missing_skills: string[]
  breakdown: ScoreBreakdown[]
  /** analysis: lấy từ lượt phân tích đã có của CV này; estimate: ước tính nhanh bằng quy tắc. */
  score_source?: "analysis" | "estimate"
  analysis_id?: string | null
}

/** Lời khuyên nghề nghiệp do LLM viết cho vị trí #1 (CareerAdvice). */
export interface CareerAdvice {
  summary: string
  top_position_advice: string
  action_plan: string[]
}

export interface RecommendJdsResponse {
  cv_version_id: string | null
  /** Đã sắp theo mức phù hợp giảm dần; phần tử đầu là gợi ý #1. */
  recommendations: JdRecommendationItem[]
  advice: CareerAdvice | null
}

/** Vị trí SV đã lưu ("Đã lưu"). Backend chưa có endpoint (DESIGN.md mục 12), hiện chỉ có ở mock. */
export interface SavedJd {
  jd_id: string
  saved_at: ISODateString
}

/**
 * Tạo một JD tự dán để dùng lại (ví dụ khi so sánh nhiều vị trí, POST /jd/compare chỉ nhận jd_ids).
 * Backend hiện chỉ tạo JD tự dán bên trong POST /gap-analysis; đây là endpoint đề xuất, mới có ở mock.
 */
export interface CreatePastedJdRequest extends JdFields {
  /** Toàn văn JD (≥ JD_MIN_WORDS từ). */
  text: string
  /** Kỹ năng từ bước tách (JdDraft). */
  skills?: JdSkill[]
  skills_source?: JdDraft["skills_source"]
  /** true: sinh viên đã xem lại các trường (hộp Thêm JD); bắt buộc tên vị trí, cấp bậc, mô tả, yêu cầu. */
  reviewed?: boolean
}

// ---------- So sánh nhiều vị trí (POST /jd/compare) ----------

/** Giới hạn số JD so sánh một lần của backend (CompareJDsRequest). */
export const COMPARE_MIN_JDS = 2
export const COMPARE_MAX_JDS = 3

/** CompareJDsRequest: cv_version_id hoặc cv_text, cùng 2–3 JD khác nhau. */
export interface CompareJdsRequest {
  cv_version_id?: string
  cv_text?: string
  jd_ids: string[]
}

/** Kết quả đối sánh của một JD (JDComparisonItem), chấm qua LLM theo PRD 5.2. */
export interface JdComparisonItem {
  /** 1 là phù hợp nhất. */
  rank: number
  jd_id: string
  title: string
  company: string | null
  industry: string | null
  level: string | null
  /** 0–100. */
  match_score: number
  match_label: MatchLabel
  /** Có bằng chứng sử dụng trong CV. */
  matched_skills: string[]
  /** Chỉ được liệt kê trong CV. */
  partial_skills: string[]
  missing_skills: string[]
  breakdown: ScoreBreakdown[]
  llm_summary: string | null
  llm_used: boolean
  /** Số yêu cầu kỹ năng trích được từ JD (lượt so sánh cũ không có). */
  requirement_count?: number
  /** given: có sẵn; llm: vừa trích bằng AI; dictionary: AI lỗi, chỉ có kỹ năng nhận ra theo từ điển. */
  requirements_source?: "given" | "llm" | "dictionary"
}

export interface CompareJdsResponse {
  /** Mã lượt so sánh trong lịch sử (backend lưu mỗi lượt kèm kết quả). */
  id?: string | null
  cv_version_id: string | null
  /** Ví dụ "v2.1". */
  cv_label: string | null
  cv_name: string | null
  total_compared: number
  /** Đã sắp theo match_score giảm dần. */
  comparisons: JdComparisonItem[]
  /** Kỹ năng còn thiếu ở tất cả các JD đã chọn. */
  common_missing_skills: string[]
  /** Kỹ năng thiếu chung → link lộ trình roadmap.sh (chỉ kỹ năng có lộ trình riêng). */
  common_missing_roadmaps?: Record<string, string>
  created_at?: ISODateString | null
}

// ---------- Phân tích khoảng cách (US-SV-02, US-SV-05, PRD mục 5.2) ----------

export type AnalysisStatus = "processing" | "completed" | "failed"

/** Các bước thật của pipeline phân tích, theo thứ tự chạy. */
export type AnalysisStep = "parse" | "retrieve" | "compare" | "generate" | "verify_grounding"

/**
 * matched → "Khớp" (Match = 1): có bằng chứng cụ thể trong Kinh nghiệm / Dự án / Học vấn / Hoạt động
 * partial → "Một phần" (Match = 0.5): chỉ được liệt kê, chưa có mô tả sử dụng
 * missing → "Thiếu" (Match = 0): không xuất hiện trong CV — không tự điền bằng chứng
 */
export type MatchStatus = "matched" | "partial" | "missing"

/** Câu trích nguyên văn từ CV làm bằng chứng. */
export interface CvEvidence {
  line_no: number
  text: string
  section: string | null
  /** Ví dụ "Kinh nghiệm", "Dự án", "Kỹ năng". */
  section_label: string
}

/** Một dòng bảng Evidence: yêu cầu của JD và mức đáp ứng trong CV. */
export interface RequirementAssessment {
  id: string
  skill: string
  importance: RequirementImportance
  /** Trọng số 3 / 2 / 1. */
  weight: number
  /** 0, 0.5 hoặc 1. */
  match: number
  status: MatchStatus
  evidence: CvEvidence | null
  /** Ví dụ "FastAPI → tính là Python (taxonomy)". */
  note: string | null
  /** Lộ trình học kỹ năng trên roadmap.sh (chỉ có cho kỹ năng ngành CNTT). */
  roadmap_url?: string | null
  /** false khi kỹ năng không thuộc CNTT, khi đó roadmap_url chỉ là trang danh sách chung. */
  is_it_supported?: boolean
}

/** Phân rã điểm theo mức độ yêu cầu (hiển thị khi bấm "Xem thêm"). */
export interface ScoreBreakdown {
  importance: RequirementImportance
  label: string
  weight: number
  total: number
  matched: number
  partial: number
  missing: number
  /** Σ(w × Match) của nhóm. */
  earned: number
  /** Σw của nhóm. */
  possible: number
}

/** Gợi ý diễn đạt lại một dòng CV, đã qua kiểm tra grounding. */
export interface AnalysisSuggestion {
  /** Dùng làm response_id cho like/dislike. */
  id: string
  skill: string
  /** Dòng CV được thay; null với lượt phân tích cũ. */
  line_no?: number | null
  section_label: string | null
  original_text: string
  suggested_text: string
  reason: string
}

// ---------- Trình tối ưu CV (US-SV-03) ----------

/** Vị trí trong CV gốc làm căn cứ cho một gợi ý. */
export interface EvidenceSpan {
  text: string
  line_start: number
  line_end: number
}

export type SuggestionStatus = "pending" | "accepted" | "edited" | "rejected"

/** ats_keyword: câu mới dùng đúng tên kỹ năng trong JD mà câu gốc chưa có; star_quantify: cần số liệu (AC2, chưa làm). */
export type SuggestionKind = "rephrase" | "star_quantify" | "ats_keyword"

export interface Suggestion {
  id: string
  kind: SuggestionKind
  skill: string
  /** Dòng trong CvDocument mà gợi ý này thay thế. */
  line_id: string
  /** Dòng nối của gạch ý bị ngắt dòng khi trích PDF: hiển thị gộp với line_id, câu thay thế thay cả gạch ý. */
  extra_line_ids?: string[]
  original_text: string
  /** Nội dung AI đề xuất. */
  proposed_text: string
  /** Nội dung sẽ vào CV sau quyết định (câu AI hoặc bản SV sửa); null khi chưa quyết định hoặc đã bỏ qua. */
  final_text: string | null
  /** Lý do AI đề xuất (hiển thị trên thẻ gợi ý). */
  rationale: string
  evidence_span: EvidenceSpan
  status: SuggestionStatus
  /** true khi AI cần SV bổ sung ngữ cảnh/chứng cứ trước khi gợi ý (US-SV-03 AC2, backend chưa làm). */
  needs_context: boolean
  context_question: string | null
}

// ---------- Nội dung CV (hiển thị ở Trình tối ưu và Xuất CV) ----------

export interface CvDocLine {
  /** Dạng "l{line_no}". */
  id: string
  /** Số dòng trong CV gốc (đếm các dòng có nội dung), khớp với EvidenceSpan.line_start. */
  line_no: number
  text: string
  /**
   * Cách trình bày trong mẫu CV (backend src/services/cv_layout.py); thiếu thì coi là "bullet".
   * entry: tên mục con in đậm, thời gian (date) căn phải · role: in nghiêng · tech: in nghiêng đậm ·
   * label: "Nhãn:" in đậm · text: đoạn văn · name / contact: phần đầu.
   */
  kind?: CvLineKind
  /** Thời gian của dòng entry, ví dụ "Jun 2024 – Present". */
  date?: string | null
  /** Nửa sau của câu bị xuống dòng khi trích PDF/OCR: ghép vào dòng trước khi trình bày. */
  cont?: boolean
}

export type CvLineKind = "name" | "contact" | "text" | "entry" | "role" | "tech" | "label" | "bullet"

export interface CvDocSection {
  id: string
  /** Tiêu đề mục như trong CV, ví dụ "KINH NGHIỆM LÀM VIỆC". */
  title: string
  lines: CvDocLine[]
}

/** Nội dung CV tách theo mục từ văn bản đã trích (không giữ được thiết kế của file gốc). */
export interface CvDocument {
  /** Các dòng trước mục đầu tiên: họ tên, liên hệ... */
  header: CvDocLine[]
  sections: CvDocSection[]
  /** Kỹ năng SV tự ghi là đang học; không bao giờ ghi là thành thạo và không tính điểm khi phân tích lại. */
  developing_skills: { name: string; note: string }[]
  /** Ngôn ngữ CV: đặt tiêu đề "Kỹ năng đang phát triển" / "Developing Skills". */
  lang?: "vi" | "en"
}

/** Cách xem một phiên bản CV trong app: ảnh từng trang PDF gốc, hoặc nội dung theo mẫu CV (DOCX, bản đã tối ưu). */
export type CvPreviewInfo =
  | { kind: "pages"; page_count: number; document: null }
  | { kind: "document"; page_count: null; document: CvDocument }

// ---------- Trình tối ưu CV (US-SV-03) & Xuất CV ----------

/** Kỹ năng JD yêu cầu mà CV chưa có; SV tự xác nhận, AI không tự thêm kỹ năng vào CV (US-SV-05). */
export interface CapabilityCheck {
  /** Mã yêu cầu JD trong lượt phân tích. */
  id: string
  skill: string
  importance: RequirementImportance
  jd_requirement: string
  status: "pending" | "has_experience" | "no_experience"
  /** Mô tả SV cung cấp khi chọn "đã có kinh nghiệm". */
  context: string | null
  /** Ghi chú đang học khi chọn "chưa có kinh nghiệm". */
  learning_note: string | null
  /** "Có, đã dùng": phần CV sẽ thêm câu (id trong OptimizerSession.entries). */
  entry_id?: string | null
  /** Câu cho CV viết từ lời kể của SV (AI, không thêm thông tin mới), chờ SV duyệt. */
  draft_text?: string | null
  /** Câu sẽ thêm vào CV khi Hoàn tất (đã áp dụng hoặc SV sửa). */
  final_text?: string | null
  line_status?: "pending" | "accepted" | "edited" | "rejected"
  /** Lộ trình học trên roadmap.sh (chỉ kỹ năng CNTT); hiện khi SV chọn "Chưa có". */
  roadmap_url?: string | null
}

/** Chỗ có thể thêm câu kinh nghiệm mới: một dự án / công việc trong CV, hoặc cuối một mục. */
export interface CvEntry {
  id: string
  label: string
  /** Câu mới chèn ngay sau dòng này của document. */
  after_line_id: string
}

/**
 * Trình tối ưu của một lượt phân tích. Quyết định của SV nằm trong bản nháp; "Hoàn tất" tạo đúng một phiên bản CV
 * mới (result_cv) rồi khoá phiên (status = "finalized").
 */
export interface OptimizerSession {
  analysis_id: string
  status: "draft" | "finalized"
  jd: Pick<JobDescription, "id" | "title" | "company" | "industry" | "level" | "source">
  /** CV–JD Matching Score của lượt phân tích. */
  match_score: number | null
  match_label: MatchLabel | null
  /** false: lượt phân tích chấm bằng quy tắc dự phòng nên không có gợi ý diễn đạt lại. */
  llm_used: boolean
  /** Gợi ý không qua guardrail, đang chờ cố vấn xem lại. */
  pending_review_count: number
  /** Phiên bản CV được tối ưu. */
  cv: CvVersion
  /** Phiên bản tạo ra khi "Hoàn tất"; null khi chưa hoàn tất hoặc SV đã xoá phiên bản đó. */
  result_cv: CvVersion | null
  /** Nội dung phiên bản được tối ưu (chưa áp gợi ý). */
  document: CvDocument
  /** Nội dung phiên bản tạo ra khi "Hoàn tất" (đúng như file DOCX). */
  result_document: CvDocument | null
  suggestions: Suggestion[]
  /**
   * pending: chưa soạn gợi ý viết lại riêng cho phiên (gọi api.prepareOptimizerSuggestions); failed: soạn lỗi (AI bận /
   * hết lượt), SV bấm Thử lại; ready (hoặc không có, ở chế độ mock): có gợi ý để duyệt.
   */
  suggestions_state?: "pending" | "ready" | "failed"
  /** Số câu AI đã xem xét và cho là đã rõ, không cần sửa. */
  kept_count?: number
  /** Lần soạn gợi ý gần nhất. */
  suggestions_attempted_at?: ISODateString | null
  capability_checks: CapabilityCheck[]
  entries?: CvEntry[]
  finalized_at: ISODateString | null
}

export interface SuggestionDecisionRequest {
  /** undo: đưa gợi ý về chờ duyệt (chỉ khi chưa "Hoàn tất"). */
  decision: "accept" | "edit" | "reject" | "undo"
  /** Bắt buộc khi decision = "edit". */
  edited_text?: string
}

export interface CapabilityDraftRequest {
  context: string
  entry_id: string
}

export interface CapabilityLineDecisionRequest {
  decision: "accept" | "edit" | "reject" | "undo"
  /** Bắt buộc khi decision = "edit". */
  edited_text?: string
}

export interface CapabilityAnswerRequest {
  has_experience: boolean
  /** Bắt buộc khi has_experience = true. */
  context?: string
  /**
   * Chỉ khi has_experience = false: SV tự ghi mình đang học kỹ năng này (ví dụ "Đang học chứng chỉ PL-300").
   * Khi có, kỹ năng vào mục "Kỹ năng đang phát triển" của phiên bản mới, không bao giờ ghi là thành thạo.
   */
  learning_note?: string
}

/** docx: tải file; print: in / lưu PDF từ trình duyệt; text: sao chép các câu đã sửa để tự dán vào CV gốc. */
export type ExportFormat = "docx" | "print" | "text"

export interface ExportCvRequest {
  format: ExportFormat
  /** SV đã tick cam kết liêm chính học thuật. */
  integrity_confirmed: boolean
}

export interface ExportCvResponse {
  id: string
  format: ExportFormat
  confirmed_at: ISODateString
}

/**
 * Một lượt phân tích CV–JD. Backend chạy nền: frontend hỏi lại getGapAnalysis cho tới khi status khác "processing"
 * (current_step cho biết bước đang chạy); các trường kết quả chỉ có ý nghĩa khi status = "completed".
 */
export interface GapAnalysis {
  id: string
  /** Dùng cho khảo sát CSAT. */
  response_id: string
  status: AnalysisStatus
  current_step: AnalysisStep | null
  error_message: string | null
  cv_version_id: string
  cv_file_name: string
  /** Ví dụ "v2.0". */
  cv_label: string
  jd: Pick<JobDescription, "id" | "title" | "company" | "industry" | "level" | "source">
  created_at: ISODateString
  completed_at: ISODateString | null
  /** CV–JD Matching Score 0–100 = Σ(w × Match) / Σw × 100 (PRD mục 5.2). */
  match_score: number | null
  /** Thấp (< 50) / Trung bình (50–74) / Cao (≥ 75). */
  match_label: "low" | "medium" | "high" | null
  counts: Record<MatchStatus, number>
  breakdown: ScoreBreakdown[]
  requirements: RequirementAssessment[]
  suggestions: AnalysisSuggestion[]
  /** Số gợi ý không qua guardrail, đang chờ cố vấn xem lại. */
  pending_review_count: number
  summary: string | null
  /** Một kỹ năng của JD có trong CV mà nhà tuyển dụng nhiều khả năng sẽ hỏi sâu (chỉ có khi AI chấm). */
  interview_focus?: string | null
  /** false khi AI không khả dụng và điểm được chấm bằng quy tắc dự phòng. */
  llm_used: boolean
}

// ---------- Phỏng vấn thử (US-SV-04, thang STAR 0–5 theo PRD mục 5.1) ----------

export type StarCriterion = "situation" | "task" | "action" | "result"

/** Điểm 4 tiêu chí STAR, thang 0–5. */
export type StarScores = Record<StarCriterion, number>

export interface InterviewJdRef {
  id: string
  title: string
  company: string | null
  source: "library" | "pasted"
}

/** Câu hỏi đang chờ trả lời. */
export interface InterviewQuestion {
  /** Bắt đầu từ 1. */
  index: number
  /** Ví dụ "Làm việc nhóm". */
  theme: string
  text: string
}

/** Một câu đã trả lời (hoặc hết giờ) kèm điểm S/T/A/R. */
export interface InterviewTurn {
  /** Dùng làm response_id cho like/dislike nhận xét. */
  id: string
  index: number
  theme: string
  question: string
  /** null khi hết giờ mà chưa có câu trả lời. */
  answer: string | null
  timed_out: boolean
  star: StarScores | null
  /** Trung bình 4 tiêu chí (0–5). */
  score: number | null
  feedback: string | null
}

/**
 * Trạng thái buổi phỏng vấn. Mỗi buổi 4 câu, mỗi câu có hạn chót do backend giữ (seconds_left);
 * tạm dừng được 1 lần, tối đa 1 phút. Buổi bỏ dở bị xoá và không tính lượt.
 */
/** with_cv: câu hỏi dựa trên CV và JD; jd_only: chỉ dựa trên vị trí, không cần CV. */
export type InterviewMode = "with_cv" | "jd_only"

export interface InterviewSession {
  id: string
  status: "in_progress" | "completed"
  jd: InterviewJdRef
  interview_mode?: InterviewMode
  cv_version_id: string | null
  cv_file_name: string | null
  question_count: number
  seconds_per_question: number
  /** null khi đã hoàn thành. */
  current_question: InterviewQuestion | null
  seconds_left: number | null
  paused: boolean
  pause_used: boolean
  pause_seconds_left: number | null
  /** Các câu đã trả lời, theo thứ tự. */
  turns: InterviewTurn[]
  created_at: ISODateString
  /** Legacy capability field. PhoWhisper availability is checked on the user's device. */
  voice_input?: boolean
}

export interface CreateInterviewRequest {
  jd_id: string
  /** Bỏ trống khi phỏng vấn chỉ theo vị trí (interview_mode = "jd_only"). */
  cv_version_id: string | null
  interview_mode: InterviewMode
}

export interface SubmitAnswerRequest {
  question_index: number
  text: string
  /** true khi hết giờ và frontend tự nộp phần đang gõ. */
  timed_out?: boolean
}

/**
 * allowed = false: bị guardrail chặn (lạc đề, quá ngắn...), không tính câu, đồng hồ vẫn chạy.
 * allowed = true: câu đã chấm; next_question là câu tiếp theo hoặc null khi buổi đã xong (finished).
 */
export interface SubmitAnswerResponse {
  allowed: boolean
  reason: string | null
  turn: InterviewTurn | null
  next_question: InterviewQuestion | null
  seconds_left: number | null
  finished: boolean
}

/** Cần luyện thêm (< 2) · Đạt cơ bản (< 3) · Khá (< 4) · Tốt (≥ 4). */
export type InterviewLabel = "weak" | "basic" | "fair" | "good"

export interface InterviewReport {
  id: string
  /** Dùng cho khảo sát CSAT. */
  response_id: string
  jd: InterviewJdRef
  interview_mode?: InterviewMode
  cv_file_name: string | null
  created_at: ISODateString
  completed_at: ISODateString
  duration_seconds: number
  overall_score: number
  label: InterviewLabel
  star: StarScores
  weakest: StarCriterion
  turns: InterviewTurn[]
  timed_out_count: number
  /** Chỉ gợi ý khung trả lời, không viết sẵn câu trả lời chứa thành tích SV chưa nêu. */
  guidance: string[]
  /** So sánh với buổi đầu tiên của cùng vị trí (từ buổi thứ 2). */
  comparison: { first_session_id: string; first_score: number; first_completed_at: ISODateString; delta: number } | null
  /** Nhận xét của cố vấn phụ trách (khi SV đã chia sẻ báo cáo và cố vấn đã viết). */
  advisor_review: ReportAdvisorReview | null
}

export interface ReportAdvisorReview {
  id: string
  advisor_name: string
  comment: string
  updated_at: ISODateString
  read: boolean
}

/** Một buổi đã hoàn thành trong danh sách gần đây. */
export interface InterviewSummary {
  id: string
  jd: InterviewJdRef
  completed_at: ISODateString
  overall_score: number
  star: StarScores
}

/** Hạn mức buổi có chấm điểm theo vị trí trong tuần (PRD: 3 buổi / vị trí / tuần). */
export interface InterviewQuota {
  jd_id: string
  used: number
  limit: number
  remaining: number
  resets_at: ISODateString
}

// ---------- Phản hồi (B3, US-SV-06) ----------

/** Lượt dùng được chấm sao (CSAT). */
export type CsatActivity = "gap_analysis" | "optimizer" | "interview"
/** Phần nhỏ được like / dislike. */
export type ThumbActivity = "gap_suggestion" | "interview_turn" | "job_recommendation" | "jd_compare"

export type FeedbackRequest =
  | {
      response_id: string
      kind: "thumb"
      /** 1 = hữu ích, -1 = chưa hữu ích */
      value: 1 | -1
      activity?: ThumbActivity
      comment?: string
    }
  | {
      response_id: string
      kind: "csat"
      /** 1–5 sao */
      value: 1 | 2 | 3 | 4 | 5
      activity: CsatActivity
      comment?: string
      /** Chỉ khi 1–3 sao: mã lý do chọn nhanh (lib/feedback.ts). */
      tags?: string[]
      /** "Bạn có dùng lại không?" (tuỳ chọn). */
      would_reuse?: boolean
    }

export interface FeedbackResponse {
  id: string
  /** Đã có phản hồi trước đó cho cùng response_id (US-SV-06 AC3). */
  already_submitted: boolean
  /** Giá trị đang được lưu (giá trị cũ nếu already_submitted = true). */
  value: number
}

/** Phản hồi đã gửi cho một response_id; value = null nếu chưa gửi. */
export interface FeedbackStatus {
  kind: "thumb" | "csat"
  value: number | null
}

// ---------- Tổng quan (S1) & Lịch sử – Tiến bộ (S8) của SV ----------

/** Thấp (< 50) / Trung bình (50–74) / Cao (≥ 75). */
export type MatchLabel = "low" | "medium" | "high"

/** Một lượt phân tích trong danh sách (mọi trạng thái). */
export interface AnalysisRow {
  id: string
  jd: InterviewJdRef
  cv_version_id: string
  cv_label: string
  cv_file_name: string
  status: AnalysisStatus
  current_step: AnalysisStep | null
  /** CV–JD Matching Score 0–100; null khi chưa xong hoặc lỗi. */
  match_score: number | null
  match_label: MatchLabel | null
  created_at: ISODateString
  completed_at: ISODateString | null
}

/** Một buổi phỏng vấn đã hoàn thành trong danh sách. */
export interface InterviewRow {
  id: string
  jd: InterviewJdRef
  completed_at: ISODateString
  duration_seconds: number
  /** 0–5. */
  overall_score: number
  label: InterviewLabel
  star: StarScores
  timed_out_count: number
  /** jd_only: hỏi chỉ dựa trên JD, không dùng CV. */
  interview_mode?: "jd_only" | "with_cv"
  cv_file_name?: string | null
  /** Ví dụ "v1.0"; null khi phiên bản đó đã bị xoá. */
  cv_label?: string | null
}

/** Điểm tổng (0–5) của một buổi, dùng để vẽ biểu đồ. */
export interface SessionScore {
  /** id buổi phỏng vấn. */
  id: string
  completed_at: ISODateString
  score: number
}

type QuotaInfo = {
  /** Số buổi còn lại của vị trí trong tuần. */
  quota_remaining: number
  quota_resets_at: ISODateString
}

/**
 * Việc nên làm tiếp theo, theo thứ tự: tải CV → phân tích với một JD → luyện phỏng vấn vị trí vừa phân tích
 * → luyện tiếp để cải thiện tiêu chí yếu nhất của buổi gần nhất.
 */
export type NextStep =
  | { kind: "upload_cv" }
  | { kind: "analyze"; cv_version_id: string; cv_label: string }
  | ({ kind: "interview"; jd: InterviewJdRef; analysis_id: string; match_score: number | null } & QuotaInfo)
  | ({
      kind: "improve"
      jd: InterviewJdRef
      session_id: string
      criterion: StarCriterion
      criterion_score: number
      guidance: string
    } & QuotaInfo)

/** Điểm trung bình S/T/A/R của các buổi gần nhất (tối đa 5 buổi) và tiêu chí yếu nhất. */
export interface StarSummary {
  average: StarScores
  weakest: StarCriterion
  session_count: number
}

export interface StudentOverview {
  cv_count: number
  cv_latest_at: ISODateString | null
  /** Số buổi đã hoàn thành. */
  interview_count: number
  /** Số buổi hoàn thành trong tuần này (mọi vị trí). */
  interview_week_count: number
  /** Lượt phân tích hoàn thành gần nhất. */
  latest_match: {
    analysis_id: string
    jd: InterviewJdRef
    cv_label: string
    score: number | null
    label: MatchLabel | null
    completed_at: ISODateString
  } | null
  /** Buổi gần nhất, so với buổi đầu tiên của cùng vị trí (điểm 0–5 chỉ so được trong cùng vị trí). */
  latest_interview: {
    id: string
    jd: InterviewJdRef
    completed_at: ISODateString
    score: number
    label: InterviewLabel
    /** null khi đây là buổi đầu tiên của vị trí. */
    first_score: number | null
    delta: number | null
    session_count: number
    /** Tối đa 5 buổi gần nhất của vị trí, cũ → mới. */
    trend: SessionScore[]
  } | null
  /** Trung bình S/T/A/R của tối đa 5 buổi gần nhất (mọi vị trí). */
  star: StarSummary | null
  in_progress: {
    /** Lượt phân tích đang chạy. */
    analyses: AnalysisRow[]
    /** Buổi phỏng vấn đang dở và còn quay lại phòng được. */
    interview: {
      id: string
      jd: InterviewJdRef
      /** Câu đang làm, bắt đầu từ 1. */
      current_index: number
      question_count: number
      seconds_left: number | null
      paused: boolean
    } | null
  }
  next_step: NextStep
  /** Kỹ năng "Thiếu" trong lần phân tích gần nhất, nhóm Bắt buộc trước (tối đa 6). */
  skills_to_learn: { analysis_id: string; jd: InterviewJdRef; skills: SkillToLearn[]; total_missing: number } | null
  /** Tối đa 5, mới nhất trước. */
  recent_analyses: AnalysisRow[]
  /** Tối đa 5, mới nhất trước. */
  recent_interviews: InterviewRow[]
}

export type ProgressRange = "30d" | "90d" | "all"

/** Một vị trí SV đã luyện phỏng vấn hoặc phân tích (dùng cho bộ lọc). */
export interface PositionOption {
  jd: InterviewJdRef
  interview_count: number
  analysis_count: number
  last_activity_at: ISODateString
}

/**
 * Tiến bộ phỏng vấn của một vị trí (PRD mục 5.1): lớp 1 là điểm tổng qua các buổi,
 * lớp 2 là S/T/A/R của buổi trước so với buổi gần nhất.
 */
export interface InterviewProgress {
  jd: InterviewJdRef
  session_count: number
  /** Các buổi trong khoảng thời gian, cũ → mới. */
  points: SessionScore[]
  first_score: number
  latest_score: number
  /** null khi mới có 1 buổi. */
  delta_from_first: number | null
  delta_from_previous: number | null
  latest_session_id: string
  previous_session_id: string | null
  star_latest: StarScores
  star_previous: StarScores | null
}

/** Độ khớp với một JD qua các phiên bản CV (mỗi phiên bản lấy lần phân tích gần nhất), theo số phiên bản. */
export interface CvProgress {
  jd: InterviewJdRef
  points: { analysis_id: string; cv_version_id: string; cv_label: string; match_score: number; completed_at: ISODateString }[]
  /** Phiên bản mới nhất − phiên bản đầu; null nếu mới có 1 phiên bản. */
  delta: number | null
}

export interface StudentProgress {
  range: ProgressRange
  jd_id: string | null
  last_activity_at: ISODateString | null
  /** Mọi vị trí đã có hoạt động (không phụ thuộc bộ lọc). */
  positions: PositionOption[]
  /** Hoạt động gần nhất trước. */
  interview_progress: InterviewProgress[]
  cv_progress: CvProgress[]
  /** Mới nhất trước. */
  interviews: InterviewRow[]
  analyses: AnalysisRow[]
}

// ---------- Chia sẻ với Cố vấn ----------
// Mặc định mọi tài liệu là riêng tư. Không chia sẻ thì cố vấn chỉ thấy số liệu tổng hợp (điểm từng buổi, chênh lệch,
// cờ "Cần chú ý", ngày hoạt động); nội dung CV, câu trả lời phỏng vấn và chi tiết phân tích cần SV bật chia sẻ.

export interface AdvisorContact {
  id: string
  full_name: string
  /** Ví dụ "Cố vấn hướng nghiệp" */
  title: string
  email: string
  office: string | null
  /** Ví dụ "Thứ 3 & Thứ 5 (14:00 – 16:30)" */
  office_hours: string | null
  avatar_url: string | null
}

export type SharedItemKind = "cv" | "interview_report"

/** Một tài liệu SV có thể bật/tắt chia sẻ. */
export interface SharedItem {
  /** id của phiên bản CV hoặc buổi phỏng vấn. */
  id: string
  kind: SharedItemKind
  title: string
  /** CV: "Phiên bản v2.0"; báo cáo: tên công ty. */
  subtitle: string | null
  /** "primary": CV đang dùng; "draft": bản nháp. */
  tag: "primary" | "draft" | null
  created_at: ISODateString
  /** CV: độ khớp JD gần nhất (0–100); báo cáo phỏng vấn: điểm STAR (0–5). */
  score: number | null
  shared: boolean
  /** Lần gần nhất cố vấn mở tài liệu; null nếu chưa xem. */
  advisor_viewed_at: ISODateString | null
  has_advisor_comment: boolean
}

/** Nhận xét của cố vấn cho một báo cáo phỏng vấn của SV. */
export interface AdvisorFeedback {
  id: string
  advisor_name: string
  comment: string
  /** Lần cập nhật gần nhất của nhận xét. */
  created_at: ISODateString
  read: boolean
  target: { kind: "interview_report"; id: string; label: string }
}

export interface SharingOverview {
  /** null khi SV chưa được phân công cố vấn. */
  advisor: AdvisorContact | null
  items: SharedItem[]
  feedback: AdvisorFeedback[]
}

export interface UpdateSharingRequest {
  item_ids: string[]
  shared: boolean
}

// ---------- Cài đặt & Quyền riêng tư ----------

export interface StudentSettings {
  full_name: string
  /** Email đăng nhập (email cá nhân, không cần email trường). */
  email: string
  phone: string | null
  /** YYYY-MM-DD */
  date_of_birth: string | null
  /** Lần đổi mật khẩu gần nhất; null nếu chưa đổi kể từ khi tạo tài khoản. */
  password_updated_at: ISODateString | null
  /** Thời điểm SV đồng ý điều khoản xử lý dữ liệu & cam kết liêm chính; null nếu đã rút lại. */
  consent_accepted_at: ISODateString | null
  storage: { used_bytes: number; limit_bytes: number; allocated_by: string }
  privacy: {
    /** Đóng góp dữ liệu đã ẩn danh để cải thiện chất lượng gợi ý. */
    anonymous_contribution: boolean
  }
  notifications: {
    advisor_comment: boolean
    report_ready: boolean
    weekly_reminder: boolean
    /** Gửi thêm qua email, ngoài chuông thông báo trong hệ thống. */
    email: boolean
  }
}

export interface ChangePasswordRequest {
  current_password: string
  new_password: string
}

// ---------- Tài khoản: đăng ký, đăng nhập, quên mật khẩu ----------
// Chỉ sinh viên tự đăng ký; tài khoản cố vấn do CareerV cấp. Email là email cá nhân (không cần email trường).

export interface LoginRequest {
  email: string
  password: string
}

export interface LoginResponse {
  role: Role
  profile: UserProfile
  /** true: đăng nhập bằng mật khẩu tạm, chuyển sang trang Đặt mật khẩu mới. */
  must_change_password?: boolean
}

export interface RegisterRequest {
  full_name: string
  /** YYYY-MM-DD */
  date_of_birth: string
  phone: string
  email: string
  password: string
  /** Đồng ý xử lý dữ liệu và cam kết liêm chính (cả hai bắt buộc). */
  consent: true
  integrity_pledge: true
}

export interface PasswordResetRequest {
  email: string
}

export interface PasswordResetConfirmRequest {
  token: string
  new_password: string
}

export interface ChangePasswordResponse {
  password_updated_at: ISODateString
}

/** Sửa hồ sơ cá nhân; trường không gửi thì giữ nguyên. Email dùng đăng nhập nên không đổi ở đây. */
export interface UpdateProfileRequest {
  full_name?: string
  phone?: string
  /** YYYY-MM-DD */
  date_of_birth?: string
}

export interface UpdateSettingsRequest {
  privacy?: Partial<StudentSettings["privacy"]>
  notifications?: Partial<StudentSettings["notifications"]>
}

// ---------- Cố vấn (US-ADV-01..03) ----------
// Phân quyền: mọi endpoint /advisor/* chỉ trả dữ liệu SV thuộc danh sách phụ trách (403 "forbidden" nếu không).
// Số liệu luôn xem được; nội dung (CV, báo cáo phỏng vấn, chi tiết kỹ năng) cần SV bật chia sẻ (403 "not_shared").
// Điểm STAR 0–5 chỉ so sánh trong cùng vị trí: chênh lệch và cờ tính trên vị trí của buổi gần nhất.

/** Tiến bộ ở vị trí đang luyện: ≥ +0,3 tiến bộ, ≤ −0,3 giảm (PRD mục 5.1); < 2 buổi là chưa đủ dữ liệu. */
export type StudentTrend = "improving" | "stable" | "declining" | "insufficient"

/** Cờ "Cần chú ý": 2 vòng liên tiếp không tăng điểm (US-ADV-02 AC1). */
export interface StudentFlag {
  jd: InterviewJdRef
  /** Số thứ tự các buổi liên quan trong vị trí, ví dụ [2, 3, 4]. */
  rounds: number[]
  scores: number[]
  flagged_at: ISODateString
}

export interface AssignedStudent {
  id: string
  full_name: string
  /** Dòng phụ dưới tên (hiện là email). */
  subtitle: string
  email: string
  phone?: string | null
  avatar_url: string | null
  /** Vị trí của buổi phỏng vấn gần nhất (hoặc lượt phân tích gần nhất). */
  target: InterviewJdRef | null
  interview_count: number
  /** Số buổi ở vị trí đang luyện. */
  focus_session_count: number
  first_score: number | null
  latest_score: number | null
  /** null khi vị trí đang luyện mới có < 2 buổi → "Chưa đủ dữ liệu" (US-ADV-01 AC2). */
  score_delta: number | null
  trend: StudentTrend
  flag: StudentFlag | null
  /** Độ khớp CV–JD (0–100) của lượt phân tích gần nhất. */
  latest_match: number | null
  /** Kỹ năng bắt buộc còn thiếu; rỗng khi SV chưa chia sẻ CV của lượt phân tích đó. */
  missing_required: string[]
  last_active_at: ISODateString | null
  shared_items: number
  total_items: number
  /** Báo cáo SV đã chia sẻ mà bạn chưa nhận xét. */
  pending_reviews: number
}

/** Dòng mở rộng ở danh sách SV phụ trách (chỉ số liệu). */
export interface AdvisorStudentProgress {
  interview_progress: InterviewProgress[]
  cv_progress: CvProgress[]
  star: StarSummary | null
  /** Câu nhận xét ghép từ tiêu chí yếu nhất (theo quy tắc, không gọi AI). */
  insight: string | null
  /** Gợi ý cho buổi tư vấn tới, sinh từ tình trạng của SV. */
  suggestions: string[]
}

export interface AdvisorCv extends CvVersion {
  /** Mở được nội dung / file khi SV đã chia sẻ. */
  shared: boolean
}

/** Kết quả phân tích gần nhất (US-ADV-03 AC1); danh sách kỹ năng rỗng khi SV chưa chia sẻ CV của lần đó. */
export interface AdvisorGap {
  analysis_id: string
  created_at: ISODateString
  cv_version_id: string
  cv_label: string
  jd: InterviewJdRef
  match_score: number | null
  match_label: MatchLabel | null
  shared: boolean
  matched: string[]
  partial: string[]
  missing: string[]
}

/** Nhận xét của bạn cho một báo cáo SV đã chia sẻ. Không thay đổi điểm AI. */
export interface AdvisorReviewInfo {
  id: string
  comment: string
  created_at: ISODateString
  updated_at: ISODateString
  /** Lúc SV xem bản nhận xét hiện tại; null nếu chưa xem. */
  seen_at: ISODateString | null
}

export interface AdvisorInterviewRow extends InterviewRow {
  shared: boolean
  /** Ví dụ "3,4/5 (Khá) · Mạnh nhất: Bối cảnh 4 · Yếu nhất: Kết quả 2,6 · 1 câu hết giờ". */
  summary: string
  review: AdvisorReviewInfo | null
}

export type AdvisorNoteTag = "behavior" | "soft_skill" | "technical" | "watch"

/** Ghi chú nội bộ: chỉ cố vấn viết ra mới thấy, SV không bao giờ thấy. */
export interface AdvisorNote {
  id: string
  body: string
  tags: AdvisorNoteTag[]
  pinned: boolean
  created_at: ISODateString
  updated_at: ISODateString
}

export interface AdvisorNoteRequest {
  body: string
  tags: AdvisorNoteTag[]
}

export interface AdvisorNoteUpdate {
  body?: string
  tags?: AdvisorNoteTag[]
  pinned?: boolean
}

export interface AdvisorStudentDetail extends AdvisorStudentProgress {
  student: AssignedStudent
  /** Mọi phiên bản CV, mới nhất trước (US-ADV-03 AC2). */
  cvs: AdvisorCv[]
  /** null → "SV chưa chọn vị trí ứng tuyển" (US-ADV-03 AC3). */
  target_jd: JobDescription | null
  latest_gap: AdvisorGap | null
  /** Mới nhất trước. */
  interviews: AdvisorInterviewRow[]
  notes: AdvisorNote[]
}

/** Báo cáo đầy đủ của buổi SV đã chia sẻ, kèm nhận xét của bạn. */
export type AdvisorInterviewReport = Omit<InterviewReport, "advisor_review"> & { review: AdvisorReviewInfo | null }

export interface ReviewInterviewRequest {
  comment: string
}

/** Trạng thái như nhãn ở danh sách SV: cờ "Cần chú ý" trước, sau đó là xu hướng điểm. */
export type StudentStatus = "flagged" | StudentTrend

export interface WeeklyScore {
  /** Thứ Hai 00:00 giờ Việt Nam. */
  week_start: ISODateString
  /** TB điểm buổi gần nhất của mỗi SV tính đến cuối tuần, thang 0–5. */
  average: number
  student_count: number
}

/** S/T/A/R trung bình của nhóm (mỗi SV lấy TB tối đa 5 buổi gần nhất). */
export interface CohortStar {
  average: StarScores
  weakest: StarCriterion
  /** Số SV có tiêu chí yếu nhất trùng với tiêu chí yếu nhất của nhóm. */
  weakest_count: number
  student_count: number
}

export interface RecentReview extends AdvisorReviewInfo {
  student_id: string
  student_name: string
  avatar_url: string | null
  session_id: string
  jd: InterviewJdRef
}

/** Buổi SV đã chia sẻ mà cố vấn chưa nhận xét (nút "Nhận xét" mở thẳng đúng buổi). */
export interface PendingReviewSession {
  session_id: string
  student_id: string
  student_name: string
  avatar_url: string | null
  jd: InterviewJdRef
  completed_at: ISODateString
  overall_score: number | null
}

/** Tổng quan cả nhóm SV phụ trách (chỉ số liệu tổng hợp). Mục tiêu theo PRD mục 9. */
export interface AdvisorOverview {
  advisor_name: string
  student_count: number
  /** Số SV đang chia sẻ ít nhất một tài liệu. */
  sharing_count: number
  pending_reviews: number
  /** Số SV có lượt phân tích / buổi phỏng vấn hoàn thành trong active_days ngày. */
  active_count: number
  active_days: number
  /** Mục tiêu tỷ lệ SV hoạt động (%). */
  active_target: number
  /** TB điểm buổi gần nhất của các SV đã phỏng vấn. */
  average_score: number | null
  scored_count: number
  /** TB chênh lệch (gần nhất − buổi đầu) ở vị trí đang luyện của từng SV có ≥ 2 buổi. */
  average_delta: number | null
  delta_count: number
  weekly_scores: WeeklyScore[]
  status_counts: Record<StudentStatus, number>
  star: CohortStar | null
  /** Câu nhận xét ghép theo quy tắc từ tiêu chí yếu nhất của nhóm. */
  insight: string | null
  flagged_students: AssignedStudent[]
  /** Tối đa 5 SV có chênh lệch dương lớn nhất. */
  top_improvers: AssignedStudent[]
  /** Tối đa 5 nhận xét bạn gửi gần đây, bản mới nhất trước. */
  recent_reviews: RecentReview[]
  /** Buổi chờ nhận xét, chờ lâu nhất trước (tối đa 10). */
  pending_sessions: PendingReviewSession[]
}

// ---------- Tin nhắn SV ↔ cố vấn phụ trách ----------
// Hội thoại xác định bằng mã SV. Chỉ SV và cố vấn đang phụ trách SV đó đọc / gửi được (403 "forbidden");
// SV chưa được phân công cố vấn: 404 "no_advisor".

/** Người ở phía bên kia hội thoại. */
export interface ChatParticipant {
  id: string
  full_name: string
  role: Role
  /** SV: email; cố vấn: chức danh. */
  subtitle: string
  avatar_url: string | null
  /** Giờ tư vấn (chỉ với cố vấn). */
  office_hours: string | null
}

export interface ChatMessage {
  id: string
  body: string
  created_at: ISODateString
  /** Tin do người đang xem gửi. */
  mine: boolean
  /** Lúc người nhận đọc; null nếu chưa đọc. */
  read_at: ISODateString | null
}

export interface ConversationSummary {
  /** Mã hội thoại (mã SV). */
  student_id: string
  counterpart: ChatParticipant
  last_message: ChatMessage | null
  unread_count: number
}

export interface Conversation {
  student_id: string
  counterpart: ChatParticipant
  /** Tối đa 200 tin gần nhất, cũ → mới. */
  messages: ChatMessage[]
}

// ---------- Thông báo (chuông trên topbar) ----------

export type NotificationKind =
  | "advisor_comment"
  | "interview_report"
  | "gap_analysis"
  | "integrity_alert"
  | "student_activity"
  | "student_inactive"
  /** SV: có cố vấn mới; cố vấn: được phân công thêm SV. */
  | "advisor_assigned"
  /** Quản trị viên: SV mới tạo tài khoản, đang chờ phân công. */
  | "student_registered"

export interface AppNotification {
  id: string
  kind: NotificationKind
  title: string
  body: string
  created_at: ISODateString
  read: boolean
  /** Nút hành động (ví dụ "Xem báo cáo") dẫn tới trang liên quan. */
  action_label: string | null
  action_href: string | null
}

// ---------- Lỗi ----------

export interface ApiErrorBody {
  detail: string
  code?: string
}

// ---------- Quản trị (thống kê, tài khoản cố vấn, phân công SV) ----------

export type AdminPeriod = 7 | 30 | 90

export interface AdminStats {
  days: AdminPeriod
  users: {
    student_count: number
    /** SV tạo tài khoản trong 7 ngày qua. */
    new_students_week: number
    /** Tổng số SV ở cuối mỗi tuần (7 tuần, cũ → mới). */
    student_series: number[]
    /** SV có lượt phân tích / buổi phỏng vấn hoàn thành trong kỳ. */
    active_count: number
    active_series: number[]
    /** Cố vấn đang hoạt động (không tính tài khoản tạm khoá). */
    advisor_count: number
    assigned_count: number
    unassigned_count: number
  }
  usage: {
    weekly: { week_start: string; analyses: number; interviews: number }[]
    analyses: number
    /** % thay đổi so với kỳ trước; null khi kỳ trước chưa có lượt nào. */
    analyses_change: number | null
    interviews: number
    interviews_change: number | null
    /** Phiên bản CV tạo từ Trình tối ưu trong kỳ. */
    optimized_cvs: number
  }
  satisfaction: {
    csat: number | null
    count: number
    target: number
    /** Số lượt theo số sao, khoá "1"…"5". */
    distribution: Record<"1" | "2" | "3" | "4" | "5", number>
    /** Số lượt chấm 1–3 sao trong kỳ. */
    low_count: number
    /** Lý do chưa hài lòng, nhiều nhất trước (tối đa 5). */
    reasons: { reason: string; label: string; activities: CsatActivity[]; count: number }[]
    /** Like / dislike theo từng phần. */
    helpful: { activity: ThumbActivity; label: string; likes: number; total: number }[]
  }
  /** Nhận xét kèm đánh giá CSAT, không có tên SV. */
  recent_comments: AdminComment[]
}

export interface AdminComment {
  id: string
  /** Số sao 1–5. */
  value: number
  activity: CsatActivity | null
  /** null khi sinh viên chỉ chọn lý do, không viết chữ. */
  comment: string | null
  tags: { reason: string; label: string }[]
  created_at: ISODateString
}

export interface AdminCommentsQuery {
  /** Bỏ trống = mọi lúc. */
  days?: AdminPeriod
  stars?: 1 | 2 | 3 | 4 | 5
  activity?: CsatActivity
  /** Mã lý do, ví dụ "off_target". */
  reason?: string
  offset?: number
  limit?: number
}

export interface AdminCommentsPage {
  total: number
  items: AdminComment[]
}

export type AdvisorAccountStatus = "active" | "password_pending" | "disabled"

export interface AdminAdvisor {
  id: string
  full_name: string
  email: string
  title: string
  avatar_url: string | null
  student_count: number
  /** Buổi SV đã chia sẻ mà cố vấn chưa nhận xét. */
  pending_reviews: number
  status: AdvisorAccountStatus
  last_active_at: ISODateString | null
  created_at: ISODateString
}

export interface CreateAdvisorRequest {
  full_name: string
  email: string
  title: string
  temporary_password: string
}

export interface UpdateAdvisorRequest {
  full_name?: string
  email?: string
  title?: string
  /** true = tạm khoá, false = mở khoá. */
  disabled?: boolean
}

export interface AdminStudent {
  id: string
  full_name: string
  email: string
  phone: string | null
  avatar_url: string | null
  /** null = chưa phân công. */
  advisor: { id: string; full_name: string; disabled: boolean } | null
  created_at: ISODateString
  last_active_at: ISODateString | null
}

export interface AssignAdvisorResponse {
  assigned: number
  unchanged: number
}

// ---------- Quản trị: thư viện JD ----------

export interface AdminJdRow {
  id: string
  title: string
  company: string | null
  industry: string | null
  level: JobLevel | null
  skills: JdSkill[]
  status: "published" | "hidden"
  /** Lượt phân tích CV + buổi phỏng vấn hoàn thành trong 30 ngày. */
  usage_30d: number
  updated_at: ISODateString
}

/** JD sinh viên tự dán, gộp theo vị trí – công ty (không kèm tên sinh viên). */
export interface AdminUploadedJd {
  sample_jd_id: string
  title: string
  company: string | null
  level: JobLevel | null
  skills: JdSkill[]
  student_count: number
  last_added_at: ISODateString
  /** JD thư viện tương ứng nếu đã có. */
  library_jd_id: string | null
}

export interface AdminJdDetail extends JobDescription {
  status?: string | null
  source_jd_id?: string | null
  updated_at?: ISODateString | null
}

export interface AdminJdUpsert extends JdFields {
  skills?: JdSkill[]
  /** Toàn văn đã dán (không có thì backend dựng từ các mục). */
  text?: string | null
  source_jd_id?: string | null
  status?: "published" | "hidden"
}
