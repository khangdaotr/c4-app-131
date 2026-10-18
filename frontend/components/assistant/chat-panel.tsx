'use client';

import { useEffect, useMemo, useRef, useState } from "react"
import {
  AlertCircle,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  Copy,
  Crosshair,
  Info,
  MessageCircleQuestion,
  RotateCw,
  Sparkles,
  Square,
  SquarePen,
  ThumbsDown,
  ThumbsUp,
  X,
} from "lucide-react"
import { toast } from "sonner"

import { ActionBadges } from "@/components/assistant/action-badges"
import { AssistantMarkdown } from "@/components/assistant/assistant-markdown"
import { AssistantCards, AssistantChips } from "@/components/assistant/assistant-cards"
import { useAssistant } from "@/components/assistant/assistant-provider"
import { targetLabel } from "@/components/assistant/element-highlighter"
import { SourceAccordion } from "@/components/assistant/source-accordion"
import { getBreadcrumb, shellOf } from "@/components/shell/nav-config"
import { useProfile } from "@/components/shell/profile-context"
import { deleteFeedback, getAssistantStatus, submitFeedback, type AssistantStatusResponse } from "@/lib/assistant-api"
import { isAssistantRefusal } from "@/lib/assistant-response"
import { ADVISOR_FEATURES } from "@/lib/config"
import { cn } from "@/lib/utils"
import type { UserRole } from "@/types/assistant"

/** Câu hỏi gợi ý theo trang đang mở (khớp tài liệu hướng dẫn của trợ lý). */
const SUGGESTIONS: [RegExp, string[]][] = [
  [/^\/student\/analysis/, ["Nút bắt đầu phân tích ở đâu?", "Mức phù hợp được tính thế nào?", "Dán JD cần những gì?", "So sánh nhiều vị trí cùng lúc thế nào?"]],
  [/^\/student\/cv/, ["Làm sao để tải CV lên?", "CV hỗ trợ định dạng nào?", "Đổi CV đang dùng thế nào?", "Khôi phục phiên bản cũ ra sao?"]],
  [/^\/student\/interview/, ["Trả lời theo khung STAR thế nào?", "Mỗi tuần được luyện mấy buổi?", "Xem báo cáo buổi cũ ở đâu?", ADVISOR_FEATURES ? "Chia sẻ báo cáo cho cố vấn thế nào?" : "Điểm STAR được chấm thế nào?"]],
  [/^\/student\/history/, ["Lọc chỉ các buổi phỏng vấn thế nào?", "Vì sao chưa thấy mức tiến bộ?", "Mở lại kết quả phân tích cũ ở đâu?"]],
  [/^\/student\/library/, ["Thêm JD từ tin tuyển dụng bên ngoài thế nào?", "Mức phù hợp trong thư viện nghĩa là gì?", "Lưu vị trí để dùng lại thế nào?"]],
  [/^\/student\/share/, ["Cố vấn xem được những gì?", "Tắt chia sẻ thì cố vấn còn thấy điểm không?", "Xem nhận xét của cố vấn ở đâu?"]],
  [/^\/student/, ["Bắt đầu phân tích CV thế nào?", "Luyện phỏng vấn thử thế nào?", "Thêm JD của tôi ở đâu?", ADVISOR_FEATURES ? "Chia sẻ kết quả với cố vấn thế nào?" : "Tối ưu CV thế nào?"]],
  [/^\/advisor\/students/, ["Lọc sinh viên cần chú ý thế nào?", "Gửi nhận xét buổi phỏng vấn ra sao?", "Ghi chú khác nhận xét thế nào?"]],
  [/^\/advisor/, ["Sinh viên cần chú ý là gì?", "Tỷ lệ hoạt động 30 ngày nghĩa là gì?", "Tìm buổi chờ nhận xét ở đâu?", "Vì sao không xem được CV của sinh viên?"]],
]

function suggestionsFor(pathname: string, role: UserRole): { page: string; items: string[] } {
  const items = SUGGESTIONS.find(([pattern]) => pattern.test(pathname))?.[1] ?? []
  const page = getBreadcrumb(shellOf(role), pathname).at(-1)?.label ?? "này"
  return { page, items }
}

