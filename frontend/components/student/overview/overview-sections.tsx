"use client"

import Link from "next/link"
import { useEffect, useState, type ComponentProps, type ReactNode } from "react"
import {
  ArrowUpRight,
  ChevronRight,
  FileSearch,
  FileUp,
  Library,
  Loader2,
  Mail,
  MessagesSquare,
  Mic,
  ScanText,
  ShieldCheck,
  Target,
  Upload,
  type LucideIcon,
} from "lucide-react"

import { useChat } from "@/components/chat/chat-context"
import { EmptyState } from "@/components/common/empty-state"
import { MatchBadge } from "@/components/common/match-badge"
import { MetricColumn } from "@/components/common/metric-column"
import { SoftPanel } from "@/components/common/panel"
import { QuickLink, TaskCard } from "@/components/common/task-card"
import { WidgetFooter, Zone, ZoneLink } from "@/components/common/zone"
import { IMPORTANCE_META } from "@/components/student/analysis/jd-picker-sections"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ADVISOR_FEATURES } from "@/lib/config"
import { ANALYSIS_STEPS, MATCH_LABEL_META, formatPercent } from "@/lib/analysis"
import { formatDate, formatRelativeTime } from "@/lib/format"
import {
  QUESTION_COUNT,
  SECONDS_PER_QUESTION,
  STAR_META,
  STAR_ORDER,
  TREND_THRESHOLD,
  formatScore,
  mmss,
} from "@/lib/interview"
import type { AnalysisRow, InterviewRow, NextStep, StudentOverview } from "@/lib/types"
import { cn } from "@/lib/utils"

type TaskCardProps = ComponentProps<typeof TaskCard>

const signed = (n: number) => `${n > 0 ? "+" : ""}${formatScore(n)}`

/** "08/10" cho dòng "Cập nhật" dưới cột chỉ số. */
const shortDate = (iso: string) => formatDate(iso).slice(0, 5)

/** SV mới: chưa có CV, chưa phân tích, chưa phỏng vấn. */
export function isNewStudent(overview: StudentOverview): boolean {
  return overview.cv_count === 0 && overview.recent_analyses.length === 0 && overview.interview_count === 0
}

// ---------- Lời chào ----------

/** Tên gọi = từ cuối và từ áp cuối của họ tên ("Nguyễn Minh Anh" → "Minh Anh"). */
function callName(fullName: string): string {
  return fullName.trim().split(/\s+/).slice(-2).join(" ")
}

const DAY_MS = 24 * 60 * 60 * 1000
const INACTIVE_DAYS = 7
const SESSION_MINUTES = (QUESTION_COUNT * SECONDS_PER_QUESTION) / 60

/** Dòng phụ khi chưa có độ khớp để báo: chọn theo hoạt động thật của SV. */
function encouragement(overview: StudentOverview, now: Date): string {
  const { interview_count, interview_week_count, latest_interview: latest, in_progress } = overview
  if (isNewStudent(overview)) return "Tải CV lên để bắt đầu đối chiếu với vị trí bạn muốn."

  const activity = [
    overview.cv_latest_at,
    latest?.completed_at,
    ...overview.recent_analyses.map((a) => a.created_at),
  ].flatMap((iso) => (iso ? [new Date(iso).getTime()] : []))
  const busy = in_progress.interview !== null || in_progress.analyses.length > 0
  const idleDays = activity.length > 0 ? Math.floor((now.getTime() - Math.max(...activity)) / DAY_MS) : 0
  if (!busy && idleDays >= INACTIVE_DAYS) return `Đã ${idleDays} ngày bạn chưa quay lại. Bắt nhịp lại nhé.`

  if (interview_count === 0) return "Phân tích CV với một JD để biết mình đang ở đâu."
  if (interview_week_count > 0 && latest?.delta != null && latest.delta >= TREND_THRESHOLD) {
    return "Điểm STAR của bạn đang đi lên. Giữ nhịp luyện đều nhé."
  }
  return `Một buổi phỏng vấn thử khoảng ${SESSION_MINUTES} phút là đủ giữ nhịp tuần này.`
}

function timeGreeting(now: Date): string {
  const hour = now.getHours()
  if (hour < 11) return "Chào buổi sáng"
  if (hour < 14) return "Chào buổi trưa"
  if (hour < 18) return "Chào buổi chiều"
  return "Chào buổi tối"
}

