"use client"

import Link from "next/link"
import { useCallback, useEffect, useState } from "react"
import { AlertCircle, ChevronDown, ChevronRight, TimerOff, UserPlus } from "lucide-react"

import { InterviewFeedback, plainText } from "@/components/common/interview-feedback"
import { FeedbackWidget } from "@/components/FeedbackWidget"
import { EmptyState } from "@/components/common/empty-state"
import { PageHeader } from "@/components/common/page-header"
import { Panel } from "@/components/common/panel"
import { RateRow } from "@/components/common/rate-dialog"
import { Zone, ZoneLink } from "@/components/common/zone"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ADVISOR_FEATURES } from "@/lib/config"
import { api } from "@/lib/api"
import { formatDate } from "@/lib/format"
import { STAR_META, STAR_ORDER, TREND_THRESHOLD } from "@/lib/interview"
import type { InterviewReport as Report, InterviewTurn, ReportAdvisorReview, StarCriterion } from "@/lib/types"
import { useApi } from "@/lib/use-api"
import { cn } from "@/lib/utils"

/** Điểm phỏng vấn luôn một chữ số thập phân: "3,8" (DESIGN.md 8.1, không gắn nhãn). */
const score1 = (n: number) => n.toLocaleString("vi-VN", { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const signed = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${score1(Math.abs(n))}`
/** "09/10" */
const shortDate = (iso: string) => formatDate(iso).slice(0, 5)

// Bản vẽ "Báo cáo phỏng vấn" (WIREFRAMES A14). PRD US-SV-04 / US-SV-06, S7 + S7b.
export function InterviewReport({ sessionId }: { sessionId: string }) {
  const fetchReport = useCallback(() => api.getInterviewReport(sessionId), [sessionId])
  const { data: report, error, reload } = useApi(fetchReport)

  if (error) {
    return (
      <Panel className="mx-auto mt-10 w-full max-w-lg p-0">
        <EmptyState
          icon={AlertCircle}
          title="Không tải được báo cáo phỏng vấn"
          description={error.message}
          action={
            <Button size="brand" onClick={reload}>
              Thử lại
            </Button>
          }
        />
      </Panel>
    )
  }

  if (!report) {
    return (
      <div className="grid gap-14 md:gap-16" aria-busy="true" aria-label="Đang tải báo cáo">
        <div className="grid gap-3 pt-8 pb-2 md:pt-12">
          <Skeleton className="h-9 w-2/3 max-w-md rounded-xl md:h-[46px]" />
          <Skeleton className="h-6 w-1/2 max-w-sm rounded-lg" />
        </div>
        {[160, 220, 320].map((h) => (
          <div key={h} className="grid gap-7">
            <Skeleton className="h-8 w-56 rounded-lg" />
            <Skeleton className="rounded-card" style={{ height: h }} />
          </div>
        ))}
      </div>
    )
  }

  return <ReportView report={report} />
}

// Bố cục vùng và khối kiểu Stripe (DESIGN.md 3.6): tiêu đề trang, các vùng cách nhau 56–72px, không thẻ bao.
function ReportView({ report }: { report: Report }) {
  const retryHref = `/student/interview/new?jd=${encodeURIComponent(report.jd.id)}`
  const minutes = Math.max(1, Math.round(report.duration_seconds / 60))
  const meta = [
    report.jd.company,
    shortDate(report.completed_at),
    `${report.turns.length} câu`,
    `${minutes} phút`,
    report.timed_out_count > 0 ? `${report.timed_out_count} câu hết giờ` : null,
    report.interview_mode === "jd_only" ? "Không dùng CV" : null,
  ]
    .filter(Boolean)
    .join(" · ")

  return (
    <div className="grid gap-14 md:gap-[72px]">
      <PageHeader
        title={report.jd.title}
        description={meta}
        actions={
          <>
            {ADVISOR_FEATURES && (
              <Button
                variant="ghost"
                size="brand"
                className="glass text-ink shadow-xs hover:bg-card"
                nativeButton={false}
                render={<Link href="/student/share" />}
              >
                <UserPlus strokeWidth={1.75} aria-hidden />
                Chia sẻ với cố vấn
              </Button>
            )}
            <Button size="brand" nativeButton={false} render={<Link href={retryHref} />}>
              Luyện lại vị trí này
              <ChevronRight aria-hidden />
            </Button>
          </>
        }
      />

      <ScoreZone report={report} />

      <div className={cn("grid gap-14 lg:gap-16", ADVISOR_FEATURES && "lg:grid-cols-2")}>
        {/* Chỉ gợi ý khung trả lời, không viết sẵn câu trả lời chứa thành tích SV chưa nêu */}
        <Zone id="guidance-title" title="Hướng dẫn cải thiện" className="min-w-0 [&>div:last-child]:pt-2">
          <ol>
            {report.guidance.map((g, i) => (
              <li key={g} className="flex gap-3.5 border-b border-line py-4">
                <span className="grid size-[26px] shrink-0 place-items-center rounded-full bg-blue-soft text-[13px] font-semibold text-accent-strong tabular-nums">
                  {i + 1}
                </span>
                <p className="min-w-0 pt-0.5 leading-6 text-ink">{g}</p>
              </li>
            ))}
          </ol>
          <p className="mt-3.5 text-[13px] text-ink-3">Hệ thống chỉ gợi ý cách trình bày, không viết sẵn câu trả lời.</p>
        </Zone>

        {ADVISOR_FEATURES && (
        <Zone id="advisor-title" title="Nhận xét của cố vấn" className="min-w-0 [&>div:last-child]:pt-[22px]">
          {report.advisor_review ? (
            <AdvisorReview review={report.advisor_review} />
          ) : (
            <div className="grid gap-3">
              <p className="text-ink-2">
                Chưa có nhận xét. Chia sẻ báo cáo này với cố vấn để nhận góp ý về cách trả lời.
              </p>
              <ZoneLink href="/student/share">Chia sẻ với cố vấn</ZoneLink>
            </div>
          )}
        </Zone>
        )}
      </div>

      <Zone id="turns-title" title="Chi tiết từng câu" className="[&>div:last-child]:pt-1.5">
        <TurnList turns={report.turns} />
      </Zone>

      <Csat report={report} />
    </div>
  )
}

// ---------- Điểm buổi phỏng vấn ----------

function ScoreZone({ report }: { report: Report }) {
  const c = report.comparison
  const delta = c?.delta ?? null
  const deltaClass =
    delta === null
      ? ""
      : delta >= TREND_THRESHOLD
        ? "border-good-line bg-good-soft text-good"
        : delta <= -TREND_THRESHOLD
          ? "border-warn-line bg-warn-soft text-warn"
          : "border-line-strong bg-surface text-ink-2"

  return (
    <Zone id="score-title" title="Điểm buổi phỏng vấn">
      <div className="flex flex-wrap gap-x-16 gap-y-10">
        <div className="min-w-[200px] flex-none">
          <div className="flex h-[22px] items-center gap-2">
            <h3 className="text-base font-semibold text-ink">Điểm trung bình</h3>
            {delta !== null && (
              <span
                className={cn("rounded-badge border px-1.5 text-xs leading-5 font-semibold tabular-nums", deltaClass)}
                title="So với buổi đầu tiên của vị trí này"
              >
                {signed(delta)}
              </span>
            )}
          </div>
          <p className="mt-1.5 text-5xl leading-[56px] font-semibold tracking-[-0.02em] text-ink tabular-nums">
            {score1(report.overall_score)}
            <span className="text-xl font-medium text-ink-3"> / 5</span>
          </p>
          <p className="mt-1 text-sm text-ink-3">
            {c
              ? `Buổi đầu tiên ${score1(c.first_score)} · ${shortDate(c.first_completed_at)}`
              : "Buổi đầu tiên của vị trí này"}
          </p>
        </div>

        <ul className="grid min-w-0 flex-[1_1_560px] grid-cols-2 gap-x-6 gap-y-8 sm:gap-x-10 md:grid-cols-4 lg:border-l lg:border-line lg:pl-10">
          {STAR_ORDER.map((key) => (
            <StarColumn key={key} criterion={key} score={report.star[key]} weakest={key === report.weakest} />
          ))}
        </ul>
      </div>
    </Zone>
  )
}

function StarColumn({ criterion, score, weakest }: { criterion: StarCriterion; score: number; weakest: boolean }) {
  const meta = STAR_META[criterion]
  return (
    <li className="min-w-0">
      <div className="flex h-[22px] items-center gap-2">
        <h3 className="truncate text-base font-semibold text-ink">{meta.label}</h3>
        <span className="text-[13px] text-ink-3">{meta.letter}</span>
      </div>
      {/* Badge "Yếu nhất" đặt cạnh số để 4 cột luôn thẳng hàng khi cột hẹp */}
      <p className="mt-2 mb-3 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-[26px] leading-8 font-medium text-ink tabular-nums">{score1(score)}</span>
        {weakest && <Badge variant="warn">Yếu nhất</Badge>}
      </p>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-surface"
        role="meter"
        aria-label={`${meta.label}: ${score1(score)} trên 5`}
        aria-valuemin={0}
        aria-valuemax={5}
        aria-valuenow={score}
      >
        <div className={cn("h-full rounded-full", weakest ? "bg-gold" : "bg-blue")} style={{ width: `${(score / 5) * 100}%` }} />
      </div>
    </li>
  )
}

// ---------- Nhận xét của cố vấn ----------

const initials = (name: string) =>
  name
    .trim()
    .split(/\s+/)
    .slice(-2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("")

/** Nhận xét của cố vấn phụ trách; mở báo cáo là tính đã xem (cố vấn thấy "SV đã xem"). */
function AdvisorReview({ review }: { review: ReportAdvisorReview }) {
  useEffect(() => {
    if (!review.read) void api.markAdvisorFeedbackRead(review.id).catch(() => undefined)
  }, [review.id, review.read])

  return (
    <div>
      <div className="flex gap-3.5">
        <span
          className="grid size-10 shrink-0 place-items-center rounded-full bg-good-soft text-[13px] font-semibold text-good"
          aria-hidden
        >
          {initials(review.advisor_name)}
        </span>
        <div className="min-w-0">
          <p className="text-sm">
            <span className="font-semibold text-ink">{review.advisor_name}</span>
            <span className="text-ink-3"> · {shortDate(review.updated_at)}</span>
          </p>
          <p className="mt-1.5 break-words whitespace-pre-line text-ink-2">{review.comment}</p>
        </div>
      </div>
      <p className="mt-[18px] text-[13px] text-ink-3">Điểm AI giữ nguyên. Nhận xét giúp bạn biết nên luyện gì tiếp.</p>
    </div>
  )
}

// ---------- Chi tiết từng câu ----------

/** Mỗi lúc chỉ mở một câu: mở câu khác thì câu đang mở tự đóng lại. Mặc định mở câu đầu tiên. */
function TurnList({ turns }: { turns: InterviewTurn[] }) {
  const [openId, setOpenId] = useState<string | null>(turns[0]?.id ?? null)
  return (
    <div>
      {turns.map((turn) => (
        <TurnItem
          key={turn.id}
          turn={turn}
          open={openId === turn.id}
          onToggle={() => setOpenId((id) => (id === turn.id ? null : turn.id))}
        />
      ))}
    </div>
  )
}

function TurnItem({ turn, open, onToggle }: { turn: InterviewTurn; open: boolean; onToggle: () => void }) {
  const panelId = `turn-${turn.id}`
  const lowest = turn.star ? STAR_ORDER.reduce((a, b) => (turn.star![b] < turn.star![a] ? b : a)) : null

  return (
    <div className="border-b border-line">
      <h3>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={onToggle}
          className="-mx-2.5 flex w-[calc(100%+20px)] items-center gap-3.5 rounded-lg px-2.5 py-4 text-left transition-colors hover:bg-panel"
        >
          <span className="w-5 shrink-0 text-sm font-semibold text-ink-3 tabular-nums">{turn.index}</span>
          <span className="min-w-0 flex-1 font-medium text-ink">{plainText(turn.question)}</span>
          {turn.timed_out && (
            <Badge variant="warn" className="hidden sm:inline-flex">
              <TimerOff aria-hidden />
              Hết giờ
            </Badge>
          )}
          <span className="shrink-0 font-semibold text-ink tabular-nums">{score1(turn.score ?? 0)}</span>
          <ChevronDown
            className={cn("size-[18px] shrink-0 text-ink-3 transition-transform duration-200", open && "rotate-180")}
            strokeWidth={1.75}
            aria-hidden
          />
        </button>
      </h3>
      {open && (
        <div id={panelId} className="grid gap-8 pt-1 pb-6 md:grid-cols-2 md:pl-9">
          <div className="min-w-0">
            <p className="mb-2 text-[13px] text-ink-3">Câu trả lời của bạn · {turn.theme}</p>
            {turn.answer ? (
              <p className="break-words whitespace-pre-line text-ink-2">{turn.answer}</p>
            ) : (
              <p className="text-ink-3 italic">Hết giờ khi chưa có câu trả lời.</p>
            )}
          </div>
          <div className="min-w-0">
            <p className="mb-2 text-[13px] text-ink-3">Nhận xét</p>
            {turn.feedback && <InterviewFeedback text={turn.feedback} className="mb-3.5" />}
            {turn.star && (
              <div className="flex flex-wrap gap-2">
                {STAR_ORDER.map((key) => (
                  <Badge key={key} variant={key === lowest ? "warn" : "neutral"} className="tabular-nums">
                    {STAR_META[key].letter} {score1(turn.star![key])}
                  </Badge>
                ))}
              </div>
            )}
            <FeedbackWidget variant="thumbs" responseId={turn.id} activity="interview_turn" className="mt-4" />
          </div>
        </div>
      )}
    </div>
  )
}

// ---------- Khảo sát CSAT (US-SV-06) ----------

function Csat({ report }: { report: Report }) {
  return (
    <RateRow
      responseId={report.response_id}
      activity="interview"
      title="Đánh giá buổi phỏng vấn"
      subtitle={report.jd.company ? `${report.jd.title} · ${report.jd.company}` : report.jd.title}
      askReuse
      question="Bạn thấy buổi luyện phỏng vấn này thế nào?"
      buttonLabel="Đánh giá buổi này"
      doneLabel="buổi này"
      className="-mt-4 border-t border-line pt-8 md:-mt-6"
    />
  )
}
