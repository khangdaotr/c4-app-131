// Cài đặt mock cho từng hàm trong lib/api.ts. Trả về cùng kiểu với API thật.

import {
  mockAdvisor,
  mockAdvisorNotifications,
  mockStudentNotifications,
  mockCvVersions,
  mockGapAnalysis,
  mockInterviewQuestionBank,
  mockInterviewReport,
  mockJdLibrary,
  mockRecentInterviews,
  mockStarGuidance,
  mockStudent,
} from "@/lib/mocks/data"
import {
  buildCohort,
  detailOf,
  overviewOf,
  progressOf,
  summarize,
  syntheticReport,
  type StudentSource,
} from "@/lib/mocks/advisor"
import * as adminMock from "@/lib/mocks/admin"
import { MAX_MESSAGE_CHARS, seedThreads, toChatMessage, unreadFor, type StoredMessage } from "@/lib/mocks/chat"
import { mockCvDocument, mockSuggestions } from "@/lib/mocks/optimizer"
import { draftDocument } from "@/lib/cv-document"
import { mockAnalysisSeeds, mockInterviewRows } from "@/lib/mocks/progress"
import { buildOverview, buildProgress } from "@/lib/mocks/student-progress"
import { mockAdvisorContact, mockInitialReviews, mockInitialShared, mockSettings } from "@/lib/mocks/sharing"
import { adviceFor, recommendFromProfile, skillProfileOf } from "@/lib/mocks/library"
import { compareFromProfile } from "@/lib/mocks/compare"
import * as jdMock from "@/lib/mocks/jds"
import type {
  AdminJdDetail,
  AdminJdRow,
  AdminJdUpsert,
  AdminUploadedJd,
  JdDraft,
  JdFields,
  AdminCommentsPage,
  AdminCommentsQuery,
  AdminPeriod,
  AdminStats,
  AdminAdvisor,
  AdminStudent,
  AssignAdvisorResponse,
  CreateAdvisorRequest,
  UpdateAdvisorRequest,
  UserProfile,
  AdvisorFeedback,
  AdvisorInterviewReport,
  AdvisorNote,
  AdvisorNoteRequest,
  AdvisorNoteUpdate,
  AdvisorOverview,
  AdvisorReviewInfo,
  AdvisorStudentDetail,
  AdvisorStudentProgress,
  AnalysisRow,
  AnalysisStep,
  AppNotification,
  AssignedStudent,
  CapabilityAnswerRequest,
  CvEntry,
  CapabilityLineDecisionRequest,
  CapabilityDraftRequest,
  CapabilityCheck,
  ChangePasswordRequest,
  UpdateProfileRequest,
  LoginRequest,
  LoginResponse,
  PasswordResetConfirmRequest,
  PasswordResetRequest,
  RegisterRequest,
  ChangePasswordResponse,
  ChatMessage,
  ChatParticipant,
  CompareJdsRequest,
  CompareJdsResponse,
  Conversation,
  ConversationSummary,
  CreateGapAnalysisRequest,
  CreateInterviewRequest,
  CreatePastedJdRequest,
  CvDocument,
  CvVersion,
  ExportCvRequest,
  ExportCvResponse,
  FeedbackRequest,
  FeedbackResponse,
  FeedbackStatus,
  GapAnalysis,
  InterviewQuestion,
  InterviewQuota,
  InterviewReport,
  InterviewRow,
  InterviewSession,
  InterviewSummary,
  InterviewTurn,
  JobDescription,
  OptimizerSession,
  ProgressRange,
  RecommendJdsRequest,
  RecommendJdsResponse,
  ReviewInterviewRequest,
  Role,
  SavedJd,
  SharedItem,
  SharingOverview,
  StarCriterion,
  StarScores,
  StudentOverview,
  StudentProgress,
  StudentSettings,
  SubmitAnswerRequest,
  SubmitAnswerResponse,
  Suggestion,
  SuggestionDecisionRequest,
  UpdateSettingsRequest,
  UpdateSharingRequest,
} from "@/lib/types"
import { COMPARE_MAX_JDS, COMPARE_MIN_JDS, JD_MIN_WORDS } from "@/lib/types"
import { ApiError } from "@/lib/api-error"
import { MOCK_SCENARIO } from "@/lib/config"
import { roadmapUrlOf, withRoadmap } from "@/lib/mocks/roadmap"

const delay = (ms = 400) => new Promise((resolve) => setTimeout(resolve, ms))
const clone = <T>(value: T): T => structuredClone(value)

const MAX_UPLOAD_BYTES = 5 * 1024 * 1024
const isNewStudent = MOCK_SCENARIO !== "sample"
const submittedFeedback = new Map<string, number>()
let cvVersions = isNewStudent ? [] : clone(mockCvVersions)
// Vị trí đã lưu ("Đã lưu" ở Thư viện JD); backend chưa có endpoint nên chỉ sống trong phiên mock.
let savedJds: SavedJd[] = isNewStudent
  ? []
  : [
      { jd_id: "jd-mkt-analyst", saved_at: new Date(Date.now() - 2 * 86_400_000).toISOString() },
      { jd_id: "jd-fe-junior", saved_at: new Date(Date.now() - 5 * 86_400_000).toISOString() },
    ]
// JD SV tự dán (backend lưu lại theo chủ sở hữu, GET /jd trả về cùng thư viện). Mất khi tải lại trang.
const findJd = (id: string) => mockJdLibrary.find((j) => j.id === id) ?? jdMock.findPasted(id)
const countJdWords = (text: string) => text.split(/\s+/).filter(Boolean).length

// ---- Phiên bản CV theo từng CV (mô phỏng src/services/cv_versions.py) ----
// cvVersions giữ mọi phiên bản của mọi CV; các phiên bản cùng family_id là một CV.

/** Các CV, mỗi CV là danh sách phiên bản mới nhất trước; CV vừa có bản mới đứng trước. */
function cvFamilies(): CvVersion[][] {
  const groups = new Map<string, CvVersion[]>()
  for (const cv of [...cvVersions].sort((a, b) => b.version - a.version)) {
    groups.set(cv.family_id, [...(groups.get(cv.family_id) ?? []), cv])
  }
  return [...groups.values()]
}

/** Các phiên bản của CV chứa phiên bản id (nhận cả mã CV), mới nhất trước. */
function cvFamilyOf(id: string): CvVersion[] {
  const cv = cvVersions.find((c) => c.id === id || c.family_id === id)
  if (!cv) throw new ApiError(404, "Không tìm thấy phiên bản CV.", "cv_not_found")
  return cvVersions.filter((c) => c.family_id === cv.family_id).sort((a, b) => b.version - a.version)
}

/** Thẻ CV: bản mới nhất kèm số phiên bản; vị trí lấy từ bản gần nhất đã phân tích nếu bản mới nhất chưa phân tích. */
function cvCard(versions: CvVersion[]): CvVersion {
  const target = versions.find((v) => v.target_title)?.target_title ?? null
  return { ...versions[0], version_count: versions.length, target_title: versions[0].target_title ?? target }
}

/** Nội dung CV mẫu dạng văn bản (bản demo không có file CV thật). */
function sampleCvText(fullName: string): string {
  const doc = mockCvDocument
  return [
    fullName,
    ...doc.header.slice(1).map((l) => l.text),
    ...doc.sections.flatMap((sec) => [sec.title, ...sec.lines.map((l) => `- ${l.text}`)]),
  ].join("\n")
}

const nextCvSequence = () => Math.max(0, ...cvVersions.map((c) => c.version)) + 1

/**
 * Thêm bản mới vào CV chứa baseId: số phụ +1 (tối ưu) hoặc số chính +1, về .0 (khôi phục).
 * CV đang dùng thì bản mới tự thành bản đang dùng. Trả về đúng đối tượng đã thêm (sửa tiếp được, ví dụ tên file).
 */
function appendCvVersion(
  baseId: string,
  fields: Omit<CvVersion, "id" | "version" | "label" | "family_id" | "version_count" | "is_active">,
  newMajor: boolean,
): CvVersion {
  const family = cvFamilyOf(baseId)
  const [, major, minor] = /v(\d+)\.(\d+)/.exec(family[0].label)!.map(Number)
  const version = nextCvSequence()
  const active = family.some((v) => v.is_active)
  if (active) cvVersions = cvVersions.map((c) => ({ ...c, is_active: false }))
  const created: CvVersion = {
    ...fields,
    id: `cv-v${version}`,
    version,
    label: newMajor ? `v${major + 1}.0` : `v${major}.${minor + 1}`,
    family_id: family[0].family_id,
    version_count: family.length + 1,
    is_active: active,
  }
  cvVersions.unshift(created)
  return created
}
const notifications: Record<Role, AppNotification[]> = {
  student: isNewStudent ? [] : clone(mockStudentNotifications),
  // Thông báo đầu tiên nói về buổi của Minh Anh: chỉ có khi Minh Anh có dữ liệu mẫu
  advisor: clone(isNewStudent ? mockAdvisorNotifications.slice(1) : mockAdvisorNotifications),
  admin: [
    {
      id: "n-q1",
      kind: "student_registered",
      title: "Hoàng Minh Thu vừa tạo tài khoản",
      body: "Sinh viên mới đang chờ phân công cố vấn.",
      created_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
      read: false,
      action_label: "Phân công",
      action_href: "/admin/students?filter=unassigned",
    },
  ],
}

// ---- Trình tối ưu CV (lưu trong bộ nhớ, mô phỏng src/services/cv_optimizer.py) ----

interface MockOptimization {
  status: OptimizerSession["status"]
  /** Quyết định hiện tại theo mã gợi ý (bản nháp). */
  decisions: Record<string, { action: "accept" | "edit" | "reject"; final_text: string }>
  /** Trả lời kiểm tra kỹ năng thiếu theo mã yêu cầu JD. */
  answers: Record<
    string,
    {
      has_experience: boolean
      context: string | null
      learning_note: string | null
      entry_id?: string
      draft_text?: string
      decision?: "accept" | "edit" | "reject"
      final_text?: string | null
    }
  >
  /** US-SV-03 AC2 (chỉ có ở mock): ngữ cảnh SV bổ sung theo mã gợi ý. */
  contexts: Record<string, string>
  result_cv_id: string | null
  result_document: CvDocument | null
  finalized_at: string | null
}
const optimizations: Record<string, MockOptimization> = {}
const MAX_EDIT_CHARS = 600
const reports: Record<string, InterviewReport> = {}
/** Các buổi đã hoàn thành trước phiên mock (thang 0–5); rỗng ở kịch bản SV mới hoặc sau khi xoá toàn bộ dữ liệu. */
let seededInterviews: InterviewRow[] = isNewStudent ? [] : clone(mockInterviewRows)

// ---- Phỏng vấn thử: mô phỏng quy tắc của backend (src/services/interview.py) ----

