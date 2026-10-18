"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { recognize, usePhoWhisperPreparation } from "./speech/phowhisper"
import { SAMPLE_RATE } from "./speech/protocol"
import { cleanSpeech, mergeTranscript } from "./speech/transcript"

const PAUSE_SAMPLES = SAMPLE_RATE * 0.7
const MAX_WINDOW = SAMPLE_RATE * 8
const PREVIEW_INTERVAL = SAMPLE_RATE * 2
const OVERLAP = SAMPLE_RATE * 0.6
const MAX_BACKLOG = SAMPLE_RATE * 16
const MAX_RECORD_SECONDS = 290

interface Segment {
  id: number
  frames: Float32Array[]
  samples: number
  lastVoice: number
  voiced: boolean
  voicedSamples: number
  overlaps: boolean
  lastPreview: number
}
interface Decode {
  run: number
  segment: number
  audio: Float32Array
  final: boolean
  overlaps: boolean
}
interface Transcript { text: string; overlaps: boolean; final: boolean }
function flatten(frames: Float32Array[]): Float32Array {
  const result = new Float32Array(frames.reduce((sum, frame) => sum + frame.length, 0))
  let offset = 0
  for (const frame of frames) { result.set(frame, offset); offset += frame.length }
  return result
}
function newSegment(id: number): Segment {
  return { id, frames: [], samples: 0, lastVoice: 0, voiced: false, voicedSamples: 0, overlaps: false, lastPreview: 0 }
}

