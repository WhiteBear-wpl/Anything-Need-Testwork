"""Ablation adapters mirroring AITC's BM25, RRF and optional rerank semantics."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from app.services.knowledge_service import _make_bm25, _rrf_fuse, _tokenize
from app.services.llm import rerank_documents
from app.services.settings_service import RuntimeModelConfig
from benchmarks.rag.corpus import CorpusChunk


StrategyName = Literal["vector", "bm25", "hybrid_rrf", "hybrid_rerank"]
VectorSearch = Callable[[str, int], Awaitable[list[tuple[str, float]]]]


@dataclass(frozen=True)
class StrategyResult:
    status: str
    ranked_chunk_ids: list[str]
    latency_ms: float
    fallback_used: bool = False
    error: str = ""


def _bm25_hits(corpus: Sequence[CorpusChunk], query: str, top_n: int) -> list[dict]:
    tokens = _tokenize(query)
    if not tokens:
        return []
    tokenized = [_tokenize(f"{item.heading}\n{item.content}") for item in corpus]
    if not any(tokenized):
        return []
    scores = _make_bm25(tokenized).get_scores(tokens)
    ordered = sorted(zip(corpus, scores), key=lambda item: item[1], reverse=True)
    return [
        {"chroma_id": item.chunk_id, "content": item.content, "title": item.document, "heading": item.heading, "score": 0.0}
        for item, score in ordered[:top_n]
        if score > 0
    ]


async def retrieve_variant(
    strategy: StrategyName,
    corpus: Sequence[CorpusChunk],
    query: str,
    config: RuntimeModelConfig,
    *,
    top_k: int,
    vector_search: VectorSearch | None = None,
    recall_top_k: int = 20,
    threshold: float = 0.35,
    rrf_k: int = 60,
) -> StrategyResult:
    """Return a ranking for one strategy; an unavailable optional service is explicit."""
    started = time.perf_counter()
    if strategy == "hybrid_rerank" and not config.rerank_configured:
        return StrategyResult("not_executed", [], (time.perf_counter() - started) * 1000, error="Rerank 模型未配置")
    if strategy in {"vector", "hybrid_rrf", "hybrid_rerank"} and vector_search is None:
        return StrategyResult("not_executed", [], (time.perf_counter() - started) * 1000, error="真实 Embedding 检索未配置")

    vector_hits: list[dict] = []
    if vector_search is not None and strategy != "bm25":
        by_id = {item.chunk_id: item for item in corpus}
        for chunk_id, score in await vector_search(query, recall_top_k):
            if score >= threshold and chunk_id in by_id:
                item = by_id[chunk_id]
                vector_hits.append({"chroma_id": chunk_id, "content": item.content, "title": item.document, "heading": item.heading, "score": score})
    keyword_hits = _bm25_hits(corpus, query, recall_top_k)
    if strategy == "vector":
        ranked = vector_hits[:top_k]
    elif strategy == "bm25":
        ranked = keyword_hits[:top_k]
    else:
        ranked = _rrf_fuse(vector_hits, keyword_hits, k=rrf_k)
    if strategy != "hybrid_rerank":
        return StrategyResult("completed", [item["chroma_id"] for item in ranked[:top_k]], (time.perf_counter() - started) * 1000)
    try:
        reranked = await rerank_documents(query, [item["content"] for item in ranked], config, top_n=top_k)
    except Exception:
        return StrategyResult("completed", [item["chroma_id"] for item in ranked[:top_k]], (time.perf_counter() - started) * 1000, fallback_used=True)
    return StrategyResult("completed", [ranked[index]["chroma_id"] for index, _ in reranked if index < len(ranked)][:top_k], (time.perf_counter() - started) * 1000)