// Lời chào theo buổi + một câu, 2 nút đối diện bên phải; nền trong suốt để dải pastel hiện phía sau.
export function Greeting({ fullName, overview }: { fullName: string; overview: StudentOverview }) {
  const now = new Date()
  const match = overview.latest_match

  const primary = match
    ? { label: "Xem kết quả", href: `/student/analysis/${encodeURIComponent(match.analysis_id)}` }
    : overview.cv_count === 0
      ? { label: "Tải CV lên", href: "/student/cv" }
      : { label: "Phân tích CV với JD", href: "/student/analysis/new" }
  const secondary = overview.cv_count === 0
    ? { label: "Mở Thư viện JD", href: "/student/library" }
    : { label: "Luyện phỏng vấn", href: "/student/interview/new" }

  return (
    <section
      aria-labelledby="overview-greeting"
      className="flex flex-wrap items-end justify-between gap-x-8 gap-y-5 pt-8 pb-2 md:pt-12"
    >
      <div className="min-w-0 flex-[1_1_480px]">
        <h1
          id="overview-greeting"
          className="font-heading text-[30px] leading-9 font-semibold tracking-[-0.025em] text-balance text-ink md:text-[40px] md:leading-[46px]"
        >
          {timeGreeting(now)}, {callName(fullName)}!
        </h1>
        <p className="mt-2.5 text-base leading-[26px] text-ink-2 md:text-[17px]">{encouragement(overview, now)}</p>
      </div>
      <div className="flex flex-wrap gap-2.5">
        <Button
          variant="ghost"
          size="brand"
          className="glass text-ink shadow-xs hover:bg-card"
          nativeButton={false}
          render={<Link href={secondary.href} />}
        >
          {secondary.label}
        </Button>
        <Button size="brand" nativeButton={false} render={<Link href={primary.href} />}>
          {primary.label}
          <ChevronRight aria-hidden />
        </Button>
      </div>
    </section>
  )
}

// ---------- Việc nên làm tiếp ----------

/** Đếm ngược tại chỗ từ số giây backend trả về lúc tải trang. */
function useCountdown(initial: number | null, running: boolean): number | null {
  const [left, setLeft] = useState(initial)
  useEffect(() => {
    if (!running || initial === null) return
    const endsAt = Date.now() + initial * 1000
    const timer = setInterval(() => setLeft(Math.max(0, Math.round((endsAt - Date.now()) / 1000))), 1000)
    return () => clearInterval(timer)
  }, [initial, running])
  return left
}

type ActiveInterview = NonNullable<StudentOverview["in_progress"]["interview"]>

function InterviewClock({ interview }: { interview: ActiveInterview }) {
  const left = useCountdown(interview.seconds_left, !interview.paused)
  if (interview.paused) return <>Đang tạm dừng</>
  if (left === 0) return <span className="font-medium text-bad">Hết giờ câu này, quay lại ngay</span>
  if (left === null) return <>Câu trả lời đã được lưu</>
  return (
    <>
      Còn <span className="font-semibold text-ink tabular-nums">{mmss(left)}</span> cho câu này
    </>
  )
}

function interviewTask(interview: ActiveInterview): TaskCardProps {
  const { current_index: index, question_count: total } = interview
  return {
    icon: Mic,
    kind: "Phỏng vấn thử",
    title: interview.jd.title,
    meta: `${interview.paused ? "Dừng ở" : "Đang làm"} câu ${index} / ${total}`,
    progress: { done: index - 1, total },
    footnote: <InterviewClock interview={interview} />,
    action: { label: `Tiếp tục câu ${index}`, href: `/student/interview/${encodeURIComponent(interview.id)}` },
  }
}

function analysisTask(analysis: AnalysisRow): TaskCardProps {
  const index = ANALYSIS_STEPS.findIndex((s) => s.key === analysis.current_step)
  return {
    icon: ScanText,
    kind: "Đang phân tích",
    title: analysis.jd.title,
    meta: index >= 0 ? `Bước ${index + 1} / ${ANALYSIS_STEPS.length}: ${ANALYSIS_STEPS[index].title}` : "Đang chuẩn bị",
    progress: { done: Math.max(index, 0), total: ANALYSIS_STEPS.length },
    footnote: `CV ${analysis.cv_label}`,
    action: { label: "Xem tiến độ", href: `/student/analysis/${encodeURIComponent(analysis.id)}` },
  }
}

