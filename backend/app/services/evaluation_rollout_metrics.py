"""Read-only rollout evidence for terminal evaluation Worker runs."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.evaluation import EvaluationScorecard, EvalResult


TERMINAL_RUN_STATUSES = ("completed", "failed", "cancelled")
SKILL_TERMINAL_EVENTS = {"skill_completed", "skill_failed", "skill_cancelled"}


def _rate(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def _event_skill(event: AgentRunEvent) -> str:
    payload = _event_payload(event)
    return str(payload.get("skill") or "")


def _event_payload(event: AgentRunEvent) -> dict:
    try:
        payload = json.loads(event.payload_summary or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _event_result_id(event: AgentRunEvent) -> int | None:
    value = _event_payload(event).get("result_id")
    return value if isinstance(value, int) and value > 0 else None


def _duplicate_skill_lifecycle_count(events: list[AgentRunEvent]) -> int:
    open_attempts: set[tuple[int, str]] = set()
    duplicates = 0
    for event in events:
        if event.event_type != "skill_started" and event.event_type not in SKILL_TERMINAL_EVENTS:
            continue
        key = (event.agent_run_id, _event_skill(event))
        if event.event_type == "skill_started":
            if key in open_attempts:
                duplicates += 1
            else:
                open_attempts.add(key)
        elif key in open_attempts:
            open_attempts.remove(key)
        else:
            duplicates += 1
    return duplicates


def _cancellation_latencies(events: list[AgentRunEvent]) -> list[float]:
    requested_at = {}
    latencies = []
    for event in events:
        if event.event_type == "run_cancel_requested":
            requested_at[event.agent_run_id] = event.created_at
        elif event.event_type == "run_cancelled":
            started = requested_at.get(event.agent_run_id)
            if started is not None and event.created_at is not None:
                latencies.append(
                    max(0.0, (event.created_at - started).total_seconds() * 1000)
                )
    return latencies


def build_evaluation_rollout_report(
    db: Session,
    project_id: int,
    *,
    limit: int = 30,
) -> dict:
    """Aggregate bounded gray-rollout metrics without exposing event payloads."""
    runs = list(
        db.scalars(
            select(AgentRun)
            .where(
                AgentRun.project_id == project_id,
                AgentRun.evaluation_run_id.is_not(None),
                AgentRun.status.in_(TERMINAL_RUN_STATUSES),
            )
            .order_by(AgentRun.id.desc())
            .limit(max(1, min(int(limit), 100)))
        ).all()
    )
    agent_run_ids = [run.id for run in runs]
    eval_run_ids = [run.evaluation_run_id for run in runs]
    if not runs:
        return {
            "terminal_run_count": 0,
            "judged_batch_count": 0,
            "judge_attempted_batch_count": 0,
            "judge_unavailable_count": 0,
            "judge_unavailable_rate": 0.0,
            "judge_retry_batch_count": 0,
            "judge_retry_rate": 0.0,
            "cancellation_latency_ms": {"count": 0, "average": None, "maximum": None},
            "duplicate_skill_lifecycle_event_count": 0,
        }

    scorecards = list(
        db.scalars(
            select(EvaluationScorecard)
            .join(EvalResult, EvaluationScorecard.result_id == EvalResult.id)
            .where(EvalResult.run_id.in_(eval_run_ids))
        ).all()
    )
    events = list(
        db.scalars(
            select(AgentRunEvent)
            .where(AgentRunEvent.agent_run_id.in_(agent_run_ids))
            .order_by(AgentRunEvent.agent_run_id, AgentRunEvent.sequence)
        ).all()
    )
    judged_scorecards = [
        card
        for card in scorecards
        if card.judge_status in {"completed", "unavailable"}
    ]
    judged_batch_count = len(judged_scorecards)
    unavailable_count = sum(
        card.judge_status == "unavailable" for card in judged_scorecards
    )
    scorecard_result_ids = {card.result_id for card in scorecards}
    result_eval_run_ids = dict(
        db.execute(
            select(EvalResult.id, EvalResult.run_id).where(
                EvalResult.id.in_(scorecard_result_ids)
            )
        ).all()
    ) if scorecard_result_ids else {}
    judged_eval_run_ids = {
        result_eval_run_ids.get(card.result_id) for card in judged_scorecards
    }
    eligible_legacy_retry_runs = {
        run.id for run in runs if run.evaluation_run_id in judged_eval_run_ids
    }
    attempted_result_ids = {card.result_id for card in judged_scorecards}
    retry_result_ids: set[int] = set()
    scoped_retry_run_ids: set[int] = set()
    legacy_retry_run_ids: set[int] = set()
    for event in events:
        if event.event_type not in {
            "evaluation_judge_started",
            "evaluation_judge_retry",
        }:
            continue
        result_id = _event_result_id(event)
        if result_id is not None and result_id in scorecard_result_ids:
            attempted_result_ids.add(result_id)
            if event.event_type == "evaluation_judge_retry":
                retry_result_ids.add(result_id)
                scoped_retry_run_ids.add(event.agent_run_id)
        elif event.event_type == "evaluation_judge_retry":
            # Historical events predate result_id. Count at most one retry batch
            # per run and never combine it with scoped evidence from that run.
            legacy_retry_run_ids.add(event.agent_run_id)
    retry_count = len(retry_result_ids) + len(
        (legacy_retry_run_ids - scoped_retry_run_ids) & eligible_legacy_retry_runs
    )
    attempted_batch_count = len(attempted_result_ids)
    latencies = _cancellation_latencies(events)

    return {
        "terminal_run_count": len(runs),
        "judged_batch_count": judged_batch_count,
        "judge_attempted_batch_count": attempted_batch_count,
        "judge_unavailable_count": unavailable_count,
        "judge_unavailable_rate": _rate(unavailable_count, judged_batch_count),
        "judge_retry_batch_count": retry_count,
        "judge_retry_rate": _rate(retry_count, attempted_batch_count),
        "cancellation_latency_ms": {
            "count": len(latencies),
            "average": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "maximum": round(max(latencies), 1) if latencies else None,
        },
        "duplicate_skill_lifecycle_event_count": _duplicate_skill_lifecycle_count(events),
    }
