import { env, pipeline, TextStreamer, InterruptableStoppingCriteria, type AutomaticSpeechRecognitionPipeline, type AutomaticSpeechRecognitionConfig, type PretrainedModelOptions } from "@huggingface/transformers"

import {
  PHOWHISPER_MODEL, PHOWHISPER_SOURCE, PHOWHISPER_REVISION, PHOWHISPER_ASSET_VERSION,
  SAMPLE_RATE, type ModelManifest, type Preparation, type WorkerRequest, type WorkerResponse,
} from "./protocol"

const scope = self as unknown as {
  location: Location
  navigator: { hardwareConcurrency: number; gpu?: { requestAdapter(): Promise<unknown> } }
  crossOriginIsolated: boolean
  postMessage(message: WorkerResponse): void
  addEventListener(type: "message", listener: (event: MessageEvent<WorkerRequest>) => void): void
}
let transcriber: AutomaticSpeechRecognitionPipeline | null = null
let preparing: Promise<void> | null = null
let activeId: number | null = null
type ProgressInfo = Parameters<NonNullable<PretrainedModelOptions["progress_callback"]>>[0]
const createRecognizer = pipeline as (task: "automatic-speech-recognition", model: string, options: PretrainedModelOptions) => Promise<AutomaticSpeechRecognitionPipeline>
const stopping = new InterruptableStoppingCriteria()
let state: Omit<Preparation, "typingOnly"> = {
  phase: "idle", progress: 0, loaded: 0, total: 0, backend: null,
  persistentCache: false, message: "",
}
const send = (message: WorkerResponse) => scope.postMessage(message)
function update(patch: Partial<typeof state>) {
  state = { ...state, ...patch }
  send({ type: "preparation", state })
}

async function prepare() {
  update({ phase: "loading", progress: 0, message: "Đang kiểm tra mô hình PhoWhisper…" })
  const response = await fetch(`/models/${PHOWHISPER_MODEL}/manifest.json`)
  if (!response.ok) throw new Error("Máy chủ chưa có mô hình PhoWhisper. Bạn có thể gõ câu trả lời.")
  const manifest: ModelManifest = await response.json()
  if (manifest.source !== PHOWHISPER_SOURCE || manifest.revision !== PHOWHISPER_REVISION || manifest.asset_version !== PHOWHISPER_ASSET_VERSION) {
    throw new Error("Phiên bản PhoWhisper chưa khớp. Hãy tải lại trang hoặc gõ câu trả lời.")
  }
  const runtimeResponse = await fetch("/onnx/manifest.json")
  if (!runtimeResponse.ok) throw new Error("Chưa tải được bộ nhận diện giọng nói. Hãy thử lại.")
  const runtime: { version: string } = await runtimeResponse.json()
  env.allowLocalModels = true
  env.allowRemoteModels = false
  env.localModelPath = "/models/"
  env.useFSCache = false
  env.useBrowserCache = false
  const wasm = env.backends.onnx.wasm!
  wasm.wasmPaths = new URL(`/onnx/${runtime.version}/`, scope.location.origin).href
  wasm.numThreads = scope.crossOriginIsolated ? Math.min(4, scope.navigator.hardwareConcurrency || 1) : 1
  wasm.proxy = false

  let cache: Cache | null = null
  try { cache = await caches.open(`phowhisper-${PHOWHISPER_ASSET_VERSION}`) } catch { /* Restricted/private storage: this tab still works. */ }
  update({ persistentCache: cache !== null })
  // Cache writes can fail when device storage is full. Recognition should still work in this tab.
  env.useCustomCache = true
  env.customCache = {
    async match(request: string) {
      const url = new URL(request, scope.location.origin)
      if (url.origin !== scope.location.origin) return undefined
      try { return await cache?.match(url.href) } catch { return undefined }
    },
    async put(request: string, result: Response) {
      try { await cache?.put(new URL(request, scope.location.origin).href, result) }
      catch { update({ persistentCache: false }) }
    },
  }

  let gpu = false
  try { gpu = Boolean(await scope.navigator.gpu?.requestAdapter()) } catch { /* Use CPU. */ }
  const loaded = new Map<string, number>()
  const load = async (useGpu: boolean) => {
    const encoder = useGpu ? "onnx/encoder_model.onnx" : "onnx/encoder_model_quantized.onnx"
    const files = ["config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json", "preprocessor_config.json", encoder, "onnx/decoder_model_merged_quantized.onnx"]
    const total = files.reduce((sum, file) => sum + (manifest.files[file]?.bytes ?? 0), 0)
    update({ backend: useGpu ? "webgpu" : "wasm", total, loaded: 0, progress: 0 })
    const progress = (event: ProgressInfo) => {
      if (!("file" in event)) return
      if (event.status === "progress") loaded.set(event.file, event.loaded)
      if (event.status === "done") loaded.set(event.file, manifest.files[event.file]?.bytes ?? loaded.get(event.file) ?? 0)
      const bytes = files.reduce((sum, file) => sum + Math.min(loaded.get(file) ?? 0, manifest.files[file]?.bytes ?? 0), 0)
      update({ loaded: bytes, progress: total ? Math.min(100, Math.round(bytes / total * 100)) : 0 })
    }
    // The floating encoder benefits from WebGPU. Dynamic-int8 decoder graphs run on WASM.
    transcriber = await createRecognizer("automatic-speech-recognition", PHOWHISPER_MODEL, {
      device: { encoder_model: useGpu ? "webgpu" : "wasm", decoder_model_merged: "wasm" },
      dtype: { encoder_model: useGpu ? "fp32" : "q8", decoder_model_merged: "q8" },
      progress_callback: progress,
    })
    update({ phase: "warming", progress: 100, message: "Đang khởi động PhoWhisper trên thiết bị…" })
    // Exercise encoder and decoder before allowing the lobby to create a timed interview.
    await transcriber(new Float32Array(SAMPLE_RATE), { language: "vi", task: "transcribe", max_new_tokens: 1 })
  }
  try { await load(gpu) }
  catch (error) {
    await transcriber?.dispose().catch(() => {})
    transcriber = null
    if (!gpu) throw error
    update({ phase: "loading", message: "Đang chuyển sang nhận diện bằng CPU trên thiết bị…" })
    await load(false)
  }
  update({ phase: "ready", progress: 100, message: "PhoWhisper đã sẵn sàng trên thiết bị." })
}

