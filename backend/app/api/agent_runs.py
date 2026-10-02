"""Project-scoped durable AgentRun inspection and replay APIs."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agent_runtime.inline import stream_run_events
from app.agent_runtime.repository import AgentRunRepository
from app.api.deps import require_project_access
from app.config import settings
from app.database import SessionLocal, get_db
from app.models.agent import AgentThread
from app.models.agent_run import AgentRun, AgentRunEvent
from app.schemas import AgentRunEventOut, AgentRunOut


router = APIRouter(
    prefix="/projects/{project_id}/agent-runs",
    tags=["agent-runs"],
    dependencies=[Depends(require_project_access)],
)


def _scoped_run(db: Session, project_id: int, run_id: int) -> AgentRun:
    run = db.query(AgentRun).filter(
        AgentRun.id == run_id,
        AgentRun.project_id == project_id,
    ).first()
    if run is None:
        raise HTTPException(404, "Agent 运行不存在")
    return run


@router.get("/rollout-report")
def get_rollout_report(
    project_id: int,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Return bounded, non-sensitive rollout evidence for recent project runs."""
    runs = (
        db.query(AgentRun)
        .filter(AgentRun.project_id == project_id)
        .order_by(AgentRun.id.desc())
        .limit(limit)
        .all()
    )
    run_ids = [run.id for run in runs]
    evidence = (
        db.query(AgentRunEvent.agent_run_id, AgentRunEvent.event_type)
        .filter(
            AgentRunEvent.agent_run_id.in_(run_ids),
            AgentRunEvent.event_type.in_(("budget_warning", "budget_would_exhaust")),
        )
        .all()
        if run_ids
        else []
    )
    warning_ids = {run_id for run_id, kind in evidence if kind == "budget_warning"}
    would_exhaust_ids = {
        run_id for run_id, kind in evidence if kind == "budget_would_exhaust"
    }
    by_kind = {
        kind: {
            "runs": sum(run.run_kind == kind for run in runs),
            "warnings": sum(
                run.run_kind == kind and run.id in warning_ids for run in runs
            ),
        }
        for kind in ("chat", "generation", "evaluation")
    }
    return {
        "mode": settings.runtime_budget_mode,
        "runs": len(runs),
        "warnings": len(warning_ids),
        "would_exhaust": len(would_exhaust_ids),
        "budget_exhausted": sum(
            run.status == "budget_exhausted" for run in runs
        ),
        "interrupted": sum(run.status == "interrupted" for run in runs),
        "usage_accounting_unknown": sum(
            int(run.usage_accounting_version or 0) == 0 for run in runs
        ),
        "by_kind": by_kind,
    }


@router.get("/{run_id}", response_model=AgentRunOut)
def get_agent_run(project_id: int, run_id: int, db: Session = Depends(get_db)):
    return _scoped_run(db, project_id, run_id)


@router.get("/{run_id}/events", response_model=list[AgentRunEventOut])
def list_agent_run_events(
    project_id: int,
    run_id: int,
    after_sequence: int = 0,
    db: Session = Depends(get_db),
):
    _scoped_run(db, project_id, run_id)
    return db.query(AgentRunEvent).filter(
        AgentRunEvent.agent_run_id == run_id,
        AgentRunEvent.sequence > max(0, after_sequence),
    ).order_by(AgentRunEvent.sequence.asc()).all()


@router.get("/{run_id}/children", response_model=list[AgentRunOut])
def list_agent_run_children(
    project_id: int,
    run_id: int,
    db: Session = Depends(get_db),
):
    _scoped_run(db, project_id, run_id)
    return db.query(AgentRun).filter(
        AgentRun.project_id == project_id,
        AgentRun.parent_run_id == run_id,
    ).order_by(AgentRun.id.asc()).all()


@router.get("", response_model=list[AgentRunOut])
def list_agent_runs(
    project_id: int,
    thread_id: int | None = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(AgentRun).filter(AgentRun.project_id == project_id)
    if thread_id is not None:
        query = query.filter(AgentRun.thread_id == thread_id)
    return query.order_by(AgentRun.id.desc()).limit(limit).all()


@router.post("/{run_id}/cancel", response_model=AgentRunOut)
def cancel_agent_run(project_id: int, run_id: int, db: Session = Depends(get_db)):
    run = _scoped_run(db, project_id, run_id)
    was_waiting = run.status == "waiting_human"
    if not AgentRunRepository(db).request_cancel(run.id):
        raise HTTPException(400, "该运行已结束，无法取消")
    if was_waiting and run.run_kind == "chat" and run.thread_id is not None:
        thread = db.get(AgentThread, run.thread_id)
        if thread is not None:
            try:
                pending = json.loads(thread.pending_approval or "{}")
            except json.JSONDecodeError:
                pending = {}
            if not pending or pending.get("agent_run_id") in (None, run.id):
                thread.pending_approval = ""
                thread.checkpoint_thread_id = ""
                db.commit()
    return db.get(AgentRun, run.id)


def _sse_event(event: AgentRunEvent) -> str:
    try:
        payload = json.loads(event.payload_summary or "{}")
    except json.JSONDecodeError:
        payload = {}
    return "data: " + json.dumps(
        {
            "run_id": event.agent_run_id,
            "sequence": event.sequence,
            "event_type": event.event_type,
            "stage": event.stage,
            "payload": payload,
            "created_at": event.created_at,
        },
        ensure_ascii=False,
        default=str,
    ) + "\n\n"


@router.get("/{run_id}/stream")
def stream_agent_run(
    project_id: int,
    run_id: int,
    after_sequence: int = 0,
    db: Session = Depends(get_db),
):
    _scoped_run(db, project_id, run_id)

    async def body():
        async for event in stream_run_events(
            SessionLocal,
            run_id,
            after_sequence=after_sequence,
        ):
            yield _sse_event(event)

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
