"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useCallback, useEffect, useEffectEvent, useRef, useState, type ReactNode } from "react"
import { AlertCircle, Circle, CircleCheck, LogOut, Pause, Play, Timer, TimerOff } from "lucide-react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/common/confirm-dialog"
import { EmptyState } from "@/components/common/empty-state"
import { Panel } from "@/components/common/panel"
import { InterviewChat, type Rejection } from "@/components/student/interview/interview-chat"
import { useProfile } from "@/components/shell/profile-context"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { api, ApiError } from "@/lib/api"
import { PAUSE_MAX_SECONDS, QUESTION_THEMES, SECONDS_PER_QUESTION, STAR_META, STAR_ORDER, mmss } from "@/lib/interview"
import { setLeaveGuard } from "@/lib/leave-guard"
import type { InterviewSession, InterviewTurn } from "@/lib/types"
import { useApi } from "@/lib/use-api"
import { SetFocusTitle } from "@/components/shell/focus-title"
import { cn } from "@/lib/utils"

/** Hết giờ mà gửi thất bại (mất mạng...) thì thử lại sau ngần này. */
const RETRY_MS = 5000

// Figma: frame "Phòng phỏng vấn (Distraction-free)" (18:3478). PRD US-SV-04, S6.
export function InterviewRoom({ sessionId }: { sessionId: string }) {
  const fetchSession = useCallback(() => api.getInterview(sessionId), [sessionId])
  const { data: session, error, reload } = useApi(fetchSession)

  if (error) {
    // 404: buổi đã bị huỷ/không tồn tại; 410: SV rời phòng quá lâu nên buổi đã bị huỷ.
    const gone = error instanceof ApiError && (error.status === 404 || error.status === 410)
    return (
      <Panel className="mx-auto mt-10 w-full max-w-lg p-0">
        <EmptyState
          icon={AlertCircle}
          title={gone ? "Buổi phỏng vấn không còn" : "Không mở được phòng phỏng vấn"}
          description={error.message}
          action={
            gone ? (
              <Button size="brand" nativeButton={false} render={<Link href="/student/interview/new" />}>
                Thiết lập buổi mới
              </Button>
            ) : (
              <Button size="brand" onClick={reload}>
                Thử lại
              </Button>
            )
          }
        />
      </Panel>
    )
  }

  if (!session) {
    return (
      <div className="grid gap-6" aria-busy="true" aria-label="Đang chuẩn bị phòng phỏng vấn">
        <Skeleton className="h-16 rounded-xl" />
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_300px]">
          <Skeleton className="h-[480px] rounded-card" />
          <Skeleton className="h-[360px] rounded-card" />
        </div>
      </div>
    )
  }

  return <Room key={session.id} initial={session} />
}