scope.addEventListener("message", (event) => {
  const request = event.data
  if (request.type === "prepare") {
    if (transcriber && state.phase === "ready") { send({ type: "preparation", state }); return }
    preparing ??= prepare().catch(async (error: unknown) => {
      await transcriber?.dispose().catch(() => {})
      transcriber = null
      update({ phase: "error", message: error instanceof Error ? error.message : "Không chuẩn bị được PhoWhisper." })
    }).finally(() => { preparing = null })
    return
  }
  if (request.type === "cancel") {
    if (activeId === request.id) stopping.interrupt()
    return
  }
  if (!transcriber || state.phase !== "ready" || activeId !== null) {
    send({ type: "error", id: request.id, message: "PhoWhisper chưa sẵn sàng. Hãy thử lại hoặc gõ câu trả lời." })
    return
  }
  activeId = request.id
  stopping.reset()
  const started = performance.now()
  let partial = ""
  const streamer = new TextStreamer(transcriber.tokenizer, {
    skip_prompt: true, skip_special_tokens: true,
    callback_function(text: string) { partial += text; send({ type: "partial", id: request.id, text: partial }) },
  })
  const options: Partial<AutomaticSpeechRecognitionConfig> & { stopping_criteria: InterruptableStoppingCriteria } = {
    language: "vi", task: "transcribe", return_timestamps: false,
    max_new_tokens: 160, num_beams: 1, repetition_penalty: 1.05,
    streamer, stopping_criteria: stopping,
  }
  void transcriber(request.audio, options).then((output) => {
    const result = Array.isArray(output) ? output[0] : output
    send({ type: "result", id: request.id, text: result.text.trim(), elapsedMs: performance.now() - started })
  }).catch((error: unknown) => {
    send({ type: "error", id: request.id, message: error instanceof Error ? error.message : "Không nhận diện được đoạn nói." })
  }).finally(() => { activeId = null })
})
