"use client"

import Link from "next/link"
import { useCallback, useEffect, useLayoutEffect, useRef, type KeyboardEvent } from "react"
import { Check, ChevronRight, Info, Loader2, Mic, Square, TimerOff } from "lucide-react"

import { plainText } from "@/components/common/interview-feedback"
import { UserAvatar } from "@/components/shell/user-avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { MAX_ANSWER_CHARS, MIN_ANSWER_CHARS } from "@/lib/interview"
import type { InterviewQuestion, InterviewTurn } from "@/lib/types"
import { usePhoWhisper } from "@/lib/use-phowhisper"
import { setTypingOnly, usePhoWhisperPreparation } from "@/lib/speech/phowhisper"
import { SpeechPreparation } from "./speech-preparation"
import { cn } from "@/lib/utils"

// S6: khung hội thoại phỏng vấn (bản vẽ "Phòng phỏng vấn"). Logic đồng hồ / nộp bài nằm ở InterviewRoom;
// component này chỉ hiển thị. Như một buổi phỏng vấn thật: không hiện điểm hay nhận xét sau từng câu.

/** Thông báo guardrail cho một câu: không tính câu, SV sửa rồi gửi lại. */
export interface Rejection {
  id: string
  questionIndex: number
  reason: string
}

interface InterviewChatProps {
  total: number
  turns: InterviewTurn[]
  current: InterviewQuestion | null
  rejections: Rejection[]
  candidateName: string | undefined
  candidateAvatar: string | null | undefined
  draft: string
  onDraftChange: (value: string) => void
  onSend: () => void
  sending: boolean
  /** Đang tạm dừng: khoá ô nhập. */
  paused: boolean
  finished: boolean
  reportHref: string
}