/** PCM never leaves the device. Final windows are ordered; obsolete previews are replaced, not queued. */
export function usePhoWhisper({ onTranscript }: { onTranscript?: (text: string) => void } = {}) {
  const preparation = usePhoWhisperPreparation()
  const [isRecording, setIsRecording] = useState(false)
  const [isStarting, setIsStarting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [recordSeconds, setRecordSeconds] = useState(0)
  const [provisional, setProvisional] = useState(false)
  const [slow, setSlow] = useState(false)
  const alive = useRef(true)
  const run = useRef(0)
  const recording = useRef(false)
  const starting = useRef(false)
  const flushing = useRef(false)
  const stream = useRef<MediaStream | null>(null)
  const context = useRef<AudioContext | null>(null)
  const source = useRef<MediaStreamAudioSourceNode | null>(null)
  const capture = useRef<AudioWorkletNode | null>(null)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)
  const segment = useRef(newSegment(0))
  const transcripts = useRef(new Map<number, Transcript>())
  const finals = useRef<Decode[]>([])
  const preview = useRef<Decode | null>(null)
  const pumping = useRef(false)
  const active = useRef<ReturnType<typeof recognize> | null>(null)
  const onTranscriptRef = useRef(onTranscript)
  const finishRef = useRef<(discard: boolean) => void>(() => {})
  const flushAck = useRef<(() => void) | null>(null)
  const warned = useRef(false)
  const slowCount = useRef(0)
  useEffect(() => { onTranscriptRef.current = onTranscript }, [onTranscript])

  const release = useCallback(() => {
    if (timer.current) clearInterval(timer.current)
    timer.current = null
    capture.current?.disconnect()
    source.current?.disconnect()
    capture.current = null
    source.current = null
    stream.current?.getTracks().forEach((track) => track.stop())
    stream.current = null
    void context.current?.close().catch(() => {})
    context.current = null
  }, [])

  const publishTranscript = useCallback(() => {
    let text = ""
    let partial = false
    for (const [, result] of [...transcripts.current.entries()].sort(([a], [b]) => a - b)) {
      text = mergeTranscript(text, cleanSpeech(result.text), result.overlaps)
      partial ||= !result.final
    }
    if (alive.current) setProvisional(partial)
    onTranscriptRef.current?.(text)
  }, [])

  const pump = useCallback(async () => {
    if (pumping.current) return
    pumping.current = true
    if (alive.current) setBusy(true)
    try {
      while (finals.current.length || preview.current) {
        const task = finals.current.shift() ?? preview.current!
        if (!task.final) preview.current = null
        if (task.run !== run.current) continue
        const duration = task.audio.length / SAMPLE_RATE
        const update = (text: string, final: boolean) => {
          if (!alive.current || task.run !== run.current) return
          transcripts.current.set(task.segment, { text, final, overlaps: task.overlaps })
          publishTranscript()
        }
        const job = recognize(task.audio, (text) => update(text, false))
        active.current = job
        try {
          const result = await job.promise
          if (task.run !== run.current) continue
          update(result.text, task.final)
          slowCount.current = result.elapsedMs > duration * 1000 ? slowCount.current + 1 : 0
          if (slowCount.current >= 2 && alive.current) setSlow(true)
        } catch (error) {
          if (task.run !== run.current) continue
          if (!warned.current) {
            warned.current = true
            toast.error(error instanceof Error ? error.message : "Không nhận diện được đoạn nói. Bạn có thể gõ tiếp.")
          }
          // Preserve text already shown; do not submit this audio to a remote service.
          finishRef.current(true)
        } finally { if (active.current === job) active.current = null }
      }
    } finally {
      pumping.current = false
      if (alive.current && !flushing.current) setBusy(false)
    }
  }, [publishTranscript])

  const snapshot = useCallback((final: boolean) => {
    const current = segment.current
    if (!current.voiced || current.voicedSamples < SAMPLE_RATE * 0.2 || current.samples < SAMPLE_RATE * 0.3) return
    const task: Decode = {
      run: run.current, segment: current.id, audio: flatten(current.frames), final, overlaps: current.overlaps,
    }
    if (final) {
      if (preview.current?.segment === current.id) preview.current = null
      finals.current.push(task)
    } else preview.current = task
    void pump()
  }, [pump])

  const consume = useCallback((audio: Float32Array) => {
    const current = segment.current
    current.frames.push(audio)
    current.samples += audio.length
    let sum = 0
    for (const value of audio) sum += value * value
    if (Math.sqrt(sum / audio.length) >= 0.015) {
      current.voiced = true
      current.voicedSamples += audio.length
      current.lastVoice = current.samples
    }
    if (!current.voiced) {
      const tail = flatten(current.frames).slice(-SAMPLE_RATE * 0.3)
      current.frames = [tail]
      current.samples = tail.length
      return
    }
    const paused = current.samples - current.lastVoice >= PAUSE_SAMPLES
    if ((paused && current.samples >= SAMPLE_RATE * 0.8) || current.samples >= MAX_WINDOW) {
      snapshot(true)
      const next = newSegment(current.id + 1)
      if (!paused) {
        const overlap = flatten(current.frames).slice(-OVERLAP)
        next.frames = [overlap]
        next.samples = next.lastVoice = overlap.length
        next.overlaps = true
      }
      segment.current = next
      const backlog = finals.current.reduce((total, item) => total + item.audio.length, 0)
      if (backlog > MAX_BACKLOG && !flushing.current) {
        setSlow(true)
        toast.info("Thiết bị xử lý chậm nên micro đã dừng. Bạn có thể đợi nhận diện xong hoặc giữ chữ hiện có để gõ tiếp.")
        finishRef.current(false)
      }
    } else if (!flushing.current && current.samples - current.lastPreview >= PREVIEW_INTERVAL && !finals.current.length) {
      current.lastPreview = current.samples
      snapshot(false)
    }
  }, [snapshot])

  const finish = useCallback((discard: boolean) => {
    starting.current = false
    recording.current = false
    if (alive.current) { setIsStarting(false); setIsRecording(false) }
    if (timer.current) clearInterval(timer.current)
    timer.current = null
    if (discard) {
      run.current++
      finals.current = []
      preview.current = null
      active.current?.cancel()
      flushing.current = false
      flushAck.current?.()
      flushAck.current = null
      release()
      if (alive.current) { setBusy(false); setProvisional(false) }
      return
    }
    if (!capture.current || flushing.current) return
    flushing.current = true
    if (alive.current) setBusy(true)
    const captureRun = run.current
    let timeout: ReturnType<typeof setTimeout>
    const flushed = new Promise<void>((resolve) => {
      flushAck.current = resolve
      timeout = setTimeout(resolve, 1000)
      capture.current!.port.postMessage({ type: "flush" })
    })
    void flushed.then(() => {
      clearTimeout(timeout)
      flushAck.current = null
      if (captureRun !== run.current) return
      snapshot(true)
      segment.current = newSegment(segment.current.id + 1)
      release()
      flushing.current = false
      if (!pumping.current && alive.current) setBusy(false)
    })
  }, [release, snapshot])
  useEffect(() => { finishRef.current = finish }, [finish])

  const start = useCallback(async () => {
    if (recording.current || starting.current || flushing.current || finals.current.length || preparation.phase !== "ready") return
    starting.current = true
    setIsStarting(true)
    const captureRun = ++run.current
    transcripts.current.clear()
    segment.current = newSegment(0)
    warned.current = false
    slowCount.current = 0
    setSlow(false)
    setProvisional(false)
    setRecordSeconds(0)
    try {
      const mic = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
      if (!alive.current || captureRun !== run.current) { mic.getTracks().forEach((track) => track.stop()); return }
      stream.current = mic
      const audioContext = new AudioContext()
      context.current = audioContext
      await audioContext.resume()
      await audioContext.audioWorklet.addModule("/audio/pcm-capture-worklet.js")
      if (!alive.current || captureRun !== run.current) return
      const node = new AudioWorkletNode(audioContext, "interview-pcm-capture", { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] })
      capture.current = node
      node.port.onmessage = (event: MessageEvent<{ type: "audio"; audio: Float32Array } | { type: "flushed" }>) => {
        if (captureRun !== run.current) return
        if (event.data.type === "flushed") flushAck.current?.()
        else consume(event.data.audio)
      }
      source.current = audioContext.createMediaStreamSource(mic)
      source.current.connect(node)
      // Worklet output is silence; connecting it keeps processing active without microphone feedback.
      node.connect(audioContext.destination)
      recording.current = true
      setIsRecording(true)
      const startedAt = performance.now()
      timer.current = setInterval(() => {
        const seconds = Math.floor((performance.now() - startedAt) / 1000)
        setRecordSeconds(seconds)
        if (seconds >= MAX_RECORD_SECONDS) finishRef.current(false)
      }, 250)
    } catch (error) {
      if (captureRun !== run.current) return
      release()
      toast.error(error instanceof DOMException && error.name === "NotAllowedError"
        ? "Hãy cấp quyền micro, hoặc gõ câu trả lời."
        : "Không bật được micro trên thiết bị này. Bạn có thể gõ câu trả lời.")
    } finally {
      if (captureRun === run.current) { starting.current = false; if (alive.current) setIsStarting(false) }
    }
  }, [consume, preparation.phase, release])

  const stop = useCallback(() => {
    if (starting.current) finish(true)
    else if (recording.current) finish(false)
  }, [finish])
  const cancel = useCallback(() => finish(true), [finish])
  const toggle = useCallback(() => { if (recording.current) finish(false); else void start() }, [finish, start])
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false; finish(true) }
  }, [finish])

  return {
    preparation, isRecording, isStarting, isTranscribing: !isRecording && busy,
    recordSeconds, provisional, slow, toggle, stop, cancel,
  }
}