/** Sinh viên: hai chữ cuối của tên; cố vấn: học vị + tên (như lời chào ở trang Tổng quan). */
function callName(fullName: string | undefined, role: UserRole): string {
  if (!fullName) return ""
  const words = fullName.trim().split(/\s+/)
  if (role === "student") return words.slice(-2).join(" ")
  const title = fullName.match(/^(ThS|TS|PGS\.TS|GS\.TS)\./i)?.[0]
  return title ? `${title} ${words.at(-1)}` : (words.at(-1) ?? "")
}

/** Trạng thái AI; chỉ hỏi khi khung đang mở. `null` khi chưa biết, để không báo nhầm lúc mới mở. */
function useAssistantStatus(): AssistantStatusResponse | null {
  const [status, setStatus] = useState<AssistantStatusResponse | null>(null)
  useEffect(() => {
    let disposed = false
    let pending = false
    let controller: AbortController | null = null
    const refresh = async () => {
      if (pending) return
      pending = true
      controller = new AbortController()
      const timeout = window.setTimeout(() => controller?.abort(), 8000)
      try {
        const next = await getAssistantStatus(controller.signal)
        if (!disposed) setStatus(next)
      } catch {
        if (!disposed) setStatus({ is_live: false, status: "offline", provider: "none", model: "" })
      } finally {
        window.clearTimeout(timeout)
        pending = false
      }
    }
    void refresh()
    const interval = window.setInterval(() => { void refresh() }, 35000)
    return () => {
      disposed = true
      window.clearInterval(interval)
      controller?.abort()
    }
  }, [])
  return status
}

const iconButton = "grid size-9 shrink-0 place-items-center rounded-full text-ink-2 transition-colors hover:bg-surface hover:text-ink disabled:pointer-events-none disabled:opacity-40"

function PanelHeader({ subtitle, onClose, onNewChat, canReset }: { subtitle: string; onClose: () => void; onNewChat?: () => void; canReset: boolean }) {
  return (
    <header className="flex shrink-0 items-center gap-3 border-b border-line py-2.5 pr-2.5 pl-2 sm:pl-4">
      <button type="button" onClick={onClose} aria-label="Đóng trợ lý" className={cn(iconButton, "sm:hidden")}>
        <ChevronLeft className="size-5" aria-hidden />
      </button>
      <span className="grid size-9 shrink-0 place-items-center rounded-[10px] bg-blue-soft text-blue max-sm:hidden">
        <Sparkles className="size-[18px]" strokeWidth={1.75} aria-hidden />
      </span>
      <span className="grid min-w-0 flex-1">
        <h2 id="assistant-chat-title" className="truncate text-[15px] leading-5 font-semibold text-ink">Trợ lý hướng dẫn</h2>
        <span className="truncate text-[13px] text-ink-3">{subtitle}</span>
      </span>
      {onNewChat && (
        <button type="button" onClick={onNewChat} disabled={!canReset} aria-label="Cuộc trò chuyện mới" title="Cuộc trò chuyện mới" className={iconButton}>
          <SquarePen className="size-[17px]" strokeWidth={1.75} aria-hidden />
        </button>
      )}
      <button type="button" onClick={onClose} aria-label="Đóng trợ lý" title="Đóng" className={cn(iconButton, "max-sm:hidden")}>
        <X className="size-[18px]" aria-hidden />
      </button>
    </header>
  )
}

