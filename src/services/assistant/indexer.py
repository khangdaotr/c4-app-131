"""Run from the repository root: python -m src.services.assistant.indexer."""

import argparse
import hashlib
import logging
from pathlib import Path

from src.config import get_settings
from src.services.assistant.chunker import DocChunk, MarkdownDocChunker
from src.services.assistant.hybrid_search import ASSISTANT_INDEX_LOCK, invalidate_retriever, save_bm25_corpus
from src.services.assistant.vector_store import AssistantVectorStore


def build_assistant_index(docs_dir: str | None = None) -> int:
    root = Path(docs_dir if docs_dir is not None else get_settings().assistant_docs_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Assistant documents directory not found: {root}")
    files = sorted(root.rglob("*.md"))
    if not files:
        raise ValueError(f"No Markdown documents found in {root}; existing index was not cleared")
    chunker = MarkdownDocChunker()
    chunks: list[DocChunk] = []
    for path in files:
        try:
            document_chunks = chunker.chunk_file(path, source=path.relative_to(root).as_posix())
            if not document_chunks:
                raise ValueError("Document has no indexable content")
            chunks.extend(document_chunks)
        except ValueError as exc:
            raise ValueError(f"Invalid Assistant document {path}: {exc}") from exc
    # One corpus stamp invalidates shared answers even when an unrelated guide
    # changes. Include action metadata as well as text; never use file mtimes.
    version = hashlib.sha256("\n".join(chunk.model_dump_json() for chunk in chunks).encode("utf-8")).hexdigest()
    chunks = [chunk.model_copy(update={"docs_version": version}) for chunk in chunks]
    # Validate every document before modifying the existing collection.
    with ASSISTANT_INDEX_LOCK:
        invalidate_retriever()
        store = AssistantVectorStore()
        store.replace_chunks(chunks)
        save_bm25_corpus(store, chunks)
    print(f"Embedding backend: {store.embedding_service.embedding_id}")
    print(f"Successfully indexed {len(chunks)} chunks from {len(files)} files")
    return len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild Assistant Chroma and BM25 indexes")
    parser.add_argument("--docs-dir", help="Override the configured Markdown documents directory")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        from src.services.providers.gateway import initialize_gateway_runtime

        initialize_gateway_runtime()
        build_assistant_index(args.docs_dir)
    except (OSError, ValueError, RuntimeError):
        parser.exit(1, "Assistant indexing unavailable\n")


if __name__ == "__main__":
    main()
