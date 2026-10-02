"""CLI and artifact writer for reproducible RAG retrieval ablations."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.ai.embedding_factory import embedding_configured, embedding_context
from app.models.system_config import SystemConfig
from app.database import SessionLocal
from app.services.settings_service import RuntimeModelConfig, runtime_config
from benchmarks.rag.corpus import CorpusChunk, build_corpus
from benchmarks.rag.metrics import RetrievalObservation, summarize_strategy
from benchmarks.rag.report import render_report
from benchmarks.rag.retrieval_variants import StrategyName, VectorSearch, retrieve_variant
from benchmarks.rag.schema import BenchmarkDataset, load_dataset

ROOT = Path(__file__).resolve().parent
PARAMETERS = {"top_k": [1, 3, 5], "recall_top_k": 20, "threshold": 0.35, "rrf_k": 60}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def create_vector_search(corpus: Sequence[CorpusChunk], config: RuntimeModelConfig, directory: Path) -> VectorSearch:
    directory.mkdir(parents=True, exist_ok=True)
    collection = "rag_benchmark"
    docs = [Document(page_content=f"{item.heading}\n{item.content}", metadata={"chunk_id": item.chunk_id}) for item in corpus]
    ids = [item.chunk_id for item in corpus]
    async with embedding_context(config) as embeddings:
        store = Chroma(collection_name=collection, embedding_function=embeddings, persist_directory=str(directory), collection_metadata={"hnsw:space": "cosine"})
        store.delete(ids=ids)
        await store.aadd_documents(docs, ids=ids)

    cache: dict[tuple[str, int], list[tuple[str, float]]] = {}

    async def search(query: str, top_n: int) -> list[tuple[str, float]]:
        key = (query, top_n)
        if key in cache:
            return cache[key]
        async with embedding_context(config) as embeddings:
            store = Chroma(collection_name=collection, embedding_function=embeddings, persist_directory=str(directory), collection_metadata={"hnsw:space": "cosine"}, relevance_score_fn=lambda distance: max(0.0, min(1.0, 1.0 - distance)))
            rows = await store.asimilarity_search_with_relevance_scores(query, k=top_n)
        cache[key] = [(str(doc.metadata["chunk_id"]), float(score)) for doc, score in rows]
        return cache[key]
    return search


async def run_benchmark(dataset: BenchmarkDataset, corpus: Sequence[CorpusChunk], config: RuntimeModelConfig, output_dir: Path, *, rounds: int = 3, vector_search: VectorSearch | None = None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    if vector_search is None and embedding_configured(config):
        vector_search = await create_vector_search(corpus, config, output_dir / "vector-store")
    strategies: list[StrategyName] = ["bm25"]
    if vector_search is not None:
        strategies += ["vector", "hybrid_rrf"]
    strategies.append("hybrid_rerank")
    raw_rows: list[dict] = []
    strategy_summary: dict[str, dict] = {}
    for strategy in strategies:
        observations = []
        for round_no in range(1, rounds + 1):
            for query in dataset.queries:
                result = await retrieve_variant(strategy, corpus, query.query, config, top_k=5, vector_search=vector_search)
                observations.append(RetrievalObservation(query, result.ranked_chunk_ids, result.latency_ms, result.status, result.fallback_used))
                raw_rows.append({"strategy": strategy, "round": round_no, "query_id": query.query_id, "ranked_chunk_ids": result.ranked_chunk_ids, "latency_ms": result.latency_ms, "status": result.status, "fallback_used": result.fallback_used, "error": result.error})
        metric = summarize_strategy(observations)
        statuses = {row.status for row in observations}
        strategy_summary[strategy] = {"status": "completed" if "completed" in statuses else "not_executed", "error": next((row["error"] for row in raw_rows if row["strategy"] == strategy and row["error"]), ""), "availability": metric.availability, "p95_latency_ms": metric.p95_latency_ms or 0.0, "metrics": {str(k): values for k, values in metric.metrics_by_k.items()}, "fallback_count": metric.fallback_count}
    artifact = {"title": "AITC RAG 检索离线领域基准评测", "timestamp_utc": datetime.now(timezone.utc).isoformat(), "dataset_sha256": _sha256(ROOT / "dataset.json"), "corpus_sha256": hashlib.sha256(json.dumps([asdict(item) for item in corpus], ensure_ascii=False, sort_keys=True).encode()).hexdigest(), "retrieval_parameters": PARAMETERS, "models": {"embedding": config.embedding_model, "rerank": config.rerank_model}, "queries": raw_rows, "strategies": strategy_summary}
    (output_dir / "raw-results.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(render_report(artifact), encoding="utf-8")
    return artifact


def _config() -> RuntimeModelConfig:
    db = SessionLocal()
    try:
        row = db.query(SystemConfig).first()
        return runtime_config(row) if row else RuntimeModelConfig()
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    corpus = build_corpus(ROOT / "knowledge")
    dataset = load_dataset(ROOT / "dataset.json", {item.chunk_id for item in corpus})
    asyncio.run(run_benchmark(dataset, corpus, _config(), args.output_dir, rounds=args.rounds))


if __name__ == "__main__":
    main()
