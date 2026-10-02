"""Process-local ownership and SQLite replay for inline assistant runs."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

from app.agent_runtime.contracts import RunStatus
from app.models.agent_run import AgentRun, AgentRunEvent


TERMINAL_STATUSES = {
    RunStatus.COMPLETED.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
    RunStatus.BUDGET_EXHAUSTED.value,
    RunStatus.INTERRUPTED.value,
}


class InlineAgentSupervisor:
    """Retain one strong asyncio task reference per inline AgentRun."""

    def __init__(self):
        self._tasks: dict[int, asyncio.Task] = {}

    def start(
        self,
        run_id: int,
        operation: Callable[[], Awaitable[None]],
    ) -> asyncio.Task:
        current = self._tasks.get(run_id)
        if current is not None and not current.done():
            return current
        task = asyncio.create_task(operation(), name=f"agent-inline-{run_id}")
        self._tasks[run_id] = task

        def remove(completed: asyncio.Task) -> None:
            if self._tasks.get(run_id) is completed:
                self._tasks.pop(run_id, None)

        task.add_done_callback(remove)
        return task

    def is_running(self, run_id: int) -> bool:
        task = self._tasks.get(run_id)
        return bool(task is not None and not task.done())

    async def wait(self, run_id: int) -> None:
        task = self._tasks.get(run_id)
        if task is not None:
            await task

    def discard(self, run_id: int) -> None:
        task = self._tasks.pop(run_id, None)
        if task is not None and not task.done():
            task.cancel()


inline_agent_supervisor = InlineAgentSupervisor()


async def stream_run_events(
    session_factory,
    run_id: int,
    *,
    after_sequence: int = 0,
    poll_seconds: float = 0.2,
) -> AsyncIterator[AgentRunEvent]:
    """Replay persisted events after a cursor and stop after terminal drain."""
    cursor = max(0, int(after_sequence))
    while True:
        db = session_factory()
        try:
            events = (
                db.query(AgentRunEvent)
                .filter(
                    AgentRunEvent.agent_run_id == run_id,
                    AgentRunEvent.sequence > cursor,
                )
                .order_by(AgentRunEvent.sequence.asc())
                .all()
            )
            run = db.get(AgentRun, run_id)
            subscription_complete = (
                run is None
                or run.status in TERMINAL_STATUSES
                or run.status == RunStatus.WAITING_HUMAN.value
            )
            for event in events:
                db.expunge(event)
        finally:
            db.close()
        for event in events:
            cursor = event.sequence
            yield event
        if subscription_complete:
            return
        await asyncio.sleep(max(0.01, float(poll_seconds)))
