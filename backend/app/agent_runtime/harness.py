"""Govern low-level model invocations without taking over LangGraph routing."""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from app.agent_runtime.budget import BudgetLedger, estimate_tokens
from app.agent_runtime.contracts import (
    BudgetExhausted,
    BudgetMode,
    RunContext,
    RuntimeCancelled,
)
from app.agent_runtime.repository import AgentRunRepository
from app.models.agent_run import AgentRun
from app.services.llm import LLMCallError
from app.services.redaction import redact_output
from app.config import settings


ResultT = TypeVar("ResultT")
_active_runtime_harness: ContextVar["RuntimeHarness | None"] = ContextVar(
    "active_runtime_harness", default=None
)


@contextmanager
def active_runtime_harness(harness: "RuntimeHarness"):
    """Make a harness available to a graph node without checkpointing it."""
    token = _active_runtime_harness.set(harness)
    try:
        yield
    finally:
        _active_runtime_harness.reset(token)


def get_active_runtime_harness() -> "RuntimeHarness | None":
    return _active_runtime_harness.get()


def _is_retryable_transport_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if not isinstance(exc, LLMCallError):
        return False
    message = str(exc).lower()
    non_retryable_markers = ("api key", "401", "403", "404", "地址", "模型名")
    return not any(marker in message for marker in non_retryable_markers)