/** Lộ trình 4 bước; thanh đoạn của thẻ "bước tiếp theo" cho biết SV đang ở bước nào. */
const JOURNEY: NextStep["kind"][] = ["upload_cv", "analyze", "interview", "improve"]

function quotaNote(step: { quota_remaining: number; quota_resets_at: string }): ReactNode {
  return step.quota_remaining > 0 ? (
    `Còn ${step.quota_remaining} lượt tuần này`
  ) : (
    <span className="text-warn">Hết lượt, mở lại {shortDate(step.quota_resets_at)}</span>
  )
}

function nextStepTask(step: NextStep): TaskCardProps {
  const progress = { done: JOURNEY.indexOf(step.kind), total: JOURNEY.length }
  const kindOf = (label: string) => `Bước ${progress.done + 1} / ${progress.total} · ${label}`
  switch (step.kind) {
    case "upload_cv":
      return {
        icon: Upload,
        kind: kindOf("Tải CV"),
        title: "Tải CV đầu tiên của bạn",
        meta: "PDF hoặc DOCX, tối đa 5MB",
        progress,
        footnote: "Cần CV để đối chiếu với JD",
        action: { label: "Tải CV lên", href: "/student/cv" },
      }
    case "analyze":
      return {
        icon: ScanText,
        kind: kindOf("Phân tích CV & JD"),
        title: `Phân tích CV ${step.cv_label} với một JD`,
        meta: "Xem độ khớp và kỹ năng còn thiếu",
        progress,
        footnote: "Khoảng 30 giây",
        action: { label: "Bắt đầu", href: `/student/analysis/new?cv=${encodeURIComponent(step.cv_version_id)}` },
      }
    case "interview":
      return {
        icon: Mic,
        kind: kindOf("Luyện phỏng vấn"),
        title: step.jd.title,
        meta: `${step.match_score !== null ? `CV khớp ${formatPercent(step.match_score)}% · ` : ""}${QUESTION_COUNT} câu STAR, ${SECONDS_PER_QUESTION / 60} phút mỗi câu`,
        progress,
        footnote: quotaNote(step),
        action:
          step.quota_remaining > 0
            ? { label: "Vào phòng", href: `/student/interview/new?jd=${encodeURIComponent(step.jd.id)}` }
            : { label: "Xem kết quả", href: `/student/analysis/${encodeURIComponent(step.analysis_id)}` },
      }
    case "improve": {
      const meta = STAR_META[step.criterion]
      return {
        icon: Target,
        kind: kindOf("Cải thiện STAR"),
        title: `Cải thiện phần ${meta.label}`,
        meta: `${formatScore(step.criterion_score)} / 5 ở ${step.jd.title}`,
        progress,
        footnote: quotaNote(step),
        action:
          step.quota_remaining > 0
            ? { label: "Luyện lại", href: `/student/interview/new?jd=${encodeURIComponent(step.jd.id)}` }
            : { label: "Xem báo cáo", href: `/student/interview/${encodeURIComponent(step.session_id)}/report` },
      }
    }
  }
}

/**
 * Tối đa 2 thẻ: việc đang dở (nếu có) + bước tiếp theo; còn chỗ thì thêm kết quả gần nhất chưa trùng với bước tiếp theo.
 * Lượt phân tích đang chạy khác vẫn thấy ở "Phân tích gần đây".
 */
