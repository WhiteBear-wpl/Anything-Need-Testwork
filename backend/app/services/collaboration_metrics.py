"""Read-only metrics for controlled multi-agent generation and rollout."""

import json
from collections import Counter
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.generation import GeneratedCaseCandidate, GeneratedCaseDraft, GenerationTask


def _source_agents(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        value = []
    if not isinstance(value, list):
        value = []
    agents = []
    for item in value:
        agent = str(item or "").strip()
        if agent and agent not in agents:
            agents.append(agent)
    return agents or ["case_writer"]


def _event_agent(event: AgentRunEvent) -> str:
    try:
        payload = json.loads(event.payload_summary or "{}")
    except (json.JSONDecodeError, TypeError):
        return "unknown"
    if not isinstance(payload, dict):
        return "unknown"
    return str(payload.get("agent") or "unknown")


def _ordered_counts(counter: Counter) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def build_task_collaboration_summary(
    db: Session,
    project_id: int,
    task_id: int,
    run_id: int,
) -> dict[str, Any]:
    task = (
        db.query(GenerationTask)
        .filter(GenerationTask.id == task_id, GenerationTask.project_id == project_id)
        .first()
    )
    if task is None:
        raise ValueError("generation task does not belong to project")

    candidates = (
        db.query(GeneratedCaseCandidate)
        .filter(
            GeneratedCaseCandidate.task_id == task_id,
            GeneratedCaseCandidate.agent_run_id == run_id,
        )
        .order_by(GeneratedCaseCandidate.id.asc())
        .all()
    )
    drafts = (
        db.query(GeneratedCaseDraft)
        .filter(
            GeneratedCaseDraft.task_id == task_id,
            GeneratedCaseDraft.agent_run_id == run_id,
        )
        .order_by(GeneratedCaseDraft.id.asc())
        .all()
    )
    warnings = (
        db.query(AgentRunEvent)
        .filter(
            AgentRunEvent.agent_run_id == run_id,
            AgentRunEvent.event_type == "agent_warning",
        )
        .all()
    )

    candidate_counts = Counter(candidate.source_agent for candidate in candidates)
    disposition_counts = Counter(candidate.merge_disposition for candidate in candidates)
    warning_counts = Counter(_event_agent(event) for event in warnings)
    draft_counts: Counter = Counter()
    adopted_counts: Counter = Counter()
    edited_counts: Counter = Counter()
    for draft in drafts:
        agents = _source_agents(draft.source_agents)
        draft_counts.update(agents)
        if draft.review_status == "adopted":
            adopted_counts.update(agents)
            if draft.was_edited:
                edited_counts.update(agents)

    return {
        "candidate_count": len(candidates),
        "candidate_counts_by_agent": _ordered_counts(candidate_counts),
        "disposition_counts": _ordered_counts(disposition_counts),
        "warning_counts_by_agent": _ordered_counts(warning_counts),
        "draft_counts_by_agent": _ordered_counts(draft_counts),
        "adopted_participation_by_agent": _ordered_counts(adopted_counts),
        "edited_participation_by_agent": _ordered_counts(edited_counts),
        "candidates": [
            {
                "id": candidate.id,
                "source_agent": candidate.source_agent,
                "status": candidate.status,
                "merge_disposition": candidate.merge_disposition,
                "merge_reason": candidate.merge_reason,
                "created_at": candidate.created_at,
            }
            for candidate in candidates
        ],
    }


def build_project_rollout_report(
    db: Session,
    project_id: int,
    limit: int = 30,
) -> dict[str, Any]:
    window_size = min(30, max(1, int(limit)))
    ranked_terminal_runs = (
        db.query(
            AgentRun.id.label("run_id"),
            func.row_number()
            .over(
                partition_by=AgentRun.generation_task_id,
                order_by=(AgentRun.created_at.desc(), AgentRun.id.desc()),
            )
            .label("task_run_rank"),
        )
        .filter(
            AgentRun.project_id == project_id,
            AgentRun.generation_task_id.isnot(None),
            AgentRun.status.in_(("completed", "failed", "cancelled")),
        )
        .subquery()
    )
    runs = (
        db.query(AgentRun)
        .join(
            ranked_terminal_runs,
            AgentRun.id == ranked_terminal_runs.c.run_id,
        )
        .filter(ranked_terminal_runs.c.task_run_rank == 1)
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(window_size)
        .all()
    )
    run_ids = [run.id for run in runs]
    events = (
        db.query(AgentRunEvent).filter(AgentRunEvent.agent_run_id.in_(run_ids)).all()
        if run_ids
        else []
    )
    candidates = (
        db.query(GeneratedCaseCandidate)
        .filter(GeneratedCaseCandidate.agent_run_id.in_(run_ids))
        .all()
        if run_ids
        else []
    )
    drafts = (
        db.query(GeneratedCaseDraft)
        .filter(GeneratedCaseDraft.agent_run_id.in_(run_ids))
        .all()
        if run_ids
        else []
    )

    status_counts = Counter(run.status for run in runs)
    terminal_count = sum(
        status_counts[status] for status in ("completed", "failed", "cancelled")
    )
    failure_rate = round(status_counts["failed"] / terminal_count * 100, 2) if terminal_count else 0.0
    durations = [
        int((run.finished_at - run.started_at).total_seconds() * 1000)
        for run in runs
        if run.started_at is not None and run.finished_at is not None
    ]
    average_duration_ms = round(sum(durations) / len(durations)) if durations else None

    event_types_by_run: dict[int, set[str]] = {}
    for event in events:
        event_types_by_run.setdefault(event.agent_run_id, set()).add(event.event_type)
    agent_started_count = sum(event.event_type == "agent_started" for event in events)
    agent_warning_count = sum(event.event_type == "agent_warning" for event in events)
    selected_count = sum(candidate.merge_disposition == "selected" for candidate in candidates)
    merged_duplicate_count = sum(
        candidate.merge_disposition == "merged_duplicate" for candidate in candidates
    )

    reviewed_draft_count = 0
    adopted_draft_count = 0
    specialist_influenced_adopted_count = 0
    adoption_participation: Counter = Counter()
    for draft in drafts:
        agents = _source_agents(draft.source_agents)
        if draft.review_status in ("adopted", "rejected"):
            reviewed_draft_count += 1
        if draft.review_status == "adopted":
            adopted_draft_count += 1
            adoption_participation.update(agents)
            if any(agent != "case_writer" for agent in agents):
                specialist_influenced_adopted_count += 1

    sample_size = len(runs)
    terminal_events = {"run_completed", "run_failed", "run_cancelled"}
    def has_complete_lifecycle(run: AgentRun) -> bool:
        event_types = event_types_by_run.get(run.id, set())
        if run.status == "cancelled" and "run_cancelled" in event_types:
            return True
        return "run_claimed" in event_types and bool(event_types & terminal_events)

    runs_with_complete_events = sum(has_complete_lifecycle(run) for run in runs)
    gates = {
        "sample_complete": sample_size >= 30,
        "events_present": sample_size > 0 and runs_with_complete_events == sample_size,
        "system_failure_rate_ok": terminal_count > 0 and failure_rate < 2.0,
        "specialist_adoption_observed": specialist_influenced_adopted_count > 0,
    }
    return {
        "sample_size": sample_size,
        "target_sample_size": 30,
        "completed_runs": status_counts["completed"],
        "failed_runs": status_counts["failed"],
        "cancelled_runs": status_counts["cancelled"],
        "system_failure_rate": failure_rate,
        "average_duration_ms": average_duration_ms,
        "duration_baseline_available": False,
        "duration_baseline_note": "历史 BackgroundTasks 缺少统一 started_at/finished_at，暂不判断 1.5 倍门槛",
        "agent_started_count": agent_started_count,
        "agent_warning_count": agent_warning_count,
        "candidate_count": len(candidates),
        "selected_count": selected_count,
        "merged_duplicate_count": merged_duplicate_count,
        "reviewed_draft_count": reviewed_draft_count,
        "adopted_draft_count": adopted_draft_count,
        "specialist_influenced_adopted_count": specialist_influenced_adopted_count,
        "adoption_participation_by_agent": _ordered_counts(adoption_participation),
        "gates": gates,
    }
