"""Build browser assets from pinned, official VinAI PhoWhisper weights.

Run from the repository root: python -m scripts.export_phowhisper
Conversion dependencies are separate from the API: requirements-phowhisper.txt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.request import urlopen

SOURCE_MODEL = "vinai/PhoWhisper-base"
SOURCE_REVISION = "7ebdb9e88f5cc5271fb88f4d642c82ff9388650e"
# v2: v1 could ship optimum's English-only generation_config; bumping changes URLs and browser cache names.
ASSET_VERSION = f"{SOURCE_REVISION}-v2"
ROOT = Path(__file__).resolve().parents[1]
LICENSE_URL = "https://raw.githubusercontent.com/VinAIResearch/PhoWhisper/main/LICENSE"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_license(target: Path) -> None:
    path = target / "LICENSE.txt"
    if not path.exists():
        with urlopen(LICENSE_URL, timeout=30) as response:
            path.write_bytes(response.read())


def main(*, rebuild: bool = False) -> None:
    import onnx
    from huggingface_hub import snapshot_download
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from optimum.exporters.onnx import main_export

    work = ROOT / ".tools" / "phowhisper-assets"
    export = work / "onnx-export"
    target = ROOT / "frontend" / "public" / "models" / "phowhisper-base" / ASSET_VERSION
    if (target / "manifest.json").exists() and not rebuild:
        copy_license(target)
        manifest_path = target / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        license_path = target / "LICENSE.txt"
        manifest["files"]["LICENSE.txt"] = {"bytes": license_path.stat().st_size, "sha256": digest(license_path)}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Already prepared: {target}")
        return

    snapshot = snapshot_download(
        SOURCE_MODEL,
        revision=SOURCE_REVISION,
        cache_dir=str(work / "hub"),
        local_dir=str(work / "source"),
        allow_patterns=["*.json", "*.txt", "*.bin", "README.md"],
    )
    print(f"Exporting {SOURCE_MODEL}@{SOURCE_REVISION}", flush=True)
    main_export(
        model_name_or_path=snapshot,
        output=export,
        task="automatic-speech-recognition-with-past",
        opset=17,
        device="cpu",
        trust_remote_code=False,
        do_validation=True,
        atol=1e-3,
    )
    target.mkdir(parents=True, exist_ok=True)
    copy_license(target)
    graphs = target / "onnx"
    graphs.mkdir(exist_ok=True)
    for path in export.iterdir():
        if path.suffix in {".json", ".txt"}:
            shutil.copy2(path, target / path.name)
    # Explicitly retain VinAI's tokenizer and processor, rather than another Whisper model's files.
    for path in Path(snapshot).iterdir():
        if path.suffix in {".json", ".txt"}:
            shutil.copy2(path, target / path.name)
    # Transformers.js rejects language="vi" unless the config declares a multilingual model.
    generation = json.loads((target / "generation_config.json").read_text(encoding="utf-8"))
    if not generation.get("is_multilingual") or "<|vi|>" not in generation.get("lang_to_id", {}):
        raise RuntimeError("generation_config.json is not VinAI's multilingual config; re-run the export")

    for name in ("encoder_model", "decoder_model_merged"):
        original = export / f"{name}.onnx"
        quantize_dynamic(
            model_input=str(original),
            model_output=str(graphs / f"{name}_quantized.onnx"),
            weight_type=QuantType.QInt8,
            op_types_to_quantize=["MatMul", "Gemm", "Gather"],
            per_channel=False,
            reduce_range=False,
            extra_options={"EnableSubgraph": True, "MatMulConstBOnly": True},
        )
    # Float encoder on WebGPU + quantized decoder on WASM; all-q8 WASM on other devices.
    shutil.copy2(export / "encoder_model.onnx", graphs / "encoder_model.onnx")
    # ORT Web bundled with Transformers.js 3 supports ONNX IR <= 10. The graphs use
    # opset 17 and no newer IR features, even if a newer onnx helper stamped IR 13.
    for path in graphs.glob("*.onnx"):
        graph = onnx.load(str(path))
        graph.ir_version = min(graph.ir_version, 10)
        onnx.checker.check_model(graph)
        onnx.save(graph, str(path))
    for name in ("config.json", "generation_config.json"):
        path = target / name
        config: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        config["forced_decoder_ids"] = None
        if name == "generation_config.json":
            config.update(language="vi", task="transcribe")
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "source": SOURCE_MODEL,
        "revision": SOURCE_REVISION,
        "asset_version": ASSET_VERSION,
        "license": "BSD-3-Clause",
        "license_url": "https://github.com/VinAIResearch/PhoWhisper/blob/main/LICENSE",
        "conversion": {
            package: version(package)
            for package in ("torch", "transformers", "optimum-onnx", "onnx", "onnxruntime")
        },
        "files": {
            path.relative_to(target).as_posix(): {"bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(target.rglob("*"))
            if path.is_file() and path.name != "manifest.json"
        },
    }
    # Publish the manifest last: an interrupted export is never advertised as usable.
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Browser assets ready: {target}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true", help="Recreate already prepared browser assets")
    main(rebuild=parser.parse_args().rebuild)
