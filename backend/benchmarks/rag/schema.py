"""Validated, immutable contracts for the RAG retrieval benchmark."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping


QueryCategory = Literal["semantic", "exact", "composite", "distractor", "no_answer"]
_CATEGORIES = {"semantic", "exact", "composite", "distractor", "no_answer"}


@dataclass(frozen=True)
class GoldRelevance:
    chunk_id: str
    grade: int


@dataclass(frozen=True)
class BenchmarkQuery:
    query_id: str
    query: str
    category: QueryCategory
    gold_relevance: Mapping[str, int]
    notes: str


@dataclass(frozen=True)
class BenchmarkDataset:
    version: int
    queries: tuple[BenchmarkQuery, ...]


def load_dataset(path: Path, available_chunk_ids: set[str] | None = None) -> BenchmarkDataset:
    """Load benchmark labels and reject evidence that cannot be scored faithfully."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid dataset JSON: {exc.msg}") from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("version"), int):
        raise ValueError("dataset requires integer version")
    queries = raw.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("dataset requires non-empty queries")

    parsed: list[BenchmarkQuery] = []
    seen_ids: set[str] = set()
    for item in queries:
        if not isinstance(item, dict):
            raise ValueError("query must be an object")
        query_id = item.get("query_id")
        query = item.get("query")
        category = item.get("category")
        notes = item.get("notes", "")
        gold = item.get("gold_relevance", {})
        if not isinstance(query_id, str) or not query_id.strip():
            raise ValueError("query requires query_id")
        if query_id in seen_ids:
            raise ValueError(f"duplicate query_id: {query_id}")
        seen_ids.add(query_id)
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"query {query_id} requires non-empty query")
        if category not in _CATEGORIES:
            raise ValueError(f"query {query_id} has invalid category")
        if not isinstance(notes, str):
            raise ValueError(f"query {query_id} notes must be a string")
        if not isinstance(gold, dict):
            raise ValueError(f"query {query_id} gold_relevance must be an object")
        if category == "no_answer" and gold:
            raise ValueError(f"no_answer query {query_id} must not have gold evidence")
        if category != "no_answer" and not gold:
            raise ValueError(f"query {query_id} requires gold evidence")

        normalized_gold: dict[str, int] = {}
        for chunk_id, grade in gold.items():
            if not isinstance(chunk_id, str) or not chunk_id:
                raise ValueError(f"query {query_id} has invalid gold chunk ID")
            if not isinstance(grade, int) or isinstance(grade, bool) or grade not in {1, 2, 3}:
                raise ValueError(f"query {query_id} has invalid relevance grade")
            if available_chunk_ids is not None and chunk_id not in available_chunk_ids:
                raise ValueError(f"unknown gold chunk: {chunk_id}")
            normalized_gold[chunk_id] = grade

        parsed.append(
            BenchmarkQuery(
                query_id=query_id,
                query=query.strip(),
                category=category,
                gold_relevance=normalized_gold,
                notes=notes.strip(),
            )
        )
    return BenchmarkDataset(version=raw["version"], queries=tuple(parsed))
