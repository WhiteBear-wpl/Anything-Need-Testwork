"""Pure ranking and operational metrics for retrieval benchmark artifacts."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import fmean
from typing import Sequence

from benchmarks.rag.schema import BenchmarkQuery


@dataclass(frozen=True)
class QueryMetrics:
    recall_at_k: float
    mrr_at_k: float
    ndcg_at_k: float
    no_answer_false_positive: bool


@dataclass(frozen=True)
class RetrievalObservation:
    query: BenchmarkQuery
    ranked_chunk_ids: Sequence[str]
    latency_ms: float
    status: str
    fallback_used: bool = False


@dataclass(frozen=True)
class StrategyMetrics:
    query_count: int
    availability: float
    mean_latency_ms: float | None
    p95_latency_ms: float | None
    metrics_by_k: dict[int, dict[str, float | None]]
    category_metrics: dict[str, dict[int, dict[str, float | None]]]
    fallback_count: int


def score_query(query: BenchmarkQuery, ranked_chunk_ids: Sequence[str], k: int) -> QueryMetrics:
    """Score a single ranking; relevance grades 2 and 3 count as answer-bearing hits."""
    ranked = list(ranked_chunk_ids[:k])
    if query.category == "no_answer":
        return QueryMetrics(0.0, 0.0, 0.0, bool(ranked))

    grades = query.gold_relevance
    relevant_ranks = [
        rank
        for rank, chunk_id in enumerate(ranked, start=1)
        if grades.get(chunk_id, 0) >= 2
    ]
    recall = 1.0 if relevant_ranks else 0.0
    mrr = 1.0 / relevant_ranks[0] if relevant_ranks else 0.0
    dcg = sum(
        (2 ** grades.get(chunk_id, 0) - 1) / math.log2(rank + 1)
        for rank, chunk_id in enumerate(ranked, start=1)
        if grades.get(chunk_id, 0) > 0
    )
    ideal_grades = sorted(grades.values(), reverse=True)[:k]
    ideal_dcg = sum(
        (2**grade - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(ideal_grades, start=1)
    )
    return QueryMetrics(recall, mrr, dcg / ideal_dcg if ideal_dcg else 0.0, False)


def percentile(values: Sequence[float], percent: float) -> float | None:
    """Return nearest-rank percentile; returns None for an empty input."""
    if not values:
        return None
    if not 0 < percent <= 100:
        raise ValueError("percent must be within (0, 100]")
    ordered = sorted(values)
    return ordered[math.ceil(percent / 100 * len(ordered)) - 1]


def _aggregate(observations: Sequence[RetrievalObservation], k: int) -> dict[str, float | None]:
    completed = [item for item in observations if item.status == "completed"]
    answer_scores = [score_query(item.query, item.ranked_chunk_ids, k) for item in completed if item.query.category != "no_answer"]
    no_answer_scores = [score_query(item.query, item.ranked_chunk_ids, k) for item in completed if item.query.category == "no_answer"]
    return {
        "recall": fmean(item.recall_at_k for item in answer_scores) if answer_scores else None,
        "mrr": fmean(item.mrr_at_k for item in answer_scores) if answer_scores else None,
        "ndcg": fmean(item.ndcg_at_k for item in answer_scores) if answer_scores else None,
        "no_answer_false_positive_rate": (
            fmean(float(item.no_answer_false_positive) for item in no_answer_scores)
            if no_answer_scores
            else None
        ),
    }


def summarize_strategy(
    observations: Sequence[RetrievalObservation], *, top_ks: Sequence[int] = (1, 3, 5)
) -> StrategyMetrics:
    """Aggregate one strategy without treating unavailable runs as quality failures."""
    if any(k < 1 for k in top_ks):
        raise ValueError("top_k must be positive")
    rows = list(observations)
    grouped: dict[str, list[RetrievalObservation]] = defaultdict(list)
    for row in rows:
        grouped[row.query.category].append(row)
    completed_count = sum(row.status == "completed" for row in rows)
    latencies = [row.latency_ms for row in rows if row.latency_ms >= 0]
    return StrategyMetrics(
        query_count=len(rows),
        availability=completed_count / len(rows) if rows else 0.0,
        mean_latency_ms=fmean(latencies) if latencies else None,
        p95_latency_ms=percentile(latencies, 95),
        metrics_by_k={k: _aggregate(rows, k) for k in top_ks},
        category_metrics={
            category: {k: _aggregate(category_rows, k) for k in top_ks}
            for category, category_rows in sorted(grouped.items())
        },
        fallback_count=sum(row.fallback_used for row in rows),
    )
