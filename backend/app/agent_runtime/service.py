import json
from dataclasses import asdict
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.agent_runtime.contracts import ExecutionBudget, ExecutionMode, RunKind, RunStatus
from app.agent_runtime.profiles import budget_for
from app.agent_runtime.repository import AgentRunRepository
from app.models.agent_run import AgentRun, AgentSpec
from app.models.generation import GenerationTask
from app.models.project import Project


def is_runtime_v2_enabled(global_enabled: bool, project: Project) -> bool:
    return bool(global_enabled and project.agent_runtime_v2_enabled)


def is_unified_runtime_enabled(
    global_runtime_enabled: bool,
    unified_runtime_enabled: bool,
    project: Project,
) -> bool:
    return bool(
        unified_runtime_enabled
        and is_runtime_v2_enabled(global_runtime_enabled, project)
    )


def _safe_model_snapshot(model_snapshot: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in model_snapshot.items():
        lowered = key.lower()
        if "key" in lowered or "secret" in lowered or "token" in lowered:
            continue
        if "url" in lowered and isinstance(value, str) and value:
            try:
                parsed = urlsplit(value)
                host = parsed.hostname
                if not parsed.scheme or not host:
                    value = ""
                else:
                    host_text = f"[{host}]" if ":" in host else host
                    netloc = host_text + (f":{parsed.port}" if parsed.port else "")
                    value = urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
            except ValueError:
                value = ""
        safe[key] = value
    return safe


def create_assistant_run(
    db: Session,
    *,
    project_id: int,
    thread_id: int,
    message_id: int,
    model_snapshot: dict[str, Any],
) -> AgentRun:
    """Create the immutable inline parent run for one assistant user message."""
    existing = (
        db.query(AgentRun)
        .filter(
            AgentRun.project_id == project_id,
            AgentRun.message_id == message_id,
            AgentRun.run_kind == RunKind.CHAT.value,
        )
        .order_by(AgentRun.id.desc())
        .first()
    )
    if existing is not None:
        return existing
    snapshot = {
        "name": "assistant",
        "version": "v1",
        "model": _safe_model_snapshot(model_snapshot),
    }
    spec = db.query(AgentSpec).filter(
        AgentSpec.name == "assistant", AgentSpec.version == "v1"
    ).first()
    if spec is None:
        spec = AgentSpec(
            name="assistant",
            version="v1",
            definition=json.dumps(snapshot, ensure_ascii=False),
        )
        db.add(spec)
        db.flush()
    run = AgentRun(
        project_id=project_id,
        thread_id=thread_id,
        message_id=message_id,
        agent_spec_id=spec.id,
        run_kind=RunKind.CHAT.value,
        execution_mode=ExecutionMode.INLINE.value,
        status=RunStatus.QUEUED.value,
        usage_accounting_version=1,
        agent_spec_snapshot=json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
        budget_snapshot=json.dumps(
            asdict(budget_for(RunKind.CHAT)), ensure_ascii=False, sort_keys=True
        ),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def create_case_writer_run(
    db: Session,
    task: GenerationTask,
    *,
    model_snapshot: dict[str, Any],
    budget: ExecutionBudget | None = None,
    resume: bool = False,
    parent_run_id: int | None = None,
    resume_from_run_id: int | None = None,
) -> AgentRun:
    budget = budget or budget_for(RunKind.GENERATION)
    active_run = (
        db.query(AgentRun)
        .filter(
            AgentRun.generation_task_id == task.id,
            AgentRun.status.in_((
                RunStatus.QUEUED.value,
                RunStatus.RUNNING.value,
                RunStatus.WAITING_HUMAN.value,
            )),
        )
        .order_by(AgentRun.id.desc())
        .first()
    )
    if active_run is not None:
        return active_run
    try:
        strategy_config = json.loads(task.strategy_config or "{}")
    except (json.JSONDecodeError, TypeError):
        strategy_config = {}
    if not isinstance(strategy_config, dict):
        strategy_config = {}
    skill_policy = strategy_config.get("skill_policy")
    if not isinstance(skill_policy, dict):
        skill_policy = {"policy_revision": 0, "catalog_fingerprint": "", "specialists": {}}
    snapshot = {
        "name": "case_writer",
        "version": "v2",
        "schema_version": "case-list-v1",
        "execution_mode": "resume" if resume else "start",
        "model": _safe_model_snapshot(model_snapshot),
        "strategy_config": strategy_config,
        "skill_policy": skill_policy,
    }
    spec = db.query(AgentSpec).filter(AgentSpec.name == "case_writer", AgentSpec.version == "v2").first()
    if spec is None:
        spec = AgentSpec(name="case_writer", version="v2", definition=json.dumps(snapshot, ensure_ascii=False))
        db.add(spec)
        db.flush()
    run = AgentRun(
        project_id=task.project_id,
        generation_task_id=task.id,
        agent_spec_id=spec.id,
        status=RunStatus.QUEUED.value,
        parent_run_id=parent_run_id,
        resume_from_run_id=resume_from_run_id,
        run_kind=RunKind.GENERATION.value,
        execution_mode=ExecutionMode.WORKER.value,
        usage_accounting_version=1,
        agent_spec_snapshot=json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
        budget_snapshot=json.dumps(asdict(budget), ensure_ascii=False, sort_keys=True),
    )
    db.add(run)
    try:
        if parent_run_id is not None:
            db.flush()
            AgentRunRepository(db)._stage_event(
                parent_run_id,
                "child_run_created",
                stage="child",
                payload_summary=json.dumps(
                    {
                        "child_run_id": run.id,
                        "task_id": task.id,
                        "run_kind": RunKind.GENERATION.value,
                        "status": RunStatus.QUEUED.value,
                    },
                    ensure_ascii=False,
                ),
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        active_run = (
            db.query(AgentRun)
            .filter(
                AgentRun.generation_task_id == task.id,
                AgentRun.status.in_((
                    RunStatus.QUEUED.value,
                    RunStatus.RUNNING.value,
                    RunStatus.WAITING_HUMAN.value,
                )),
            )
            .order_by(AgentRun.id.desc())
            .first()
        )
        if active_run is not None:
            return active_run
        raise
    db.refresh(run)
    return run


def create_evaluation_runner_run(
    db: Session,
    eval_run,
    *,
    model_snapshot: dict[str, Any],
    budget: ExecutionBudget | None = None,
    parent_run_id: int | None = None,
    resume_from_run_id: int | None = None,
) -> AgentRun:
    """Queue one durable Worker run for a frozen evaluation experiment."""
    budget = budget or budget_for(RunKind.EVALUATION)
    active = (
        db.query(AgentRun)
        .filter(
            AgentRun.evaluation_run_id == eval_run.id,
            AgentRun.status.in_((RunStatus.QUEUED.value, RunStatus.RUNNING.value, RunStatus.WAITING_HUMAN.value)),
        )
        .first()
    )
    if active is not None:
        return active
    try:
        config_snapshot = json.loads(eval_run.config_snapshot or eval_run.config or "{}")
    except (json.JSONDecodeError, TypeError):
        raise ValueError(f"evaluation run {eval_run.id} has an invalid immutable config snapshot")
    snapshot = {
        "name": "evaluation_runner",
        "version": "v1",
        "execution_mode": "start",
        "evaluation_run_id": eval_run.id,
        "config_snapshot": config_snapshot,
        "model": _safe_model_snapshot(model_snapshot),
    }
    spec = db.query(AgentSpec).filter(AgentSpec.name == "evaluation_runner", AgentSpec.version == "v1").first()
    if spec is None:
        spec = AgentSpec(name="evaluation_runner", version="v1", definition=json.dumps(snapshot, ensure_ascii=False))
        db.add(spec)
        db.flush()
    run = AgentRun(
        project_id=eval_run.project_id,
        evaluation_run_id=eval_run.id,
        agent_spec_id=spec.id,
        status=RunStatus.QUEUED.value,
        parent_run_id=parent_run_id,
        resume_from_run_id=resume_from_run_id,
        run_kind=RunKind.EVALUATION.value,
        execution_mode=ExecutionMode.WORKER.value,
        usage_accounting_version=1,
        agent_spec_snapshot=json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
        budget_snapshot=json.dumps(asdict(budget), ensure_ascii=False, sort_keys=True),
    )
    db.add(run)
    db.flush()
    eval_run.agent_run_id = run.id
    db.commit()
    db.refresh(run)
    return run