function Room({ initial }: { initial: InterviewSession }) {
  const router = useRouter()
  const profile = useProfile()
  const total = initial.question_count

  const [turns, setTurns] = useState(initial.turns)
  const [current, setCurrent] = useState(initial.current_question)
  const [finished, setFinished] = useState(initial.status === "completed")
  const [rejections, setRejections] = useState<Rejection[]>([])
  const [draft, setDraft] = useState("")
  const [sending, setSending] = useState(false)
  const [confirmEnd, setConfirmEnd] = useState(false)
  // Đồng hồ: hạn chót tính theo giờ máy từ số giây còn lại backend trả về.
  const [now, setNow] = useState(() => Date.now())
  const [deadlineAt, setDeadlineAt] = useState<number | null>(() =>
    initial.seconds_left !== null ? Date.now() + initial.seconds_left * 1000 : null,
  )
  const [pausedUntil, setPausedUntil] = useState<number | null>(() =>
    initial.paused ? Date.now() + (initial.pause_seconds_left ?? PAUSE_MAX_SECONDS) * 1000 : null,
  )
  const [frozenLeft, setFrozenLeft] = useState(initial.seconds_left ?? 0)
  const [pauseUsed, setPauseUsed] = useState(initial.pause_used)
  const submittingRef = useRef(false)
  const resumingRef = useRef(false)

  const paused = pausedUntil !== null
  const secondsLeft = paused ? frozenLeft : deadlineAt === null ? 0 : Math.max(0, Math.ceil((deadlineAt - now) / 1000))
  const pauseLeft = paused ? Math.max(0, Math.ceil((pausedUntil - now) / 1000)) : 0
  const active = !finished && current !== null

  function applyTimer(session: InterviewSession) {
    const t = Date.now()
    setPauseUsed(session.pause_used)
    if (session.paused) {
      setPausedUntil(t + (session.pause_seconds_left ?? PAUSE_MAX_SECONDS) * 1000)
      setFrozenLeft(session.seconds_left ?? 0)
    } else {
      setPausedUntil(null)
      setDeadlineAt(session.seconds_left !== null ? t + session.seconds_left * 1000 : null)
    }
  }

  async function submit(timedOut: boolean) {
    if (!current || submittingRef.current) return
    submittingRef.current = true
    setSending(true)
    try {
      const res = await api.submitAnswer(initial.id, { question_index: current.index, text: draft, timed_out: timedOut })
      if (!res.allowed) {
        // Guardrail: không tính câu, giữ nguyên nội dung để SV sửa; đồng hồ vẫn chạy.
        setRejections((r) => [
          ...r,
          { id: `${current.index}-${Date.now()}`, questionIndex: current.index, reason: res.reason ?? "Câu trả lời chưa hợp lệ." },
        ])
        if (res.seconds_left !== null) setDeadlineAt(Date.now() + res.seconds_left * 1000)
        return
      }
      setTurns((t) => [...t, res.turn!])
      setDraft("")
      if (res.finished) {
        setFinished(true)
        setCurrent(null)
        setDeadlineAt(null)
      } else {
        setCurrent(res.next_question)
        setDeadlineAt(Date.now() + (res.seconds_left ?? SECONDS_PER_QUESTION) * 1000)
      }
    } catch (err) {
      // Buổi đã đổi trạng thái ở backend (hết hạn, đã trả lời câu này...): tải lại để lấy trạng thái đúng.
      if (err instanceof ApiError && (err.status === 404 || err.status === 409 || err.status === 410)) {
        toast.error(err.message)
        window.location.reload()
        return
      }
      if (timedOut) {
        toast.error("Không gửi được câu trả lời do lỗi kết nối. Hệ thống sẽ thử lại sau vài giây.")
        setDeadlineAt(Date.now() + RETRY_MS)
      } else {
        toast.error(err instanceof Error ? err.message : "Không gửi được câu trả lời.")
      }
    } finally {
      submittingRef.current = false
      setSending(false)
    }
  }

  async function pause() {
    try {
      applyTimer(await api.pauseInterview(initial.id))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Không tạm dừng được.")
    }
  }

  async function resume() {
    if (resumingRef.current) return
    resumingRef.current = true
    try {
      applyTimer(await api.resumeInterview(initial.id))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Không tiếp tục được.")
    } finally {
      resumingRef.current = false
    }
  }

  // Mỗi nhịp đồng hồ: hết giờ thì tự nộp phần đang gõ; hết 1 phút tạm dừng thì tự chạy lại.
  const onTick = useEffectEvent((t: number) => {
    setNow(t)
    if (!active || sending) return
    if (pausedUntil !== null) {
      if (t >= pausedUntil) void resume()
      return
    }
    if (deadlineAt !== null && t >= deadlineAt) void submit(true)
  })
  useEffect(() => {
    const timer = setInterval(() => onTick(Date.now()), 500)
    return () => clearInterval(timer)
  }, [])

  // Đang làm dở: rời phòng = bỏ dở buổi (bị xoá, không tính lượt), nên hỏi xác nhận trước.
  useEffect(() => {
    if (!active) {
      setLeaveGuard(null)
      return
    }
    setLeaveGuard(
      `Đã trả lời ${turns.length}/${total} câu. Buổi này sẽ không được lưu và không tính lượt.`,
      () => api.abandonInterview(initial.id),
    )
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener("beforeunload", warn)
    return () => {
      setLeaveGuard(null)
      window.removeEventListener("beforeunload", warn)
    }
  }, [active, turns.length, total, initial.id])

  async function endEarly() {
    setConfirmEnd(false)
    setLeaveGuard(null)
    try {
      await api.abandonInterview(initial.id)
    } catch {
      // Backend vẫn tự huỷ buổi bỏ dở khi quá hạn.
    }
    toast.info("Đã kết thúc buổi phỏng vấn. Buổi này không được lưu và không tính lượt.")
    // Quay lại thiết lập với đúng vị trí đang luyện
    router.push(`/student/interview/new?jd=${encodeURIComponent(initial.jd.id)}`)
  }

  const answeredIndexes = new Set(turns.map((t) => t.index))
  const urgent = active && !paused && secondsLeft <= 60

  return (
    <div className="grid gap-8">
      <SetFocusTitle title={initial.jd.title} />
      <RoomHeader
        title={initial.jd.title}
        tone={finished ? "done" : paused ? "paused" : "live"}
        status={finished ? "Đã hoàn thành" : paused ? `Đang tạm dừng · tự chạy lại sau ${pauseLeft} giây` : "Đang phỏng vấn"}
      >
        <RoomProgress
          total={total}
          answered={answeredIndexes}
          currentIndex={current?.index ?? null}
          label={`Câu ${Math.min(turns.length + (finished ? 0 : 1), total)} / ${total}`}
        />

        {active && (
          <div className="flex items-center gap-1.5 sm:gap-2">
            <span
              role="timer"
              aria-label={`Còn ${secondsLeft} giây cho câu này`}
              className={cn(
                "inline-flex h-[38px] items-center gap-1.5 rounded-full px-3 text-[15px] font-semibold tabular-nums sm:gap-2 sm:px-3.5",
                urgent ? "bg-warn-soft" : "bg-surface",
                secondsLeft <= 10 && !paused ? "animate-pulse text-bad" : urgent ? "text-warn" : "text-ink",
              )}
            >
              <Timer className="size-4" strokeWidth={1.75} aria-hidden />
              {mmss(secondsLeft)}
            </span>
            {paused ? (
              <Button
                variant="dark"
                className="h-[38px] rounded-full px-3 font-semibold sm:px-3.5"
                aria-label="Tiếp tục"
                onClick={() => void resume()}
              >
                <Play aria-hidden />
                <span className="hidden sm:inline">Tiếp tục</span>
              </Button>
            ) : (
              <Button
                variant="soft"
                className="h-[38px] rounded-full px-3 font-semibold sm:px-3.5"
                aria-label={pauseUsed ? "Đã dùng tạm dừng" : "Tạm dừng"}
                onClick={() => void pause()}
                disabled={pauseUsed || sending}
                title={pauseUsed ? "Mỗi buổi chỉ được tạm dừng 1 lần" : `Tạm dừng tối đa ${PAUSE_MAX_SECONDS} giây`}
              >
                <Pause aria-hidden />
                <span className="hidden sm:inline">{pauseUsed ? "Đã dùng tạm dừng" : "Tạm dừng"}</span>
              </Button>
            )}
            <Button
              variant="ghost"
              className="h-[38px] rounded-full px-3 font-semibold text-bad hover:bg-bad-soft hover:text-bad sm:px-3.5"
              aria-label="Kết thúc sớm"
              onClick={() => setConfirmEnd(true)}
            >
              <LogOut aria-hidden />
              <span className="hidden sm:inline">Kết thúc sớm</span>
            </Button>
          </div>
        )}
      </RoomHeader>

      <div className="grid items-start gap-x-12 gap-y-10 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0">
          <InterviewChat
            total={total}
            turns={turns}
            current={finished ? null : current}
            rejections={rejections}
            candidateName={profile?.full_name}
            candidateAvatar={profile?.avatar_url}
            draft={draft}
            onDraftChange={setDraft}
            onSend={() => void submit(false)}
            sending={sending}
            paused={paused}
            finished={finished}
            reportHref={`/student/interview/${encodeURIComponent(initial.id)}/report`}
          />
        </div>

        <aside className="grid min-w-0 gap-10 lg:sticky lg:top-44">
          <QuestionRoadmap total={total} turns={turns} currentIndex={finished ? null : (current?.index ?? null)} />
          {!finished && <StarGuide />}
        </aside>
      </div>

      <ConfirmDialog
        open={confirmEnd}
        onOpenChange={setConfirmEnd}
        destructive
        icon={LogOut}
        title="Kết thúc buổi phỏng vấn?"
        description="Buổi này sẽ không được lưu và không tính lượt."
        facts={[
          { label: "Đã trả lời", value: `${turns.length} / ${total} câu` },
          { label: "Báo cáo", value: "Không có" },
        ]}
        cancelLabel="Ở lại phòng"
        confirmLabel="Kết thúc, không lưu"
        onConfirm={endEarly}
      />
    </div>
  )
}

