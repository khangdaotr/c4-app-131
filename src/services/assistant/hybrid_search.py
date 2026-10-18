"""BM25 + vector retrieval using reciprocal rank fusion (k=60)."""

import json
import logging
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any

from rank_bm25 import BM25Okapi

from src.config import get_settings
from src.services.assistant.chunker import DocChunk
from src.services.assistant.embedding import tokenize
from src.services.assistant.guardrails import has_careerv_topic
from src.services.assistant.vector_store import AssistantVectorStore

logger = logging.getLogger(__name__)
ASSISTANT_INDEX_LOCK = RLock()
MIN_RETRIEVAL_SCORE = 0.42
CITATION_SCORE_RATIO = 0.7
MAX_CITATIONS = 3
RRF_K = 60
MAX_RRF_SCORE = 2.0 / (RRF_K + 1)


@lru_cache(maxsize=1)
def _cached_retriever(
    config: tuple[str, str, str, str], corpus_stamp: tuple[int, int] | None
) -> "AssistantHybridRetriever":
    """Cache identity includes the collection, embedding config and corpus file revision."""
    return AssistantHybridRetriever()


def invalidate_retriever() -> None:
    """Discard the old collection handle before replacement, including failed rebuilds."""
    with ASSISTANT_INDEX_LOCK:
        _cached_retriever.cache_clear()


def get_assistant_retriever() -> "AssistantHybridRetriever":
    """Reuse Chroma and BM25 until a rebuild or configuration change."""
    settings = get_settings()
    directory = Path(settings.assistant_chroma_persist_dir).resolve()
    path = directory / f"{settings.assistant_chroma_collection}_bm25.json"
    with ASSISTANT_INDEX_LOCK:
        try:
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            stamp = None
        return _cached_retriever(
            (
                str(directory),
                settings.assistant_chroma_collection,
                settings.assistant_embedding_model,
                settings.assistant_embedding_device,
            ),
            stamp,
        )


# Vietnamese function words and generic help phrasing are not topic evidence.
QUERY_STOP_WORDS = frozenset(
    "và là gì ở đâu tôi có thể cho với trong các những được không nào sao thế này một bạn "
    "bao nhiêu hãy giúp làm của để về cách hướng dẫn trang nút mở đừng chỉ "
    "thời tiết ngày mai nay hôm giờ tuần tháng năm bảo biết nào "
    "cảm thấy chào ơi khỏe tên hôm nay nhỉ ạ nhé vui buồn thế nào "
    "cam thay chao oi khoe ten hom nhi a nhe the nao hello hi".split()
)


def select_citation_chunks(chunks: list[dict[str, Any]], limit: int = MAX_CITATIONS) -> list[dict[str, Any]]:
    """Gate absolute relevance before applying the relative citation cutoff."""
    if not chunks or limit <= 0:
        return []
    ranked = sorted(chunks, key=lambda item: (-item["score"], item["chunk_id"]))
    max_score = ranked[0]["score"]
    threshold = get_settings().rag_abstain_threshold
    if max_score < threshold:
        return []
    cutoff = max(threshold, CITATION_SCORE_RATIO * max_score)
    return [item for item in ranked if item["score"] >= cutoff][: min(limit, MAX_CITATIONS)]


def corpus_path(store: AssistantVectorStore) -> Path:
    return store.persist_dir / f"{store.collection_name}_bm25.json"