function taskCards(overview: StudentOverview): TaskCardProps[] {
  const { in_progress, next_step: step, latest_match: match, latest_interview: latest } = overview
  const active = in_progress.interview
    ? interviewTask(in_progress.interview)
    : in_progress.analyses[0] && analysisTask(in_progress.analyses[0])

  const extras: TaskCardProps[] = []
  if (match?.score != null && !(step.kind === "interview" && step.analysis_id === match.analysis_id)) {
    extras.push({
      icon: FileSearch,
      kind: "Kết quả phân tích",
      title: match.jd.title,
      meta: `CV ${match.cv_label} khớp ${formatPercent(match.score)}%`,
      progress: { value: match.score / 100 },
      footnote: formatRelativeTime(match.completed_at),
      action: { label: "Xem kết quả", href: `/student/analysis/${encodeURIComponent(match.analysis_id)}` },
    })
  }
  if (latest && !(step.kind === "improve" && step.session_id === latest.id)) {
    extras.push({
      icon: MessagesSquare,
      kind: "Báo cáo phỏng vấn",
      title: latest.jd.title,
      meta: `${formatScore(latest.score)} / 5${latest.delta !== null ? ` · ${signed(latest.delta)} so với buổi đầu` : ""}`,
      footnote: formatRelativeTime(latest.completed_at),
      action: { label: "Xem báo cáo", href: `/student/interview/${encodeURIComponent(latest.id)}/report` },
    })
  }

  return [...(active ? [active] : []), nextStepTask(step), ...extras].slice(0, 2)
}

export function NextTasks({ overview }: { overview: StudentOverview }) {
  const cards = taskCards(overview)
  const { openChat } = useChat()
  return (
    <SoftPanel aria-labelledby="next-tasks" className="grid gap-4 sm:px-[26px] sm:pb-[26px]">
      <h2 id="next-tasks" className="font-heading text-[22px] leading-7 font-bold text-ink">
        Việc nên làm tiếp
      </h2>
      <div className="flex flex-wrap items-stretch gap-3.5">
        {cards.map((card) => (
          <TaskCard key={`${card.kind}-${card.action.href}`} {...card} className="flex-[1_1_280px]" />
        ))}
        <nav aria-label="Lối tắt" className="flex min-w-[240px] flex-[1_1_240px] flex-col gap-2.5 lg:flex-[0_1_300px]">
          <QuickLink icon={Library} label="Mở Thư viện JD" href="/student/library" />
          <QuickLink icon={FileUp} label="Tải lên CV mới" href="/student/cv" />
          {ADVISOR_FEATURES && <QuickLink icon={Mail} label="Nhắn tin cho cố vấn" onClick={() => openChat()} />}
        </nav>
      </div>
    </SoftPanel>
  )
}

// ---------- Tiến độ của bạn ----------

export function ProgressMetrics({ overview }: { overview: StudentOverview }) {
  const { latest_match: match, star, latest_interview: latest, recent_analyses, recent_interviews } = overview

  // Độ khớp chỉ so được giữa các lượt cùng một JD.
  const sameJd = match
    ? recent_analyses.filter((a) => a.jd.id === match.jd.id && a.status === "completed" && a.match_score !== null)
    : []
  const previous = sameJd.find((a) => a.id !== match?.analysis_id)
  const matchPoints = sameJd.map((a) => a.match_score as number).reverse()

  const starAverage = star ? STAR_ORDER.reduce((sum, key) => sum + star.average[key], 0) / STAR_ORDER.length : null
  const starPoints = recent_interviews.map((r) => r.overall_score).reverse()

  const matchDelta = match?.score != null && previous?.match_score != null ? match.score - previous.match_score : null

  return (
    <Zone id="progress-title" title="Tiến độ của bạn" aside={<ZoneLink href="/student/history">Xem tất cả</ZoneLink>}>
      {/* Hai chỉ số có biểu đồ chiếm phần rộng; số buổi tuần này chỉ là một con số nên cột hẹp, gần vuông */}
      <div className="grid gap-x-12 gap-y-10 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_200px]">
        <MetricColumn
          label="Độ khớp CV gần nhất"
          value={match?.score != null ? `${formatPercent(match.score)}%` : "—"}
          delta={
            matchDelta !== null && matchDelta !== 0
              ? { text: `${matchDelta > 0 ? "+" : ""}${formatPercent(matchDelta)}`, positive: matchDelta > 0 }
              : undefined
          }
          compare={
            previous?.match_score != null
              ? `${formatPercent(previous.match_score)}% ở CV ${previous.cv_label}`
              : match?.label
                ? `Mức ${MATCH_LABEL_META[match.label].text.toLowerCase()}`
                : "chưa phân tích"
          }
          points={matchPoints.length > 1 ? matchPoints : undefined}
          link={
            match
              ? { label: "Xem thêm", href: `/student/analysis/${encodeURIComponent(match.analysis_id)}` }
              : { label: "Phân tích ngay", href: "/student/analysis/new" }
          }
          note={match && `Cập nhật ${shortDate(match.completed_at)}`}
        />
        <MetricColumn
          label="Điểm STAR trung bình"
          value={starAverage !== null ? `${formatScore(starAverage)} / 5` : "—"}
          delta={
            latest?.delta != null && latest.delta !== 0
              ? { text: signed(latest.delta), positive: latest.delta > 0 }
              : undefined
          }
          compare={star ? `${star.session_count} buổi gần nhất` : "chưa có buổi nào"}
          points={starPoints.length > 1 ? starPoints : undefined}
          link={{ label: "Xem thêm", href: "/student/history" }}
          note={latest && `Cập nhật ${shortDate(latest.completed_at)}`}
        />
        <div className="sm:col-span-2 sm:max-w-[200px] lg:col-span-1">
          <MetricColumn
            label="Buổi phỏng vấn tuần này"
            value={overview.interview_week_count}
            compare={`tổng ${overview.interview_count} buổi`}
            link={{ label: "Xem thêm", href: "/student/history" }}
          />
        </div>
      </div>
    </Zone>
  )
}