/** Khi trợ lý đang chỉ một nút: thu khung chat thành thẻ nhỏ ở trên để không che nút đó (bản vẽ TroLyChiNut). */
function PointingCard({ selector, onClose, onReopen }: { selector: string; onClose: () => void; onReopen: () => void }) {
  const label = useMemo(() => targetLabel(selector), [selector])
  return (
    <section
      id="assistant-chat-panel"
      aria-labelledby="assistant-chat-title"
      className="fixed inset-x-2 top-2 z-[65] overflow-hidden rounded-[18px] bg-card shadow-dialog ring-1 ring-line sm:inset-x-auto sm:top-[4.75rem] sm:right-6 sm:w-[400px] print:hidden"
    >
      <PanelHeader subtitle="Đang chỉ vị trí nút trên trang" onClose={onClose} canReset={false} />
      <div className="flex items-center gap-2.5 px-4 py-3 text-sm text-ink-2">
        <Crosshair className="size-4 shrink-0" strokeWidth={1.75} aria-hidden />
        <span className="min-w-0 flex-1">
          {label ? <>Đang chỉ <b className="font-semibold text-ink">{label}</b> trên trang.</> : "Đang chỉ vị trí trên trang."}
        </span>
        <button type="button" onClick={onReopen} className="shrink-0 font-semibold text-blue hover:underline">
          Mở lại khung chat
        </button>
      </div>
    </section>
  )
}

