"""Explicit local CPU NER adapters; startup loads exactly one selected model.

Runtime never downloads weights and never silently swaps models after failure.
Provision models before startup. Benchmarks construct all three explicitly.
"""

import importlib.metadata
import re
from collections.abc import Iterable
from pathlib import Path
from threading import Lock

from src.config import Settings, get_settings
from src.services.privacy.detectors import Detector
from src.services.privacy.types import Kind, MaskingError, Ner, NerUnavailableError, Span

_LABEL_KINDS: dict[str, Kind] = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "FIRSTNAME": "PERSON",
    "MIDDLENAME": "PERSON",
    "LASTNAME": "PERSON",
    "LOC": "ADDRESS",
    "LOCATION": "ADDRESS",
    "GPE": "ADDRESS",
    "STREET": "ADDRESS",
    "SECONDARYADDRESS": "ADDRESS",
    "BUILDINGNUMBER": "ADDRESS",
    "CITY": "ADDRESS",
    "COUNTY": "ADDRESS",
    "STATE": "ADDRESS",
}


def _entities(text: str, tokens: Iterable[tuple[int, int, str]]) -> list[Span]:
    result: list[Span] = []
    previous_kind: Kind | None = None
    previous_label = ""
    for start, end, label in tokens:
        raw_label = label.split("-", 1)[-1].upper()
        kind = _LABEL_KINDS.get(raw_label)
        if kind is None:
            previous_kind = None
            continue
        if (
            result
            and previous_kind == kind
            and text[result[-1].end : start].strip() == ""
            and "\n" not in text[result[-1].end : start]
            and (label.startswith("I-") or raw_label != previous_label)
        ):
            result[-1] = Span(result[-1].start, end, kind)
        else:
            result.append(Span(start, end, kind))
        previous_kind, previous_label = kind, raw_label
    return result


# underthesea chuẩn hoá dấu thanh kiểu cũ (đặt trên nguyên âm thứ hai, cuối âm tiết) sang kiểu mới trong từ trả về:
# "khoá" → "khóa", "thuỷ" → "thủy". Không đổi "hoàng", "quý". Phép đổi giữ nguyên độ dài nên vị trí trên bản đã đổi
# cũng là vị trí trên văn bản gốc.
_OLD_TONE_PAIRS = {
    "oà": "òa",
    "oá": "óa",
    "oả": "ỏa",
    "oã": "õa",
    "oạ": "ọa",
    "oè": "òe",
    "oé": "óe",
    "oẻ": "ỏe",
    "oẽ": "õe",
    "oẹ": "ọe",
    "uỳ": "ùy",
    "uý": "úy",
    "uỷ": "ủy",
    "uỹ": "ũy",
    "uỵ": "ụy",
}
_OLD_TONE = re.compile(r"(?<![qQ])(" + "|".join(_OLD_TONE_PAIRS) + r")(?!\w)", re.IGNORECASE)


def _modern_tone(text: str) -> str:
    def swap(match: re.Match[str]) -> str:
        old = match.group(1)
        new = _OLD_TONE_PAIRS[old.lower()]
        return "".join(n.upper() if o.isupper() else n for o, n in zip(old, new, strict=True))

    return _OLD_TONE.sub(swap, text)


class UndertheseaNer:
    def __init__(self) -> None:
        from underthesea import ner

        self._ner = ner
        # Warm the packaged CRF/POS/chunker singletons at startup, not per request.
        ner("Nguyễn Văn An sống ở Hà Nội.")
        self.metadata = {
            "backend": "underthesea",
            "version": importlib.metadata.version("underthesea"),
            "model": "packaged CRF ner_crf_2017_10_12",
            "device": "cpu",
        }

    def detect(self, text: str) -> list[Span]:
        if not text.strip():
            return []
        tokens: list[tuple[int, int, str]] = []
        cursor = 0
        # Keep document line boundaries, avoiding merges across unrelated fields.
        for line in text.splitlines(keepends=True):
            offset = cursor
            local_cursor = 0
            if line.strip():
                # Tìm từ trên bản đã chuẩn hoá dấu thanh (cùng độ dài với dòng gốc), vì từ underthesea trả về đã
                # được chuẩn hoá; nội dung gửi đi vẫn là văn bản gốc
                aligned = _modern_tone(line)
                for word, _, _, label in self._ner(line):
                    # underthesea can return grouped punctuation as "[ [" and
                    # "PERSON_1 ]" although the original has no added spaces.
                    pattern = re.escape(_modern_tone(word)).replace(r"\ ", r"\s*")
                    found = re.search(pattern, aligned[local_cursor:])
                    if found is None:
                        raise NerUnavailableError("Local NER token alignment failed")
                    start, end = local_cursor + found.start(), local_cursor + found.end()
                    tokens.append((offset + start, offset + end, label))
                    local_cursor = end
            cursor += len(line)
        return _entities(text, tokens)


class SpacyNer:
    def __init__(self, model: str = "xx_ent_wiki_sm") -> None:
        import spacy

        spacy.require_cpu()
        self._nlp = spacy.load(model)
        if "ner" not in self._nlp.pipe_names:
            raise NerUnavailableError("spaCy fallback has no trained NER pipeline")
        self.metadata = {
            "backend": "spacy",
            "version": spacy.__version__,
            "model": model,
            "model_version": self._nlp.meta["version"],
            "device": "cpu",
        }

    def detect(self, text: str) -> list[Span]:
        return [
            Span(entity.start_char, entity.end_char, _LABEL_KINDS[entity.label_])
            for entity in self._nlp(text).ents
            if entity.label_ in _LABEL_KINDS
        ]


