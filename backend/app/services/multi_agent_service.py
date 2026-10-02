"""Persistence and deterministic merge rules for controlled specialist output."""

import json
import asyncio
import time
from hashlib import sha256
from dataclasses import dataclass
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.agent_runtime.collaboration import MergeDisposition
from app.agent_runtime.contracts import BudgetExhausted, RuntimeCancelled
from app.models.generation import GeneratedCaseCandidate
from app.services.redaction import redact_output


@dataclass(frozen=True)
class CandidateCase:
    source_agent: str
    case: Mapping[str, Any]
    evidence_refs: list[dict[str, Any]]


@dataclass(frozen=True)
class MergedCase:
    case: dict[str, Any]
    source_agents: list[str]
    evidence_refs: list[dict[str, Any]]
    merge_reason: str


def persist_candidates(
    db: Session,
    task_id: int,
    requirement_item_id: int | None,
    agent_run_id: int | None,
    source_agent: str,
    cases: list[dict[str, Any]],
    evidence_refs: list[dict[str, Any]],
) -> list[GeneratedCaseCandidate]:
    rows = [
        GeneratedCaseCandidate(
            task_id=task_id,
            requirement_item_id=requirement_item_id,
            agent_run_id=agent_run_id,
            source_agent=source_agent,
            payload=json.dumps(case, ensure_ascii=False),
            evidence_refs=json.dumps(evidence_refs, ensure_ascii=False),
        )
        for case in cases
    ]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def _normalized_steps(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [value]
    if not isinstance(value, list):
        value = [value]
    return tuple(" ".join(str(item).split()).lower() for item in value)


def _case_key(case: Mapping[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    return (
        " ".join(str(case.get("title") or "").split()).lower(),
        str(case.get("case_type") or "functional").lower(),
        _normalized_steps(case.get("steps") or []),
    )


def _candidate_fingerprint(case: Mapping[str, Any]) -> str:
    canonical = json.dumps(_case_key(case), ensure_ascii=False, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def classify_candidate_dispositions(
    candidates: list[CandidateCase],
) -> list[tuple[MergeDisposition, str]]:
    """Classify every candidate without discarding duplicate audit rows."""
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    decisions: list[tuple[MergeDisposition, str]] = []
    for candidate in candidates:
        key = _case_key(candidate.case)
        if key in seen:
            decisions.append(
                (MergeDisposition.MERGED_DUPLICATE, "duplicate_normalized_steps")
            )
        else:
            seen.add(key)
            decisions.append((MergeDisposition.SELECTED, ""))
    return decisions


def persist_candidate_cases(
    db: Session,
    task_id: int,
    requirement_item_id: int | None,
    agent_run_id: int | None,
    candidates: list[CandidateCase],
    decisions: list[tuple[MergeDisposition, str]],
    *,
    attempt_no: int = 0,
) -> list[GeneratedCaseCandidate]:
    if len(candidates) != len(decisions):
        raise ValueError("candidate decisions must align with candidates")
    rows = []
    occurrences: Counter[tuple[str, str]] = Counter()
    for candidate, (disposition, reason) in zip(candidates, decisions, strict=True):
        fingerprint = _candidate_fingerprint(candidate.case)
        occurrence_key = (candidate.source_agent, fingerprint)
        occurrence = occurrences[occurrence_key]
        occurrences[occurrence_key] += 1
        candidate_key = sha256(
            f"{int(attempt_no)}:{fingerprint}:{occurrence}".encode("utf-8")
        ).hexdigest()
        row = None
        if agent_run_id is not None:
            row = (
                db.query(GeneratedCaseCandidate)
                .filter(
                    GeneratedCaseCandidate.agent_run_id == agent_run_id,
                    GeneratedCaseCandidate.requirement_item_id == requirement_item_id,
                    GeneratedCaseCandidate.source_agent == candidate.source_agent,
                    GeneratedCaseCandidate.candidate_key == candidate_key,
                )
                .first()
            )
        if row is None:
            row = GeneratedCaseCandidate(
                task_id=task_id,
                requirement_item_id=requirement_item_id,
                agent_run_id=agent_run_id,
                source_agent=candidate.source_agent,
                candidate_key=candidate_key,
                payload=json.dumps(candidate.case, ensure_ascii=False),
                evidence_refs=json.dumps(candidate.evidence_refs, ensure_ascii=False),
            )
            db.add(row)
        row.merge_disposition = disposition.value
        row.merge_reason = reason
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def _append_unique(items: list[dict[str, Any]], additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {json.dumps(item, ensure_ascii=False, sort_keys=True) for item in items}
    for item in additions:
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if marker not in seen:
            items.append(dict(item))
            seen.add(marker)
    return items


def merge_candidates(candidates: list[CandidateCase]) -> list[MergedCase]:
    """Merge exact normalized duplicates while retaining a complete source chain."""
    merged_by_key: dict[tuple[str, str, tuple[str, ...]], MergedCase] = {}
    for candidate in candidates:
        key = _case_key(candidate.case)
        current = merged_by_key.get(key)
        if current is None:
            merged_by_key[key] = MergedCase(
                case=dict(candidate.case),
                source_agents=[candidate.source_agent],
                evidence_refs=[dict(ref) for ref in candidate.evidence_refs],
                merge_reason="",
            )
            continue
        sources = list(current.source_agents)
        if candidate.source_agent not in sources:
            sources.append(candidate.source_agent)
        merged_by_key[key] = MergedCase(
            case=current.case,
            source_agents=sources,
            evidence_refs=_append_unique(list(current.evidence_refs), candidate.evidence_refs),
            merge_reason="duplicate_normalized_steps",
        )
    return list(merged_by_key.values())


async def run_specialists(
    roles: list[str],
    invoke: Callable[[str], Awaitable[list[dict[str, Any]]]],
    *,
    runtime: Any | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    """Run independent initial specialists with a hard concurrency ceiling of two."""
    semaphore = asyncio.Semaphore(2)

    async def run_one(role: str):
        async with semaphore:
            started_at = time.monotonic()
            if runtime is not None:
                runtime.record_agent_event("agent_started", role)
            try:
                result = await invoke(role)
            except (BudgetExhausted, RuntimeCancelled):
                raise
            except Exception as exc:
                if runtime is not None:
                    runtime.record_agent_event(
                        "agent_warning",
                        role,
                        duration_ms=int((time.monotonic() - started_at) * 1000),
                        message=str(exc),
                    )
                return role, [], {
                    "agent": role,
                    "message": redact_output(str(exc), limit=500),
                }
            if runtime is not None:
                runtime.record_agent_event(
                    "agent_completed",
                    role,
                    candidate_count=len(result),
                    duration_ms=int((time.monotonic() - started_at) * 1000),
                )
            return role, result, None

    outcomes = await asyncio.gather(*(run_one(role) for role in roles))
    cases = {role: result for role, result, warning in outcomes if not warning}
    warnings = [warning for _, _, warning in outcomes if warning]
    return cases, warnings