const QUESTION_COUNT = 4
const QUESTION_SECONDS = 300
const PAUSE_MAX_SECONDS = 60
/** Quá hạn chót câu hiện tại ngần này mà không nộp → coi như SV đã rời phòng, buổi bị huỷ. */
const ABANDON_AFTER_SECONDS = 120
const MIN_ANSWER_CHARS = 30
const WEEKLY_LIMIT = 3
const BLOCKED_REASON = "Mình chỉ hỗ trợ nội dung liên quan buổi phỏng vấn. Bạn hãy thử trả lời lại nhé."
const CRITERIA: StarCriterion[] = ["situation", "task", "action", "result"]
const GUIDANCE = mockStarGuidance

interface MockInterview {
  session: InterviewSession
  /** Hạn chót câu hiện tại (ms). */
  deadline: number
  pausedAt: number | null
}
const interviews: Record<string, MockInterview> = {}

const round2 = (n: number) => Math.round(n * 100) / 100

function mockQuestion(index: number, role: string): InterviewQuestion {
  const { theme, template } = mockInterviewQuestionBank[index - 1]
  return { index, theme, text: template.replace("{role}", role) }
}

function resumeMock(iv: MockInterview, now: number) {
  if (iv.pausedAt === null) return
  iv.deadline += Math.min(now - iv.pausedAt, PAUSE_MAX_SECONDS * 1000)
  iv.pausedAt = null
}

// ---- Lịch sử so sánh vị trí: kịch bản mẫu có sẵn 3 lượt, tính lúc cần (JD và CV mẫu đã sẵn sàng) ----

let compareHistory: CompareJdsResponse[] | null = null

function compareHistoryRows(): CompareJdsResponse[] {
  if (compareHistory) return compareHistory
  const cv = cvVersions.find((c) => c.id === "cv-v3")
  const seeds: [string[], number][] = [
    [["jd-da-intern", "jd-ba-intern", "jd-po-assistant"], 2],
    [["jd-ba-intern", "jd-po-assistant"], 8],
    [["jd-fe-junior", "jd-be-intern"], 23],
  ]
  compareHistory =
    isNewStudent || !cv
      ? []
      : seeds.map(([ids, daysAgo], i) => ({
          ...compareFromProfile(ids.map((id) => findJd(id)!), cv.family_id, cv),
          id: `cmp-mau-${i + 1}`,
          created_at: new Date(Date.now() - daysAgo * 86_400_000).toISOString(),
        }))
  return compareHistory
}

/** Trạng thái trả về: tính giây còn lại, tự chạy lại khi đã tạm dừng đủ 1 phút. */
function interviewView(iv: MockInterview): InterviewSession {
  const now = Date.now()
  if (iv.pausedAt !== null && now - iv.pausedAt >= PAUSE_MAX_SECONDS * 1000) resumeMock(iv, now)
  const active = iv.session.status === "in_progress"
  const reference = iv.pausedAt ?? now
  return clone({
    ...iv.session,
    seconds_left: active ? Math.max(0, Math.round((iv.deadline - reference) / 1000)) : null,
    paused: iv.pausedAt !== null,
    pause_seconds_left: iv.pausedAt !== null ? Math.max(0, PAUSE_MAX_SECONDS - Math.round((now - iv.pausedAt) / 1000)) : null,
    // Demo sessions also support on-device PhoWhisper; the client checks model/device readiness.
    voice_input: true,
  })
}

/** Chấm STAR 0–5 theo từ khoá (thay cho LLM ở chế độ mock). */
function mockStar(text: string): StarScores {
  const t = text.toLowerCase()
  const words = text.split(/\s+/).filter(Boolean).length
  const base = words > 60 ? 3 : words > 30 ? 2.5 : 2
  const has = (re: RegExp) => re.test(t)
  return {
    situation: Math.min(5, base + (has(/dự án|bối cảnh|khi |lúc|công ty|môn học|đồ án/) ? 1 : 0)),
    task: Math.min(5, base + (has(/nhiệm vụ|phụ trách|vai trò|mục tiêu/) ? 1 : 0)),
    action: Math.min(5, base + (has(/em đã|tôi đã|sử dụng|xây dựng|phân tích|đề xuất|tổ chức/) ? 1 : 0)),
    result: Math.min(5, base - 0.5 + (has(/\d+\s*%|\d+ (giờ|ngày|người|buổi)|kết quả|giúp|đúng hạn/) ? 1.5 : 0)),
  }
}

/** Đầu tuần (thứ Hai 00:00 theo giờ máy) để tính hạn mức. */
function weekStart(): number {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7))
  return d.getTime()
}

function interviewQuota(jdId: string): InterviewQuota {
  const start = weekStart()
  const used = completedInterviews().filter((r) => r.jd.id === jdId && new Date(r.completed_at).getTime() >= start).length
  return {
    jd_id: jdId,
    used,
    limit: WEEKLY_LIMIT,
    remaining: Math.max(0, WEEKLY_LIMIT - used),
    resets_at: new Date(start + 7 * 86_400_000).toISOString(),
  }
}

function completeInterview(iv: MockInterview): InterviewReport {
  const turns = iv.session.turns
  const average = (c: StarCriterion) => round2(turns.reduce((sum, t) => sum + (t.star?.[c] ?? 0), 0) / turns.length)
  const star: StarScores = {
    situation: average("situation"),
    task: average("task"),
    action: average("action"),
    result: average("result"),
  }
  const overall = round2(turns.reduce((sum, t) => sum + (t.score ?? 0), 0) / turns.length)
  const ranked = [...CRITERIA].sort((a, b) => star[a] - star[b])
  const timedOut = turns.filter((t) => t.timed_out).length
  const first = completedInterviews()
    .filter((r) => r.jd.id === iv.session.jd.id)
    .at(-1)
  const completedAt = new Date().toISOString()
  iv.session.status = "completed"
  iv.session.current_question = null
  const report: InterviewReport = {
    id: iv.session.id,
    response_id: iv.session.id,
    jd: iv.session.jd,
    cv_file_name: iv.session.cv_file_name,
    created_at: iv.session.created_at,
    completed_at: completedAt,
    duration_seconds: Math.round((Date.now() - new Date(iv.session.created_at).getTime()) / 1000),
    overall_score: overall,
    label: overall >= 4 ? "good" : overall >= 3 ? "fair" : overall >= 2 ? "basic" : "weak",
    star,
    weakest: ranked[0],
    turns: clone(turns),
    timed_out_count: timedOut,
    guidance: [
      GUIDANCE[ranked[0]],
      GUIDANCE[ranked[1]],
      ...(timedOut ? [`Bạn có ${timedOut} câu hết giờ. Hãy luyện trả lời gọn theo 4 ý S – T – A – R trong khoảng 3–4 phút.`] : []),
    ],
    comparison: first
      ? {
          first_session_id: first.id,
          first_score: first.overall_score,
          first_completed_at: first.completed_at,
          delta: round2(overall - first.overall_score),
        }
      : null,
    advisor_review: null,
  }
  reports[iv.session.id] = report
  return report
}

const analyses: Record<string, GapAnalysis> = Object.fromEntries(
  (isNewStudent ? [] : [clone(mockGapAnalysis), ...mockAnalysisSeeds.map(seededAnalysis)]).map((a) => [a.id, a]),
)
/** Thời điểm tạo từng lượt phân tích mock, dùng để mô phỏng tiến độ theo các bước của pipeline thật. */
const analysisStartedAt: Record<string, number> = {}
const ANALYSIS_STEPS: AnalysisStep[] = ["parse", "retrieve", "compare", "generate", "verify_grounding"]
const MOCK_STEP_MS = 1200

function withProgress(analysis: GapAnalysis): GapAnalysis {
  const started = analysisStartedAt[analysis.id]
  const index = started === undefined ? ANALYSIS_STEPS.length : Math.floor((Date.now() - started) / MOCK_STEP_MS)
  // Như backend: mỗi yêu cầu kèm lộ trình roadmap.sh (lib/mocks/roadmap.ts)
  const view = { ...clone(analysis), requirements: analysis.requirements.map(withRoadmap) }
  if (index >= ANALYSIS_STEPS.length) return view
  return { ...view, status: "processing", current_step: ANALYSIS_STEPS[index], completed_at: null }
}



// ---- Tổng quan & Lịch sử (thang 0–5), tổng hợp bằng lib/mocks/student-progress.ts ----

function matchLabelOf(score: number | null): AnalysisRow["match_label"] {
  if (score === null) return null
  return score >= 75 ? "high" : score >= 50 ? "medium" : "low"
}

/** Lượt phân tích mẫu từ mockAnalysisSeeds; nội dung kỹ năng dùng lại mockGapAnalysis. */
function seededAnalysis(seed: (typeof mockAnalysisSeeds)[number]): GapAnalysis {
  const cv = mockCvVersions.find((c) => c.id === seed.cv_version_id)!
  const jd = mockJdLibrary.find((j) => j.id === seed.jd_id)!
  const failed = seed.status === "failed"
  return {
    ...clone(mockGapAnalysis),
    id: seed.id,
    response_id: seed.id,
    status: seed.status,
    error_message: failed ? "Không phân tích được CV lúc này. Hãy thử lại sau ít phút." : null,
    cv_version_id: cv.id,
    cv_file_name: cv.file_name,
    cv_label: cv.label,
    jd: { id: jd.id, title: jd.title, company: jd.company, industry: jd.industry, level: jd.level, source: jd.source },
    created_at: seed.created_at,
    completed_at: failed ? null : new Date(new Date(seed.created_at).getTime() + 40_000).toISOString(),
    match_score: seed.match_score,
    match_label: matchLabelOf(seed.match_score),
    suggestions: failed ? [] : mockGapAnalysis.suggestions.map((sg) => ({ ...sg, id: `${seed.id}-${sg.id}` })),
    ...(failed && { requirements: [], breakdown: [], counts: { matched: 0, partial: 0, missing: 0 }, summary: null }),
  }
}

/** Buổi đã hoàn thành (buổi vừa làm trong phiên mock và buổi mẫu), mới nhất trước. */
function completedInterviews(): InterviewRow[] {
  const finished: InterviewRow[] = Object.values(reports).map((r) => ({
    id: r.id,
    jd: r.jd,
    completed_at: r.completed_at,
    duration_seconds: r.duration_seconds,
    overall_score: r.overall_score,
    label: r.label,
    star: r.star,
    timed_out_count: r.timed_out_count,
  }))
  return clone([...finished, ...seededInterviews]).sort((a, b) => b.completed_at.localeCompare(a.completed_at))
}

