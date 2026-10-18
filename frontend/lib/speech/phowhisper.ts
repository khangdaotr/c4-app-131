"use client"

import { useEffect, useSyncExternalStore } from "react"
import type { Preparation, WorkerRequest, WorkerResponse } from "./protocol"

const INITIAL: Preparation = {
  phase: "idle", progress: 0, loaded: 0, total: 0, backend: null,
  persistentCache: false, message: "", typingOnly: false,
}
let state = INITIAL
let worker: Worker | null = null
let sequence = 0
let preparation: Promise<void> | null = null
let resolvePreparation: (() => void) | null = null
let rejectPreparation: ((error: Error) => void) | null = null
let preferenceLoaded = false
let decodeQueue: Promise<unknown> = Promise.resolve()
let idleTimer: ReturnType<typeof setTimeout> | null = null
const listeners = new Set<() => void>()
interface Job {
  resolve: (result: { text: string; elapsedMs: number }) => void
  reject: (error: Error) => void
  partial?: (text: string) => void
  timer: ReturnType<typeof setTimeout>
}
const jobs = new Map<number, Job>()

function publish(patch: Partial<Preparation>) {
  state = { ...state, ...patch }
  listeners.forEach((listener) => listener())
}
function fail(message: string) {
  worker?.terminate()
  worker = null
  const error = new Error(message)
  rejectPreparation?.(error)
  resolvePreparation = rejectPreparation = null
  preparation = null
  for (const job of jobs.values()) { clearTimeout(job.timer); job.reject(error) }
  jobs.clear()
  publish({ phase: "error", message })
}
function getWorker() {
  if (worker) return worker
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || typeof Worker === "undefined" || typeof AudioWorkletNode === "undefined") {
    throw new Error("Trình duyệt chưa hỗ trợ nhận diện trên thiết bị. Hãy dùng HTTPS và trình duyệt mới, hoặc gõ câu trả lời.")
  }
  worker = new Worker(new URL("./phowhisper.worker.ts", import.meta.url), { type: "module" })
  worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
    const message = event.data
    if (message.type === "preparation") {
      publish(message.state)
      if (message.state.phase === "ready") {
        resolvePreparation?.()
        resolvePreparation = rejectPreparation = null
        preparation = null
      } else if (message.state.phase === "error") {
        rejectPreparation?.(new Error(message.state.message))
        resolvePreparation = rejectPreparation = null
        preparation = null
      }
      return
    }
    const job = jobs.get(message.id)
    if (!job) return
    if (message.type === "partial") { job.partial?.(message.text); return }
    clearTimeout(job.timer)
    jobs.delete(message.id)
    if (message.type === "error") job.reject(new Error(message.message))
    else job.resolve({ text: message.text, elapsedMs: message.elapsedMs })
  }
  worker.onerror = (event) => { event.preventDefault(); fail("Không chạy được PhoWhisper trên thiết bị. Hãy thử lại hoặc gõ câu trả lời.") }
  worker.onmessageerror = () => fail("Không đọc được kết quả giọng nói. Hãy thử lại hoặc gõ câu trả lời.")
  return worker
}
function send(message: WorkerRequest, transfer: Transferable[] = []) { getWorker().postMessage(message, transfer) }

export function preparePhoWhisper(): Promise<void> {
  if (state.phase === "ready") return Promise.resolve()
  if (preparation) return preparation
  preparation = new Promise<void>((resolve, reject) => { resolvePreparation = resolve; rejectPreparation = reject })
  const result = preparation
  publish({ phase: "loading", message: "Đang chuẩn bị nhận diện giọng nói…" })
  try { send({ type: "prepare" }) }
  catch (error) { fail(error instanceof Error ? error.message : "Không khởi động được PhoWhisper.") }
  return result
}

export function setTypingOnly(typingOnly: boolean) {
  try { sessionStorage.setItem("interview-typing-only", String(typingOnly)) } catch { /* Optional preference. */ }
  publish({ typingOnly })
  if (typingOnly && (state.phase === "loading" || state.phase === "warming")) {
    fail("Đã chọn trả lời bằng cách gõ.")
    publish({ phase: "idle", progress: 0, loaded: 0, total: 0, message: "" })
  }
}

export function recognize(audio: Float32Array, partial?: (text: string) => void) {
  const id = ++sequence
  let cancelled = false
  const promise = decodeQueue.catch(() => {}).then(() => {
    if (cancelled) return { text: "", elapsedMs: 0 }
    return new Promise<{ text: string; elapsedMs: number }>((resolve, reject) => {
      const timer = setTimeout(() => fail("Thiết bị xử lý giọng nói quá lâu. Bạn có thể giữ phần chữ đã có và gõ tiếp."), 60000)
      jobs.set(id, { resolve, reject, partial, timer })
      try { send({ type: "transcribe", id, audio }, [audio.buffer]) }
      catch (error) { clearTimeout(timer); jobs.delete(id); reject(error instanceof Error ? error : new Error("Không nhận diện được giọng nói.")) }
    })
  })
  decodeQueue = promise.catch(() => {})
  return {
    promise,
    // Keep the promise pending until the worker acknowledges interruption, so the next job never overlaps it.
    cancel() { cancelled = true; if (jobs.has(id)) send({ type: "cancel", id }) },
  }
}

function subscribe(listener: () => void) {
  if (idleTimer) clearTimeout(idleTimer)
  idleTimer = null
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
    const disposeWhenIdle = () => {
      if (listeners.size) return
      if (jobs.size || preparation) { idleTimer = setTimeout(disposeWhenIdle, 120000); return }
      worker?.terminate()
      worker = null
      publish({ phase: "idle", progress: 0, loaded: 0, total: 0, backend: null })
    }
    if (!listeners.size) idleTimer = setTimeout(disposeWhenIdle, 120000)
  }
}
export function usePhoWhisperPreparation(autoPrepare = false) {
  const snapshot = useSyncExternalStore(subscribe, () => state, () => INITIAL)
  useEffect(() => {
    if (!preferenceLoaded) {
      preferenceLoaded = true
      try { publish({ typingOnly: sessionStorage.getItem("interview-typing-only") === "true" }) } catch { /* Storage disabled. */ }
    }
    if (autoPrepare && !state.typingOnly) void preparePhoWhisper().catch(() => {})
  }, [autoPrepare])
  return snapshot
}
