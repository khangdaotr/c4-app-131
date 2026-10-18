"""E5 or OpenRouter (bge-m3) embeddings with a deterministic, normalized offline fallback."""

import hashlib
import logging
import math
import re
import unicodedata
from threading import RLock
from typing import Any, ClassVar

from src.config import get_settings
from src.services.providers.gateway import (
    egress_scan,
    embedding_call,
    encode_e5,
    load_e5_model,
    provider_scope,
    telemetry_policy,
)

logger = logging.getLogger(__name__)


def tokenize(text: str) -> list[str]:
    """Use the same Unicode normalization for hashing and BM25."""
    return re.findall(r"\w+", unicodedata.normalize("NFC", text).casefold())


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


class OpenRouterEmbedder:
    """Remote embeddings (e.g. baai/bge-m3) through OpenRouter's OpenAI-compatible API."""

    def __init__(self, model: str, api_key: str, base_url: str, batch_size: int) -> None:
        from openai import OpenAI

        self.model = model
        self.batch_size = batch_size
        self._client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=60)

    def encode(self, masked: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for offset in range(0, len(masked), self.batch_size):
            payload = {"model": self.model, "input": masked[offset : offset + self.batch_size]}
            # Scan the complete outbound body, as for every other provider call.
            with provider_scope() as scope:
                egress_scan(payload, scope)
            with telemetry_policy():
                result = self._client.embeddings.create(**payload, encoding_format="float")
            vectors.extend(_normalize(list(item.embedding)) for item in sorted(result.data, key=lambda d: d.index))
        if len(vectors) != len(masked):
            raise RuntimeError("Embedding provider returned an unexpected number of vectors")
        return vectors


class AssistantEmbeddingService:
    """One model per process; never silently mix embedding spaces in an index."""

    _instance: ClassVar["AssistantEmbeddingService | None"] = None
    _lock: ClassVar[RLock] = RLock()
    _remote: "OpenRouterEmbedder | None" = None

    def __new__(cls) -> "AssistantEmbeddingService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self) -> None:
        with self._lock:
            if getattr(self, "_initialized", False):
                return
            settings = get_settings()
            self._model: Any = None
            self._remote: OpenRouterEmbedder | None = None
            self._used_model = False
            self.model_name = settings.assistant_embedding_model
            self.dimension = 384
            if settings.assistant_embedding_provider == "openrouter":
                # Remote embedding: never load torch/E5 into server RAM. A missing key fails loudly
                # instead of silently indexing with hashing vectors.
                if not settings.openrouter_api_key:
                    raise RuntimeError("ASSISTANT_EMBEDDING_PROVIDER=openrouter requires OPENROUTER_API_KEY")
                self.model_name = settings.assistant_embedding_api_model
                self._remote = OpenRouterEmbedder(
                    settings.assistant_embedding_api_model,
                    settings.openrouter_api_key,
                    settings.assistant_embedding_api_base_url,
                    settings.assistant_embedding_api_batch_size,
                )
                self.dimension = 0  # Known after the first response.
                self._initialized = True
                return
            try:
                self._model = load_e5_model(self.model_name, settings.assistant_embedding_device)
                dimension = getattr(self._model, "get_embedding_dimension", None)
                if callable(dimension):
                    self.dimension = int(dimension())
                else:
                    self.dimension = int(self._model.get_sentence_embedding_dimension())
            except Exception as exc:
                self._model = None
                logger.warning("E5 unavailable (%s); using deterministic hashing embeddings", type(exc).__name__)
            self._initialized = True

    @property
    def embedding_id(self) -> str:
        """Persist this identifier to reject incompatible queries after a restart."""
        if self._remote is not None:
            # Dimension is omitted: it is fixed by the model and unknown before the first call.
            return f"openrouter:{self.model_name}"
        if self._model is None:
            return "hashing-sha256-v1:384"
        return f"e5:{self.model_name}:{self.dimension}"

    def _hash(self, text: str) -> list[float]:
        vector = [0.0] * 384
        words = tokenize(text)
        features = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % 384] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]

    def _encode(self, texts: list[str], prefix: str) -> list[list[float]]:
        if not texts:
            return []
        with self._lock, provider_scope(mask_only=True):
            if self._remote is not None:
                # bge-m3 needs no task prefixes. Failures raise: mixing spaces would corrupt the index.
                vectors = embedding_call(texts, self._remote.encode, retries=2)
                self.dimension = len(vectors[0])
                return vectors
            if self._model is not None:
                try:
                    vectors = encode_e5(self._model, texts, prefix)
                    self._used_model = True
                    return vectors
                except Exception:
                    if self._used_model:
                        raise RuntimeError(
                            "E5 encoding failed; refusing to mix embeddings. Rebuild the index."
                        ) from None
                    self._model = None
                    self.dimension = 384
                    logger.warning("E5 encoding unavailable; using deterministic hashing embeddings")
            # Prefixes identify the E5 task; exclude them from lexical hashing.
            return embedding_call(texts, lambda masked: [self._hash(text) for text in masked], local=True)

    def embed_query(self, query: str) -> list[float]:
        return self._encode([query], "query: ")[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts, "passage: ")
