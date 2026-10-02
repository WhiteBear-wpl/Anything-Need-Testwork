import json
from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent_runtime.contracts import RunEventType, RunStatus
from app.models.agent_run import AgentRun, AgentRunArtifact, AgentRunEvent
from app.services.redaction import redact_output


class AgentRunRepository:
    """Persistence boundary for the first SQLite-backed agent-run queue."""

    def __init__(self, db: Session, lease_seconds: int = 90):
        self.db = db
        self.lease_seconds = lease_seconds

    def claim_next_run(self, worker_id: str, now: datetime) -> AgentRun | None:
        candidate = self.db.scalar(
            select(AgentRun)
            .where(
                AgentRun.status == RunStatus.QUEUED.value,
                AgentRun.cancel_requested.is_(False),
            )
            .order_by(AgentRun.created_at.asc(), AgentRun.id.asc())
            .limit(1)
        )
        if candidate is None:
            return None

        try:
            budget = json.loads(candidate.budget_snapshot or "{}")
        except (json.JSONDecodeError, TypeError):
            budget = {}
        max_runtime_seconds = int(
            budget.get("max_runtime_seconds", 900)
            if isinstance(budget, dict)
            else 900
        )

        claimed = self.db.execute(
            update(AgentRun)
            .where(
                AgentRun.id == candidate.id,
                AgentRun.status == RunStatus.QUEUED.value,
                AgentRun.cancel_requested.is_(False),
            )
            .values(
                status=RunStatus.RUNNING.value,
                lease_owner=worker_id,
                lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                started_at=now,
                deadline_at=now + timedelta(seconds=max_runtime_seconds),
                tokens_reserved=0,
            )
        )
        if claimed.rowcount != 1:
            self.db.rollback()
            return None
        self.db.commit()
        self.append_event(candidate.id, "run_claimed", now=now)
        return self.db.get(AgentRun, candidate.id)

    def recover_expired_leases(self, now: datetime) -> int:
        result = self.db.execute(
            update(AgentRun)
            .where(
                AgentRun.status == RunStatus.RUNNING.value,
                AgentRun.lease_expires_at.is_not(None),
                AgentRun.lease_expires_at < now,
            )
            .values(
                status=RunStatus.QUEUED.value,
                lease_owner="",
                lease_expires_at=None,
                started_at=None,
                deadline_at=None,
                tokens_reserved=0,
            )
        )
        self.db.commit()
        return int(result.rowcount or 0)

    def request_cancel(self, run_id: int) -> bool:
        for attempt in range(3):
            now = datetime.now()
            try:
                immediate = self.db.execute(
                    update(AgentRun)
                    .where(
                        AgentRun.id == run_id,
                        AgentRun.status.in_((
                            RunStatus.QUEUED.value,
                            RunStatus.WAITING_HUMAN.value,
                        )),
                        AgentRun.cancel_requested.is_(False),
                    )
                    .values(
                        cancel_requested=True,
                        status=RunStatus.CANCELLED.value,
                        stop_reason=RunStatus.CANCELLED.value,
                        finished_at=now,
                        waiting_since=None,
                        lease_owner="",
                        lease_expires_at=None,
                    )
                )
                running = self.db.execute(
                    update(AgentRun)
                    .where(
                        AgentRun.id == run_id,
                        AgentRun.status == RunStatus.RUNNING.value,
                        AgentRun.cancel_requested.is_(False),
                    )
                    .values(cancel_requested=True)
                )
                immediate_count = int(immediate.rowcount or 0)
                running_count = int(running.rowcount or 0)
                if not immediate_count and not running_count:
                    self.db.rollback()
                    return False
                self._stage_event(
                    run_id,
                    RunEventType.RUN_CANCEL_REQUESTED.value,
                    now=now,
                )
                if immediate_count:
                    self._stage_event(
                        run_id,
                        RunEventType.RUN_CANCELLED.value,
                        now=now,
                    )
                self.db.commit()
                return True
            except IntegrityError:
                self.db.rollback()
                if attempt == 2:
                    raise
            except Exception:
                self.db.rollback()
                raise
        raise RuntimeError("unreachable")

    def mark_terminal(
        self,
        run_id: int,
        status: RunStatus | str,
        *,
        now: datetime | None = None,
        payload_summary: str = "{}",
    ) -> bool:
        """Persist a terminal run transition and its audit event atomically."""
        status_value = status.value if isinstance(status, RunStatus) else str(status)
        event_types = {
            RunStatus.COMPLETED.value: RunEventType.RUN_COMPLETED.value,
            RunStatus.FAILED.value: RunEventType.RUN_FAILED.value,
            RunStatus.CANCELLED.value: RunEventType.RUN_CANCELLED.value,
            RunStatus.BUDGET_EXHAUSTED.value: RunEventType.RUN_BUDGET_EXHAUSTED.value,
            RunStatus.INTERRUPTED.value: RunEventType.RUN_INTERRUPTED.value,
        }
        if status_value not in event_types:
            raise ValueError(f"unsupported terminal run status: {status_value}")
        terminal_at = now or datetime.now()
        for attempt in range(3):
            try:
                parent_run_id = self.db.scalar(
                    select(AgentRun.parent_run_id)
                    .where(AgentRun.id == run_id)
                    .execution_options(autoflush=False)
                )
                values = {
                    "status": status_value,
                    "stop_reason": status_value,
                    "finished_at": terminal_at,
                    "lease_owner": "",
                    "lease_expires_at": None,
                }
                if status_value == RunStatus.CANCELLED.value:
                    values["cancel_requested"] = True
                changed = self.db.execute(
                    update(AgentRun)
                    .where(
                        AgentRun.id == run_id,
                        AgentRun.status.in_((
                            RunStatus.QUEUED.value,
                            RunStatus.RUNNING.value,
                            RunStatus.WAITING_HUMAN.value,
                        )),
                    )
                    .values(**values)
                )
                if changed.rowcount != 1:
                    self.db.rollback()
                    return False
                self._stage_event(
                    run_id,
                    event_types[status_value],
                    payload_summary=payload_summary,
                    now=terminal_at,
                )
                if parent_run_id is not None:
                    parent_event_types = {
                        RunStatus.COMPLETED.value: "child_run_completed",
                        RunStatus.FAILED.value: "child_run_failed",
                        RunStatus.CANCELLED.value: "child_run_cancelled",
                        RunStatus.BUDGET_EXHAUSTED.value: "child_run_budget_exhausted",
                        RunStatus.INTERRUPTED.value: "child_run_interrupted",
                    }
                    self._stage_event(
                        parent_run_id,
                        parent_event_types[status_value],
                        stage="child",
                        payload_summary=json.dumps(
                            {"child_run_id": run_id, "status": status_value},
                            ensure_ascii=False,
                        ),
                        now=terminal_at,
                    )
                self.db.commit()
                return True
            except IntegrityError:
                self.db.rollback()
                if attempt == 2:
                    raise
            except Exception:
                self.db.rollback()
                raise
        raise RuntimeError("unreachable")

    def start_inline(self, run_id: int, now: datetime) -> bool:
        run = self.db.get(AgentRun, run_id, populate_existing=True)
        if run is None:
            return False
        try:
            budget = json.loads(run.budget_snapshot or "{}")
        except (json.JSONDecodeError, TypeError):
            budget = {}
        max_runtime_seconds = int(
            budget.get("max_runtime_seconds", 900)
            if isinstance(budget, dict)
            else 900
        )
        changed = self.db.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.status == RunStatus.QUEUED.value,
                AgentRun.cancel_requested.is_(False),
            )
            .values(
                status=RunStatus.RUNNING.value,
                started_at=now,
                deadline_at=now + timedelta(seconds=max_runtime_seconds),
                waiting_since=None,
                stop_reason="",
            )
        )
        if changed.rowcount != 1:
            self.db.rollback()
            return False
        self._stage_event(run_id, "run_started", now=now)
        self.db.commit()
        return True

    def mark_waiting_human(self, run_id: int, now: datetime) -> bool:
        changed = self.db.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.status == RunStatus.RUNNING.value,
                AgentRun.cancel_requested.is_(False),
            )
            .values(status=RunStatus.WAITING_HUMAN.value, waiting_since=now)
        )
        if changed.rowcount != 1:
            self.db.rollback()
            return False
        self._stage_event(run_id, "run_waiting_human", now=now)
        self.db.commit()
        return True

    def resume_inline(self, run_id: int, now: datetime) -> bool:
        run = self.db.get(AgentRun, run_id, populate_existing=True)
        if (
            run is None
            or run.status != RunStatus.WAITING_HUMAN.value
            or run.cancel_requested
        ):
            return False
        paused_seconds = (
            max(0.0, (now - run.waiting_since).total_seconds())
            if run.waiting_since is not None
            else 0.0
        )
        deadline = (
            run.deadline_at + timedelta(seconds=paused_seconds)
            if run.deadline_at is not None
            else None
        )
        changed = self.db.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.status == RunStatus.WAITING_HUMAN.value,
                AgentRun.cancel_requested.is_(False),
            )
            .values(
                status=RunStatus.RUNNING.value,
                waiting_since=None,
                deadline_at=deadline,
            )
        )
        if changed.rowcount != 1:
            self.db.rollback()
            return False
        self._stage_event(run_id, "run_resumed", now=now)
        self.db.commit()
        return True

    def reconcile_stale_inline(self, now: datetime) -> int:
        run_ids = self.db.scalars(
            select(AgentRun.id).where(
                AgentRun.execution_mode == "inline",
                AgentRun.status == RunStatus.RUNNING.value,
                AgentRun.deadline_at.is_not(None),
                AgentRun.deadline_at < now,
            )
        ).all()
        changed = 0
        for run_id in run_ids:
            changed += int(
                self.mark_terminal(run_id, RunStatus.INTERRUPTED, now=now)
            )
        return changed

    def heartbeat(self, run_id: int, worker_id: str, now: datetime) -> bool:
        result = self.db.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.status == RunStatus.RUNNING.value,
                AgentRun.lease_owner == worker_id,
            )
            .values(lease_expires_at=now + timedelta(seconds=self.lease_seconds))
        )
        self.db.commit()
        return bool(result.rowcount)

    def append_event(
        self,
        run_id: int,
        event_type: str,
        *,
        stage: str = "",
        payload_summary: str = "{}",
        now: datetime | None = None,
    ) -> AgentRunEvent:
        for attempt in range(3):
            try:
                event = self._stage_event(
                    run_id,
                    event_type,
                    stage=stage,
                    payload_summary=payload_summary,
                    now=now,
                )
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                if attempt == 2:
                    raise
                continue
            except Exception:
                self.db.rollback()
                raise
            self.db.refresh(event)
            return event
        raise RuntimeError("unreachable")

    def _stage_event(
        self,
        run_id: int,
        event_type: str,
        *,
        stage: str = "",
        payload_summary: str = "{}",
        now: datetime | None = None,
    ) -> AgentRunEvent:
        current = self.db.scalar(
            select(func.max(AgentRunEvent.sequence)).where(
                AgentRunEvent.agent_run_id == run_id
            )
        )
        pending = max(
            (
                item.sequence
                for item in self.db.new
                if isinstance(item, AgentRunEvent) and item.agent_run_id == run_id
            ),
            default=0,
        )
        event = AgentRunEvent(
            agent_run_id=run_id,
            sequence=max(current or 0, pending) + 1,
            event_type=event_type,
            stage=stage,
            payload_summary=payload_summary,
        )
        if now is not None:
            event.created_at = now
        self.db.add(event)
        return event

    def store_artifact(
        self,
        run_id: int,
        kind: str,
        payload: str,
        *,
        now: datetime | None = None,
        retention_days: int = 30,
    ) -> AgentRunArtifact:
        created_at = now or datetime.now()
        safe_payload = redact_output(str(payload), limit=20_000)
        artifact = AgentRunArtifact(
            agent_run_id=run_id,
            kind=kind,
            payload=safe_payload,
            content_preview=redact_output(str(payload), limit=500),
            sha256=sha256(safe_payload.encode("utf-8")).hexdigest(),
            created_at=created_at,
            expires_at=created_at + timedelta(days=retention_days),
        )
        self.db.add(artifact)
        self.db.commit()
        self.db.refresh(artifact)
        return artifact
