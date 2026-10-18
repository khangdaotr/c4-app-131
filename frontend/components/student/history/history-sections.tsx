"use client"

import Link from "next/link"
import { useState, type ReactNode } from "react"
import {
  Clock,
  FileSearch,
  FileText,
  GitCompareArrows,
  Loader2,
  MessagesSquare,
  ScanText,
  type LucideIcon,
} from "lucide-react"

import { EmptyState } from "@/components/common/empty-state"
import { MatchBadge } from "@/components/common/match-badge"
import { ProgressChart } from "@/components/student/history/progress-chart"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { formatPercent } from "@/lib/analysis"
import { ADVISOR_FEATURES } from "@/lib/config"
import { formatDate } from "@/lib/format"
import { STAR_META, STAR_ORDER, formatScore, trendOf } from "@/lib/interview"
import type { AnalysisRow, CompareJdsResponse, CvProgress, InterviewProgress, InterviewRow } from "@/lib/types"
import { cn } from "@/lib/utils"

const pad = (n: number) => String(n).padStart(2, "0")
/** "07/09" */
const shortDate = (iso: string) => {
  const d = new Date(iso)
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}`
}
const signed = (n: number, format: (n: number) => string = formatScore) => `${n > 0 ? "+" : ""}${format(n)}`

// ---------- Tiến bộ phỏng vấn theo vị trí (PRD mục 5.1, 2 lớp) ----------

export function DeltaLine({ label, delta }: { label: string; delta: number }) {
  const trend = trendOf(delta)
  return (
    <p className="flex flex-wrap items-baseline gap-x-1.5 text-sm">
      <strong className={cn("font-heading", trend.className)}>{signed(delta)}</strong>
      <span className="text-ink-2">{label}</span>
      <span className={cn("text-xs font-medium", trend.className)}>· {trend.text}</span>
    </p>
  )
}

/** Lớp 2: S/T/A/R buổi trước so với buổi gần nhất. */
export function StarCompare({ group }: { group: InterviewProgress }) {
  const previous = group.star_previous
  return (
    <div className="grid content-start gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-ink">Điểm từng tiêu chí</p>
        <span className="flex flex-wrap items-center gap-3 text-xs text-ink-2">
          {previous && (
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-3 rounded-sm bg-ink-3/40" aria-hidden />
              Buổi trước
            </span>
          )}
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-3 rounded-sm bg-violet" aria-hidden />
            Buổi gần nhất
          </span>
        </span>
      </div>
      <ul className="grid gap-3">
        {STAR_ORDER.map((key) => {
          const latest = group.star_latest[key]
          const before = previous?.[key]
          const delta = before !== undefined ? Math.round((latest - before) * 100) / 100 : null
          return (
            <li key={key} className="grid gap-1">
              <div className="flex items-center justify-between gap-2 text-sm">
                <span className="flex items-center gap-2 font-medium text-ink">
                  <span className="grid size-6 place-items-center rounded-md bg-blue-soft text-xs font-bold text-blue">
                    {STAR_META[key].letter}
                  </span>
                  {STAR_META[key].label}
                </span>
                <span className="flex items-center gap-2 text-xs">
                  {before !== undefined && <span className="text-ink-2">{formatScore(before)} →</span>}
                  <strong className="font-heading text-sm text-ink">{formatScore(latest)}/5</strong>
                  {delta !== null && <span className={cn("font-semibold", trendOf(delta).className)}>({signed(delta)})</span>}
                </span>
              </div>
              {before !== undefined && (
                <div className="h-1.5 overflow-hidden rounded-full bg-surface" aria-hidden>
                  <div className="h-full rounded-full bg-ink-3/40" style={{ width: `${(before / 5) * 100}%` }} />
                </div>
              )}
              <div className="h-1.5 overflow-hidden rounded-full bg-surface" aria-hidden>
                <div className="h-full rounded-full bg-violet" style={{ width: `${(latest / 5) * 100}%` }} />
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

// ---------- Vùng "Tiến bộ": 2 khối cạnh nhau (bản vẽ TienBo) ----------

/** Badge chênh lệch cạnh tiêu đề khối: tăng xanh lá, giảm cam, không đổi xám (cùng kiểu MetricColumn). */
function DeltaBadge({ text, value, title }: { text: string; value: number; title: string }) {
  return (
    <span
      title={title}
      className={cn(
        "rounded-badge border px-1.5 text-xs leading-5 font-semibold tabular-nums",
        value > 0
          ? "border-good-line bg-good-soft text-good"
          : value < 0
            ? "border-warn-line bg-warn-soft text-warn"
            : "border-line-strong bg-surface text-ink-2",
      )}
    >
      {text}
    </span>
  )
}

interface PickerProps {
  label: string
  items: { value: string; label: string }[]
  value: string
  onChange: (value: string) => void
}

function Picker({ label, items, value, onChange }: PickerProps) {
  return (
    <Select items={items} value={value} onValueChange={(v) => v && onChange(String(v))}>
      <SelectTrigger
        aria-label={label}
        className="h-[38px] w-full min-w-0 rounded-[10px] border-line-strong bg-card px-3 text-sm font-medium text-ink shadow-xs sm:w-60"
      >
        <SelectValue className="min-w-0 truncate" />
      </SelectTrigger>
      <SelectContent align="end">
        {items.map((item) => (
          <SelectItem key={item.value} value={item.value}>
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

/** Khung một khối: tiêu đề 16px + badge bên trái, bộ chọn bên phải; điện thoại thì bộ chọn xuống dòng, rộng hết. */
function ProgressBlock({
  id,
  title,
  badge,
  picker,
  children,
}: {
  id: string
  title: string
  badge?: ReactNode
  picker?: ReactNode
  children: ReactNode
}) {
  return (
    <section aria-labelledby={id} className="min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2.5">
        <div className="flex items-center gap-2">
          <h3 id={id} className="text-base font-semibold text-ink">
            {title}
          </h3>
          {badge}
        </div>
        {picker && <div className="w-full sm:w-auto">{picker}</div>}
      </div>
      {children}
    </section>
  )
}

const jdLabel = (jd: { title: string; company: string | null }) => (jd.company ? `${jd.title} · ${jd.company}` : jd.title)

export function InterviewProgressBlock({ groups }: { groups: InterviewProgress[] }) {
  const [jdId, setJdId] = useState<string | null>(null)
  const group = groups.find((g) => g.jd.id === jdId) ?? groups[0]

  if (!group) {
    return (
      <ProgressBlock id="progress-interview" title="Điểm phỏng vấn">
        <EmptyState
          icon={MessagesSquare}
          title="Chưa có buổi phỏng vấn nào"
          description="Hoàn thành buổi phỏng vấn thử đầu tiên để theo dõi điểm qua từng buổi."
          action={
            <Button variant="soft" size="brand" nativeButton={false} render={<Link href="/student/interview/new" />}>
              Luyện phỏng vấn
            </Button>
          }
        />
      </ProgressBlock>
    )
  }

  const delta = group.delta_from_first
  return (
    <ProgressBlock
      id="progress-interview"
      title="Điểm phỏng vấn"
      badge={delta !== null && <DeltaBadge text={signed(delta)} value={delta} title="So với buổi đầu" />}
      picker={
        groups.length > 1 ? (
          <Picker
            label="Chọn vị trí"
            items={groups.map((g) => ({ value: g.jd.id, label: g.jd.title }))}
            value={group.jd.id}
            onChange={setJdId}
          />
        ) : undefined
      }
    >
      <p className="mt-1.5 text-[26px] leading-8 text-ink tabular-nums">
        {formatScore(group.latest_score)} <span className="text-[15px] text-ink-3">/ 5</span>
      </p>
      {group.points.length > 1 ? (
        <ProgressChart
          points={group.points.map((p) => ({
            label: shortDate(p.completed_at),
            detail: formatDate(p.completed_at),
            value: p.score,
          }))}
          ticks={[1, 3, 5]}
          format={(v) => `${formatScore(v)} / 5`}
        />
      ) : (
        <p className="mt-3.5 text-sm text-ink-2">Mới có 1 buổi ở vị trí này. Luyện thêm để thấy điểm thay đổi.</p>
      )}
      <p className="mt-2 text-[13px] text-ink-3">
        Điểm chỉ so sánh trong cùng một vị trí.{groups.length === 1 && ` ${jdLabel(group.jd)}.`}
      </p>
    </ProgressBlock>
  )
}

export function CvProgressBlock({ groups }: { groups: CvProgress[] }) {
  const [jdId, setJdId] = useState<string | null>(null)
  const group = groups.find((g) => g.jd.id === jdId) ?? groups[0]

  if (!group) {
    return (
      <ProgressBlock id="progress-cv" title="Độ khớp CV">
        <EmptyState
          icon={FileSearch}
          title="Chưa có lượt phân tích nào"
          description="Phân tích CV với một JD để xem độ khớp qua từng phiên bản CV."
          action={
            <Button variant="soft" size="brand" nativeButton={false} render={<Link href="/student/analysis/new" />}>
              Phân tích CV với JD
            </Button>
          }
        />
      </ProgressBlock>
    )
  }

  const latest = group.points[group.points.length - 1]
  return (
    <ProgressBlock
      id="progress-cv"
      title="Độ khớp CV"
      badge={
        group.delta !== null && (
          <DeltaBadge text={signed(group.delta, formatPercent)} value={group.delta} title="So với phiên bản CV đầu" />
        )
      }
      picker={
        groups.length > 1 ? (
          <Picker
            label="Chọn vị trí để so độ khớp"
            items={groups.map((g) => ({ value: g.jd.id, label: g.jd.title }))}
            value={group.jd.id}
            onChange={setJdId}
          />
        ) : undefined
      }
    >
      <p className="mt-1.5 text-[26px] leading-8 text-ink tabular-nums">{formatPercent(latest.match_score)}%</p>
      {group.points.length > 1 ? (
        <ProgressChart
          points={group.points.map((p) => ({
            label: p.cv_label,
            detail: `CV ${p.cv_label} · ${formatDate(p.completed_at)}`,
            value: p.match_score,
          }))}
          ticks={[0, 50, 100]}
          threshold={{ value: 75, label: "Cao" }}
          format={(v) => `${formatPercent(v)}%`}
        />
      ) : (
        <p className="mt-3.5 text-sm text-ink-2">Tối ưu CV rồi phân tích lại với vị trí này để thấy độ khớp thay đổi.</p>
      )}
      <p className="mt-2 text-[13px] text-ink-3">So với {jdLabel(group.jd)}</p>
    </ProgressBlock>
  )
}

// ---------- Vùng "Dòng thời gian": gộp phỏng vấn, phân tích và so sánh vị trí, chia theo tháng ----------

export type TimelineFilter = "all" | "interview" | "analysis" | "compare"

interface TimelineEntry {
  key: string
  at: string
  icon: LucideIcon
  kind: string
  title: ReactNode
  /** CV đã dùng ("CV_MinhAnh.pdf · v1.0") hoặc "Chỉ dựa trên JD". */
  cv: string | null
  score: ReactNode
  href: string
  linkLabel: string
  reviewed: boolean
}

/** "CV_MinhAnh.pdf · v1.0": tên file và phiên bản CV đã dùng. */
function cvRef(fileName: string | null | undefined, label: string | null | undefined): string | null {
  return [fileName, label].filter(Boolean).join(" · ") || null
}

function interviewEntry(row: InterviewRow, reviewed: boolean): TimelineEntry {
  return {
    key: `iv-${row.id}`,
    at: row.completed_at,
    icon: MessagesSquare,
    kind: "Phỏng vấn",
    title: row.jd.title,
    cv: row.interview_mode === "jd_only" ? "Chỉ dựa trên JD, không dùng CV" : cvRef(row.cv_file_name, row.cv_label),
    // Phỏng vấn hiện x,x / 5, không gắn nhãn (DESIGN.md mục 8.1).
    score: `${formatScore(row.overall_score)} / 5`,
    href: `/student/interview/${encodeURIComponent(row.id)}/report`,
    linkLabel: "Báo cáo",
    reviewed,
  }
}

function AnalysisScore({ row }: { row: AnalysisRow }) {
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
      {formatPercent(row.match_score)}%
      {row.match_label && <MatchBadge label={row.match_label} />}
    </>
  )
}

function analysisEntry(row: AnalysisRow): TimelineEntry {
  return {
    key: `ga-${row.id}`,
    at: row.created_at,
    icon: ScanText,
    kind: "Phân tích",
    title: row.jd.title,
    cv: cvRef(row.cv_file_name, row.cv_label),
    score: <AnalysisScore row={row} />,
    href: `/student/analysis/${encodeURIComponent(row.id)}`,
    linkLabel: "Xem",
    reviewed: false,
  }
}

/** Lượt so sánh đã lưu (bản vẽ LichSuSoSanhA): mở lại đúng kết quả lúc so sánh, không chạy lại AI. */
function compareEntry(row: CompareJdsResponse & { id: string; created_at: string }): TimelineEntry {
  const top = row.comparisons[0]
  return {
    key: `cmp-${row.id}`,
    at: row.created_at,
    icon: GitCompareArrows,
    kind: "So sánh",
    title: (
      <>
        {row.comparisons.length} vị trí{" "}
        <span className="font-normal text-ink-3">· {row.comparisons.map((c) => c.title).join(", ")}</span>
      </>
    ),
    cv: cvRef(row.cv_name, row.cv_label),
    score: top && (
      <>
        <span className="text-[13px] font-medium whitespace-nowrap text-ink-3">cao nhất</span>
        {formatPercent(top.match_score)}%
        <MatchBadge label={top.match_label} />
      </>
    ),
    href: `/student/analysis/compare/${encodeURIComponent(row.id)}`,
    linkLabel: "Xem",
    reviewed: false,
  }
}

const isSaved = (row: CompareJdsResponse): row is CompareJdsResponse & { id: string; created_at: string } =>
  Boolean(row.id && row.created_at)

function monthLabel(iso: string, now: Date): string {
  const d = new Date(iso)
  return d.getFullYear() === now.getFullYear() ? `Tháng ${d.getMonth() + 1}` : `Tháng ${d.getMonth() + 1}/${d.getFullYear()}`
}

/**
 * Máy tính: một dòng 5 cột (ngày, loại, tiêu đề, điểm, link). Điện thoại: 2 hàng — tiêu đề + điểm, rồi ngày · loại + link.
 * Cụm ngày/loại là `display: contents` từ sm để hai ô của nó thành ô lưới riêng.
 */
function TimelineRow({ entry }: { entry: TimelineEntry }) {
  const Icon = entry.icon
  return (
    <li className="border-b border-line">
      <Link
        href={entry.href}
        className="-mx-2.5 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 rounded-[10px] px-2.5 py-3 text-ink transition-colors hover:bg-panel sm:grid-cols-[64px_120px_minmax(0,1fr)_170px_72px] sm:py-3.5"
      >
        <span className="order-3 flex min-w-0 items-center gap-2 text-[13px] text-ink-3 sm:contents">
          <span className="text-ink-3 tabular-nums sm:order-1 sm:text-sm">{shortDate(entry.at)}</span>
          <span aria-hidden className="sm:hidden">
            ·
          </span>
          <span className="inline-flex items-center gap-1.5 sm:order-2 sm:gap-2 sm:text-sm sm:text-ink-2">
            <Icon className="size-3.5 sm:size-4" strokeWidth={1.75} aria-hidden />
            {entry.kind}
          </span>
          {ADVISOR_FEATURES && entry.reviewed && <span className="truncate text-accent-strong sm:hidden">· Cố vấn đã nhận xét</span>}
        </span>
        <span className="order-1 grid min-w-0 gap-0.5 sm:order-3">
          <span className="flex min-w-0 items-center gap-2.5">
            <span className="truncate text-[15px] font-medium">{entry.title}</span>
            {ADVISOR_FEATURES && entry.reviewed && (
              <Badge variant="blue" className="hidden sm:inline-flex">
                Cố vấn đã nhận xét
              </Badge>
            )}
          </span>
          {entry.cv && (
            <span className="flex min-w-0 items-center gap-1.5 text-[13px] text-ink-3">
              <FileText className="size-3.5 shrink-0" strokeWidth={1.75} aria-hidden />
              <span className="truncate">{entry.cv}</span>
            </span>
          )}
        </span>
        <span className="order-2 inline-flex items-center justify-end gap-2 text-[15px] font-semibold tabular-nums sm:order-4">
          {entry.score}
        </span>
        <span className="order-4 text-right text-sm font-semibold text-blue sm:order-5">{entry.linkLabel}</span>
      </Link>
    </li>
  )
}

const PAGE_SIZE = 10

export function Timeline({
  filter,
  interviews,
  analyses,
  comparisons,
  reviewedIds,
}: {
  filter: TimelineFilter
  interviews: InterviewRow[]
  analyses: AnalysisRow[]
  comparisons: CompareJdsResponse[]
  reviewedIds: Set<string>
}) {
  const [limit, setLimit] = useState(PAGE_SIZE)
  const show = (kind: TimelineFilter) => filter === "all" || filter === kind
  const entries = [
    ...(show("interview") ? interviews.map((r) => interviewEntry(r, reviewedIds.has(r.id))) : []),
    ...(show("analysis") ? analyses.map(analysisEntry) : []),
    ...(show("compare") ? comparisons.filter(isSaved).map(compareEntry) : []),
  ].sort((a, b) => b.at.localeCompare(a.at))

  if (entries.length === 0) {
    const empty = {
      all: { icon: ScanText, title: "Chưa có hoạt động nào" },
      interview: { icon: MessagesSquare, title: "Chưa có buổi phỏng vấn nào" },
      analysis: { icon: FileSearch, title: "Chưa có lượt phân tích nào" },
      compare: { icon: GitCompareArrows, title: "Chưa có lượt so sánh vị trí nào" },
    }[filter]
    return <EmptyState icon={empty.icon} title={empty.title} className="border-b border-line" />
  }

  const now = new Date()
  const visible = entries.slice(0, limit)
  const months: { label: string; rows: TimelineEntry[] }[] = []
  for (const entry of visible) {
    const label = monthLabel(entry.at, now)
    const current = months[months.length - 1]
    if (current?.label === label) current.rows.push(entry)
    else months.push({ label, rows: [entry] })
  }

  return (
    <div>
      {months.map((month, i) => (
        <section key={month.label} aria-label={month.label}>
          <h3 className={cn("pb-1.5 text-[13px] font-semibold text-ink-3", i === 0 ? "pt-0" : "pt-6")}>{month.label}</h3>
          <ul>
            {month.rows.map((entry) => (
              <TimelineRow key={entry.key} entry={entry} />
            ))}
          </ul>
        </section>
      ))}
      {visible.some((e) => e.key.startsWith("cmp-")) && (
        <p className="mt-3.5 flex items-start gap-2 text-[13px] text-ink-3">
          <Clock className="mt-0.5 size-3.5 shrink-0" strokeWidth={1.75} aria-hidden />
          Lượt so sánh mở lại đúng kết quả đã lưu, không phải chờ AI chạy lại. Xoá lượt so sánh ở trang kết quả.
        </p>
      )}
      {entries.length > limit && (
        <div className="mt-5 flex justify-center">
          <Button
            variant="outline"
            className="h-[38px] rounded-full border-line-strong bg-card px-[18px] font-semibold shadow-xs"
            onClick={() => setLimit((n) => n + PAGE_SIZE)}
          >
            Tải thêm
          </Button>
        </div>
      )}
    </div>
  )
}