export function InterviewChat(props: InterviewChatProps) {
  const { total, turns, current, rejections, candidateName, candidateAvatar, draft, sending, paused, finished } =
    props
  const { onDraftChange } = props
  const endRef = useRef<HTMLDivElement>(null)

  // Nói câu trả lời: chữ nhận diện được ghi nối vào phần đã gõ trước khi bấm ghi âm
  const typedBeforeRef = useRef("")
  const onTranscriptUpdate = useCallback(
    (speech: string) => {
      const typed = typedBeforeRef.current.trim()
      onDraftChange((typed && speech ? `${typed} ${speech.trimStart()}` : typed || speech).slice(0, MAX_ANSWER_CHARS))
    },
    [onDraftChange],
  )
  const speech = usePhoWhisperPreparation(!finished)
  const stt = usePhoWhisper({ onTranscript: onTranscriptUpdate })
  const voiceInput = !speech.typingOnly && speech.phase === "ready"
  const { stop: stopRecording, cancel: cancelRecording } = stt
  // Tạm dừng: dừng ghi và vẫn chuyển phần đã nói thành chữ; buổi kết thúc: bỏ đoạn đang ghi
  useEffect(() => {
    if (finished) cancelRecording()
    else if (sending) cancelRecording()
    else if (paused) stopRecording()
  }, [paused, finished, sending, stopRecording, cancelRecording])
  useLayoutEffect(() => () => cancelRecording(), [current?.index, cancelRecording])
  const voiceBusy = stt.isStarting || stt.isRecording || stt.isTranscribing
  const clock = `${String(Math.floor(stt.recordSeconds / 60)).padStart(2, "0")}:${String(stt.recordSeconds % 60).padStart(2, "0")}`

  const length = draft.trim().length
  const canSend = !sending && !paused && !voiceBusy && length >= MIN_ANSWER_CHARS && length <= MAX_ANSWER_CHARS
  const last = current?.index === total

  function toggleRecording() {
    if (!voiceBusy) typedBeforeRef.current = draft
    stt.toggle()
  }

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [turns.length, current?.index, rejections.length, sending])

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      if (canSend) props.onSend()
    }
  }

  const rejectionsOf = (index: number) => rejections.filter((r) => r.questionIndex === index)

  return (
    <div className="grid gap-5">
      <ol className="grid gap-6" aria-label="Hội thoại phỏng vấn" aria-live="polite">
        {turns.map((turn) => (
          <li key={turn.id} className="grid gap-5">
            <QuestionBubble index={turn.index} total={total} theme={turn.theme} text={turn.question} />
            {rejectionsOf(turn.index).map((r) => (
              <SystemBubble key={r.id} reason={r.reason} />
            ))}
            <AnswerBubble turn={turn} name={candidateName} avatar={candidateAvatar} />
          </li>
        ))}
        {current && (
          <li className="grid gap-5">
            <QuestionBubble index={current.index} total={total} theme={current.theme} text={current.text} />
            {rejectionsOf(current.index).map((r) => (
              <SystemBubble key={r.id} reason={r.reason} />
            ))}
          </li>
        )}
        {sending && (
          <li className="flex items-center gap-2.5 justify-self-start rounded-full bg-panel px-4 py-2 text-sm text-ink-2">
            <span className="flex gap-1" aria-hidden>
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="size-1.5 animate-pulse rounded-full bg-ink-2"
                  style={{ animationDelay: `${i * 150}ms` }}
                />
              ))}
            </span>
            AI đang đọc câu trả lời của bạn…
          </li>
        )}
      </ol>

      {finished ? (
        <section aria-live="polite" className="flex flex-col items-center gap-3 border-t border-line pt-10 pb-4 text-center">
          <span className="grid size-14 place-items-center rounded-full bg-good-soft text-good">
            <Check className="size-6" strokeWidth={2.25} aria-hidden />
          </span>
          <h2 className="text-2xl leading-8 font-semibold text-ink sm:text-[28px] sm:leading-9">
            Bạn đã hoàn thành buổi phỏng vấn
          </h2>
          <p className="max-w-[460px] text-ink-2">Báo cáo gồm điểm STAR từng câu và hướng dẫn cải thiện đã sẵn sàng.</p>
          <div className="mt-2 flex flex-wrap justify-center gap-2.5">
            <Button size="brand" nativeButton={false} render={<Link href={props.reportHref} />}>
              Xem báo cáo
              <ChevronRight aria-hidden />
            </Button>
            <Button variant="soft" size="brand" nativeButton={false} render={<Link href="/student" />}>
              Về Tổng quan
            </Button>
          </div>
        </section>
      ) : (
        current && (
          <div className="sticky bottom-4 grid gap-3 rounded-card bg-card p-4 shadow-[var(--shadow-float),0_0_0_1px_var(--line)]">
            {(!voiceInput && !voiceBusy) && <SpeechPreparation state={speech} />}
            <label htmlFor="interview-answer" className="sr-only">
              Câu trả lời cho câu {current.index}
            </label>
            <textarea
              id="interview-answer"
              value={draft}
              onChange={(e) => props.onDraftChange(e.target.value)}
              onKeyDown={onKeyDown}
              maxLength={MAX_ANSWER_CHARS}
              disabled={paused || sending}
              readOnly={voiceBusy}
              placeholder={
                stt.isStarting ? "Đang bật micro…" : paused
                  ? "Đang tạm dừng…"
                  : stt.isRecording
                    ? "Đang nghe…"
                    : stt.isTranscribing
                      ? "Đang chuyển giọng nói thành chữ…"
                      : voiceInput
                        ? "Gõ câu trả lời hoặc bấm Nói câu trả lời…"
                        : "Gõ câu trả lời của bạn…"
              }
              className="block min-h-32 w-full resize-y rounded-xl border border-line-strong bg-card px-4 py-3.5 text-base leading-[26px] text-ink transition-[border-color,box-shadow] outline-none placeholder:text-ink-3 focus:border-ink focus:shadow-[0_0_0_4px_var(--surface)] disabled:bg-panel disabled:opacity-70"
            />
            {stt.isRecording && (
              <p role="status" className="flex items-center gap-2 text-[13px] text-bad">
                <span aria-hidden className="relative flex size-2.5">
                  <span className="absolute inline-flex size-full rounded-full bg-bad opacity-60 motion-safe:animate-ping" />
                  <span className="relative inline-flex size-2.5 rounded-full bg-bad" />
                </span>
                <span>
                  Đang nghe <span className="font-semibold tabular-nums">{clock}</span>. Nói tự nhiên bằng tiếng Việt,
                  có thể xen thuật ngữ tiếng Anh; chữ nháp cập nhật trong lúc nói, bấm Dừng nói khi xong.
                </span>
              </p>
            )}
            {stt.provisional && <p className="text-xs text-ink-3" role="status">Chữ nháp đang được cập nhật; bạn có thể sửa sau khi nhận diện xong.</p>}
            {stt.isTranscribing && (
              <p role="status" className="flex items-center gap-2 text-[13px] text-ink-2">
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
                Đang chuyển nốt đoạn cuối thành chữ…
              </p>
            )}
            {(stt.slow || stt.isTranscribing) && (
              <div className="flex flex-wrap items-center gap-2 text-sm text-warn">
                {stt.slow && <span>Thiết bị đang xử lý chậm.</span>}
                <Button variant="ghost" size="sm" onClick={() => { stt.cancel(); setTypingOnly(true) }}>Giữ chữ hiện có và gõ tiếp</Button>
              </div>
            )}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <span className={cn("text-[13px] tabular-nums", length > 0 && length < MIN_ANSWER_CHARS ? "text-warn" : "text-ink-3")}>
                {draft.length} / {MAX_ANSWER_CHARS} ký tự
              </span>
              <span className="text-[13px] text-ink-3">
                {length < MIN_ANSWER_CHARS ? `Cần thêm ${MIN_ANSWER_CHARS - length} ký tự để gửi` : "Ctrl + Enter để gửi"}
              </span>
              <span className="flex-1" />
              {voiceInput && (
              <Button
                variant="outline"
                size="brand"
                onClick={toggleRecording}
                disabled={paused || sending || stt.isStarting || stt.isTranscribing}
                aria-pressed={stt.isRecording}
                className={cn(stt.isRecording && "border-bad text-bad hover:bg-bad-soft hover:text-bad")}
              >
                {stt.isStarting || stt.isTranscribing ? (
                  <Loader2 className="animate-spin" aria-hidden />
                ) : stt.isRecording ? (
                  <Square aria-hidden />
                ) : (
                  <Mic aria-hidden />
                )}
                {stt.isStarting ? "Đang bật micro…" : stt.isTranscribing ? "Đang chuyển thành chữ…" : stt.isRecording ? "Dừng nói" : "Nói câu trả lời"}
              </Button>
              )}
              <Button size="brand" onClick={props.onSend} disabled={!canSend}>
                {last ? "Gửi và kết thúc" : "Gửi câu trả lời"}
                <ChevronRight aria-hidden />
              </Button>
            </div>
          </div>
        )
      )}
      {/* Mốc cuộn đặt sau ô trả lời: cuộn tới đây thì ô trả lời nằm dưới câu hỏi, không đè lên câu hỏi */}
      <div ref={endRef} className="-mt-5" />
    </div>
  )
}