// ---------- Các khối trong vùng ----------

/**
 * Một khối trong vùng (phương án A): tiêu đề đậm, các dòng kẻ mảnh, dòng chân "Xem … / ghi chú".
 * Không có viền bao quanh; tiêu đề và dòng chân cho biết khối bắt đầu và kết thúc ở đâu.
 */
function Widget({
  id,
  title,
  footer,
  children,
}: {
  id: string
  title: string
  footer?: ComponentProps<typeof WidgetFooter>
  children: ReactNode
}) {
  return (
    <section aria-labelledby={id} className="flex min-w-0 flex-col">
      <h3 id={id} className="mb-1.5 text-base font-semibold text-ink">
        {title}
      </h3>
      <div className="flex-1">{children}</div>
      {footer && <WidgetFooter {...footer} className="mt-3.5" />}
    </section>
  )
}

function LinkRow({ href, title, meta, aside }: { href: string; title: string; meta: ReactNode; aside: ReactNode }) {
  return (
    <li className="border-b border-line">
      <Link
        href={href}
        className="-mx-2.5 flex items-center gap-3 rounded-[10px] px-2.5 py-3 transition-colors hover:bg-panel"
      >
        <span className="grid min-w-0 flex-1">
          <span className="truncate text-[15px] font-medium text-ink">{title}</span>
          <span className="truncate text-[13px] text-ink-3">{meta}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2">{aside}</span>
      </Link>
    </li>
  )
}

function Bar({ value, tone = "bg-blue" }: { value: number; tone?: string }) {
  return (
    <span className="block h-1.5 w-[72px] shrink-0 overflow-hidden rounded-full bg-surface sm:w-[90px]" aria-hidden>
      <span className={cn("block h-full rounded-full", tone)} style={{ width: `${Math.round(value * 100)}%` }} />
    </span>
  )
}

function ListEmpty({ icon, title, text }: { icon: LucideIcon; title: string; text: string }) {
  return <EmptyState icon={icon} title={title} description={text} className="border-b border-line py-8" />
}

function AnalysisStatus({ row }: { row: AnalysisRow }) {
  if (row.status === "processing") {
    return (
      <Badge variant="blue">
        <Loader2 className="animate-spin" aria-hidden />
        Đang phân tích
      </Badge>
    )
  }
  if (row.status === "failed" || row.match_score === null) return <Badge variant="bad">Lỗi</Badge>
  return (
    <>
      <span className="text-[15px] font-semibold text-ink tabular-nums">{formatPercent(row.match_score)}%</span>
      {row.match_label && <MatchBadge label={row.match_label} />}
    </>
  )
}

export function RecentAnalyses({ items }: { items: AnalysisRow[] }) {
  return (
    <Widget
      id="recent-analyses"
      title="Phân tích gần đây"
      footer={
        items.length > 0
          ? { link: { label: "Xem tất cả", href: "/student/history" }, note: `${items.length} lượt gần nhất` }
          : undefined
      }
    >
      {items.length === 0 ? (
        <ListEmpty icon={FileSearch} title="Chưa có lượt phân tích" text="Các lượt đối chiếu CV với JD sẽ hiện ở đây." />
      ) : (
        <ul>
          {items.map((row) => (
            <LinkRow
              key={row.id}
              href={`/student/analysis/${encodeURIComponent(row.id)}`}
              title={row.jd.title}
              meta={`CV ${row.cv_label} · ${formatRelativeTime(row.created_at)}`}
              aside={<AnalysisStatus row={row} />}
            />
          ))}
        </ul>
      )}
    </Widget>
  )
}