// ---------- Thanh trạng thái, tiến độ và lộ trình câu hỏi ----------

type RoomTone = "idle" | "live" | "paused" | "done"

const TONE: Record<RoomTone, { text: string; dot: string }> = {
  idle: { text: "text-ink-3", dot: "bg-ink-3" },
  live: { text: "text-bad", dot: "animate-pulse bg-bad" },
  paused: { text: "text-warn", dot: "bg-warn" },
  done: { text: "text-good", dot: "bg-good" },
}

/** Thanh dính dưới header: vị trí, trạng thái buổi; children là tiến độ câu, đồng hồ và các nút điều khiển. */
export function RoomHeader({
  title,
  status,
  tone,
  children,
}: {
  title: string
  status: string
  tone: RoomTone
  children?: ReactNode
}) {
  return (
    <div className="sticky top-16 z-20 -mx-4 -mt-6 border-b border-line bg-card/90 px-4 py-2.5 backdrop-blur-md sm:-mx-6 sm:-mt-8 sm:px-6 sm:py-3">
      {/* Điện thoại: tên vị trí + đồng hồ/nút trên một dòng, tiến độ xuống dòng dưới để thanh dính thấp gọn */}
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <div className="grid min-w-0 flex-1 sm:flex-none">
          <p className="truncate text-base font-semibold text-ink">{title}</p>
          <p className={cn("flex items-center gap-1.5 text-[13px] font-medium", TONE[tone].text)}>
            <span className={cn("size-1.5 rounded-full", TONE[tone].dot)} aria-hidden />
            {status}
          </p>
        </div>
        {children}
      </div>
    </div>
  )
}

