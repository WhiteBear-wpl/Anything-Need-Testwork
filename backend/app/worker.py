"""Single-process worker for durable AgentRun execution."""

import asyncio
import json
import logging
import os
import socket
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.agent_runtime.contracts import ExecutionBudget, RunContext, RunStatus
from app.agent_runtime.repository import AgentRunRepository
from app.config import settings
from app.database import SessionLocal
from app.models.agent_run import AgentRun
from app.services.evaluation_service import run_evaluation_workflow
from app.workflows.generation.runner import run_generation_workflow


logger = logging.getLogger(__name__)
DEFAULT_LOCK_PATH = Path(__file__).resolve().parents[1] / "data" / "agent-worker.lock"


@contextmanager
def worker_process_lock(lock_path: str | Path = DEFAULT_LOCK_PATH):
    """Hold an OS-released lock so only one local SQLite worker can run."""
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("AITC Agent Worker is already running") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("AITC Agent Worker is already running") from exc
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


class SQLiteAgentWorker:
    """Claims one SQLite-backed AgentRun at a time and invokes the existing graph."""

    def __init__(
        self,
        session_factory=SessionLocal,
        *,
        worker_id: str | None = None,
        runner: Callable = run_generation_workflow,
        evaluation_runner: Callable = run_evaluation_workflow,
        lease_seconds: int | None = None,
        heartbeat_interval_seconds: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.session_factory = session_factory
        self.worker_id = worker_id or f"{socket.gethostname()}-{id(self)}"
        self.runner = runner
        self.evaluation_runner = evaluation_runner
        self.lease_seconds = lease_seconds or settings.agent_run_lease_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds or max(
            1.0, self.lease_seconds / 3
        )
        self.sleep = sleep

    @staticmethod
    def _run_context(run) -> RunContext:
        try:
            spec_snapshot = json.loads(run.agent_spec_snapshot or "{}")
            budget_data = json.loads(run.budget_snapshot or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"AgentRun {run.id} has an invalid immutable snapshot") from exc
        return RunContext(
            run_id=run.id,
            project_id=run.project_id,
            task_id=run.generation_task_id or 0,
            spec_snapshot=spec_snapshot if isinstance(spec_snapshot, dict) else {},
            budget=ExecutionBudget(**budget_data) if isinstance(budget_data, dict) else ExecutionBudget(),
        )

    def run_once(self, *, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        db = self.session_factory()
        try:
            repository = AgentRunRepository(db, lease_seconds=self.lease_seconds)
            repository.recover_expired_leases(now)
            run = repository.claim_next_run(self.worker_id, now)
            if run is None:
                return False
            context = self._run_context(run)
        finally:
            db.close()

        resume = context.spec_snapshot.get("execution_mode") == "resume"
        asyncio.run(self._execute_with_heartbeat(context, resume=resume))
        return True

    async def _heartbeat_until_stopped(self, run_id: int, stopped: asyncio.Event) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    stopped.wait(), timeout=self.heartbeat_interval_seconds
                )
                return
            except TimeoutError:
                db = self.session_factory()
                try:
                    repository = AgentRunRepository(
                        db, lease_seconds=self.lease_seconds
                    )
                    renewed = repository.heartbeat(run_id, self.worker_id, datetime.now())
                    run = db.get(AgentRun, run_id, populate_existing=True)
                finally:
                    db.close()
                if not renewed:
                    if run is not None and run.status in {
                        RunStatus.COMPLETED.value,
                        RunStatus.FAILED.value,
                        RunStatus.CANCELLED.value,
                        RunStatus.BUDGET_EXHAUSTED.value,
                        RunStatus.INTERRUPTED.value,
                    }:
                        return
                    raise RuntimeError(f"AgentRun {run_id} lease ownership was lost")

    async def _execute_with_heartbeat(self, context: RunContext, *, resume: bool) -> None:
        stopped = asyncio.Event()
        if context.spec_snapshot.get("name") == "evaluation_runner":
            eval_run_id = context.spec_snapshot.get("evaluation_run_id")
            if not isinstance(eval_run_id, int) or eval_run_id <= 0:
                raise RuntimeError(f"AgentRun {context.run_id} has no immutable evaluation_run_id")
            work = self.evaluation_runner(eval_run_id, run_context=context)
        else:
            work = self.runner(context.task_id, run_context=context, resume=resume)
        runner_task = asyncio.create_task(work)
        heartbeat_task = asyncio.create_task(
            self._heartbeat_until_stopped(context.run_id, stopped)
        )
        done, _ = await asyncio.wait(
            {runner_task, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if heartbeat_task in done and heartbeat_task.exception() is not None:
            runner_task.cancel()
            await asyncio.gather(runner_task, return_exceptions=True)
            raise heartbeat_task.exception()
        try:
            await runner_task
        finally:
            stopped.set()
            await heartbeat_task

    def serve_forever(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("Agent worker run failed; continuing queue polling")
            self.sleep(settings.agent_worker_poll_seconds)


def main() -> None:
    with worker_process_lock():
        SQLiteAgentWorker().serve_forever()


if __name__ == "__main__":
    main()