/** Ô vuông "AI" của người phỏng vấn. */
export function CoachMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("grid size-10 shrink-0 place-items-center rounded-xl bg-ink text-[13px] font-semibold text-on-ink", className)}
    >
      AI
    </span>
  )
}

function QuestionBubble({ index, total, theme, text }: { index: number; total: number; theme: string; text: string }) {
  return (
    <div className="flex gap-3">
      <CoachMark />
      <div className="grid min-w-0 flex-1 gap-2">
        <p className="text-sm">
          <span className="font-semibold text-ink">AI Career Coach</span>
          <span className="text-ink-3"> · người phỏng vấn</span>
        </p>
        <div className="grid gap-1.5 rounded-2xl rounded-tl-md bg-panel p-4 sm:p-5">
          <p className="text-[13px] font-semibold text-ink-3">
            Câu {index} / {total} · {theme}
          </p>
          <p className="text-lg leading-7 font-semibold tracking-[-0.01em] text-ink">{plainText(text)}</p>
        </div>
      </div>
    </div>
  )
}

function AnswerBubble({ turn, name, avatar }: { turn: InterviewTurn; name: string | undefined; avatar: string | null | undefined }) {
  return (
    <div className="flex gap-3">
      <UserAvatar name={name} src={avatar} className="size-10" />
      <div className="grid min-w-0 flex-1 gap-2">
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-semibold text-ink">{name ?? "Bạn"}</span>
          <span className="text-ink-3">· ứng viên</span>
          {turn.timed_out && (
            <Badge variant="warn">
              <TimerOff aria-hidden />
              Hết giờ
            </Badge>
          )}
        </p>
        <div className="rounded-2xl rounded-tl-md border border-line bg-card p-4">
          {turn.answer ? (
            <p className="text-[15px] leading-7 break-words whitespace-pre-line text-ink">{turn.answer}</p>
          ) : (
            <p className="text-sm text-ink-3 italic">Hết giờ khi chưa có câu trả lời.</p>
          )}
        </div>
      </div>
    </div>
  )
}

/** Thông báo trung tính khi câu trả lời bị guardrail chặn (không tính câu). */
function SystemBubble({ reason }: { reason: string }) {
  return (
    <div role="status" className="flex gap-2.5 rounded-xl border border-warn-line bg-warn-soft px-4 py-3 sm:ml-13">
      <Info className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
      <div className="grid gap-0.5">
        <p className="text-sm text-ink">{reason}</p>
        <p className="text-[13px] text-ink-2">Nội dung bạn đã gõ vẫn còn trong ô nhập. Câu này chưa bị tính.</p>
      </div>
    </div>
  )
}