export function SkillsToLearn({ skills }: { skills: StudentOverview["skills_to_learn"] }) {
  const more = skills ? skills.total_missing - skills.skills.length : 0
  return (
    <Widget
      id="skills-to-learn"
      title="Kỹ năng nên học thêm"
      footer={
        skills
          ? {
              link: {
                label: more > 0 ? `Xem đủ ${skills.total_missing} kỹ năng` : "Xem phân tích",
                href: `/student/analysis/${encodeURIComponent(skills.analysis_id)}`,
              },
              note: skills.skills.length > 0 ? "Chỉ thêm vào CV khi đã học thật" : undefined,
            }
          : undefined
      }
    >
      {!skills ? (
        <ListEmpty
          icon={Target}
          title="Chưa có dữ liệu"
          text="Phân tích CV với một JD để biết kỹ năng nào vị trí đó cần mà CV chưa thể hiện."
        />
      ) : skills.skills.length === 0 ? (
        <ListEmpty
          icon={ShieldCheck}
          title="Không thiếu kỹ năng nào"
          text={`CV đã có bằng chứng cho mọi yêu cầu của vị trí ${skills.jd.title}.`}
        />
      ) : (
        <ul>
          {skills.skills.map((skill) => {
            const meta = IMPORTANCE_META[skill.importance]
            return (
              <li key={skill.name} className="flex items-center gap-3 border-b border-line py-3 sm:gap-3.5">
                {skill.roadmap_url ? (
                  // Như ô "Thiếu ở cả … vị trí" ở trang So sánh: kỹ năng có ↗ mở lộ trình học trên roadmap.sh
                  <a
                    href={skill.roadmap_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    title="Xem lộ trình học trên roadmap.sh"
                    aria-label={`${skill.name}: lộ trình học trên roadmap.sh`}
                    className="flex min-w-0 flex-1 items-center gap-1 text-[15px] font-medium text-ink transition-colors hover:text-blue"
                  >
                    <span className="truncate">{skill.name}</span>
                    <ArrowUpRight className="size-3.5 shrink-0 text-ink-3" strokeWidth={2} aria-hidden />
                  </a>
                ) : (
                  <span className="min-w-0 flex-1 truncate text-[15px] font-medium text-ink">{skill.name}</span>
                )}
                <Bar value={meta.weight / 3} />
                <span className="w-[64px] shrink-0 text-right text-[13px] text-ink-3">{meta.label}</span>
              </li>
            )
          })}
        </ul>
      )}
    </Widget>
  )
}

// Phỏng vấn hiện điểm x.x / 5, không gắn nhãn (DESIGN.md mục 8.1).
export function RecentInterviews({ items }: { items: InterviewRow[] }) {
  return (
    <Widget
      id="recent-interviews"
      title="Phỏng vấn gần đây"
      footer={
        items.length > 0
          ? { link: { label: "Xem tất cả", href: "/student/history" }, note: `${items.length} buổi gần nhất` }
          : undefined
      }
    >
      {items.length === 0 ? (
        <ListEmpty icon={MessagesSquare} title="Chưa có buổi phỏng vấn" text="Báo cáo các buổi phỏng vấn thử sẽ hiện ở đây." />
      ) : (
        <ul>
          {items.map((row) => (
            <LinkRow
              key={row.id}
              href={`/student/interview/${encodeURIComponent(row.id)}/report`}
              title={row.jd.title}
              meta={
                <>
                  {formatRelativeTime(row.completed_at)}
                  {row.timed_out_count > 0 && ` · ${row.timed_out_count} câu hết giờ`}
                </>
              }
              aside={<span className="text-[15px] font-semibold text-ink tabular-nums">{formatScore(row.overall_score)} / 5</span>}
            />
          ))}
        </ul>
      )}
    </Widget>
  )
}
