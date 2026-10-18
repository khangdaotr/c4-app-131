# PhoWhisper in the mock interview

The microphone uses **VinAI PhoWhisper-base**, originating from
[`vinai/PhoWhisper-base`](https://huggingface.co/vinai/PhoWhisper-base), pinned to
`7ebdb9e88f5cc5271fb88f4d642c82ff9388650e`. No third-party converted checkpoint is used.
VinAI publishes PyTorch weights, so deployment requires a build-time ONNX conversion.
The app serves the converted files itself. Browser speech inference uses Hugging Face
Transformers.js 3.8.1 and ONNX Runtime Web; these libraries are separate from the model.

## Prepare assets once on the development/build machine

Run from the repository root. Keep conversion dependencies separate from the API's
environment (an existing CPU PyTorch installation can be reused with system site packages):

```powershell
.venv\Scripts\python.exe -m venv --system-site-packages .tools/phowhisper-export
.tools\phowhisper-export\Scripts\python.exe -m pip install -r requirements-phowhisper.txt
.tools\phowhisper-export\Scripts\python.exe -m scripts.export_phowhisper
cd frontend
npm.cmd install
npm.cmd run build
```

The exporter downloads only the official pinned checkpoint, tokenizer, and processor;
exports and validates encoder/decoder graphs; quantizes weights; and creates
`frontend/public/models/phowhisper-base/<revision>-v1/`. `manifest.json` records the
original revision, conversion package versions, sizes, and SHA-256 digests. Model
files are generated artifacts and are ignored by Git. Copy the **entire generated
directory into deployment**, including the manifest and `onnx/` folder. These files
must be present in the deployed frontend's public directory, including when using
standalone Next.js output. They are not fetched from Hugging Face by users' browsers.

`npm install` copies the matching ONNX WASM/MJS runtime to `frontend/public/onnx/`.
After installing with `--ignore-scripts`, run `node scripts/copy-onnx-runtime.mjs`
from `frontend/` manually. Ship this directory too. Respect the upstream
[BSD-3-Clause license](https://github.com/VinAIResearch/PhoWhisper/blob/main/LICENSE)
when distributing the model. The generated manifest includes the license link.

## Browser behavior

1. The lobby downloads/reads the model, shows byte and percentage progress, then
   performs an encoder/decoder warm-up. **Sẵn sàng** stays disabled until warm-up
   completes, unless the user explicitly selects typing. Creating the interview
   remains the operation that starts its timer.
2. Revision-specific Cache Storage retains model files for later visits. The worker
   remains loaded across client navigation from lobby to interview. Storage failure
   does not prevent the current session; the UI explains when caching is unavailable.
   Private mode, browser eviction, and clearing site data can require another download.
3. When available, WebGPU runs the floating-point encoder and WASM runs the quantized
   decoder. If GPU initialization/warm-up fails, both run as q8 on WASM. CPU downloads
   are roughly 103 MiB; GPU use additionally needs a floating encoder, so its first
   download is larger. Exact progress comes from the generated manifest. WASM uses
   one thread without cross-origin isolation and up to four when isolation is enabled.
4. An AudioWorklet continuously captures mono PCM and resamples to 16 kHz. RMS voice
   detection ends utterances after about 700 ms of silence. Partial decoding updates
   every roughly two seconds when the device keeps up. Long utterances split at
   eight seconds with 600 ms overlap and transcript overlap reconciliation.
5. Only one decode runs at a time. Obsolete previews are coalesced. Final utterances
   are ordered. A growing backlog stops the microphone rather than accumulating
   unbounded recordings; users can wait or keep the visible draft and type. Stale
   results are discarded on cancellation, question changes, submission, or unmount.
6. PhoWhisper availability is independent of Groq keys. No speech recording or PCM
   is uploaded. The existing legacy `/interviews/transcribe` route remains available
   for older clients but is not called by this UI, including on failure.

Use HTTPS (or localhost), allow microphone access, and use a browser with AudioWorklet
and WebAssembly support. WebGPU is optional. Reloading directly into an active timed
interview must recreate the worker from cached files; the existing server deadline
continues to apply. First-time users should enter through the lobby.

These changes remove network transcription and the old 6–25 second recording delay.
Actual recognition speed and accuracy, especially Vietnamese mixed with English IT
terms, still depend on the user's hardware and speech. They are not guaranteed by
the model's download or warm-up completing.
