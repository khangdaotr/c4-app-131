export const PHOWHISPER_SOURCE = "vinai/PhoWhisper-base"
export const PHOWHISPER_REVISION = "7ebdb9e88f5cc5271fb88f4d642c82ff9388650e"
export const PHOWHISPER_ASSET_VERSION = `${PHOWHISPER_REVISION}-v1`
export const PHOWHISPER_MODEL = `phowhisper-base/${PHOWHISPER_ASSET_VERSION}`
export const SAMPLE_RATE = 16000

export interface Preparation {
  phase: "idle" | "loading" | "warming" | "ready" | "error"
  progress: number
  loaded: number
  total: number
  backend: "webgpu" | "wasm" | null
  persistentCache: boolean
  message: string
  typingOnly: boolean
}

export interface ModelManifest {
  source: string
  revision: string
  asset_version: string
  files: Record<string, { bytes: number; sha256: string }>
}

export type WorkerRequest =
  | { type: "prepare" }
  | { type: "transcribe"; id: number; audio: Float32Array }
  | { type: "cancel"; id: number }

export type WorkerResponse =
  | { type: "preparation"; state: Omit<Preparation, "typingOnly"> }
  | { type: "partial"; id: number; text: string }
  | { type: "result"; id: number; text: string; elapsedMs: number }
  | { type: "error"; id: number; message: string }