def save_bm25_corpus(store: AssistantVectorStore, chunks: list[DocChunk]) -> None:
    """Persist plain JSON atomically; rebuild BM25 rather than loading pickles."""
    target = corpus_path(store)
    payload = {"version": 1, "chunks": [chunk.model_dump() for chunk in chunks]}
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target.with_suffix(".tmp")
    with open(temp_target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    try:
        if target.exists():
            target.unlink()
        temp_target.rename(target)
    except Exception:
        # Fallback to direct write if rename fails
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    finally:
        temp_target.unlink(missing_ok=True)


class AssistantHybridRetriever:
    def __init__(self, vector_store: AssistantVectorStore | None = None) -> None:
        self.vector_store = vector_store or AssistantVectorStore()
        # Chroma is authoritative if a previous rebuild stopped before saving JSON.
        actual = self.vector_store.get_chunks()
        path = corpus_path(self.vector_store)
        self.chunks = actual
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload["version"] != 1:
                    raise ValueError("Unsupported BM25 corpus version")
                saved = [DocChunk.model_validate(item) for item in payload["chunks"]]
                if {c.chunk_id: c for c in saved} == {c.chunk_id: c for c in actual}:
                    self.chunks = saved
                else:
                    logger.warning("Stale BM25 corpus; rebuilding sparse retrieval from Chroma")
            except (ValueError, KeyError, TypeError):
                logger.warning("Invalid BM25 corpus; rebuilding sparse retrieval from Chroma")
        self._indexes: dict[str, tuple[list[DocChunk], BM25Okapi | None]] = {}

    def _role_index(self, role: str) -> tuple[list[DocChunk], BM25Okapi | None]:
        if role not in self._indexes:
            chunks = [chunk for chunk in self.chunks if chunk.role in (role, "all")]
            texts = [tokenize(f"{c.title} {c.section} {' '.join(c.tags)} {c.content}") for c in chunks]
            self._indexes[role] = (chunks, BM25Okapi(texts) if chunks else None)
        return self._indexes[role]

    def search(
        self, query: str, role: str, top_k: int | None = None, *, route: str | None = None
    ) -> list[dict[str, Any]]:
        limit = get_settings().assistant_top_k if top_k is None else top_k
        query_terms = set(tokenize(query)) - QUERY_STOP_WORDS
        if limit <= 0 or not query_terms:
            return []
        has_topic = has_careerv_topic(query)
        candidates = max(limit * 4, 20)
        dense = self.vector_store.search_vector(query, role, candidates)
        chunks, bm25 = self._role_index(role)
        sparse: list[dict[str, Any]] = []
        if bm25 is not None:
            scores = bm25.get_scores(sorted(query_terms))
            ranked = sorted(range(len(chunks)), key=lambda i: (-float(scores[i]), chunks[i].chunk_id))
            # Zero-score documents must not gain arbitrary reciprocal-rank credit.
            sparse = [
                {**chunks[i].model_dump(), "bm25_score": float(scores[i])} for i in ranked[:candidates] if scores[i] > 0
            ]
        fused: dict[str, dict[str, Any]] = {}
        for name, results in (("vector", dense), ("bm25", sparse)):
            for rank, item in enumerate(results, start=1):
                chunk_id = item["chunk_id"]
                if chunk_id not in fused:
                    fused[chunk_id] = {**item, "rrf_score": 0.0}
                record = fused[chunk_id]
                record[f"{name}_rank"] = rank
                if name == "bm25":
                    record["bm25_score"] = item["bm25_score"]
                record["rrf_score"] += 1.0 / (RRF_K + rank)
        for record in fused.values():
            cosine = max(0.0, min(1.0, 1.0 - record.get("distance", 1.0)))
            bm25_score = max(0.0, record.get("bm25_score", 0.0))
            # Use a fixed RRF upper bound, never the query's best score: even
            # unrelated queries have a rank-1 result. Bound BM25's unscaled
            # evidence separately so ranks cannot masquerade as confidence.
            document_terms = set(
                tokenize(f"{record.get('title', '')} {' '.join(record.get('tags', []))} {record.get('content', '')}")
            )
            matched_terms = query_terms & document_terms
            coverage = len(matched_terms) / len(query_terms)
            # A single coincidental keyword must not turn a large BM25 score
            # into strong evidence for an otherwise unrelated question.
            sparse_relevance = bm25_score / (1.0 + bm25_score) * coverage
            # Domain queries can use semantic matches (e.g. "tải" vs "upload").
            # Generic queries need lexical coverage as well as a dense score.
            relevance = max(cosine if has_topic else cosine * coverage, sparse_relevance)
            record["score"] = record["rrf_score"] / MAX_RRF_SCORE * relevance
            # Confidence must not rise just because an unrelated question was
            # asked on the document's page. Keep ranking/boosting unchanged.
            record["abstain_score"] = record["score"]
            if route is not None and record.get("route") == route:
                record["rrf_score"] *= 1.15
                record["score"] *= 1.15
            if not matched_terms or (len(query_terms) <= 3 and len(matched_terms) <= 1 and not has_topic):
                record["score"] = 0.0
                record["abstain_score"] = 0.0
        return select_citation_chunks(list(fused.values()), limit)

    def retrieve(
        self, query: str, role: str, top_k: int | None = None, *, route: str | None = None
    ) -> list[dict[str, Any]]:
        return self.search(query, role, top_k, route=route)