/** Mọi lượt phân tích (kể cả đang chạy, lỗi), mới nhất trước. */
function analysisRows(): AnalysisRow[] {
  return Object.values(analyses)
    .map(withProgress)
    .map((a) => ({
      id: a.id,
      jd: { id: a.jd.id, title: a.jd.title, company: a.jd.company, source: a.jd.source },
      cv_version_id: a.cv_version_id,
      cv_label: a.cv_label,
      cv_file_name: a.cv_file_name,
      status: a.status,
      current_step: a.current_step,
      match_score: a.status === "completed" ? a.match_score : null,
      match_label: a.status === "completed" ? matchLabelOf(a.match_score) : null,
      created_at: a.created_at,
      completed_at: a.completed_at,
    }))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
}

/** Buổi đang dở mà SV rời phòng quá lâu thì bị huỷ, giống load_session ở backend. */
function isAbandoned(iv: MockInterview, now = Date.now()): boolean {
  if (iv.pausedAt !== null && now - iv.pausedAt >= PAUSE_MAX_SECONDS * 1000) resumeMock(iv, now)
  return iv.session.status === "in_progress" && iv.pausedAt === null && now > iv.deadline + ABANDON_AFTER_SECONDS * 1000
}

/** Buổi đang dở còn quay lại phòng được; buổi đã bị bỏ quá lâu bị xoá như khi mở phòng. */
function activeInterview(): StudentOverview["in_progress"]["interview"] {
  const entry = Object.entries(interviews).find(([, iv]) => iv.session.status === "in_progress")
  if (!entry) return null
  const [id, iv] = entry
  if (isAbandoned(iv)) {
    delete interviews[id]
    return null
  }
  const view = interviewView(iv)
  return {
    id,
    jd: view.jd,
    current_index: view.current_question?.index ?? QUESTION_COUNT,
    question_count: QUESTION_COUNT,
    seconds_left: view.seconds_left,
    paused: view.paused,
  }
}

let settings: StudentSettings = { ...clone(mockSettings), consent_accepted_at: isNewStudent ? new Date().toISOString() : mockSettings.consent_accepted_at }
/** Tài liệu Minh Anh đang chia sẻ: mã → lần cố vấn xem gần nhất; không có key = riêng tư. */
const shared = new Map<string, { viewed_at: string | null }>(isNewStudent ? [] : Object.entries(clone(mockInitialShared)))
/** Nhận xét của cố vấn cho báo cáo của Minh Anh, theo mã buổi phỏng vấn. */
const advisorReviews: Record<string, AdvisorReviewInfo> = isNewStudent
  ? {}
  : Object.fromEntries(
      Object.entries(mockInitialReviews).map(([sessionId, r]) => {
        const at = new Date(Date.now() - r.days * 86_400_000).toISOString()
        const seen = r.seen ? new Date(Date.now() - r.days * 86_400_000 + 5 * 3_600_000).toISOString() : null
        return [sessionId, { id: `rv_${sessionId}`, comment: r.comment, created_at: at, updated_at: at, seen_at: seen }]
      }),
    )
/** Mật khẩu hiện tại ở chế độ mock (để thử luồng đổi mật khẩu). */
let mockPassword = "careerv123"

// ---------- Tài khoản ----------
// Tài khoản demo SV và quản trị viên (mật khẩu chung với mockPassword) và các tài khoản SV tạo mới trong phiên.
// Tài khoản cố vấn (kể cả cố vấn demo) nằm ở lib/mocks/admin.ts để quản trị viên tạo, khoá và đặt lại mật khẩu tạm.
const LOGIN_MAX_ATTEMPTS = 5
const accounts = new Map<string, { role: Role; password: () => string }>([
  ["minhanh.nguyen@gmail.com", { role: "student", password: () => mockPassword }],
  ["admin@careerv.vn", { role: "admin", password: () => mockPassword }],
])
let failedLogins = 0
/** Cố vấn đang đăng nhập ở chế độ mock (để đổi mật khẩu tạm và hiện đúng tên). */
let signedInAdvisorEmail: string | null = null

function wrongCredentials(): never {
  failedLogins += 1
  const left = LOGIN_MAX_ATTEMPTS - failedLogins
  throw new ApiError(
    401,
    left > 0
      ? `Email hoặc mật khẩu chưa đúng. Còn ${left} lần thử trước khi tạm khoá 15 phút.`
      : "Bạn đã nhập sai quá nhiều lần. Hãy thử lại sau 15 phút.",
    "invalid_credentials",
  )
}

/** Nhóm SV của cố vấn demo, dạng dùng cho trang Quản trị. */
function adminCohort(): adminMock.CohortProfile[] {
  return advisorSources().map(({ profile, sessions, analyses }) => {
    const dates = [sessions[0]?.completed_at, analyses[0]?.row.completed_at].filter((d): d is string => Boolean(d))
    return {
      id: profile.id,
      full_name: profile.full_name,
      email: profile.email,
      phone: profile.phone ?? null,
      avatar_url: profile.avatar_url,
      last_active_at: dates.sort().at(-1) ?? null,
    }
  })
}
const normalizeEmail = (email: string) => email.trim().toLowerCase()

const reviewRead = (r: AdvisorReviewInfo) => r.seen_at !== null && r.seen_at >= r.updated_at

/** Danh sách tài liệu có thể chia sẻ: mọi phiên bản CV và mọi buổi phỏng vấn đã hoàn thành. */
function sharableItems(): SharedItem[] {
  const state = (id: string) => ({ shared: shared.has(id), advisor_viewed_at: shared.get(id)?.viewed_at ?? null })
  // Mỗi CV một dòng, chia sẻ theo mã CV: cố vấn xem bản mới nhất và các bản trước
  const cvs: SharedItem[] = cvFamilies().map((versions) => {
    const cv = versions[0]
    return {
      id: cv.family_id,
      kind: "cv",
      title: cv.file_name,
      subtitle: `Phiên bản ${cv.label}${versions.length > 1 ? ` · ${versions.length} phiên bản` : ""}`,
      tag: cv.is_active ? "primary" : cv.is_draft ? "draft" : null,
      created_at: cv.uploaded_at,
      score: cv.match_score,
      ...state(cv.family_id),
      has_advisor_comment: false,
    }
  })
  const interviewItems: SharedItem[] = completedInterviews().map((iv) => ({
    id: iv.id,
    kind: "interview_report",
    title: `Phỏng vấn ${iv.jd.title}`,
    subtitle: iv.jd.company,
    tag: null,
    created_at: iv.completed_at,
    score: iv.overall_score,
    ...state(iv.id),
    has_advisor_comment: iv.id in advisorReviews,
  }))
  return [...cvs, ...interviewItems]
}

function sharingFeedback(): AdvisorFeedback[] {
  const sessions = new Map(completedInterviews().map((s) => [s.id, s]))
  return Object.entries(advisorReviews)
    .filter(([sessionId]) => sessions.has(sessionId))
    .sort(([, a], [, b]) => b.updated_at.localeCompare(a.updated_at))
    .map(([sessionId, r]) => {
      const session = sessions.get(sessionId)!
      return {
        id: r.id,
        advisor_name: mockAdvisor.full_name,
        comment: r.comment,
        created_at: r.updated_at,
        read: reviewRead(r),
        target: {
          kind: "interview_report" as const,
          id: sessionId,
          label: `Phỏng vấn ${session.jd.title} · ${new Date(session.completed_at).toLocaleDateString("vi-VN")}`,
        },
      }
    })
}

function currentSettings(): StudentSettings {
  const used = cvVersions.reduce((sum, cv) => sum + cv.size_bytes, 0)
  return clone({ ...settings, full_name: mockStudent.full_name, storage: { ...settings.storage, used_bytes: used } })
}

const IMPORTANCE_ORDER = { required: 0, preferred: 1, additional: 2 }
const IMPORTANCE_TEXT = { required: "bắt buộc", preferred: "ưu tiên", additional: "bổ trợ" }

function optimizerAnalysis(analysisId: string): { analysis: GapAnalysis; cv: CvVersion; opt: MockOptimization } {
  // Sau khi tải lại trang, lượt phân tích tạo trong phiên mock bị xoá: dùng bản mẫu để trang vẫn hiển thị.
  const analysis = withProgress(analyses[analysisId] ?? { ...clone(mockGapAnalysis), id: analysisId })
  if (analysis.status !== "completed") {
    throw new ApiError(409, "Lượt phân tích chưa hoàn tất nên chưa mở được trình tối ưu.", "analysis_not_ready")
  }
  const cv = cvVersions.find((c) => c.id === analysis.cv_version_id)
  if (!cv) {
    throw new ApiError(409, "Phiên bản CV của lượt phân tích này đã bị xoá nên không mở được trình tối ưu.", "cv_deleted")
  }
  optimizations[analysisId] ??= {
    status: "draft",
    decisions: {},
    answers: {},
    contexts: {},
    result_cv_id: null,
    result_document: null,
    finalized_at: null,
  }
  return { analysis, cv, opt: optimizations[analysisId] }
}

function requireDraft(opt: MockOptimization) {
  if (opt.status !== "draft") {
    throw new ApiError(
      409,
      "Bạn đã hoàn tất phiên tối ưu này. Hãy phân tích lại phiên bản mới để tiếp tục tối ưu.",
      "optimization_finalized",
    )
  }
}

function missingRequirements(analysis: GapAnalysis) {
  return analysis.requirements
    .filter((r) => r.status === "missing")
    .sort((a, b) => IMPORTANCE_ORDER[a.importance] - IMPORTANCE_ORDER[b.importance])
}