class RuntimeHarness:
    """Applies durable-run safety controls around a single provider invocation."""

    def __init__(
        self,
        db: Session,
        context: RunContext,
        *,
        budget_mode: BudgetMode | str | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.db = db
        self.context = context
        self.repository = AgentRunRepository(db)
        self.sleep = sleep
        self.budget = BudgetLedger(
            db,
            context,
            mode=budget_mode or settings.runtime_budget_mode,
        )

    def check_cancelled(self) -> None:
        run = self.db.get(AgentRun, self.context.run_id, populate_existing=True)
        if run is None or run.cancel_requested:
            raise RuntimeCancelled(f"Agent run {self.context.run_id} was cancelled")

    def remaining_runtime_seconds(self) -> float:
        return self.budget.remaining_seconds()

    def consume_quality_repair(self) -> None:
        self.budget.consume_quality_repair()

    def record_agent_event(
        self,
        event_type: str,
        agent: str,
        *,
        candidate_count: int | None = None,
        duration_ms: int | None = None,
        message: str = "",
    ) -> None:
        """Persist a bounded specialist lifecycle summary without raw model content."""
        payload: dict[str, Any] = {"agent": str(agent)}
        if candidate_count is not None:
            payload["candidate_count"] = max(0, int(candidate_count))
        if duration_ms is not None:
            payload["duration_ms"] = max(0, int(duration_ms))
        if message:
            payload["message"] = redact_output(message, limit=500)
        self.repository.append_event(
            self.context.run_id,
            event_type,
            stage="specialist",
            payload_summary=json.dumps(payload, ensure_ascii=False),
        )

    def record_skill_event(
        self,
        event_type: str,
        skill: str,
        version: str,
        category: str,
        *,
        duration_ms: int | None = None,
        error_type: str = "",
        message: str = "",
    ) -> None:
        """Persist only bounded Skill lifecycle metadata, never invocation content."""
        payload: dict[str, Any] = {
            "skill": str(skill),
            "version": str(version),
            "category": str(category),
        }
        if duration_ms is not None:
            payload["duration_ms"] = max(0, int(duration_ms))
        if error_type:
            payload["error_type"] = str(error_type)
        if message:
            payload["message"] = redact_output(message, limit=300)
        self.repository.append_event(
            self.context.run_id,
            event_type,
            stage="skill",
            payload_summary=json.dumps(payload, ensure_ascii=False),
        )

    def record_evaluation_event(
        self,
        event_type: str,
        stage: str,
        *,
        result_id: int | None = None,
        attempt: int | None = None,
        error_type: str = "",
        message: str = "",
    ) -> None:
        """Persist orchestration evidence without duplicating Skill lifecycle events."""
        payload: dict[str, Any] = {}
        if result_id is not None:
            payload["result_id"] = int(result_id)
        if attempt is not None:
            payload["attempt"] = max(1, int(attempt))
        if error_type:
            payload["error_type"] = str(error_type)
        if message:
            payload["message"] = redact_output(message, limit=300)
        self.repository.append_event(
            self.context.run_id,
            event_type,
            stage=str(stage),
            payload_summary=json.dumps(payload, ensure_ascii=False),
        )

    async def call_llm(
        self,
        stage: str,
        skill_name: str,
        operation: Callable[[], Awaitable[ResultT]],
        *,
        input_value: object,
        max_output_tokens: int,
    ) -> ResultT:
        """Invoke a provider with bounded transport retries and safe run evidence."""
        reservation = self.budget.reserve_llm(
            input_tokens=estimate_tokens(input_value),
            max_output_tokens=max_output_tokens,
        )
        settled = False
        try:
            for attempt in range(1, self.context.budget.max_transport_retries + 2):
                self.check_cancelled()
                try:
                    result = await operation()
                except Exception as exc:
                    if isinstance(exc, (RuntimeCancelled, BudgetExhausted)):
                        raise
                    if not _is_retryable_transport_error(exc):
                        raise
                    if attempt > self.context.budget.max_transport_retries:
                        raise
                    self.budget.consume_transport_retry()
                    self.repository.append_event(
                        self.context.run_id,
                        "llm_retry",
                        stage=stage,
                        payload_summary=json.dumps(
                            {
                                "skill": skill_name,
                                "attempt": attempt,
                                "reason": redact_output(str(exc), limit=500),
                            },
                            ensure_ascii=False,
                        ),
                    )
                    await self.sleep(float(2 ** (attempt - 1)))
                    continue

                usage = getattr(result, "usage_metadata", None)
                self.budget.settle_llm(reservation, usage, output=result)
                settled = True
                payload = json.dumps(result, ensure_ascii=False, default=str)
                self.repository.store_artifact(
                    self.context.run_id, "llm_output", payload
                )
                self.repository.append_event(
                    self.context.run_id,
                    "llm_succeeded",
                    stage=stage,
                    payload_summary=json.dumps(
                        {"skill": skill_name, "attempt": attempt},
                        ensure_ascii=False,
                    ),
                )
                return result
        finally:
            if not settled:
                self.budget.settle_llm(reservation, None, output="")

        raise RuntimeError("unreachable")

    async def run_tool(
        self,
        name: str,
        operation: Callable[[], Awaitable[ResultT]],
        *,
        timeout_seconds: float = 30.0,
    ) -> ResultT:
        """Run one Agent Tool with budget, cancellation, timeout, and safe events."""
        self.check_cancelled()
        self.budget.reserve_tool(name)
        timeout = self.budget.clamp_timeout(timeout_seconds)
        if timeout <= 0:
            limit = int(self.context.budget.max_runtime_seconds)
            raise BudgetExhausted("runtime_seconds", limit, limit)
        started = time.monotonic()
        self.repository.append_event(
            self.context.run_id,
            "tool_call_started",
            stage="tool",
            payload_summary=json.dumps({"tool": str(name)}, ensure_ascii=False),
        )
        try:
            with active_runtime_harness(self):
                async with asyncio.timeout(timeout):
                    result = await operation()
        except (RuntimeCancelled, BudgetExhausted):
            self.repository.append_event(
                self.context.run_id,
                "tool_call_cancelled",
                stage="tool",
                payload_summary=json.dumps(
                    {"tool": str(name), "error_type": "RuntimeStopped"},
                    ensure_ascii=False,
                ),
            )
            raise
        except Exception as exc:
            self.repository.append_event(
                self.context.run_id,
                "tool_call_failed",
                stage="tool",
                payload_summary=json.dumps(
                    {"tool": str(name), "error_type": type(exc).__name__},
                    ensure_ascii=False,
                ),
            )
            raise
        self.repository.append_event(
            self.context.run_id,
            "tool_call_completed",
            stage="tool",
            payload_summary=json.dumps(
                {
                    "tool": str(name),
                    "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
                },
                ensure_ascii=False,
            ),
        )
        return result