export function ChatPanel() {
  const {
    isOpen, messages, isThinking, isExecutingAction, activeAction, pathname, userRole, error, highlightSelector,
    sendMessage, stop, retryLast, clearChat, closeChat, dismissHighlight,
  } = useAssistant()
  const profile = useProfile()
  const busy = isThinking || isExecutingAction || activeAction !== null
  const [draft, setDraft] = useState("")
  const [ratings, setRatings] = useState<Record<string, 1 | -1 | undefined>>({})
  const [pendingRating, setPendingRating] = useState<Record<string, boolean | undefined>>({})
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!isOpen) return
    const previousFocus = document.activeElement
    inputRef.current?.focus({ preventScroll: true })
    return () => {
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({ preventScroll: true })
    }
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "instant" })
  }, [messages, isThinking, error, isOpen, highlightSelector])

  const submit = (text = draft) => {
    const content = text.trim()
    if (!content || busy) return
    setDraft("")
    void sendMessage(content)
    inputRef.current?.focus({ preventScroll: true })
  }

  // Bấm lại nút đã chọn để huỷ (khi bấm nhầm), như các nút thích khác trong ứng dụng.
  const rate = async (turnId: string, rating: 1 | -1) => {
    if (pendingRating[turnId]) return
    const undo = ratings[turnId] === rating
    setPendingRating((p) => ({ ...p, [turnId]: true }))
    try {
      if (undo) await deleteFeedback(turnId)
      else await submitFeedback(turnId, rating)
      setRatings((r) => ({ ...r, [turnId]: undo ? undefined : rating }))
    } catch {
      toast.error("Chưa lưu được đánh giá. Hãy thử lại.")
    } finally {
      setPendingRating((p) => ({ ...p, [turnId]: false }))
    }
  }

  const copy = (content: string) => {
    navigator.clipboard.writeText(content).then(
      () => toast.success("Đã sao chép câu trả lời"),
      () => toast.error("Không sao chép được."),
    )
  }

  if (!isOpen) return null
  if (highlightSelector) return <PointingCard selector={highlightSelector} onClose={() => { dismissHighlight(); closeChat() }} onReopen={dismissHighlight} />

  const { page, items } = suggestionsFor(pathname, userRole)
  const name = callName(profile?.full_name, userRole)

  return (
    <section
      id="assistant-chat-panel"
      role="dialog"
      aria-modal="false"
      aria-labelledby="assistant-chat-title"
      onKeyDown={(event) => {
        if (event.key === "Escape") { event.stopPropagation(); closeChat() }
      }}
      className="fixed inset-0 z-50 flex flex-col overflow-hidden bg-card text-ink sm:inset-auto sm:right-6 sm:bottom-[calc(var(--tabbar-h,0px)+var(--actionbar-h,0px)+1rem)] sm:h-[min(620px,calc(100dvh-var(--tabbar-h,0px)-var(--actionbar-h,0px)-6rem))] sm:w-[400px] sm:rounded-[18px] sm:shadow-dialog sm:ring-1 sm:ring-line print:hidden"
    >
      <PanelHeader
        subtitle="Hỏi cách dùng CareerV"
        onClose={closeChat}
        onNewChat={() => { clearChat(); setDraft(""); inputRef.current?.focus() }}
        canReset={messages.length > 0 && !isExecutingAction}
      />
      <AssistantStatusStrip />

      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-5">
        {messages.length === 0 ? (
          <div className="grid gap-5">
            <div className="grid gap-1">
              <h3 className="text-[17px] leading-6 font-semibold text-ink">{name ? `Chào ${name}, bạn cần giúp gì?` : "Bạn cần giúp gì?"}</h3>
              <p className="text-sm leading-[22px] text-ink-2">Hỏi cách dùng trang đang mở, ý nghĩa các chỉ số hoặc nhờ trợ lý chỉ vị trí một nút.</p>
            </div>
            {items.length > 0 && (
              <div className="grid gap-2">
                <p className="text-xs font-semibold tracking-[0.03em] text-ink-3 uppercase">Gợi ý cho trang {page}</p>
                <ul className="grid gap-2">
                  {items.map((item) => (
                    <li key={item}>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => submit(item)}
                        className="flex w-full items-center gap-2.5 rounded-xl bg-panel px-3 py-2.5 text-left text-sm text-ink transition-colors hover:bg-surface disabled:opacity-50"
                      >
                        <MessageCircleQuestion className="size-4 shrink-0 text-ink-3" strokeWidth={1.75} aria-hidden />
                        <span className="min-w-0 flex-1">{item}</span>
                        <ChevronRight className="size-4 shrink-0 text-ink-3" aria-hidden />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div role="log" aria-label="Trò chuyện với trợ lý" aria-live="polite" aria-relevant="additions" aria-busy={isThinking} className="grid gap-4">
            {messages.map((message) =>
              message.sender === "user" ? (
                <p key={message.id} className="max-w-[85%] justify-self-end rounded-[18px] rounded-br-md bg-ink px-3.5 py-2 text-sm leading-[22px] whitespace-pre-wrap text-on-ink wrap-anywhere">
                  <span className="sr-only">Bạn: </span>
                  {message.content}
                </p>
              ) : (
                <article key={message.id} className="grid gap-2.5">
                  <div className="text-sm leading-[22px] text-ink wrap-anywhere">
                    <span className="sr-only">Trợ lý: </span>
                    <AssistantMarkdown content={message.content} userRole={userRole} isStreaming={message.is_streaming} />
                  </div>
                  {(message.actions || message.ui_actions) && <ActionBadges actions={message.actions ?? []} uiActions={message.ui_actions} />}
                  {message.sources && !isAssistantRefusal(message.content) && <SourceAccordion sources={message.sources} userRole={userRole} />}
                  {message.cards && <AssistantCards cards={message.cards} role={userRole} />}
                  {message.chips && <AssistantChips chips={message.chips} role={userRole} disabled={busy || message !== messages.at(-1)} onSelect={(chip) => { void sendMessage(chip.label, chip) }} />}
                  {message.notices?.map((notice, index) => <p key={index} className="text-xs text-ink-3">{notice}</p>)}
                  {message.interrupted && <p className="text-xs text-ink-3">Câu trả lời đã bị gián đoạn.</p>}
                  {!message.is_streaming && (
                    <div role="group" aria-label="Đánh giá câu trả lời" className="-ml-1.5 flex items-center gap-0.5">
                      {([1, -1] as const).map((value) => {
                        const Icon = value === 1 ? ThumbsUp : ThumbsDown
                        const on = ratings[message.id] === value
                        return (
                          <button
                            key={value}
                            type="button"
                            aria-label={value === 1 ? "Hữu ích" : "Chưa hữu ích"}
                            title={on ? "Bấm lại để huỷ" : value === 1 ? "Hữu ích" : "Chưa hữu ích"}
                            aria-pressed={on}
                            disabled={!!pendingRating[message.id]}
                            onClick={() => { void rate(message.id, value) }}
                            className={cn(
                              "grid size-7 place-items-center rounded-lg transition-colors disabled:opacity-50",
                              on ? (value === 1 ? "bg-good-soft text-good" : "bg-bad-soft text-bad") : "text-ink-3 hover:bg-surface hover:text-ink",
                            )}
                          >
                            <Icon className="size-[15px]" strokeWidth={1.75} aria-hidden />
                          </button>
                        )
                      })}
                      <button type="button" aria-label="Sao chép câu trả lời" title="Sao chép" onClick={() => copy(message.content)} className="grid size-7 place-items-center rounded-lg text-ink-3 transition-colors hover:bg-surface hover:text-ink">
                        <Copy className="size-[15px]" strokeWidth={1.75} aria-hidden />
                      </button>
                    </div>
                  )}
                </article>
              ),
            )}
            {isThinking && (
              <p role="status" className="flex items-center gap-2.5 text-[13px] text-ink-3">
                <span className="flex gap-1" aria-hidden>
                  {[0, 1, 2].map((i) => <span key={i} className="size-1.5 rounded-full bg-ink-3 motion-safe:animate-pulse" style={{ animationDelay: `${i * 150}ms` }} />)}
                </span>
                Đang tìm trong hướng dẫn…
              </p>
            )}
            {error && (
              <div role="alert" className="flex items-start gap-2.5 rounded-xl bg-bad-soft px-3.5 py-3 text-sm leading-[21px] text-bad">
                <AlertCircle className="mt-0.5 size-4 shrink-0" strokeWidth={1.75} aria-hidden />
                <span className="min-w-0 flex-1">Chưa gửi được câu hỏi. {error}</span>
                <button type="button" onClick={retryLast} disabled={busy} className="inline-flex shrink-0 items-center gap-1 font-semibold hover:underline">
                  <RotateCw className="size-3.5" aria-hidden />
                  Thử lại
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      <form
        className="grid shrink-0 gap-1.5 border-t border-line px-4 pt-3 pb-3.5"
        onSubmit={(event) => { event.preventDefault(); submit() }}
      >
        <div className="flex items-end gap-2 rounded-[14px] bg-card py-1.5 pr-1.5 pl-3.5 ring-1 ring-line-strong transition-shadow focus-within:ring-ink">
          <label htmlFor="assistant-chat-input" className="sr-only">Câu hỏi cho trợ lý</label>
          <textarea
            ref={inputRef}
            id="assistant-chat-input"
            rows={1}
            value={draft}
            maxLength={8000}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              // Không gửi khi đang gõ dấu tiếng Việt bằng bộ gõ (IME)
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                submit()
              }
            }}
            placeholder="Hỏi trợ lý…"
            className="field-sizing-content max-h-32 min-h-8 flex-1 resize-none bg-transparent py-1 text-sm leading-6 outline-none placeholder:text-ink-3"
          />
          {isThinking ? <button type="button" onClick={stop} aria-label="Dừng trả lời"
            className="grid size-8 shrink-0 place-items-center rounded-full bg-ink text-on-ink">
            <Square className="size-3.5" aria-hidden />
          </button> : <button
            type="submit"
            disabled={!draft.trim() || busy}
            aria-label="Gửi câu hỏi"
            className="grid size-8 shrink-0 place-items-center rounded-full bg-ink text-on-ink transition-colors disabled:bg-surface disabled:text-ink-3"
          >
            <ArrowUp className="size-4" strokeWidth={2} aria-hidden />
          </button>}
        </div>
        {messages.length === 0 && (
          <p className="text-xs leading-[18px] text-ink-3">Trợ lý trả lời theo hướng dẫn sử dụng và có thể chưa đúng. Trợ lý chỉ thao tác khi bạn bấm.</p>
        )}
      </form>
    </section>
  )
}

/** AI bận: một dải vàng ngắn thay cho nhãn "Live / Offline" (bản vẽ TroLyTrangThai). */
function AssistantStatusStrip() {
  const status = useAssistantStatus()
  if (!status || status.is_live) return null
  return (
    <p role="status" className="flex shrink-0 items-start gap-2 border-b border-warn-line bg-warn-soft px-4 py-2 text-[13px] leading-[19px] text-warn">
      <Info className="mt-px size-[15px] shrink-0" strokeWidth={1.75} aria-hidden />
      AI đang bận nên trợ lý trích thẳng từ hướng dẫn. Câu trả lời có thể ngắn hơn.
    </p>
  )
}