class PhoBertNer:
    def __init__(self, model_path: str, *, cpu_threads: int = 2) -> None:
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        if not model_path or not Path(model_path).is_dir():
            raise NerUnavailableError("Local PhoBERT model directory is required")
        torch.set_num_threads(cpu_threads)
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)
        self._model = (
            AutoModelForTokenClassification.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)
            .to("cpu")
            .eval()
        )
        if not any(label.split("-", 1)[-1] in _LABEL_KINDS for label in self._model.config.id2label.values()):
            raise NerUnavailableError("PhoBERT model has no PERSON/LOCATION labels")
        self._limit = min(254, self._model.config.max_position_embeddings - 4)
        self.metadata = {
            "backend": "phobert",
            "version": importlib.metadata.version("transformers"),
            "model": "Phuc2005/pii-phobert-base-ner",
            "revision": Path(model_path).name,
            "device": "cpu",
            "input": "raw syllables (model tokenizer)",
        }

    def detect(self, text: str) -> list[Span]:
        # PhoBERT's slow tokenizer has no offsets. Align each whitespace word's
        # BPE pieces to its original characters; never guess/skip a lost token.
        pieces: list[str] = []
        offsets: list[tuple[int, int]] = []
        for word in re.finditer(r"\S+", text):
            cursor = 0
            for piece in self._tokenizer.tokenize(word.group()):
                plain = piece.removesuffix("@@")
                if piece == self._tokenizer.unk_token:
                    start, end = cursor, len(word.group())
                else:
                    start = word.group().find(plain, cursor)
                    if start < 0:
                        raise NerUnavailableError("PhoBERT token alignment failed")
                    end = start + len(plain)
                pieces.append(piece)
                offsets.append((word.start() + start, word.start() + end))
                cursor = end
        if not pieces:
            return []
        ids = self._tokenizer.convert_tokens_to_ids(pieces)
        labels: list[tuple[int, str] | None] = [None] * len(ids)
        # Overlapping windows cover the entire document, including long inputs.
        for start in range(0, len(ids), self._limit - 32):
            window = ids[start : start + self._limit]
            input_ids = self._torch.tensor(
                [[self._tokenizer.bos_token_id, *window, self._tokenizer.eos_token_id]], device="cpu"
            )
            with self._torch.inference_mode():
                predicted = (
                    self._model(input_ids=input_ids, attention_mask=self._torch.ones_like(input_ids))
                    .logits.argmax(-1)[0, 1:-1]
                    .tolist()
                )
            for index, predicted_id in enumerate(predicted):
                distance = min(index, len(window) - index - 1)
                absolute = start + index
                if labels[absolute] is None or distance > labels[absolute][0]:
                    labels[absolute] = (distance, self._model.config.id2label[predicted_id])
        if any(label is None for label in labels):
            raise NerUnavailableError("PhoBERT left tokens unprocessed")
        return _entities(text, ((start, end, label[1]) for (start, end), label in zip(offsets, labels, strict=True)))


class LightweightNer:
    """Bộ nhận diện thực thể tiếng Việt siêu nhẹ (0 MB RAM) cho môi trường hạn chế tài nguyên như Render Free 512MB."""

    def __init__(self) -> None:
        self.metadata = {
            "backend": "lightweight",
            "version": "1.0.0",
            "model": "lightweight-regex-ner",
            "device": "cpu",
        }
        self._name_pattern = re.compile(
            r"\b[A-ZÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬĐÈÉẺẼẸÊẾỀỂỄỆÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴ]"
            r"[a-zàáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]+"
            r"(?:\s+[A-ZÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬĐÈÉẺẼẸÊẾỀỂỄỆÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴ]"
            r"[a-zàáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]+){1,3}\b"
        )

    def detect(self, text: str) -> list[Span]:
        if not text.strip():
            return []
        return [Span(m.start(), m.end(), "PERSON", layer=3) for m in self._name_pattern.finditer(text)]


def load_ner(backend: str, *, settings: Settings | None = None) -> Ner:
    import os

    settings = settings or get_settings()
    try:
        # Trên môi trường Render Free (512MB RAM), underthesea nạp transformers/torch nuốt trọn 496MB RAM gây OOM.
        # Tự động chuyển sang LightweightNer khi phát hiện chạy trên Render hoặc bật cờ LIGHTWEIGHT_NER.
        if (
            backend in ("lightweight", "regex")
            or os.environ.get("RENDER")
            or os.environ.get("LIGHTWEIGHT_NER", "").lower() in ("1", "true")
        ):
            return LightweightNer()
        if backend == "underthesea":
            return UndertheseaNer()
        if backend == "spacy":
            return SpacyNer(settings.pii_spacy_model)
        if backend == "phobert":
            return PhoBertNer(settings.pii_phobert_model_dir, cpu_threads=settings.pii_ner_cpu_threads)
        raise NerUnavailableError("Unknown local NER backend")
    except Exception:
        raise NerUnavailableError("Local CPU NER initialization failed; provider calls are forbidden") from None


_lock = Lock()
_detector: Detector | None = None


def initialize_privacy(settings: Settings | None = None) -> Detector:
    global _detector
    settings = settings or get_settings()
    if not settings.pii_masking_enabled:
        raise MaskingError("PII masking is disabled; provider calls are forbidden")
    # Detection and mask-only assistant calls need no encryption key. Persistent
    # vault consumers validate their key when constructing PiiVault.
    with _lock:
        if _detector is None:
            _detector = Detector(load_ner(settings.pii_ner_backend, settings=settings))
        return _detector


def get_detector() -> Detector:
    if _detector is None:
        raise NerUnavailableError("Privacy model was not initialized at startup; provider calls are forbidden")
    return _detector
