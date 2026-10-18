"use client"

import { Check, Download, Loader2, Mic, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { preparePhoWhisper, setTypingOnly } from "@/lib/speech/phowhisper"
import type { Preparation } from "@/lib/speech/protocol"

export function SpeechPreparation({ state, lobby = false }: { state: Preparation; lobby?: boolean }) {
  const ready = state.phase === "ready"
  const failed = state.phase === "error"
  const warming = state.phase === "warming"
  const preparing = state.phase === "loading" || warming
  const mb = (bytes: number) => (bytes / 1024 / 1024).toLocaleString("vi-VN", { maximumFractionDigits: 1 })
  const retry = () => { setTypingOnly(false); void preparePhoWhisper().catch(() => {}) }
  return (
    <section className="grid gap-3 rounded-xl border border-line bg-surface p-4" aria-label="Chuẩn bị giọng nói">
      <div className="flex items-center gap-2 font-semibold text-ink">
        {state.typingOnly ? <Mic className="size-4" aria-hidden /> : ready ? <Check className="size-4 text-good" aria-hidden /> : preparing ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Download className="size-4" aria-hidden />}
        {state.typingOnly ? "Trả lời bằng cách gõ" : ready ? "Giọng nói đã sẵn sàng" : "Chuẩn bị giọng nói trên thiết bị"}
      </div>
      {!state.typingOnly && preparing && (
        <>
          <p className="text-sm text-ink-2" role="status" aria-live="polite">Đang tải mô hình hỗ trợ giọng nói</p>
          <div role="progressbar" aria-label="Tải mô hình hỗ trợ giọng nói" aria-valuemin={0} aria-valuemax={100} aria-valuenow={state.progress} className="h-2 overflow-hidden rounded-full bg-panel">
            <div className="h-full rounded-full bg-ink transition-[width]" style={{ width: `${state.progress}%` }} />
          </div>
        </>
      )}
      {!state.typingOnly && failed && <p role="alert" className="text-sm text-warn">{state.message}</p>}
      <div className="flex flex-wrap gap-2">
        {(state.typingOnly || failed || state.phase === "idle") && (
          <Button variant="outline" size="sm" onClick={retry}>
            <RefreshCw className="size-3.5" aria-hidden />
            {state.typingOnly ? "Dùng giọng nói" : "Thử chuẩn bị lại"}
          </Button>
        )}
        {!state.typingOnly && (
          <Button variant="ghost" size="sm" onClick={() => setTypingOnly(true)}>Tiếp tục bằng cách gõ</Button>
        )}
      </div>
    </section>
  )
}
