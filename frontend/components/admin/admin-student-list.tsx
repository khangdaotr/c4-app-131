"use client"

import { useMemo, useState } from "react"
import { AlertCircle, Search, SearchX, Users } from "lucide-react"

import { formatCount } from "@/components/admin/admin-bits"
import { AssignDialog } from "@/components/admin/assign-dialog"
import { StudentAvatar } from "@/components/advisor/students/student-bits"
import { EmptyState } from "@/components/common/empty-state"
import { PageHeader } from "@/components/common/page-header"
import { Panel } from "@/components/common/panel"
import { SegmentedControl } from "@/components/common/segmented-control"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { ADVISOR_FEATURES } from "@/lib/config"
import { formatDate, formatRelativeTime } from "@/lib/format"
import type { AdminStudent } from "@/lib/types"
import { useApi } from "@/lib/use-api"
import { cn } from "@/lib/utils"

export type AssignFilter = "all" | "unassigned" | "assigned"

const PAGE_SIZE = 20
// Tính năng cố vấn tạm ẩn (lib/config.ts): bỏ ô chọn, cột Cố vấn và nút Gán / Đổi
const ROW_GRID = ADVISOR_FEATURES
  ? "@4xl:grid @4xl:grid-cols-[22px_minmax(220px,1.6fr)_130px_minmax(170px,1.1fr)_110px_120px_64px] @4xl:items-center @4xl:gap-4"
  : "@4xl:grid @4xl:grid-cols-[minmax(220px,1.6fr)_130px_110px_120px] @4xl:items-center @4xl:gap-4"
// Cột nội dung trên điện thoại (cột 1 là ô chọn khi có phân công cố vấn)
const BODY_COL = ADVISOR_FEATURES ? "col-start-2" : "col-start-1"
const CHECKBOX =
  "size-[18px] rounded-[5px] border-line-strong bg-card data-checked:border-ink data-checked:bg-ink data-checked:text-on-ink data-indeterminate:border-ink data-indeterminate:bg-ink data-indeterminate:text-on-ink"

const matchesFilter = (s: AdminStudent, filter: AssignFilter) =>
  filter === "all" || (filter === "unassigned" ? s.advisor === null : s.advisor !== null)

