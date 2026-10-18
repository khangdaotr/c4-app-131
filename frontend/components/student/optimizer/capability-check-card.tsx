"use client"

import { useState } from "react"
import { ArrowUpRight, BookOpen, Check, Loader2, Pencil, Sparkles, Undo2 } from "lucide-react"

import { IMPORTANCE_META } from "@/components/student/analysis/jd-picker-sections"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import type {
  CapabilityAnswerRequest,
  CapabilityCheck,
  CapabilityDraftRequest,
  CapabilityLineDecisionRequest,
  CvEntry,
} from "@/lib/types"
import { ADVISOR_FEATURES } from "@/lib/config"
import { cn } from "@/lib/utils"

/** Khớp giới hạn ở backend (src/services/cv_optimizer.py). */
const MAX_CONTEXT_CHARS = 500
const MAX_LEARNING_NOTE_CHARS = 120
const MAX_EDIT_CHARS = 600

type Choice = "yes" | "learning" | "no"

const OPTIONS: { value: Choice; label: string }[] = [
  { value: "yes", label: "Có, đã dùng" },
  { value: "learning", label: "Đang học" },
  { value: "no", label: "Chưa có" },
]

/** "Đang học" và "Chưa có" đều là chưa có kinh nghiệm; khác nhau ở ghi chú đang học (vào mục Kỹ năng đang phát triển). */
function savedChoice(check: CapabilityCheck): Choice | null {
  if (check.status === "has_experience") return "yes"
  if (check.status === "no_experience") return check.learning_note ? "learning" : "no"
  return null
}

const pill =
  "inline-flex h-9 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-semibold transition-[transform,background-color,color] active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50"
const pillDark = cn(pill, "bg-ink text-on-ink hover:bg-ink/85")
const pillLine = cn(pill, "border border-line-strong bg-card text-ink hover:bg-panel")
const pillGhost = cn(pill, "px-2.5 text-ink-2 hover:text-ink")

interface CapabilityCheckCardProps {
  check: CapabilityCheck
  entries: CvEntry[]
  /** false khi đã "Hoàn tất": chỉ xem. */
  editable: boolean
  onAnswer: (body: CapabilityAnswerRequest) => Promise<void>
  onDraft: (body: CapabilityDraftRequest) => Promise<void>
  onDecide: (body: CapabilityLineDecisionRequest) => Promise<void>
}