/** Như cv_entries ở backend: dự án / công việc (dòng có tháng/năm) trong mục Kinh nghiệm, Dự án, Hoạt động. */
function mockEntries(): CvEntry[] {
  const entries: CvEntry[] = []
  for (const section of mockCvDocument.sections) {
    if (!/kinh nghiệm|dự án|hoạt động/i.test(section.title)) continue
    const label = section.title.charAt(0) + section.title.slice(1).toLocaleLowerCase("vi")
    for (const line of section.lines) {
      const title = /\d{2}\/\d{4}/.test(line.text) ? line.text.replace(/\s*\(?\d{2}\/\d{4}.*$/, "").trim() : null
      if (title || entries.length === 0) entries.push({ id: line.id, label: `${label} · ${title ?? "cuối mục"}`, after_line_id: line.id })
      else entries[entries.length - 1].after_line_id = line.id
    }
  }
  return entries
}

function optimizerView(analysisId: string): OptimizerSession {
  const { analysis, cv, opt } = optimizerAnalysis(analysisId)
  const suggestions: Suggestion[] = mockSuggestions.map((base) => {
    const context = opt.contexts[base.id]
    const s: Suggestion = context
      ? {
          ...base,
          needs_context: false,
          proposed_text: `${base.original_text.replace(/\.$/, "")} – ${context.replace(/\.$/, "")}.`,
        }
      : { ...base }
    const d = opt.decisions[base.id]
    const status = d ? ({ accept: "accepted", edit: "edited", reject: "rejected" } as const)[d.action] : "pending"
    return { ...s, status, final_text: d && d.action !== "reject" ? d.final_text : null }
  })
  const capability_checks = missingRequirements(analysis).map((r) => {
    const a = opt.answers[r.id]
    return {
      id: r.id,
      skill: r.skill,
      importance: r.importance,
      jd_requirement: `Vị trí ${analysis.jd.title} yêu cầu ${r.skill} (mức ${IMPORTANCE_TEXT[r.importance]}), nhưng CV chưa thể hiện kỹ năng này.`,
      status: a ? (a.has_experience ? "has_experience" : "no_experience") : "pending",
      context: a?.context ?? null,
      learning_note: a?.learning_note ?? null,
      entry_id: a?.entry_id ?? null,
      draft_text: a?.draft_text ?? null,
      final_text: a?.final_text ?? null,
      line_status: a?.decision ? ({ accept: "accepted", edit: "edited", reject: "rejected" } as const)[a.decision] : "pending",
      roadmap_url: roadmapUrlOf(r.skill),
    } satisfies CapabilityCheck
  })
  const resultCv = opt.result_cv_id ? (cvVersions.find((c) => c.id === opt.result_cv_id) ?? null) : null
  return clone({
    analysis_id: analysisId,
    status: opt.status,
    jd: analysis.jd,
    match_score: analysis.match_score,
    match_label: analysis.match_label,
    llm_used: analysis.llm_used,
    pending_review_count: analysis.pending_review_count,
    cv,
    result_cv: resultCv,
    document: mockCvDocument,
    result_document: resultCv ? opt.result_document : null,
    suggestions,
    capability_checks,
    entries: mockEntries(),
    finalized_at: opt.finalized_at,
  })
}

// ---------- Phía cố vấn (quy tắc và SV giả định ở lib/mocks/advisor.ts) ----------

const MINH_ANH = "sv-0142"
const MAX_COMMENT_CHARS = 2000
const cohort = buildCohort()
/** Ghi chú nội bộ của cố vấn theo mã SV. */
const advisorNotes: Record<string, AdvisorNote[]> = Object.fromEntries(cohort.map((c) => [c.profile.id, c.notes]))
advisorNotes[MINH_ANH] = isNewStudent
  ? []
  : [
      {
        id: "nt_0142",
        body: "Minh Anh tiếp thu nhanh ở câu hỏi xử lý xung đột. Phần Kết quả còn ước lượng cảm tính, cần nhắc em đối chiếu số liệu thật từ đồ án.",
        tags: ["technical"],
        pinned: true,
        created_at: new Date(Date.now() - 86_400_000).toISOString(),
        updated_at: new Date(Date.now() - 86_400_000).toISOString(),
      },
    ]

/** Minh Anh dùng chung dữ liệu với phía SV để chia sẻ / nhận xét khớp giữa hai vai trò. */
function minhAnhSource(): StudentSource {
  const completed = analysisRows()
    .filter((a) => a.status === "completed")
    .sort((a, b) => b.completed_at!.localeCompare(a.completed_at!))
  return {
    profile: {
      id: MINH_ANH,
      full_name: mockStudent.full_name,
      subtitle: mockStudent.subtitle,
      email: mockStudent.subtitle,
      phone: "0912 345 678",
      avatar_url: null,
    },
    cvs: [...cvVersions].sort((a, b) => b.version - a.version),
    analyses: completed.map((row) => ({
      row,
      requirements: (analyses[row.id]?.requirements ?? []).map((r) => ({ skill: r.skill, importance: r.importance, status: r.status })),
    })),
    sessions: completedInterviews(),
    shared: new Set(shared.keys()),
    reviews: advisorReviews,
  }
}

function advisorSources(): StudentSource[] {
  return [minhAnhSource(), ...cohort]
}

/** US-ADV-01 AC3: SV không thuộc danh sách phụ trách → 403, không trả dữ liệu nào. */
function advisorSource(id: string): StudentSource {
  const source = advisorSources().find((s) => s.profile.id === id)
  if (!source) throw new ApiError(403, "Bạn không có quyền xem hồ sơ sinh viên này.", "forbidden")
  return source
}

/** Buổi SV đã chia sẻ; ghi nhận cố vấn đã xem (Minh Anh thấy "Cố vấn đã xem"). */
function sharedSession(source: StudentSource, sessionId: string): InterviewRow {
  const row = source.sessions.find((s) => s.id === sessionId)
  if (!row) throw new ApiError(404, "Không tìm thấy buổi phỏng vấn.", "interview_not_found")
  if (!source.shared.has(sessionId)) throw new ApiError(403, "Sinh viên chưa chia sẻ báo cáo này.", "not_shared")
  if (source.profile.id === MINH_ANH) shared.set(sessionId, { viewed_at: new Date().toISOString() })
  return row
}

// ---------- Tin nhắn SV ↔ cố vấn (quy tắc và tin nhắn demo ở lib/mocks/chat.ts) ----------

/** Tin nhắn theo mã SV, cũ → mới. */
const threads: Record<string, StoredMessage[]> = seedThreads()

const advisorParticipant = (): ChatParticipant => ({
  id: mockAdvisorContact.id,
  full_name: mockAdvisorContact.full_name,
  role: "advisor",
  subtitle: mockAdvisorContact.title,
  avatar_url: mockAdvisorContact.avatar_url,
  office_hours: mockAdvisorContact.office_hours,
})

/** Hội thoại người xem được mở: SV chỉ hội thoại của mình, cố vấn chỉ SV phụ trách (403 nếu không). */
function chatThread(role: Role, studentId: string): { counterpart: ChatParticipant; messages: StoredMessage[] } {
  if (role === "student") {
    if (studentId !== MINH_ANH) throw new ApiError(403, "Bạn không có quyền xem hội thoại này.", "forbidden")
    return { counterpart: advisorParticipant(), messages: (threads[MINH_ANH] ??= []) }
  }
  const { profile } = advisorSource(studentId)
  return {
    counterpart: {
      id: profile.id,
      full_name: profile.full_name,
      role: "student",
      subtitle: profile.subtitle,
      avatar_url: profile.avatar_url,
      office_hours: null,
    },
    messages: (threads[studentId] ??= []),
  }
}

const chatStudentIds = (role: Role) =>
  role === "student"
    ? [MINH_ANH]
    : advisorSources()
        .map((s) => s.profile)
        .sort((a, b) => a.full_name.localeCompare(b.full_name, "vi"))
        .map((p) => p.id)

export const mockApi = {
  async login(body: LoginRequest): Promise<LoginResponse> {
    await delay(700)
    if (failedLogins >= LOGIN_MAX_ATTEMPTS) {
      throw new ApiError(429, "Bạn đã nhập sai quá nhiều lần. Hãy thử lại sau 15 phút.", "too_many_attempts")
    }
    const email = normalizeEmail(body.email)
    const advisor = adminMock.mockAdvisorAccount(email)
    if (advisor) {
      if ((advisor.password ?? mockPassword) !== body.password) wrongCredentials()
      failedLogins = 0
      if (advisor.disabled) {
        throw new ApiError(403, "Tài khoản đã bị tạm khoá. Hãy liên hệ quản trị viên.", "account_disabled")
      }
      signedInAdvisorEmail = email
      return { role: "advisor", profile: adminMock.advisorProfile(advisor), must_change_password: advisor.mustChange }
    }
    const account = accounts.get(email)
    if (!account || account.password() !== body.password) wrongCredentials()
    failedLogins = 0
    return { role: account.role, profile: clone(account.role === "admin" ? adminMock.mockAdmin : mockStudent) }
  },

  async register(body: RegisterRequest): Promise<LoginResponse> {
    await delay(900)
    const email = normalizeEmail(body.email)
    if (accounts.has(email)) throw new ApiError(409, "Email này đã có tài khoản.", "email_taken")
    const password = body.password
    accounts.set(email, { role: "student", password: () => password })
    return { role: "student", profile: { ...clone(mockStudent), full_name: body.full_name.trim(), subtitle: email } }
  },

  async requestPasswordReset(body: PasswordResetRequest): Promise<void> {
    await delay(600)
    void body
  },

  async confirmPasswordReset(body: PasswordResetConfirmRequest): Promise<LoginResponse> {
    await delay(700)
    if (!body.token) throw new ApiError(400, "Link đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.", "invalid_token")
    mockPassword = body.new_password
    failedLogins = 0
    return { role: "student", profile: clone(mockStudent) }
  },

  async listNotifications(role: Role) {
    await delay(500)
    return clone(notifications[role])
  },

  async markNotificationRead(role: Role, id: string) {
    await delay(150)
    notifications[role] = notifications[role].map((n) => (n.id === id ? { ...n, read: true } : n))
  },

  async markAllNotificationsRead(role: Role) {
    await delay(200)
    notifications[role] = notifications[role].map((n) => ({ ...n, read: true }))
  },

  async getMe(role: Role): Promise<UserProfile> {
    await delay(150)
    if (role === "admin") return clone(adminMock.mockAdmin)
    if (role === "student") return clone(mockStudent)
    const advisor = signedInAdvisorEmail ? adminMock.mockAdvisorAccount(signedInAdvisorEmail) : undefined
    return advisor ? { ...adminMock.advisorProfile(advisor), must_change_password: advisor.mustChange } : clone(mockAdvisor)
  },

  async changeTemporaryPassword(body: ChangePasswordRequest): Promise<ChangePasswordResponse> {
    await delay(700)
    if (body.current_password === body.new_password) {
      throw new ApiError(422, "Mật khẩu mới phải khác mật khẩu hiện tại.", "same_password")
    }
    if (!signedInAdvisorEmail || !adminMock.setAdvisorPassword(signedInAdvisorEmail, body.current_password, body.new_password, mockPassword)) {
      throw new ApiError(400, "Mật khẩu hiện tại không đúng.", "wrong_password")
    }
    return { password_updated_at: new Date().toISOString() }
  },

  // ---- Quản trị (lib/mocks/admin.ts) ----
  async getAdminStats(days: AdminPeriod): Promise<AdminStats> {
    await delay()
    return clone(adminMock.stats(days, adminCohort()))
  },

  async listAdminComments(query: AdminCommentsQuery): Promise<AdminCommentsPage> {
    await delay()
    return clone(adminMock.listComments(query))
  },

  async listAdminAdvisors(): Promise<AdminAdvisor[]> {
    await delay()
    const pending = advisorSources().map(summarize).reduce((sum, s) => sum + s.pending_reviews, 0)
    return clone(adminMock.listAdvisors(adminCohort(), pending))
  },

  async createAdvisor(body: CreateAdvisorRequest): Promise<AdminAdvisor> {
    await delay(700)
    return clone(adminMock.createAdvisor(body))
  },

  async updateAdvisor(id: string, body: UpdateAdvisorRequest): Promise<AdminAdvisor> {
    await delay(400)
    return clone(adminMock.updateAdvisor(id, body))
  },

  async resetAdvisorPassword(id: string, temporaryPassword: string): Promise<AdminAdvisor> {
    await delay(500)
    return clone(adminMock.resetAdvisorPassword(id, temporaryPassword))
  },

  async listAdminStudents(): Promise<AdminStudent[]> {
    await delay()
    return clone(adminMock.listStudents(adminCohort()))
  },

  async assignAdvisor(studentIds: string[], advisorId: string): Promise<AssignAdvisorResponse> {
    await delay(600)
    return clone(adminMock.assign(studentIds, advisorId))
  },

  async listInterviewJds(): Promise<JobDescription[]> {
    await delay()
    return clone([...jdMock.publishedLibrary(), ...jdMock.pastedJds()])
  },

  async getQuota(jdId: string): Promise<InterviewQuota> {
    await delay(150)
    return interviewQuota(jdId)
  },

  async getOverview(): Promise<StudentOverview> {
    await delay()
    return clone(
      buildOverview({
        cvs: cvVersions,
        sessions: completedInterviews(),
        analyses: analysisRows(),
        requirementsOf: (id) => analyses[id]?.requirements ?? [],
        activeInterview: activeInterview(),
        quota: interviewQuota,
        guidance: GUIDANCE,
        weekStart: weekStart(),
      }),
    )
  },

  async listCvVersions() {
    await delay()
    return clone(cvFamilies().map(cvCard))
  },

  /** Bản demo không có file thật: trả nội dung CV mẫu dạng văn bản để Xem nhanh / trang Chi tiết có nội dung. */
  async getCvText(id: string): Promise<string> {
    await delay(300)
    cvFamilyOf(id)
    return sampleCvText(mockStudent.full_name)
  },

  async listCvHistory(id: string): Promise<CvVersion[]> {
    await delay()
    const family = cvFamilyOf(id)
    return clone(family.map((v) => ({ ...v, version_count: family.length })))
  },

  /** Khôi phục: bản sao của bản cũ thành bản mới nhất với số chính mới; không xoá bản nào. */
  async restoreCv(id: string): Promise<CvVersion> {
    await delay(500)
    const source = cvVersions.find((c) => c.id === id)
    if (!source) throw new ApiError(404, "Không tìm thấy phiên bản CV.", "cv_not_found")
    if (cvFamilyOf(id)[0].id === id) throw new ApiError(409, "Đây đã là phiên bản hiện tại của CV.", "cv_already_current")
    const restored = appendCvVersion(
      id,
      {
        file_name: source.file_name,
        file_type: source.file_type,
        size_bytes: source.size_bytes,
        page_count: source.page_count,
        uploaded_at: new Date().toISOString(),
        status: "ready",
        error_message: null,
        target_title: null,
        match_score: null,
        origin: "restored",
        latest_analysis_id: null,
        source_analysis_id: null,
        source_jd_title: null,
        restored_from_label: source.label,
        is_draft: false,
      },
      true,
    )
    // Hậu tố phiên bản cũ trong tên file (…_v1.1.docx) đổi theo nhãn mới; tên không có hậu tố giữ nguyên
    restored.file_name = source.file_name.replace(/_v\d+(\.\d+)?(\.[^.]+)$/, `_${restored.label}$2`)
    return clone(restored)
  },

  // US-SV-01 AC3: sai định dạng hoặc > 5MB thì từ chối, không tạo bản ghi.
  async uploadCv(file: File): Promise<CvVersion> {
    const ext = file.name.split(".").pop()?.toLowerCase()
    if (ext !== "pdf" && ext !== "docx") {
      await delay(900)
      throw new ApiError(415, "Chỉ hỗ trợ file PDF hoặc DOCX.", "unsupported_file_type")
    }
    // Mô phỏng PDF scan (tên file chứa "scan"): đọc bằng OCR lâu hơn, file trống ("scan-trang") thì không đọc được.
    const scanned = ext === "pdf" && /scan/i.test(file.name)
    await delay(scanned ? 4500 : 900)
    if (file.size > MAX_UPLOAD_BYTES) {
      throw new ApiError(413, "File vượt quá dung lượng cho phép (tối đa 5MB).", "file_too_large")
    }
    // US-SV-01 AC2: bản scan OCR vẫn không đọc được chữ.
    if (scanned && /trang|blank/i.test(file.name)) {
      throw new ApiError(
        422,
        "Không trích xuất được nội dung CV. Hãy đảm bảo file có chữ rõ ràng hoặc tải lại bản có lớp văn bản.",
        "cv_not_extractable",
      )
    }
    // Mỗi file tải lên là một CV mới, bắt đầu từ v1.0
    const version = nextCvSequence()
    const created: CvVersion = {
      id: `cv-v${version}`,
      version,
      label: "v1.0",
      family_id: `cv-v${version}`,
      version_count: 1,
      file_name: file.name,
      file_type: ext,
      size_bytes: file.size,
      page_count: null,
      uploaded_at: new Date().toISOString(),
      status: "ready",
      error_message: null,
      target_title: null,
      match_score: null,
      origin: "upload",
      latest_analysis_id: null,
      source_analysis_id: null,
      source_jd_title: null,
      restored_from_label: null,
      // CV đầu tiên tự động là CV đang dùng.
      is_active: cvVersions.length === 0,
      is_draft: false,
    }
    cvVersions.unshift(created)
    return { ...clone(created), read_by_ocr: scanned }
  },

  /** Đặt một CV làm CV đang dùng; bản đang dùng là phiên bản mới nhất của CV đó. */
  async setActiveCv(id: string): Promise<CvVersion> {
    await delay(300)
    const head = cvFamilyOf(id)[0]
    cvVersions = cvVersions.map((cv) => ({ ...cv, is_active: cv.id === head.id }))
    return clone(cvCard(cvFamilyOf(id)))
  },

  async listJdLibrary() {
    await delay()
    return clone(jdMock.publishedLibrary())
  },

  /** Mô phỏng POST /jd/recommend: chấm theo quy tắc, tối đa top_n vị trí, lời khuyên cho vị trí #1. */
  async recommendJds(body: RecommendJdsRequest): Promise<RecommendJdsResponse> {
    await delay(body.generate_advice === false ? 500 : 1100)
    if (!body.cv_version_id) throw new ApiError(400, "Vui lòng cung cấp cv_version_id hoặc cv_text.", "cv_required")
    const cv = cvFamilyOf(body.cv_version_id)[0]
    if (cv.status !== "ready") throw new ApiError(409, "CV chưa sẵn sàng để gợi ý vị trí.", "cv_not_ready")
    const topN = Math.min(10, Math.max(1, body.top_n ?? 3))
    const recommendations = recommendFromProfile(mockJdLibrary, skillProfileOf(cv.family_id), topN)
    return {
      cv_version_id: body.cv_version_id,
      recommendations,
      advice: body.generate_advice === false ? null : adviceFor(recommendations[0]),
    }
  },

  /** GET /jd: thư viện JD và các JD SV đã tự dán. */
  async listMyJds(): Promise<JobDescription[]> {
    await delay(300)
    return clone([...jdMock.publishedLibrary(), ...jdMock.pastedJds()])
  },

  /** POST /jd: reviewed (hộp Thêm JD) bắt buộc đủ trường chính; dán nhanh (So sánh) chỉ cần tên vị trí. */
  async createPastedJd(body: CreatePastedJdRequest): Promise<JobDescription> {
    await delay(400)
    return clone(jdMock.createPasted(`jd-p-${Date.now().toString(36)}`, body))
  },

  /** POST /jd/parse: tách toàn văn bằng quy tắc (mock không gọi AI). */
  async parseJd(text: string): Promise<JdDraft> {
    await delay(900)
    return clone(jdMock.parse(text))
  },

  async listPastedJds(): Promise<JobDescription[]> {
    await delay(300)
    return clone(jdMock.pastedJds())
  },

  async updatePastedJd(id: string, fields: JdFields): Promise<JobDescription> {
    await delay(400)
    return clone(jdMock.updatePasted(id, fields))
  },

  async deletePastedJd(id: string): Promise<void> {
    await delay(300)
    jdMock.deletePasted(id)
    savedJds = savedJds.filter((s) => s.jd_id !== id)
  },

  // ---- Quản trị: thư viện JD (lib/mocks/jds.ts) ----
  async listAdminJds(): Promise<AdminJdRow[]> {
    await delay()
    return clone(jdMock.adminLibrary())
  },

  async listUploadedJds(): Promise<AdminUploadedJd[]> {
    await delay()
    return clone(jdMock.adminUploaded())
  },

  async getAdminJd(id: string): Promise<AdminJdDetail> {
    await delay(250)
    return clone(jdMock.adminGet(id))
  },

  async createAdminJd(body: AdminJdUpsert): Promise<AdminJdDetail> {
    await delay(600)
    return clone(jdMock.adminCreate(body))
  },

  async updateAdminJd(id: string, body: AdminJdUpsert): Promise<AdminJdDetail> {
    await delay(500)
    return clone(jdMock.adminUpdate(id, body))
  },

  /** Mô phỏng POST /jd/compare: 2–3 JD khác nhau, chấm theo hồ sơ kỹ năng của CV, sắp giảm dần. */
  async compareJds(body: CompareJdsRequest): Promise<CompareJdsResponse> {
    await delay(3600)
    if (!body.cv_version_id) throw new ApiError(400, "Vui lòng cung cấp cv_version_id hoặc cv_text.", "cv_required")
    const cv = cvVersions.find((c) => c.id === body.cv_version_id)
    if (!cv) throw new ApiError(404, "Không tìm thấy CV.", "cv_not_found")
    const ids = [...new Set(body.jd_ids)]
    if (ids.length < COMPARE_MIN_JDS || ids.length > COMPARE_MAX_JDS) {
      throw new ApiError(400, "Vui lòng chọn từ 2 đến 3 vị trí JD khác nhau để so sánh.", "invalid_jd_selection")
    }
    const missing = ids.filter((id) => !findJd(id))
    if (missing.length) {
      throw new ApiError(404, `Không tìm thấy thông tin JD: ${missing.join(", ")}.`, "jd_not_found")
    }
    // Như backend: mỗi lượt so sánh được lưu vào lịch sử kèm kết quả
    const result: CompareJdsResponse = {
      ...compareFromProfile(
        ids.map((id) => findJd(id)!),
        cv.family_id,
        cv,
      ),
      id: `cmp-${Date.now().toString(36)}`,
      created_at: new Date().toISOString(),
    }
    compareHistory = [result, ...compareHistoryRows()]
    return clone(result)
  },

  async listComparisonHistory(limit: number): Promise<CompareJdsResponse[]> {
    await delay(300)
    return clone(compareHistoryRows().slice(0, limit))
  },

  async deleteComparisonHistory(id: string): Promise<void> {
    await delay(300)
    compareHistory = compareHistoryRows().filter((r) => r.id !== id)
  },

  async listSavedJds(): Promise<SavedJd[]> {
    await delay(250)
    return clone(savedJds)
  },

  async saveJd(jdId: string): Promise<SavedJd> {
    await delay(200)
    if (!findJd(jdId)) throw new ApiError(404, "Không tìm thấy vị trí.", "jd_not_found")
    const existing = savedJds.find((s) => s.jd_id === jdId)
    if (existing) return clone(existing)
    const saved = { jd_id: jdId, saved_at: new Date().toISOString() }
    savedJds = [saved, ...savedJds]
    return clone(saved)
  },

  async unsaveJd(jdId: string): Promise<void> {
    await delay(200)
    savedJds = savedJds.filter((s) => s.jd_id !== jdId)
  },

  // US-SV-02 AC2: JD dán vào phải có ít nhất JD_MIN_WORDS từ. SV chỉ chọn một nguồn JD.
  async createGapAnalysis(body: CreateGapAnalysisRequest): Promise<GapAnalysis> {
    await delay(500)
    const pasted = body.jd_text?.trim() ?? ""
    if (body.jd_id && pasted) {
      throw new ApiError(422, "Chỉ chọn JD trong thư viện hoặc dán nội dung JD, không gửi cả hai.", "jd_source_conflict")
    }
    if (!body.jd_id) {
      if (!pasted) throw new ApiError(422, "Hãy chọn một JD trong thư viện hoặc dán nội dung JD.", "jd_required")
      const words = countJdWords(pasted)
      if (words < JD_MIN_WORDS) {
        throw new ApiError(422, `Nội dung JD quá ngắn (${words} từ). Hãy bổ sung tối thiểu ${JD_MIN_WORDS} từ.`, "jd_too_short")
      }
      if (!body.jd_title?.trim()) throw new ApiError(422, "Hãy nhập tiêu đề vị trí tuyển dụng.", "jd_title_required")
    }
    const cv = cvVersions.find((c) => c.id === body.cv_version_id)
    if (!cv) throw new ApiError(404, "Không tìm thấy phiên bản CV đã chọn.", "cv_not_found")
    // jd_id có thể là JD thư viện hoặc JD SV đã tự dán trước đó.
    const libraryJd = body.jd_id ? findJd(body.jd_id) : undefined
    if (body.jd_id && !libraryJd) throw new ApiError(404, "Không tìm thấy JD đã chọn.", "jd_not_found")
    const id = `ga-${Date.now().toString(36)}`
    // Kết quả gắn đúng cặp (phiên bản CV, JD) đã chọn (US-SV-02 AC1). Nội dung kỹ năng vẫn là dữ liệu mẫu.
    const analysis: GapAnalysis = {
      ...clone(mockGapAnalysis),
      id,
      response_id: id,
      cv_version_id: cv.id,
      cv_file_name: cv.file_name,
      cv_label: cv.label,
      created_at: new Date().toISOString(),
      completed_at: new Date(Date.now() + ANALYSIS_STEPS.length * MOCK_STEP_MS).toISOString(),
      suggestions: mockGapAnalysis.suggestions.map((sg) => ({ ...sg, id: `${id}-${sg.id}` })),
      jd: libraryJd
        ? {
            id: libraryJd.id,
            title: libraryJd.title,
            company: libraryJd.company,
            industry: libraryJd.industry,
            level: libraryJd.level,
            source: libraryJd.source,
          }
        : {
            id: `jd-${id}`,
            title: body.jd_title!.trim(),
            company: body.jd_company?.trim() || null,
            industry: null,
            level: null,
            source: "pasted",
          },
    }
    analyses[id] = analysis
    analysisStartedAt[id] = Date.now()
    if (!libraryJd) {
      // Như backend: JD tự dán được lưu lại để chạy lại, so sánh hoặc lưu vào "Đã lưu".
      jdMock.createPasted(analysis.jd.id, { title: body.jd_title!, company: body.jd_company, text: pasted })
    }
    cv.latest_analysis_id = id
    cv.target_title = analysis.jd.title
    cv.match_score = Math.round(analysis.match_score ?? 0)
    return withProgress(analysis)
  },

  async getGapAnalysis(id: string): Promise<GapAnalysis> {
    await delay(300)
    // Sau khi tải lại trang, dữ liệu mock trong bộ nhớ bị xoá: trả về bản mẫu để trang vẫn hiển thị.
    return withProgress(analyses[id] ?? { ...mockGapAnalysis, id })
  },

  // ---- Trình tối ưu CV (US-SV-03, US-SV-05) ----

  async getOptimizerSession(analysisId: string): Promise<OptimizerSession> {
    await delay()
    return optimizerView(analysisId)
  },

  /** Quyết định chỉ nằm trong bản nháp (AC1 theo phương án gom thay đổi, AC3 bỏ qua giữ nguyên CV). */
  async decideSuggestion(analysisId: string, id: string, body: SuggestionDecisionRequest): Promise<OptimizerSession> {
    await delay(300)
    const { opt } = optimizerAnalysis(analysisId)
    requireDraft(opt)
    const suggestion = optimizerView(analysisId).suggestions.find((s) => s.id === id)
    if (!suggestion) throw new ApiError(404, "Không tìm thấy gợi ý.", "suggestion_not_found")
    if (body.decision === "undo") {
      delete opt.decisions[id]
    } else if (body.decision === "edit") {
      const text = (body.edited_text ?? "").split(/\s+/).filter(Boolean).join(" ")
      if (!text) throw new ApiError(422, "Hãy nhập nội dung chỉnh sửa.", "edited_text_required")
      if (text.length > MAX_EDIT_CHARS) {
        throw new ApiError(422, `Nội dung chỉnh sửa tối đa ${MAX_EDIT_CHARS} ký tự.`, "edited_text_too_long")
      }
      if (text === suggestion.original_text) {
        throw new ApiError(
          422,
          "Nội dung chỉnh sửa đang giống câu gốc. Nếu không muốn thay đổi, hãy chọn Bỏ qua.",
          "edit_unchanged",
        )
      }
      opt.decisions[id] = { action: "edit", final_text: text }
    } else {
      const final = body.decision === "accept" ? suggestion.proposed_text : suggestion.original_text
      opt.decisions[id] = { action: body.decision, final_text: final }
    }
    return optimizerView(analysisId)
  },

  /** US-SV-03 AC2 (chỉ có ở mock): SV bổ sung ngữ cảnh thật, AI mới gợi ý (mock: ghép ngữ cảnh vào câu gốc). */
  async provideSuggestionContext(analysisId: string, id: string, answer: string): Promise<OptimizerSession> {
    await delay(900)
    const { opt } = optimizerAnalysis(analysisId)
    requireDraft(opt)
    if (!answer.trim()) throw new ApiError(422, "Hãy nhập ngữ cảnh trước khi gửi.")
    opt.contexts[id] = answer.trim()
    return optimizerView(analysisId)
  },

  async answerCapabilityCheck(analysisId: string, id: string, body: CapabilityAnswerRequest): Promise<OptimizerSession> {
    await delay(400)
    const { analysis, opt } = optimizerAnalysis(analysisId)
    requireDraft(opt)
    if (!missingRequirements(analysis).some((r) => r.id === id)) {
      throw new ApiError(404, "Không tìm thấy kỹ năng cần xác nhận.", "check_not_found")
    }
    if (body.has_experience) {
      const context = body.context?.trim() ?? ""
      if (!context) throw new ApiError(422, "Hãy mô tả ngắn kinh nghiệm của bạn với kỹ năng này.", "context_required")
      opt.answers[id] = { has_experience: true, context, learning_note: null }
    } else {
      const note = (body.learning_note ?? "").split(/\s+/).filter(Boolean).join(" ") || null
      opt.answers[id] = { has_experience: false, context: null, learning_note: note }
    }
    return optimizerView(analysisId)
  },

  /** Mock: không gọi AI, câu là lời kể của SV làm gọn (thêm tên kỹ năng nếu lời kể chưa nhắc). */
  async draftCapabilityLine(analysisId: string, id: string, body: CapabilityDraftRequest): Promise<OptimizerSession> {
    await delay(1200)
    const { analysis, opt } = optimizerAnalysis(analysisId)
    requireDraft(opt)
    const requirement = missingRequirements(analysis).find((r) => r.id === id)
    if (!requirement) throw new ApiError(404, "Không tìm thấy kỹ năng cần xác nhận.", "check_not_found")
    const context = body.context.split(/\s+/).filter(Boolean).join(" ")
    if (!context) throw new ApiError(422, "Hãy kể ngắn bạn đã dùng kỹ năng này ở đâu, làm những gì.", "context_required")
    if (!mockEntries().some((e) => e.id === body.entry_id)) {
      throw new ApiError(422, "Hãy chọn phần của CV để thêm câu này.", "entry_required")
    }
    let text = context.charAt(0).toLocaleUpperCase("vi") + context.slice(1).replace(/[.\s]+$/, "")
    if (!text.toLowerCase().includes(requirement.skill.toLowerCase())) text = `Sử dụng ${requirement.skill}: ${text.charAt(0).toLocaleLowerCase("vi")}${text.slice(1)}`
    opt.answers[id] = { has_experience: true, context, learning_note: null, entry_id: body.entry_id, draft_text: `${text}.` }
    return optimizerView(analysisId)
  },

  async decideCapabilityLine(analysisId: string, id: string, body: CapabilityLineDecisionRequest): Promise<OptimizerSession> {
    await delay(300)
    const { opt } = optimizerAnalysis(analysisId)
    requireDraft(opt)
    const answer = opt.answers[id]
    if (!answer?.draft_text) throw new ApiError(404, "Chưa có câu đề xuất cho kỹ năng này.", "draft_not_found")
    if (body.decision === "undo") {
      opt.answers[id] = { ...answer, decision: undefined, final_text: null }
    } else if (body.decision === "edit") {
      const text = (body.edited_text ?? "").split(/\s+/).filter(Boolean).join(" ")
      if (!text) throw new ApiError(422, "Hãy nhập nội dung chỉnh sửa.", "edited_text_required")
      opt.answers[id] = { ...answer, decision: "edit", final_text: text }
    } else {
      opt.answers[id] = { ...answer, decision: body.decision, final_text: body.decision === "accept" ? answer.draft_text : null }
    }
    return optimizerView(analysisId)
  },

  /** "Hoàn tất": thêm đúng một phiên bản mới vào cùng CV (số phụ +1, không ghi đè bản cũ) rồi khoá phiên. */
  async finalizeOptimization(analysisId: string): Promise<OptimizerSession> {
    await delay(700)
    const { analysis, cv, opt } = optimizerAnalysis(analysisId)
    requireDraft(opt)
    const view = optimizerView(analysisId)
    const doc = draftDocument(view)
    const added = view.capability_checks.some((c) => c.final_text)
    if (!view.suggestions.some((s) => s.final_text !== null) && doc.developing_skills.length === 0 && !added) {
      throw new ApiError(
        422,
        "Chưa có thay đổi nào để lưu. Hãy áp dụng ít nhất một gợi ý hoặc ghi một kỹ năng bạn đang học.",
        "no_changes",
      )
    }
    const stem = cv.file_name.replace(/\.[^.]+$/, "").replace(/_v\d+(\.\d+)?$/, "") || "CV"
    const created = appendCvVersion(
      cv.id,
      {
        file_name: "",
        file_type: "docx",
        size_bytes: cv.size_bytes,
        page_count: null,
        uploaded_at: new Date().toISOString(),
        status: "ready",
        error_message: null,
        target_title: null,
        match_score: null,
        origin: "optimized",
        latest_analysis_id: null,
        source_analysis_id: analysis.id,
        source_jd_title: analysis.jd.title,
        restored_from_label: null,
        is_draft: false,
      },
      false,
    )
    created.file_name = `${stem}_${created.label}.docx`
    Object.assign(opt, {
      status: "finalized",
      result_cv_id: created.id,
      result_document: doc,
      finalized_at: new Date().toISOString(),
    })
    return optimizerView(analysisId)
  },

  async exportCv(cvId: string, body: ExportCvRequest): Promise<ExportCvResponse> {
    await delay(300)
    if (!body.integrity_confirmed) {
      throw new ApiError(422, "Hãy xác nhận cam kết liêm chính trước khi xuất CV.", "integrity_required")
    }
    if (!cvVersions.some((cv) => cv.id === cvId)) throw new ApiError(404, "Không tìm thấy phiên bản CV.", "cv_not_found")
    return { id: `ex-${Date.now().toString(36)}`, format: body.format, confirmed_at: new Date().toISOString() }
  },

  // US-SV-04 AC3: hết 3 buổi / vị trí / tuần thì chặn. Mỗi SV chỉ có một buổi đang dở.
  async createInterview(body: CreateInterviewRequest): Promise<InterviewSession> {
    await delay(500)
    const jd = mockJdLibrary.find((j) => j.id === body.jd_id)
    if (!jd) throw new ApiError(404, "Không tìm thấy vị trí ứng tuyển.", "jd_not_found")
    // jd_only: phỏng vấn chỉ theo vị trí, không cần CV
    const cv = body.interview_mode === "jd_only" ? null : cvVersions.find((c) => c.id === body.cv_version_id)
    if (cv === undefined) throw new ApiError(404, "Không tìm thấy phiên bản CV đã chọn.", "cv_not_found")
    if (interviewQuota(jd.id).remaining === 0) {
      throw new ApiError(429, `Bạn đã dùng hết ${WEEKLY_LIMIT} buổi phỏng vấn cho vị trí này trong tuần.`, "quota_exceeded")
    }
    for (const [id, iv] of Object.entries(interviews)) if (iv.session.status === "in_progress") delete interviews[id]
    const id = `iv-${Date.now().toString(36)}`
    const iv: MockInterview = {
      session: {
        id,
        status: "in_progress",
        jd: { id: jd.id, title: jd.title, company: jd.company, source: jd.source },
        interview_mode: cv ? "with_cv" : "jd_only",
        cv_version_id: cv?.id ?? null,
        cv_file_name: cv?.file_name ?? null,
        question_count: QUESTION_COUNT,
        seconds_per_question: QUESTION_SECONDS,
        current_question: mockQuestion(1, jd.title),
        seconds_left: QUESTION_SECONDS,
        paused: false,
        pause_used: false,
        pause_seconds_left: null,
        turns: [],
        created_at: new Date().toISOString(),
      },
      deadline: Date.now() + QUESTION_SECONDS * 1000,
      pausedAt: null,
    }
    interviews[id] = iv
    return interviewView(iv)
  },

  /** Legacy server-transcription mock; the interview UI recognizes speech locally. */
  async transcribeAudio(): Promise<{ text: string }> {
    await delay(700)
    return { text: "Em có kinh nghiệm lập trình backend với Python và FastAPI." }
  },

  async getInterview(id: string): Promise<InterviewSession> {
    await delay(300)
    const iv = interviews[id]
    if (!iv) throw new ApiError(404, "Không tìm thấy buổi phỏng vấn. Buổi chưa hoàn thành không được lưu lại.", "interview_not_found")
    if (isAbandoned(iv)) {
      delete interviews[id]
      throw new ApiError(
        410,
        "Buổi phỏng vấn đã kết thúc vì bạn rời phòng quá lâu. Buổi này không bị tính lượt, hãy bắt đầu lại.",
        "interview_expired",
      )
    }
    return interviewView(iv)
  },

  // Guardrail đầu vào mô phỏng quy tắc của backend: quá ngắn / chèn lệnh thì không tính câu.
  async submitAnswer(sessionId: string, body: SubmitAnswerRequest): Promise<SubmitAnswerResponse> {
    const iv = interviews[sessionId]
    if (!iv || iv.session.status !== "in_progress") throw new ApiError(409, "Buổi phỏng vấn đã kết thúc.", "interview_not_active")
    const current = iv.session.current_question!
    if (body.question_index !== current.index) throw new ApiError(409, "Câu hỏi này đã được trả lời.", "question_mismatch")
    resumeMock(iv, Date.now())
    const text = body.text.trim()
    const blocked =
      text.length < MIN_ANSWER_CHARS
        ? `Câu trả lời quá ngắn. Hãy trả lời ít nhất ${MIN_ANSWER_CHARS} ký tự.`
        : /(bỏ qua|ignore).{0,20}(hướng dẫn|instruction)|system prompt|đóng vai/i.test(text)
          ? BLOCKED_REASON
          : null
    if (blocked && !body.timed_out) {
      await delay(300)
      return { allowed: false, reason: blocked, turn: null, next_question: null, seconds_left: interviewView(iv).seconds_left, finished: false }
    }
    await delay(1200)
    const star = blocked ? { situation: 0, task: 0, action: 0, result: 0 } : mockStar(text)
    const weakest = [...CRITERIA].sort((a, b) => star[a] - star[b])[0]
    const turn: InterviewTurn = {
      id: `${sessionId}-t${current.index}`,
      index: current.index,
      theme: current.theme,
      question: current.text,
      answer: text || null,
      timed_out: !!body.timed_out,
      star,
      score: round2(CRITERIA.reduce((sum, c) => sum + star[c], 0) / CRITERIA.length),
      feedback: blocked
        ? "Hết giờ khi chưa có câu trả lời hoàn chỉnh, câu này được 0 điểm."
        : `Câu trả lời có cấu trúc khá rõ. Gợi ý: ${GUIDANCE[weakest].charAt(0).toLowerCase()}${GUIDANCE[weakest].slice(1)}`,
    }
    iv.session.turns.push(turn)
    if (current.index < QUESTION_COUNT) {
      iv.session.current_question = mockQuestion(current.index + 1, iv.session.jd.title)
      iv.deadline = Date.now() + QUESTION_SECONDS * 1000
    } else {
      completeInterview(iv)
    }
    const view = interviewView(iv)
    return {
      allowed: true,
      reason: null,
      turn: clone(turn),
      next_question: view.current_question,
      seconds_left: view.seconds_left,
      finished: view.status === "completed",
    }
  },

  async pauseInterview(sessionId: string): Promise<InterviewSession> {
    await delay(200)
    const iv = interviews[sessionId]
    if (!iv) throw new ApiError(404, "Không tìm thấy buổi phỏng vấn.", "interview_not_found")
    if (iv.session.pause_used) throw new ApiError(409, "Bạn đã dùng lượt tạm dừng của buổi này.", "pause_used")
    iv.pausedAt = Date.now()
    iv.session.pause_used = true
    return interviewView(iv)
  },

  async resumeInterview(sessionId: string): Promise<InterviewSession> {
    await delay(200)
    const iv = interviews[sessionId]
    if (!iv) throw new ApiError(404, "Không tìm thấy buổi phỏng vấn.", "interview_not_found")
    resumeMock(iv, Date.now())
    return interviewView(iv)
  },

  /** Kết thúc sớm: buổi bị xoá, không tính lượt. */
  async abandonInterview(sessionId: string): Promise<void> {
    await delay(200)
    delete interviews[sessionId]
  },

  async getInterviewReport(sessionId: string): Promise<InterviewReport> {
    await delay()
    // Sau khi tải lại trang, dữ liệu mock trong bộ nhớ bị xoá: trả về báo cáo mẫu để trang vẫn hiển thị.
    const report = reports[sessionId] ?? { ...mockInterviewReport, id: sessionId, response_id: sessionId }
    const review = advisorReviews[sessionId]
    return clone({
      ...report,
      advisor_review: review
        ? { id: review.id, advisor_name: mockAdvisor.full_name, comment: review.comment, updated_at: review.updated_at, read: reviewRead(review) }
        : null,
    })
  },

  async getProgress(range: ProgressRange, jdId: string | null): Promise<StudentProgress> {
    await delay(500)
    const rows = analysisRows()
    if (jdId !== null && !mockJdLibrary.some((j) => j.id === jdId) && !rows.some((a) => a.jd.id === jdId)) {
      throw new ApiError(404, "Không tìm thấy vị trí ứng tuyển.", "jd_not_found")
    }
    return clone(buildProgress({ cvs: cvVersions, sessions: completedInterviews(), analyses: rows, range, jdId, now: Date.now() }))
  },

  async getSharing(): Promise<SharingOverview> {
    await delay()
    return clone({ advisor: mockAdvisorContact, items: sharableItems(), feedback: sharingFeedback() })
  },

  async updateSharing(body: UpdateSharingRequest): Promise<SharedItem[]> {
    await delay(300)
    const known = new Set(sharableItems().map((i) => i.id))
    if (body.item_ids.some((id) => !known.has(id))) {
      throw new ApiError(404, "Không tìm thấy tài liệu cần chia sẻ.", "item_not_found")
    }
    for (const id of body.item_ids) {
      if (!body.shared) shared.delete(id)
      else if (!shared.has(id)) shared.set(id, { viewed_at: null })
    }
    return sharableItems()
  },

  async markAdvisorFeedbackRead(id: string): Promise<void> {
    await delay(150)
    const review = Object.values(advisorReviews).find((r) => r.id === id)
    if (!review) throw new ApiError(404, "Không tìm thấy nhận xét.", "feedback_not_found")
    review.seen_at = new Date().toISOString()
  },

  async getSettings(): Promise<StudentSettings> {
    await delay()
    return currentSettings()
  },

  async updateSettings(body: UpdateSettingsRequest): Promise<StudentSettings> {
    await delay(300)
    settings = {
      ...settings,
      privacy: { ...settings.privacy, ...body.privacy },
      notifications: { ...settings.notifications, ...body.notifications },
    }
    return currentSettings()
  },

  async changePassword(body: ChangePasswordRequest): Promise<ChangePasswordResponse> {
    await delay(700)
    if (body.current_password !== mockPassword) {
      throw new ApiError(400, "Mật khẩu hiện tại không đúng.", "wrong_password")
    }
    if (body.new_password === mockPassword) {
      throw new ApiError(422, "Mật khẩu mới phải khác mật khẩu hiện tại.", "same_password")
    }
    mockPassword = body.new_password
    settings = { ...settings, password_updated_at: new Date().toISOString() }
    return { password_updated_at: settings.password_updated_at! }
  },

  /** Xoá cả CV (mọi phiên bản) chứa phiên bản id. */
  async deleteCv(id: string): Promise<void> {
    await delay(400)
    const family = cvFamilyOf(id)
    const familyId = family[0].family_id
    if (family.some((v) => v.is_active) && cvVersions.some((c) => c.family_id !== familyId)) {
      throw new ApiError(409, "Đây là CV đang dùng. Hãy chọn một CV khác làm CV đang dùng trước khi xoá.", "cv_active")
    }
    cvVersions = cvVersions.filter((c) => c.family_id !== familyId)
    shared.delete(familyId)
  },

  async updateProfile(body: UpdateProfileRequest): Promise<StudentSettings> {
    await delay(400)
    if (body.full_name !== undefined) {
      const name = body.full_name.trim().split(/\s+/).join(" ")
      if (name.length < 2) throw new ApiError(422, "Hãy nhập họ và tên (2–120 ký tự).", "invalid_full_name")
      mockStudent.full_name = name
    }
    if (body.phone !== undefined) {
      const digits = body.phone.replace(/[\s.-]/g, "").replace(/^\+84/, "0")
      if (!/^0\d{9}$/.test(digits)) throw new ApiError(422, "Số điện thoại cần đủ 10 chữ số, bắt đầu bằng 0.", "invalid_phone")
      settings = { ...settings, phone: `${digits.slice(0, 4)} ${digits.slice(4, 7)} ${digits.slice(7)}` }
    }
    if (body.date_of_birth !== undefined) settings = { ...settings, date_of_birth: body.date_of_birth }
    return currentSettings()
  },

  async withdrawConsent(): Promise<StudentSettings> {
    await delay(500)
    settings = { ...settings, consent_accepted_at: null }
    return currentSettings()
  },

  async requestDataExport(): Promise<{ download_url: string | null }> {
    await delay(900)
    return { download_url: null }
  },

  async deleteAllData(): Promise<void> {
    await delay(900)
    cvVersions = []
    shared.clear()
    threads[MINH_ANH] = []
    for (const key of Object.keys(advisorReviews)) delete advisorReviews[key]
    seededInterviews = []
    for (const key of Object.keys(reports)) delete reports[key]
    for (const key of Object.keys(analyses)) delete analyses[key]
  },

  async listRecentInterviews(): Promise<InterviewSummary[]> {
    await delay(300)
    const finished: InterviewSummary[] = Object.values(reports)
      .sort((a, b) => b.completed_at.localeCompare(a.completed_at))
      .map((r) => ({ id: r.id, jd: r.jd, completed_at: r.completed_at, overall_score: r.overall_score, star: r.star }))
    return clone([...finished, ...(MOCK_SCENARIO === "new_student" ? [] : mockRecentInterviews)].slice(0, 5))
  },

  // US-SV-06 AC3: không cho gửi trùng cho cùng một response_id; trả lại giá trị đã lưu.
  async sendFeedback(body: FeedbackRequest): Promise<FeedbackResponse> {
    await delay(300)
    const key = `${body.kind}:${body.response_id}`
    const existing = submittedFeedback.get(key)
    // CSAT chỉ gửi một lần; like / dislike đổi được
    if (existing !== undefined && body.kind === "csat") return { id: `fb-${key}`, already_submitted: true, value: existing }
    submittedFeedback.set(key, body.value)
    return { id: `fb-${key}`, already_submitted: false, value: body.value }
  },

  async deleteThumb(responseId: string): Promise<void> {
    await delay(200)
    submittedFeedback.delete(`thumb:${responseId}`)
  },

  async getFeedback(responseId: string, kind: "thumb" | "csat"): Promise<FeedbackStatus> {
    await delay(150)
    return { kind, value: submittedFeedback.get(`${kind}:${responseId}`) ?? null }
  },

  // ---------- Cố vấn ----------

  async getAdvisorOverview(): Promise<AdvisorOverview> {
    await delay()
    return clone(overviewOf(advisorSources(), mockAdvisor.full_name))
  },

  async listConversations(role: Role): Promise<ConversationSummary[]> {
    await delay(250)
    const rows = chatStudentIds(role).map((id) => {
      const { counterpart, messages } = chatThread(role, id)
      const last = messages.at(-1)
      return {
        student_id: id,
        counterpart,
        last_message: last ? toChatMessage(last, role) : null,
        unread_count: unreadFor(messages, role),
      }
    })
    // Có tin mới nhất trước; hội thoại chưa có tin giữ thứ tự theo tên
    const at = (c: ConversationSummary) => (c.last_message ? new Date(c.last_message.created_at).getTime() : 0)
    return clone(rows.sort((a, b) => at(b) - at(a)))
  },

  async getConversation(role: Role, studentId: string): Promise<Conversation> {
    await delay(200)
    const { counterpart, messages } = chatThread(role, studentId)
    return clone({ student_id: studentId, counterpart, messages: messages.map((m) => toChatMessage(m, role)) })
  },

  async sendMessage(role: Role, studentId: string, body: string): Promise<ChatMessage> {
    await delay(250)
    const { messages } = chatThread(role, studentId)
    const text = body.trim()
    if (!text) throw new ApiError(422, "Hãy nhập nội dung tin nhắn.", "message_required")
    if (text.length > MAX_MESSAGE_CHARS) {
      throw new ApiError(422, `Tin nhắn tối đa ${MAX_MESSAGE_CHARS} ký tự.`, "message_too_long")
    }
    const message: StoredMessage = {
      id: `msg_${Date.now().toString(36)}`,
      from: role,
      body: text,
      created_at: new Date().toISOString(),
      read_at: null,
    }
    messages.push(message)
    return clone(toChatMessage(message, role))
  },

  async markConversationRead(role: Role, studentId: string): Promise<void> {
    await delay(100)
    const now = new Date().toISOString()
    for (const m of chatThread(role, studentId).messages) if (m.from !== role && !m.read_at) m.read_at = now
  },

  async getUnreadMessageCount(role: Role): Promise<number> {
    await delay(100)
    return chatStudentIds(role).reduce((sum, id) => sum + unreadFor(chatThread(role, id).messages, role), 0)
  },

  async listAssignedStudents(): Promise<AssignedStudent[]> {
    await delay()
    return clone(advisorSources().map(summarize))
  },

  async getAdvisorStudent(id: string): Promise<AdvisorStudentDetail> {
    await delay()
    return clone(detailOf(advisorSource(id), advisorNotes[id] ?? []))
  },

  async getAdvisorStudentProgress(id: string): Promise<AdvisorStudentProgress> {
    await delay(300)
    return clone(progressOf(advisorSource(id)))
  },

  async getAdvisorInterviewReport(studentId: string, sessionId: string): Promise<AdvisorInterviewReport> {
    await delay()
    const source = advisorSource(studentId)
    const row = sharedSession(source, sessionId)
    const cv = source.cvs[0]?.file_name ?? "cv.pdf"
    const base = studentId === MINH_ANH && reports[sessionId] ? reports[sessionId] : syntheticReport(row, cv)
    const report: Partial<InterviewReport> = { ...base }
    delete report.advisor_review
    return clone({ ...(report as Omit<InterviewReport, "advisor_review">), review: source.reviews[sessionId] ?? null })
  },

  async reviewInterview(studentId: string, sessionId: string, body: ReviewInterviewRequest): Promise<AdvisorReviewInfo> {
    await delay(500)
    const source = advisorSource(studentId)
    sharedSession(source, sessionId)
    const comment = body.comment.trim()
    if (!comment) throw new ApiError(422, "Hãy nhập nội dung nhận xét.", "comment_required")
    if (comment.length > MAX_COMMENT_CHARS) {
      throw new ApiError(422, `Nhận xét tối đa ${MAX_COMMENT_CHARS} ký tự.`, "comment_too_long")
    }
    const now = new Date().toISOString()
    const existing = source.reviews[sessionId]
    source.reviews[sessionId] = existing
      ? { ...existing, comment, updated_at: now, seen_at: null }
      : { id: `rv_${sessionId}`, comment, created_at: now, updated_at: now, seen_at: null }
    return clone(source.reviews[sessionId])
  },

  async getAdvisorCvText(studentId: string, cvId: string): Promise<string> {
    await delay(300)
    const source = advisorSource(studentId)
    const cv = source.cvs.find((c) => c.id === cvId)
    if (!cv) throw new ApiError(404, "Không tìm thấy phiên bản CV.", "cv_not_found")
    if (!source.shared.has(cv.family_id)) throw new ApiError(403, "Sinh viên chưa chia sẻ CV này.", "not_shared")
    if (studentId === MINH_ANH) shared.set(cv.family_id, { viewed_at: new Date().toISOString() })
    return sampleCvText(source.profile.full_name)
  },

  async createAdvisorNote(studentId: string, body: AdvisorNoteRequest): Promise<AdvisorNote> {
    await delay(400)
    advisorSource(studentId)
    const text = body.body.trim()
    if (!text) throw new ApiError(422, "Hãy nhập nội dung ghi chú.", "note_required")
    const at = new Date().toISOString()
    const note: AdvisorNote = { id: `nt_${Date.now().toString(36)}`, body: text, tags: [...new Set(body.tags)], pinned: false, created_at: at, updated_at: at }
    advisorNotes[studentId] = [note, ...(advisorNotes[studentId] ?? [])]
    return clone(note)
  },

  async updateAdvisorNote(studentId: string, noteId: string, body: AdvisorNoteUpdate): Promise<AdvisorNote> {
    await delay(300)
    advisorSource(studentId)
    const note = (advisorNotes[studentId] ?? []).find((n) => n.id === noteId)
    if (!note) throw new ApiError(404, "Không tìm thấy ghi chú.", "note_not_found")
    if (body.body !== undefined) {
      if (!body.body.trim()) throw new ApiError(422, "Hãy nhập nội dung ghi chú.", "note_required")
      note.body = body.body.trim()
    }
    if (body.tags !== undefined) note.tags = [...new Set(body.tags)]
    if (body.pinned !== undefined) note.pinned = body.pinned
    if (body.body !== undefined || body.tags !== undefined) note.updated_at = new Date().toISOString()
    return clone(note)
  },

  async deleteAdvisorNote(studentId: string, noteId: string): Promise<void> {
    await delay(300)
    advisorSource(studentId)
    advisorNotes[studentId] = (advisorNotes[studentId] ?? []).filter((n) => n.id !== noteId)
  },
}