/** "Câu x / y" kèm các đoạn tiến độ (đã trả lời: đậm, đang trả lời: màu nhấn). */
export function RoomProgress({
  total,
  answered,
  currentIndex,
  label,
}: {
  total: number
  answered: Set<number>
  currentIndex: number | null
  label: string
}) {
  return (
    <div className="order-last flex basis-full items-center gap-3 sm:order-none sm:basis-auto">
      <span className="text-[13px] font-semibold text-ink tabular-nums">{label}</span>
      <span className="flex gap-1.5" aria-hidden>
        {Array.from({ length: total }, (_, i) => i + 1).map((index) => (
          <span
            key={index}
            className={cn(
              "h-1 w-7 rounded-full transition-colors duration-300 sm:w-9",
              answered.has(index) ? "bg-ink" : index === currentIndex ? "bg-blue" : "bg-line-strong",
            )}
          />
        ))}
      </span>
    </div>
  )
}

/** Lộ trình các câu; chỉ cho biết đã trả lời hay chưa, không hiện điểm (điểm có trong báo cáo sau buổi). */
export function QuestionRoadmap({
  total,
  turns,
  currentIndex,
}: {
  total: number
  turns: InterviewTurn[]
  currentIndex: number | null
}) {
  return (
    <section aria-labelledby="roadmap-title" className="grid gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="roadmap-title" className="text-base font-semibold text-ink">
          Lộ trình câu hỏi
        </h2>
        <span className="text-sm text-ink-3 tabular-nums">
          {turns.length} / {total}
        </span>
      </div>
      <ol className="grid gap-1">
        {QUESTION_THEMES.slice(0, total).map((theme, i) => {
          const index = i + 1
          const turn = turns.find((t) => t.index === index)
          const isCurrent = !turn && index === currentIndex
          const timedOutBlank = turn?.timed_out && !turn.answer
          return (
            <li
              key={theme}
              className={cn("-mx-3 flex gap-2.5 rounded-xl px-3 py-2.5 text-sm", isCurrent && "bg-panel")}
              aria-current={isCurrent ? "step" : undefined}
            >
              {turn ? (
                timedOutBlank ? (
                  <TimerOff className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
                ) : (
                  <CircleCheck className="mt-0.5 size-4 shrink-0 text-good" aria-hidden />
                )
              ) : isCurrent ? (
                <span className="mt-0.5 grid size-4 shrink-0 place-items-center rounded-full border-2 border-blue" aria-hidden>
                  <span className="size-1.5 rounded-full bg-blue" />
                </span>
              ) : (
                <Circle className="mt-0.5 size-4 shrink-0 text-line-strong" aria-hidden />
              )}
              <span className="grid min-w-0 flex-1">
                <span className={cn("truncate text-ink", isCurrent && "font-semibold")}>
                  Câu {index}: {theme}
                </span>
                <span className={cn("text-[13px]", timedOutBlank ? "text-warn" : "text-ink-3")}>
                  {turn ? (timedOutBlank ? "Hết giờ, chưa trả lời" : "Đã trả lời") : isCurrent ? "Đang trả lời" : "Sắp tới"}
                </span>
              </span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

/** 4 ô gợi ý trả lời theo STAR, tĩnh (không phản ứng theo câu trả lời, DESIGN.md mục 7). */
function StarGuide() {
  return (
    <section aria-labelledby="star-guide-title" className="grid gap-3">
      <h2 id="star-guide-title" className="text-base font-semibold text-ink">
        Gợi ý trả lời theo STAR
      </h2>
      <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-1">
        {STAR_ORDER.map((key) => (
          <div key={key} className="min-w-0 rounded-xl bg-panel px-3.5 py-3">
            <p className="flex items-center gap-2 text-sm font-semibold text-ink">
              <span className="grid size-[22px] place-items-center rounded-[7px] bg-card text-xs font-semibold shadow-xs">
                {STAR_META[key].letter}
              </span>
              {STAR_META[key].label}
            </p>
            <p className="mt-1 text-xs leading-[18px] text-ink-3">{STAR_META[key].hint}</p>
          </div>
        ))}
      </div>
    </section>
  )
}
