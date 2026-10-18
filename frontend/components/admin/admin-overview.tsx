"use client"

import { useCallback, useState } from "react"
import { AlertCircle, MessageSquareText, Star } from "lucide-react"

import { ACTIVITY_LABEL, CommentItem, PERIODS, formatChange, formatCount, percentOf } from "@/components/admin/admin-bits"
import { EmptyState } from "@/components/common/empty-state"
import { MetricColumn } from "@/components/common/metric-column"
import { PageHeader } from "@/components/common/page-header"
import { Panel } from "@/components/common/panel"
import { Zone, ZoneLink } from "@/components/common/zone"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { ADVISOR_FEATURES } from "@/lib/config"
import { formatScore } from "@/lib/interview"
import type { AdminPeriod, AdminStats } from "@/lib/types"
import { useApi } from "@/lib/use-api"
import { cn } from "@/lib/utils"

// Tổng quan hệ thống (bản vẽ QuanTriTongQuan). Chỉ số liệu tổng hợp; nhận xét không kèm tên sinh viên.
export function AdminOverview() {
  const [days, setDays] = useState<AdminPeriod>(30)
  const fetchStats = useCallback(() => api.getAdminStats(days), [days])
  // Đổi kỳ thì useApi giữ số liệu cũ cho tới khi có số mới (làm mờ), tránh trang nháy về khung xương
  const { data: stats, error, reload } = useApi(fetchStats)

  const actions = (
    <Select items={PERIODS} value={String(days)} onValueChange={(v) => v && setDays(Number(v) as AdminPeriod)}>
      <SelectTrigger
        aria-label="Kỳ thống kê"
        className="glass h-11 rounded-full border-transparent px-[18px] text-[15px] font-semibold text-ink shadow-xs"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="end">
        {PERIODS.map((p) => (
          <SelectItem key={p.value} value={p.value}>
            {p.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )

  if (error && !stats) {
    return (
      <Panel className="mx-auto mt-10 w-full max-w-lg p-0">
        <EmptyState
          icon={AlertCircle}
          title="Không tải được số liệu hệ thống"
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

  const unassigned = stats?.users.unassigned_count ?? 0
  return (
    <div className="grid gap-14 md:gap-16">
      <PageHeader
        title="Tổng quan hệ thống"
        description={
          !stats
            ? "Đang tải số liệu…"
            : !ADVISOR_FEATURES
              ? "Số liệu người dùng, mức sử dụng và mức hài lòng của hệ thống."
              : unassigned > 0
              ? `${formatCount(unassigned)} sinh viên mới đang chờ phân công cố vấn.`
              : "Mọi sinh viên đều đã có cố vấn phụ trách."
        }
        actions={actions}
      />
      {!stats ? (
        <OverviewSkeleton />
      ) : (
        <div className={cn("grid gap-14 transition-opacity md:gap-16", stats.days !== days && "opacity-60")}>
          <UsersZone stats={stats} />
          <UsageZone stats={stats} />
          <SatisfactionZone stats={stats} />
          <CommentsZone stats={stats} />
        </div>
      )}
    </div>
  )
}

// ---------- Người dùng ----------

function UsersZone({ stats }: { stats: AdminStats }) {
  const u = stats.users
  return (
    <Zone id="admin-users" title="Người dùng">
      <div className={cn("grid gap-x-12 gap-y-10 sm:grid-cols-2", ADVISOR_FEATURES && "lg:grid-cols-3")}>
        <MetricColumn
          label="Sinh viên"
          value={formatCount(u.student_count)}
          delta={u.new_students_week > 0 ? { text: `+${formatCount(u.new_students_week)}`, positive: true } : undefined}
          compare={`${formatCount(u.new_students_week)} mới tuần này`}
          points={u.student_series}
          link={{ label: "Xem thêm", href: "/admin/students" }}
          note="Cập nhật hôm nay"
        />
        <MetricColumn
          label={`Hoạt động ${stats.days} ngày`}
          value={formatCount(u.active_count)}
          compare={`${percentOf(u.active_count, u.student_count)} sinh viên`}
          points={u.active_series}
          link={{ label: "Xem thêm", href: "/admin/students" }}
        />
        {/* Tính năng cố vấn đang tạm ẩn (lib/config.ts) */}
        {ADVISOR_FEATURES && (
        <div className="flex min-w-0 flex-col sm:col-span-2 lg:col-span-1">
          <h3 className="text-base font-semibold text-ink">Cố vấn & phân công</h3>
          <div className="mt-3.5 flex items-center gap-4 border-b border-line pb-[18px]">
            <span className="flex items-baseline gap-2">
              <span className="text-[26px] leading-8 text-ink tabular-nums">{formatCount(u.advisor_count)}</span>
              <span className="text-sm text-ink-3">cố vấn</span>
            </span>
            <span className="ml-auto">
              <ZoneLink href="/admin/advisors">Quản lý cố vấn</ZoneLink>
            </span>
          </div>
          <div className="flex items-center gap-4 pt-[18px]">
            <span className="flex items-baseline gap-2">
              <span className={cn("text-[26px] leading-8 tabular-nums", u.unassigned_count > 0 ? "text-warn" : "text-ink")}>
                {formatCount(u.unassigned_count)}
              </span>
              <span className="text-sm text-ink-3">chưa phân công</span>
            </span>
            <span className="ml-auto">
              <ZoneLink href="/admin/students?filter=unassigned">Phân công</ZoneLink>
            </span>
          </div>
        </div>
        )}
      </div>
    </Zone>
  )
}

// ---------- Mức sử dụng ----------

function UsageZone({ stats }: { stats: AdminStats }) {
  const u = stats.usage
  const change = (n: number | null) => (n !== null && n !== 0 ? { text: formatChange(n), positive: n > 0 } : undefined)
  return (
    <Zone id="admin-usage" title="Mức sử dụng">
      <div className="grid gap-x-14 gap-y-12 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-ink">Lượt dùng theo tuần</h3>
          <WeeklyBars weekly={u.weekly} />
        </div>
        <div className="grid content-start gap-7 sm:grid-cols-3 lg:grid-cols-1">
          <MetricColumn
            label="Lượt phân tích CV"
            value={formatCount(u.analyses)}
            delta={change(u.analyses_change)}
            compare={`${stats.days} ngày`}
          />
          <MetricColumn
            label="Buổi phỏng vấn thử"
            value={formatCount(u.interviews)}
            delta={change(u.interviews_change)}
            compare={`${stats.days} ngày`}
          />
          <MetricColumn
            label="CV tạo từ trình tối ưu"
            value={formatCount(u.optimized_cvs)}
            compare={u.analyses > 0 ? `${percentOf(u.optimized_cvs, u.analyses)} lượt phân tích` : `${stats.days} ngày`}
          />
        </div>
      </div>
    </Zone>
  )
}

/** Tuần bắt đầu ngày 2026-09-28 → "T9/4" (tháng 9, tuần thứ 4 của tháng). */
function weekLabel(weekStart: string) {
  const [, month, day] = weekStart.split("-").map(Number)
  return `T${month}/${Math.ceil(day / 7)}`
}

/** Cột đôi theo tuần: phân tích CV (đậm) và phỏng vấn thử (nhạt), trục 4 mốc. */
function WeeklyBars({ weekly }: { weekly: AdminStats["usage"]["weekly"] }) {
  const peak = Math.max(1, ...weekly.flatMap((w) => [w.analyses, w.interviews]))
  const step = Math.max(1, Math.ceil(peak / 3 / 5) * 5)
  const top = step * 3
  const ticks = [3, 2, 1, 0].map((i) => i * step)
  const total = weekly.reduce((sum, w) => sum + w.analyses + w.interviews, 0)
  return (
    <figure className="mt-5">
      <div className="relative grid h-[200px] grid-cols-[28px_minmax(0,1fr)]">
        <div className="relative text-[11px] text-ink-3 tabular-nums" aria-hidden>
          {ticks.map((t) => (
            <span key={t} className="absolute left-0 -translate-y-1/2" style={{ top: `${(1 - t / top) * 100}%` }}>
              {t}
            </span>
          ))}
        </div>
        <div className="relative">
          {ticks.map((t) => (
            <span
              key={t}
              className="absolute inset-x-0 border-t border-line"
              style={{ top: `${(1 - t / top) * 100}%` }}
              aria-hidden
            />
          ))}
          <ol className="relative flex h-full items-end justify-around gap-2 px-1">
            {weekly.map((w) => (
              <li
                key={w.week_start}
                className="flex h-full items-end gap-1"
                aria-label={`${weekLabel(w.week_start)}: ${w.analyses} lượt phân tích, ${w.interviews} buổi phỏng vấn`}
              >
                <span className="w-3 rounded-t-[4px] bg-blue sm:w-4" style={{ height: `${(w.analyses / top) * 100}%` }} />
                <span className="w-3 rounded-t-[4px] bg-blue/35 sm:w-4" style={{ height: `${(w.interviews / top) * 100}%` }} />
              </li>
            ))}
          </ol>
        </div>
      </div>
      <div className="ml-7 flex justify-around px-1 pt-2 text-[11px] text-ink-3" aria-hidden>
        {weekly.map((w) => (
          <span key={w.week_start} className="w-7 text-center sm:w-9">
            {weekLabel(w.week_start)}
          </span>
        ))}
      </div>
      <figcaption className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-ink-2">
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-[3px] bg-blue" aria-hidden />
          Phân tích CV
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-[3px] bg-blue/35" aria-hidden />
          Buổi phỏng vấn thử
        </span>
        {total === 0 && <span className="text-ink-3">Chưa có lượt dùng nào trong 7 tuần qua.</span>}
      </figcaption>
    </figure>
  )
}

// ---------- Mức hài lòng ----------

function SatisfactionZone({ stats }: { stats: AdminStats }) {
  const s = stats.satisfaction
  const reached = s.csat !== null && s.csat >= s.target
  return (
    <Zone
      id="admin-satisfaction"
      title="Mức hài lòng"
      aside={<span className="text-sm text-ink-3 tabular-nums">Mục tiêu CSAT ≥ {formatScore(s.target)} / 5</span>}
    >
      <div className="grid items-start gap-x-[72px] gap-y-9 md:grid-cols-[280px_minmax(0,1fr)]">
        <div>
          <h3 className="text-base font-semibold text-ink">CSAT trung bình</h3>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-5xl leading-[54px] font-semibold text-ink tabular-nums">
              {s.csat !== null ? formatScore(s.csat) : "—"}
            </span>
            <span className="text-lg text-ink-3">/ 5</span>
          </div>
          <div className="mt-2.5 flex flex-wrap items-center gap-2.5">
            {s.csat !== null && (
              <Badge variant={reached ? "good" : "warn"}>
                <span className="size-1.5 rounded-full bg-current" aria-hidden />
                {reached ? "Đạt mục tiêu" : "Chưa đạt mục tiêu"}
              </Badge>
            )}
            <span className="text-sm text-ink-3 tabular-nums">
              {s.count > 0 ? `${formatCount(s.count)} lượt đánh giá` : `Chưa có đánh giá trong ${stats.days} ngày`}
            </span>
          </div>
        </div>
        <div className="min-w-0">
          <h3 className="mb-3.5 text-base font-semibold text-ink">Phân bố số sao</h3>
          <ul className="grid gap-3">
            {(["5", "4", "3", "2", "1"] as const).map((star) => {
              const n = s.distribution[star]
              const width = s.count > 0 ? (n / s.count) * 100 : 0
              return (
                <li key={star} className="grid grid-cols-[34px_minmax(0,1fr)_44px] items-center gap-3 text-sm">
                  <span className="flex items-center gap-1 text-ink-2 tabular-nums">
                    {star}
                    <Star className="size-3.5 fill-gold text-gold" aria-hidden />
                  </span>
                  <span className="h-1.5 overflow-hidden rounded-full bg-surface" aria-hidden>
                    <span
                      className={cn("block h-full rounded-full", Number(star) >= 3 ? "bg-blue" : "bg-warn")}
                      style={{ width: `${width}%` }}
                    />
                  </span>
                  <span className="text-right text-ink-2 tabular-nums">
                    <span className="sr-only">{star} sao: </span>
                    {percentOf(n, s.count)}
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
      </div>
      <div className="mt-11 grid items-start gap-x-[72px] gap-y-10 border-t border-line pt-8 lg:grid-cols-2">
        <Reasons stats={stats} />
        <Helpfulness stats={stats} />
      </div>
    </Zone>
  )
}

function BlockHead({ title, note }: { title: string; note: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      <span className="text-[13px] text-ink-3">{note}</span>
    </div>
  )
}

/** Lý do sinh viên chọn khi chấm 1–3 sao, nhiều nhất trước. */
function Reasons({ stats }: { stats: AdminStats }) {
  const { reasons, low_count } = stats.satisfaction
  const max = Math.max(1, ...reasons.map((r) => r.count))
  return (
    <div className="min-w-0">
      <BlockHead title="Lý do chưa hài lòng" note={`Từ ${formatCount(low_count)} lượt chấm 1–3 sao`} />
      {reasons.length === 0 ? (
        <p className="mt-4 text-sm text-ink-3">Chưa có lý do nào trong {stats.days} ngày qua.</p>
      ) : (
        <ul className="mt-3.5 grid gap-1">
          {reasons.map((r) => (
            <li key={r.reason} className="grid grid-cols-[minmax(0,1fr)_minmax(80px,140px)_28px] items-center gap-3 py-1.5 text-sm">
              <span className="min-w-0">
                <span className="block truncate font-medium text-ink">{r.label}</span>
                <span className="block truncate text-xs text-ink-3">{r.activities.map((a) => ACTIVITY_LABEL[a] ?? a).join(" · ")}</span>
              </span>
              <span className="h-1.5 overflow-hidden rounded-full bg-surface" aria-hidden>
                <span className="block h-full rounded-full bg-warn" style={{ width: `${(r.count / max) * 100}%` }} />
              </span>
              <span className="text-right text-ink-2 tabular-nums">{formatCount(r.count)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Tỷ lệ like trên tổng like / dislike của từng phần. */
function Helpfulness({ stats }: { stats: AdminStats }) {
  return (
    <div className="min-w-0">
      <BlockHead title="Mức hữu ích" note="Tỷ lệ like trên tổng like / dislike" />
      <ul className="mt-1.5">
        {stats.satisfaction.helpful.map((h) => {
          const rate = h.total > 0 ? Math.round((h.likes / h.total) * 100) : null
          return (
            <li
              key={h.activity}
              className="grid grid-cols-[minmax(0,1fr)_minmax(70px,150px)_44px_72px] items-center gap-3 border-b border-line py-3.5 text-sm last:border-b-0"
            >
              <span className="min-w-0 truncate font-medium text-ink">{h.label}</span>
              <span className="h-1.5 overflow-hidden rounded-full bg-surface" aria-hidden>
                <span
                  className={cn("block h-full rounded-full", rate !== null && rate < 70 ? "bg-warn" : "bg-good")}
                  style={{ width: `${rate ?? 0}%` }}
                />
              </span>
              <span className="text-right text-ink tabular-nums">{rate !== null ? `${rate}%` : "—"}</span>
              <span className="text-right text-ink-3 tabular-nums">{formatCount(h.total)} lượt</span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

// ---------- Nhận xét gần đây ----------

function CommentsZone({ stats }: { stats: AdminStats }) {
  const comments = stats.recent_comments
  return (
    <Zone
      id="admin-comments"
      title="Nhận xét gần đây"
      aside={<ZoneLink href="/admin/feedback">Xem tất cả</ZoneLink>}
    >
      {comments.length === 0 ? (
        <EmptyState
          icon={MessageSquareText}
          title="Chưa có nhận xét"
          description="Nhận xét sinh viên viết kèm đánh giá sao sẽ hiện ở đây."
          className="py-6"
        />
      ) : (
        <ul className="-mt-1 grid gap-x-14 md:grid-cols-2">
          {comments.map((c) => (
            <CommentItem key={c.id} comment={c} />
          ))}
        </ul>
      )}
    </Zone>
  )
}

function OverviewSkeleton() {
  return (
    <div className="grid gap-14 md:gap-16" aria-busy="true" aria-label="Đang tải số liệu">
      {[0, 1, 2].map((zone) => (
        <div key={zone} className="grid gap-7">
          <Skeleton className="h-8 w-48" />
          <div className="grid gap-10 sm:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-[150px] rounded-card" />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