// Bản vẽ QuanTriSinhVien / GanCoVan: mọi SV kèm cố vấn phụ trách; chọn nhiều SV để gán cùng một cố vấn.
export function AdminStudentList({
  initialFilter,
  initialAdvisor,
  initialQuery,
}: {
  initialFilter: AssignFilter
  initialAdvisor: string
  initialQuery: string
}) {
  const { data: students, error, reload } = useApi(api.listAdminStudents)
  const advisors = useApi(api.listAdminAdvisors)
  const [filter, setFilter] = useState<AssignFilter>(ADVISOR_FEATURES ? initialFilter : "all")
  const [advisorFilter, setAdvisorFilter] = useState(ADVISOR_FEATURES ? initialAdvisor : "all")
  const [query, setQuery] = useState(initialQuery)
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [assigning, setAssigning] = useState<AdminStudent[] | null>(null)

  const counts = useMemo(
    () =>
      Object.fromEntries(
        (["all", "unassigned", "assigned"] as AssignFilter[]).map((f) => [f, (students ?? []).filter((s) => matchesFilter(s, f)).length]),
      ) as Record<AssignFilter, number>,
    [students],
  )
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const digits = q.replace(/\D/g, "")
    return (students ?? []).filter(
      (s) =>
        matchesFilter(s, filter) &&
        (advisorFilter === "all" || s.advisor?.id === advisorFilter) &&
        (!q ||
          s.full_name.toLowerCase().includes(q) ||
          s.email.toLowerCase().includes(q) ||
          (digits.length >= 3 && (s.phone ?? "").replace(/\D/g, "").includes(digits))),
    )
  }, [students, filter, advisorFilter, query])

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const current = Math.min(page, pageCount - 1)
  const rows = filtered.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE)
  const pickedOnPage = rows.filter((s) => selected.has(s.id)).length
  const selectedStudents = (students ?? []).filter((s) => selected.has(s.id))

  const filterItems = [
    { value: "all", label: `Tất cả${students ? ` (${counts.all})` : ""}` },
    { value: "unassigned", label: `Chưa phân công${students ? ` (${counts.unassigned})` : ""}` },
    { value: "assigned", label: `Đã phân công${students ? ` (${counts.assigned})` : ""}` },
  ]
  const advisorItems = [
    { value: "all", label: "Cố vấn: Tất cả" },
    ...(advisors.data ?? []).map((a) => ({ value: a.id, label: a.status === "disabled" ? `${a.full_name} (tạm khoá)` : a.full_name })),
  ]

  function changeFilter(next: AssignFilter) {
    setFilter(next)
    setPage(0)
    history.replaceState(null, "", next === "all" ? location.pathname : `?filter=${next}`)
  }

  function toggle(id: string, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })
  }

  function togglePage(on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev)
      for (const s of rows) {
        if (on) next.add(s.id)
        else next.delete(s.id)
      }
      return next
    })
  }

  return (
    <div className="grid gap-8 md:gap-10">
      <PageHeader
        title="Sinh viên"
        description={
          !students
            ? "Đang tải danh sách…"
            : ADVISOR_FEATURES
              ? `${formatCount(counts.all)} sinh viên, ${formatCount(counts.unassigned)} người chưa được phân công cố vấn.`
              : `${formatCount(counts.all)} sinh viên.`
        }
      />

      {error ? (
        <Panel className="mx-auto w-full max-w-lg p-0">
          <EmptyState
            icon={AlertCircle}
            title="Không tải được danh sách sinh viên"
            description={error.message}
            action={
              <Button size="brand" onClick={reload}>
                Thử lại
              </Button>
            }
          />
        </Panel>
      ) : (
        <section aria-label="Danh sách sinh viên" className="@container min-w-0">
          <div className="flex flex-wrap items-center gap-3 pb-2">
            {ADVISOR_FEATURES && (
              <>
            <SegmentedControl
              aria-label="Lọc theo phân công"
              size="sm"
              value={filter}
              onChange={changeFilter}
              options={[
                { value: "all", label: "Tất cả", count: students ? counts.all : undefined },
                { value: "unassigned", label: "Chưa phân công", count: students ? counts.unassigned : undefined },
                { value: "assigned", label: "Đã phân công", count: students ? counts.assigned : undefined },
              ]}
              className="hidden sm:grid"
            />
            <div className="grid w-full grid-cols-2 gap-2.5 sm:contents">
              <Select items={filterItems} value={filter} onValueChange={(v) => v && changeFilter(v as AssignFilter)}>
                <SelectTrigger aria-label="Lọc theo phân công" className="h-10 w-full rounded-[10px] border-line-strong bg-card px-3.5 text-sm text-ink shadow-xs sm:hidden">
                  <SelectValue className="min-w-0 truncate" />
                </SelectTrigger>
                <SelectContent>
                  {filterItems.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                items={advisorItems}
                value={advisorFilter}
                onValueChange={(v) => {
                  if (!v) return
                  setAdvisorFilter(v)
                  setPage(0)
                }}
              >
                <SelectTrigger aria-label="Lọc theo cố vấn" className="h-10 w-full rounded-[10px] border-line-strong bg-card px-3.5 text-sm text-ink-2 shadow-xs sm:w-auto sm:min-w-[190px]">
                  <SelectValue className="min-w-0 truncate" />
                </SelectTrigger>
                <SelectContent>
                  {advisorItems.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
              </>
            )}
            <span className="hidden flex-1 lg:block" />
            <div className="relative w-full lg:w-[280px]">
              <Search className="pointer-events-none absolute top-1/2 left-3.5 z-[1] size-4 -translate-y-1/2 text-ink-3" strokeWidth={1.75} aria-hidden />
              <Input
                type="search"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value)
                  setPage(0)
                }}
                aria-label="Tìm sinh viên"
                placeholder="Tìm theo tên, email, SĐT"
                className="h-10 rounded-[10px] border-line-strong bg-card pr-3 pl-10 text-sm shadow-xs"
              />
            </div>
          </div>

          <div className={cn("hidden border-b border-line py-3 text-[13px] text-ink-3", ROW_GRID)}>
            {ADVISOR_FEATURES && (
            <Checkbox
              aria-label="Chọn tất cả sinh viên trên trang này"
              className={CHECKBOX}
              checked={rows.length > 0 && pickedOnPage === rows.length}
              indeterminate={pickedOnPage > 0 && pickedOnPage < rows.length}
              onCheckedChange={(on) => togglePage(on)}
              disabled={rows.length === 0}
            />
            )}
            <span>Sinh viên</span>
            <span>Số điện thoại</span>
            {ADVISOR_FEATURES && <span>Cố vấn</span>}
            <span>Ngày tạo</span>
            <span>Hoạt động</span>
            {ADVISOR_FEATURES && <span />}
          </div>

          {!students ? (
            <div className="grid gap-2 pt-3" aria-busy="true" aria-label="Đang tải danh sách">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-14 rounded-xl" />
              ))}
            </div>
          ) : students.length === 0 ? (
            <EmptyState
              icon={Users}
              title="Chưa có sinh viên"
              description={`Sinh viên tự tạo tài khoản sẽ hiện ở đây${ADVISOR_FEATURES ? " để bạn phân công cố vấn" : ""}.`}
            />
          ) : rows.length === 0 ? (
            <EmptyState
              icon={SearchX}
              title={filter === "unassigned" && !query && advisorFilter === "all" ? "Mọi sinh viên đã có cố vấn" : "Không có sinh viên nào khớp"}
              description={
                filter === "unassigned" && !query && advisorFilter === "all"
                  ? "Sinh viên mới tạo tài khoản sẽ hiện ở đây để bạn phân công."
                  : "Thử từ khoá khác hoặc chọn bộ lọc Tất cả."
              }
              action={
                <Button
                  variant="soft"
                  className="h-9 rounded-full px-4"
                  onClick={() => {
                    setQuery("")
                    setAdvisorFilter("all")
                    changeFilter("all")
                  }}
                >
                  Xem tất cả
                </Button>
              }
            />
          ) : (
            <ul>
              {rows.map((s) => {
                const on = selected.has(s.id)
                return (
                  <li
                    key={s.id}
                    className={cn(
                      "grid items-start gap-x-3 gap-y-1.5 border-b border-line py-3.5 transition-colors",
                      ADVISOR_FEATURES ? "grid-cols-[22px_minmax(0,1fr)_auto]" : "grid-cols-[minmax(0,1fr)]",
                      ROW_GRID,
                      on && "-mx-3 rounded-[10px] border-transparent bg-panel px-3",
                    )}
                  >
                    {ADVISOR_FEATURES && (
                      <Checkbox aria-label={`Chọn ${s.full_name}`} className={cn(CHECKBOX, "mt-2.5 @4xl:mt-0")} checked={on} onCheckedChange={(v) => toggle(s.id, v)} />
                    )}
                    <span className="flex min-w-0 items-center gap-3">
                      <StudentAvatar name={s.full_name} src={s.avatar_url} />
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-ink">{s.full_name}</span>
                        <span className="block truncate text-[13px] text-ink-3">{s.email}</span>
                      </span>
                    </span>
                    <span className={cn(BODY_COL, "text-sm text-ink-2 tabular-nums @4xl:col-auto")}>{s.phone ?? "—"}</span>
                    {ADVISOR_FEATURES && (
                    <span className="col-start-2 min-w-0 text-sm @4xl:col-auto">
                      {s.advisor ? (
                        <span className={cn("block truncate", s.advisor.disabled ? "text-ink-3" : "text-ink-2")}>
                          {s.advisor.full_name}
                          {s.advisor.disabled && " (tạm khoá)"}
                        </span>
                      ) : (
                        <Badge variant="warn">
                          <span className="size-1.5 rounded-full bg-current" aria-hidden />
                          Chưa phân công
                        </Badge>
                      )}
                    </span>
                    )}
                    <span className={cn(BODY_COL, "text-sm text-ink-2 @4xl:col-auto")}>
                      <span className="text-ink-3 @4xl:hidden">Tạo </span>
                      {formatDate(s.created_at)}
                      <span className="text-ink-3 @4xl:hidden"> · {s.last_active_at ? formatRelativeTime(s.last_active_at).toLowerCase() : "chưa dùng"}</span>
                    </span>
                    <span className="hidden text-sm text-ink-2 @4xl:block">
                      {s.last_active_at ? formatRelativeTime(s.last_active_at) : "Chưa dùng"}
                    </span>
                    {ADVISOR_FEATURES && (
                    <span className="col-start-3 row-start-1 text-right @4xl:col-auto @4xl:row-auto">
                      <button
                        type="button"
                        onClick={() => setAssigning([s])}
                        className="h-9 px-1 text-sm font-semibold text-blue hover:text-accent-strong"
                        aria-label={`${s.advisor ? "Đổi" : "Gán"} cố vấn cho ${s.full_name}`}
                      >
                        {s.advisor ? "Đổi" : "Gán"}
                      </button>
                    </span>
                    )}
                  </li>
                )
              })}
            </ul>
          )}

          {students && filtered.length > 0 && (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
              <span className="text-ink-3 tabular-nums">
                {current * PAGE_SIZE + 1}–{current * PAGE_SIZE + rows.length} / {formatCount(filtered.length)} sinh viên
              </span>
              {pageCount > 1 && (
                <span className="flex gap-2">
                  <PageButton disabled={current === 0} onClick={() => setPage(current - 1)}>
                    Trước
                  </PageButton>
                  <PageButton disabled={current >= pageCount - 1} onClick={() => setPage(current + 1)}>
                    Sau
                  </PageButton>
                </span>
              )}
            </div>
          )}

          {ADVISOR_FEATURES && selected.size > 0 && (
            <div className="sticky bottom-[calc(var(--tabbar-h)+16px)] z-20 mt-7">
              <div className="flex items-center gap-3 rounded-card bg-ink py-3 pr-3 pl-4 text-on-ink shadow-[0_20px_40px_-18px_rgba(24,24,27,.5)] sm:gap-3.5 sm:pr-3.5 sm:pl-5">
                <span className="font-semibold whitespace-nowrap tabular-nums">
                  Đã chọn {formatCount(selected.size)}
                  <span className="max-sm:hidden"> sinh viên</span>
                </span>
                <button type="button" onClick={() => setSelected(new Set())} className="text-sm whitespace-nowrap text-on-ink/70 hover:text-on-ink">
                  Bỏ chọn
                </button>
                <span className="flex-1" />
                <Button className="h-[38px] rounded-full bg-on-ink px-4 text-sm font-semibold text-ink hover:bg-on-ink/90" onClick={() => setAssigning(selectedStudents)}>
                  Gán cố vấn
                </Button>
              </div>
            </div>
          )}
        </section>
      )}

      {ADVISOR_FEATURES && (
      <AssignDialog
        students={assigning}
        advisors={advisors.data ?? []}
        onOpenChange={(open) => !open && setAssigning(null)}
        onAssigned={() => {
          setSelected(new Set())
          reload()
          advisors.reload()
        }}
      />
      )}
    </div>
  )
}

function PageButton({ disabled, onClick, children }: { disabled: boolean; onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="inline-flex h-8 items-center rounded-full bg-card px-3 text-[13px] font-semibold text-ink shadow-[inset_0_0_0_1px_var(--line-strong)] transition-[background-color,transform] hover:bg-panel active:scale-[.97] disabled:pointer-events-none disabled:opacity-50"
    >
      {children}
    </button>
  )
}