// Bản vẽ ToiUuKyNangA/B. PRD US-SV-05: AI không tự thêm kỹ năng còn thiếu vào CV. "Có, đã dùng": SV kể kinh nghiệm,
// AI viết thành một câu chỉ từ lời kể, SV áp dụng / sửa / bỏ qua; "Đang học": mục Kỹ năng đang phát triển; "Chưa có":
// gợi ý lộ trình học.
export function CapabilityCheckCard({ check, entries, editable, onAnswer, onDraft, onDecide }: CapabilityCheckCardProps) {
  const saved = savedChoice(check)
  const [choice, setChoice] = useState<Choice | null>(saved)
  const [context, setContext] = useState(check.context ?? "")
  const [entryId, setEntryId] = useState(check.entry_id ?? entries[0]?.id ?? "")
  const [learningNote, setLearningNote] = useState(check.learning_note ?? "")
  // Đã có câu đề xuất thì hiện câu; "Kể lại" mở lại ô lời kể để AI viết câu khác
  const [retelling, setRetelling] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState(check.final_text ?? check.draft_text ?? "")
  const [busy, setBusy] = useState<string | null>(null)

  const entry = entries.find((e) => e.id === (check.entry_id ?? entryId))
  const hasDraft = choice === "yes" && saved === "yes" && Boolean(check.draft_text) && !retelling
  const applied = check.line_status === "accepted" || check.line_status === "edited"

  /** Chạy một thao tác; lỗi đã được nơi gọi báo, ở đây chỉ giữ nguyên nội dung SV đang nhập. */
  async function run(key: string, action: () => Promise<void>, after?: () => void) {
    setBusy(key)
    try {
      await action()
      after?.()
    } catch {
      if (key === "no") setChoice(saved)
    } finally {
      setBusy(null)
    }
  }

  function pick(next: Choice) {
    setChoice(next)
    setRetelling(false)
    // "Chưa có" không cần nhập gì thêm nên lưu ngay.
    if (next === "no" && saved !== "no") void run("no", () => onAnswer({ has_experience: false }))
  }

  const learningDirty = choice === "learning" && (saved !== "learning" || learningNote.trim() !== (check.learning_note ?? ""))

  return (
    <article
      className={cn(
        "rounded-card border bg-card px-[18px] py-4 transition-colors",
        applied ? "border-good/30" : "border-line",
      )}
    >
      <div className="mb-1 flex flex-wrap items-baseline gap-x-2">
        <h3 className="font-semibold text-ink">{check.skill}</h3>
        <span className="text-xs text-ink-3">· {IMPORTANCE_META[check.importance].label}</span>
      </div>
      <p className="mb-2.5 text-sm text-ink-2">Bạn đã từng dùng {check.skill} trong dự án hoặc bài tập lớn chưa?</p>

      <div role="radiogroup" aria-label={`Kinh nghiệm với ${check.skill}`} className="flex flex-wrap gap-1.5">
        {OPTIONS.map((o) => {
          const on = choice === o.value
          return (
            <button
              key={o.value}
              type="button"
              role="radio"
              aria-checked={on}
              disabled={!editable || busy !== null}
              onClick={() => pick(o.value)}
              className={cn(
                "h-9 rounded-full border px-3.5 text-[13px] font-semibold transition-[transform,background-color,color] active:scale-[0.97] disabled:cursor-default",
                on ? "border-ink bg-ink text-on-ink" : "border-line-strong bg-card text-ink hover:bg-panel",
                !editable && !on && "opacity-60",
              )}
            >
              {o.label}
            </button>
          )
        })}
      </div>

      {/* Có, đã dùng: kể kinh nghiệm + chọn chỗ thêm → AI viết câu */}
      {choice === "yes" && !hasDraft && editable && (
        <div className="mt-3 grid animate-in gap-3 duration-300 fade-in slide-in-from-bottom-1">
          <label className="grid gap-1.5">
            <span className="text-[13px] font-medium text-ink">Bạn đã dùng {check.skill} ở đâu, làm những gì?</span>
            <Textarea
              value={context}
              onChange={(e) => setContext(e.target.value)}
              maxLength={MAX_CONTEXT_CHARS}
              placeholder="Ví dụ: trong dự án cuối kỳ, mình dùng … để …, kết quả …"
              className="min-h-[72px] rounded-[10px] px-3 py-2.5 text-sm"
            />
          </label>
          {entries.length > 0 ? (
            <div className="grid gap-1.5">
              <span className="text-[13px] font-medium text-ink">Thêm vào phần nào của CV</span>
              <Select
                items={entries.map((e) => ({ value: e.id, label: e.label }))}
                value={entryId}
                onValueChange={(v) => v && setEntryId(String(v))}
              >
                <SelectTrigger
                  aria-label="Thêm vào phần nào của CV"
                  className="h-10 w-full min-w-0 rounded-[10px] border-line-strong bg-card px-3 text-sm text-ink"
                >
                  <SelectValue className="min-w-0 truncate" />
                </SelectTrigger>
                <SelectContent>
                  {entries.map((e) => (
                    <SelectItem key={e.id} value={e.id}>
                      {e.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : (
            <p className="text-[13px] text-ink-3">
              CV chưa có mục Dự án hay Kinh nghiệm để thêm câu. Hãy bổ sung kinh nghiệm này vào CV gốc rồi phân tích lại.
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              className={pillDark}
              disabled={busy !== null || !context.trim() || !entryId || entries.length === 0}
              onClick={() =>
                void run("draft", () => onDraft({ context: context.trim(), entry_id: entryId }), () => setRetelling(false))
              }
            >
              {busy === "draft" ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Sparkles className="size-3.5" aria-hidden />}
              {busy === "draft" ? "Đang viết…" : "Viết thành câu cho CV"}
            </button>
            {retelling && (
              <button type="button" className={pillGhost} onClick={() => setRetelling(false)}>
                Huỷ
              </button>
            )}
            <span className="text-[12.5px] text-ink-3">Thường mất vài giây</span>
          </div>
        </div>
      )}

      {/* Câu đề xuất chờ duyệt */}
      {hasDraft && !applied && check.line_status !== "rejected" && (
        <div className="mt-3 animate-in duration-300 fade-in">
          {editing ? (
            <EditBox
              value={editText}
              onChange={setEditText}
              busy={busy === "edit"}
              onCancel={() => setEditing(false)}
              onSave={() =>
                void run("edit", () => onDecide({ decision: "edit", edited_text: editText.trim() }), () => setEditing(false))
              }
            />
          ) : (
            <div className="rounded-xl bg-accent-soft px-3.5 py-3 ring-1 ring-line-strong ring-inset">
              <p className="flex items-center gap-1.5 text-[12.5px] font-semibold text-accent-strong">
                <Sparkles className="size-3.5" aria-hidden />
                Câu đề xuất{entry && ` · thêm vào ${entry.label}`}
              </p>
              <p className="mt-1.5 text-[15px] leading-[23px] text-ink">{check.draft_text}</p>
            </div>
          )}
          <p className="mt-2 text-[12.5px] leading-[18px] text-ink-3">
            Dựa trên: “{check.context?.replace(/[.\s]+$/, "")}”. AI không thêm số liệu hay công cụ bạn không nhắc tới.
          </p>
          {editable && !editing && (
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" className={pillDark} disabled={busy !== null} onClick={() => void run("accept", () => onDecide({ decision: "accept" }))}>
                {busy === "accept" ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Check className="size-3.5" strokeWidth={2.25} aria-hidden />}
                Áp dụng
              </button>
              <button
                type="button"
                className={pillLine}
                disabled={busy !== null}
                onClick={() => {
                  setEditText(check.draft_text ?? "")
                  setEditing(true)
                }}
              >
                <Pencil className="size-3.5" aria-hidden />
                Sửa
              </button>
              <button type="button" className={pillGhost} disabled={busy !== null} onClick={() => void run("reject", () => onDecide({ decision: "reject" }))}>
                Bỏ qua
              </button>
              <button type="button" className={pillGhost} disabled={busy !== null} onClick={() => setRetelling(true)}>
                Kể lại
              </button>
            </div>
          )}
        </div>
      )}

      {/* Đã áp dụng: câu nằm trong bản nháp */}
      {hasDraft && applied && (
        <div className="mt-3 animate-in duration-300 fade-in">
          {editing ? (
            <EditBox
              value={editText}
              onChange={setEditText}
              busy={busy === "edit"}
              onCancel={() => setEditing(false)}
              onSave={() =>
                void run("edit", () => onDecide({ decision: "edit", edited_text: editText.trim() }), () => setEditing(false))
              }
            />
          ) : (
            <div className="flex items-start gap-2.5 rounded-xl bg-good-soft px-3.5 py-3">
              <Check className="mt-0.5 size-4 shrink-0 text-good" strokeWidth={2.25} aria-hidden />
              <div className="min-w-0">
                <p className="text-[12.5px] font-semibold text-good">
                  {check.line_status === "edited" ? "Bạn đã sửa" : "Đã thêm vào bản nháp"}
                  {entry && ` · ${entry.label}`}
                </p>
                <p className="mt-1 text-[14.5px] leading-[22px] text-ink">{check.final_text}</p>
              </div>
            </div>
          )}
          {editable && !editing && (
            <div className="mt-2.5 flex flex-wrap gap-2">
              <button
                type="button"
                className={pillLine}
                disabled={busy !== null}
                onClick={() => {
                  setEditText(check.final_text ?? "")
                  setEditing(true)
                }}
              >
                <Pencil className="size-3.5" aria-hidden />
                Sửa
              </button>
              <button type="button" className={pillGhost} disabled={busy !== null} onClick={() => void run("undo", () => onDecide({ decision: "undo" }))}>
                <Undo2 className="size-3.5" aria-hidden />
                Hoàn tác
              </button>
            </div>
          )}
        </div>
      )}

      {/* Đã bỏ qua câu đề xuất */}
      {hasDraft && check.line_status === "rejected" && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-ink-3">
          Đã bỏ qua câu đề xuất, kỹ năng này không được thêm vào CV.
          {editable && (
            <button type="button" className="font-semibold text-blue hover:text-accent-strong" onClick={() => void run("undo", () => onDecide({ decision: "undo" }))}>
              Hoàn tác
            </button>
          )}
        </div>
      )}

      {/* Bản đã hoàn tất mà SV chọn "Có" nhưng chưa viết câu */}
      {choice === "yes" && !hasDraft && !editable && check.context && (
        <p className="mt-2.5 rounded-[10px] bg-panel px-3 py-2.5 text-sm text-ink-2">{check.context}</p>
      )}

      {choice === "learning" && (
        <div className="mt-3 animate-in duration-300 fade-in slide-in-from-bottom-1">
          {editable ? (
            <label className="grid gap-1.5">
              <span className="text-[13px] font-medium text-ink">Bạn đang học ở đâu?</span>
              <Input
                value={learningNote}
                onChange={(e) => setLearningNote(e.target.value)}
                maxLength={MAX_LEARNING_NOTE_CHARS}
                placeholder="Ví dụ: Đang học chứng chỉ Microsoft PL-300"
                className="h-10 rounded-[10px] px-3 text-sm"
              />
            </label>
          ) : (
            <p className="rounded-[10px] bg-panel px-3 py-2.5 text-sm text-ink-2">{check.learning_note}</p>
          )}
          <p className="mt-1.5 text-xs text-ink-3">Sẽ thêm vào mục “Kỹ năng đang phát triển”, không ghi là thành thạo.</p>
          {editable && learningDirty && (
            <button
              type="button"
              className={cn(pillDark, "mt-2.5")}
              disabled={busy !== null || !learningNote.trim()}
              onClick={() => void run("learning", () => onAnswer({ has_experience: false, learning_note: learningNote.trim() }))}
            >
              {busy === "learning" && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
              Lưu câu trả lời
            </button>
          )}
        </div>
      )}

      {choice === "no" && (
        <div className="mt-3 flex animate-in flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-ink-2 duration-300 fade-in">
          {busy === "no" ? (
            <Loader2 className="size-4 animate-spin text-ink-3" aria-label="Đang lưu" />
          ) : check.roadmap_url ? (
            <>
              Không thêm vào CV.
              <a
                href={check.roadmap_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 font-semibold text-blue hover:text-accent-strong"
              >
                <BookOpen className="size-3.5" aria-hidden />
                Lộ trình học {check.skill} trên roadmap.sh
                <ArrowUpRight className="size-3.5" strokeWidth={2} aria-hidden />
              </a>
            </>
          ) : (
            <span>
              Không thêm vào CV. roadmap.sh chưa có lộ trình cho kỹ năng này
              {ADVISOR_FEATURES ? "; bạn có thể hỏi cố vấn hướng học phù hợp." : "."}
            </span>
          )}
        </div>
      )}
    </article>
  )
}

function EditBox({
  value,
  onChange,
  busy,
  onCancel,
  onSave,
}: {
  value: string
  onChange: (v: string) => void
  busy: boolean
  onCancel: () => void
  onSave: () => void
}) {
  return (
    <div className="grid gap-2">
      <Textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        maxLength={MAX_EDIT_CHARS}
        aria-label="Sửa câu sẽ thêm vào CV"
        className="min-h-[72px] rounded-[10px] px-3 py-2.5 text-sm"
      />
      <div className="flex gap-2">
        <button type="button" className={pillDark} disabled={busy || !value.trim()} onClick={onSave}>
          {busy && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
          Lưu câu này
        </button>
        <button type="button" className={pillGhost} disabled={busy} onClick={onCancel}>
          Huỷ
        </button>
      </div>
    </div>
  )
}
