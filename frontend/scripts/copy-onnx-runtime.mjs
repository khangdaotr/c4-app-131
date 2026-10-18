import { copyFile, mkdir, readdir, writeFile } from "node:fs/promises"
import { createRequire } from "node:module"
import path from "node:path"

const require = createRequire(import.meta.url)
const packagePath = path.join(path.dirname(require.resolve("onnxruntime-web")), "..", "package.json")
const runtime = require(packagePath)
const source = path.join(path.dirname(packagePath), "dist")
const target = path.resolve("public", "onnx", runtime.version)
await mkdir(target, { recursive: true })
for (const name of await readdir(source)) {
  if (name.startsWith("ort-wasm-simd-threaded") && /\.(wasm|mjs)$/.test(name)) {
    await copyFile(path.join(source, name), path.join(target, name))
  }
}
await writeFile(path.resolve("public", "onnx", "manifest.json"), JSON.stringify({ version: runtime.version }))
console.log(`ONNX browser runtime copied to /onnx/${runtime.version}/`)
