import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import case, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent_runtime.contracts import (
    BudgetExhausted,
    BudgetMode,
    RunContext,
    RunStatus,
    RuntimeCancelled,
)
from app.agent_runtime.repository import AgentRunRepository
from app.models.agent_run import AgentRun


_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")


def estimate_tokens(value: object) -> int:
    """Estimate tokens without adding a tokenizer dependency."""
    if value is None:
        return 0
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    cjk_count = len(_CJK_PATTERN.findall(text))
    return cjk_count + math.ceil((len(text) - cjk_count) / 4)


@dataclass(frozen=True)
class LLMReservation:
    input_tokens: int
    output_tokens: int
    reserved_tokens: int


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    source: str

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class BudgetLedger:
    """Persist budget reservations before governed side effects begin."""

    def __init__(
        self,
        db: Session,
        context: RunContext,
        *,
        mode: BudgetMode | str = BudgetMode.OBSERVE,
    ):
        self.db = db
        self.context = context
        self.mode = mode if isinstance(mode, BudgetMode) else BudgetMode(str(mode))
        self.repository = AgentRunRepository(db)

    @property
    def enforcing(self) -> bool:
        return self.mode == BudgetMode.ENFORCE

    def _run(self) -> AgentRun:
        run = self.db.get(AgentRun, self.context.run_id, populate_existing=True)
        if run is None or run.cancel_requested:
            raise RuntimeCancelled(f"Agent run {self.context.run_id} was cancelled")
        if run.status != RunStatus.RUNNING.value:
            raise RuntimeCancelled(
                f"Agent run {self.context.run_id} is not running ({run.status})"
            )
        return run

    def _runtime_exhaustion(self, run: AgentRun, now: datetime) -> BudgetExhausted | None:
        if run.deadline_at is None or run.deadline_at > now:
            return None
        limit = max(0, int(self.context.budget.max_runtime_seconds))
        return BudgetExhausted("runtime_seconds", limit, limit)

    def _raise_reservation_failure(
        self,
        *,
        llm_tokens: int = 0,
        counter: tuple[str, int] | None = None,
    ) -> None:
        run = self._run()
        runtime_error = self._runtime_exhaustion(run, datetime.now())
        if self.enforcing and runtime_error is not None:
            raise runtime_error
        if counter is not None:
            field, limit = counter
            used = int(getattr(run, field)) + 1
            if used > limit:
                raise BudgetExhausted(field.removesuffix("_used"), used, limit)
        if llm_tokens:
            attempted = int(run.tokens_used) + int(run.tokens_reserved) + llm_tokens
            if attempted > self.context.budget.max_tokens:
                raise BudgetExhausted(
                    "tokens", attempted, self.context.budget.max_tokens
                )
        raise RuntimeCancelled(f"Agent run {self.context.run_id} cannot reserve budget")

    def _usage_ratios(self, run: AgentRun, now: datetime) -> list[tuple[str, int, int]]:
        budget = self.context.budget
        values = [
            ("llm_calls", int(run.llm_calls_used), int(budget.max_llm_calls)),
            ("tool_calls", int(run.tool_calls_used), int(budget.max_tool_calls)),
            (
                "tokens",
                int(run.tokens_used) + int(run.tokens_reserved),
                int(budget.max_tokens),
            ),
            (
                "transport_retries",
                int(run.transport_retries_used),
                int(budget.max_transport_retries),
            ),
            (
                "quality_repairs",
                int(run.quality_repairs_used),
                int(budget.max_quality_repairs),
            ),
        ]
        if run.started_at is not None:
            used_seconds = max(0, int((now - run.started_at).total_seconds()))
            values.append(
                ("runtime_seconds", used_seconds, int(budget.max_runtime_seconds))
            )
        return values

    def _stage_threshold_events(self, run: AgentRun, now: datetime) -> None:
        ratios = self._usage_ratios(run, now)
        warning = max(
            (
                (used / limit, dimension, used, limit)
                for dimension, used, limit in ratios
                if limit > 0 and used / limit >= 0.8
            ),
            default=None,
        )
        if warning is not None and not run.budget_warning_emitted:
            changed = self.db.execute(
                update(AgentRun)
                .where(
                    AgentRun.id == run.id,
                    AgentRun.budget_warning_emitted.is_(False),
                )
                .values(budget_warning_emitted=True)
            )
            if changed.rowcount == 1:
                ratio, dimension, used, limit = warning
                self.repository._stage_event(
                    run.id,
                    "budget_warning",
                    stage="budget",
                    payload_summary=json.dumps(
                        {
                            "dimension": dimension,
                            "used": used,
                            "limit": limit,
                            "percent": min(100, int(ratio * 100)),
                        },
                        ensure_ascii=False,
                    ),
                    now=now,
                )
        if self.mode == BudgetMode.OBSERVE:
            exceeded = [item for item in ratios if item[2] >= 0 and item[1] > item[2]]
            if exceeded:
                dimension, used, limit = exceeded[0]
                self.repository._stage_event(
                    run.id,
                    "budget_would_exhaust",
                    stage="budget",
                    payload_summary=json.dumps(
                        {"dimension": dimension, "used": used, "limit": limit},
                        ensure_ascii=False,
                    ),
                    now=now,
                )

    def reserve_llm(
        self,
        *,
        input_tokens: int,
        max_output_tokens: int,
    ) -> LLMReservation:
        input_tokens = max(0, int(input_tokens))
        max_output_tokens = max(0, int(max_output_tokens))
        reserved = input_tokens + max_output_tokens
        budget = self.context.budget
        for attempt in range(3):
            now = datetime.now()
            conditions = [
                AgentRun.id == self.context.run_id,
                AgentRun.status == RunStatus.RUNNING.value,
                AgentRun.cancel_requested.is_(False),
            ]
            if self.enforcing:
                conditions.extend(
                    [
                        AgentRun.llm_calls_used < budget.max_llm_calls,
                        AgentRun.tokens_used + AgentRun.tokens_reserved + reserved
                        <= budget.max_tokens,
                        (AgentRun.deadline_at.is_(None)) | (AgentRun.deadline_at > now),
                    ]
                )
            try:
                changed = self.db.execute(
                    update(AgentRun)
                    .where(*conditions)
                    .values(
                        llm_calls_used=AgentRun.llm_calls_used + 1,
                        tokens_reserved=AgentRun.tokens_reserved + reserved,
                    )
                )
                if changed.rowcount != 1:
                    self.db.rollback()
                    self._raise_reservation_failure(
                        llm_tokens=reserved,
                        counter=("llm_calls_used", budget.max_llm_calls),
                    )
                run = self.db.get(
                    AgentRun, self.context.run_id, populate_existing=True
                )
                self._stage_threshold_events(run, now)
                self.db.commit()
                return LLMReservation(input_tokens, max_output_tokens, reserved)
            except IntegrityError:
                self.db.rollback()
                if attempt == 2:
                    raise
        raise RuntimeError("unreachable")

    def settle_llm(
        self,
        reservation: LLMReservation,
        usage: dict[str, Any] | None,
        *,
        output: object,
    ) -> TokenUsage:
        if isinstance(usage, dict):
            input_tokens = max(
                0,
                int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0),
            )
            output_tokens = max(
                0,
                int(
                    usage.get("output_tokens", usage.get("completion_tokens", 0))
                    or 0
                ),
            )
            source = "provider"
        else:
            input_tokens = reservation.input_tokens
            output_tokens = estimate_tokens(output)
            source = "estimated"
        token_usage = TokenUsage(input_tokens, output_tokens, source)
        now = datetime.now()
        self.db.execute(
            update(AgentRun)
            .where(AgentRun.id == self.context.run_id)
            .values(
                tokens_reserved=case(
                    (
                        AgentRun.tokens_reserved >= reservation.reserved_tokens,
                        AgentRun.tokens_reserved - reservation.reserved_tokens,
                    ),
                    else_=0,
                ),
                tokens_used=AgentRun.tokens_used + token_usage.total_tokens,
            )
        )
        run = self.db.get(AgentRun, self.context.run_id, populate_existing=True)
        self._stage_threshold_events(run, now)
        self.db.commit()
        return token_usage

    def _reserve_counter(self, field: str, limit: int) -> None:
        for attempt in range(3):
            now = datetime.now()
            column = getattr(AgentRun, field)
            conditions = [
                AgentRun.id == self.context.run_id,
                AgentRun.status == RunStatus.RUNNING.value,
                AgentRun.cancel_requested.is_(False),
            ]
            if self.enforcing:
                conditions.extend(
                    [
                        column < limit,
                        (AgentRun.deadline_at.is_(None)) | (AgentRun.deadline_at > now),
                    ]
                )
            try:
                changed = self.db.execute(
                    update(AgentRun).where(*conditions).values({field: column + 1})
                )
                if changed.rowcount != 1:
                    self.db.rollback()
                    self._raise_reservation_failure(counter=(field, limit))
                run = self.db.get(
                    AgentRun, self.context.run_id, populate_existing=True
                )
                self._stage_threshold_events(run, now)
                self.db.commit()
                return
            except IntegrityError:
                self.db.rollback()
                if attempt == 2:
                    raise
        raise RuntimeError("unreachable")

    def reserve_tool(self, _name: str) -> None:
        self._reserve_counter("tool_calls_used", self.context.budget.max_tool_calls)

    def consume_transport_retry(self) -> None:
        self._reserve_counter(
            "transport_retries_used", self.context.budget.max_transport_retries
        )

    def consume_quality_repair(self) -> None:
        self._reserve_counter(
            "quality_repairs_used", self.context.budget.max_quality_repairs
        )

    def remaining_seconds(self) -> float:
        run = self._run()
        if run.deadline_at is None:
            return float(self.context.budget.max_runtime_seconds)
        remaining = (run.deadline_at - datetime.now()).total_seconds()
        if self.enforcing and remaining <= 0:
            limit = int(self.context.budget.max_runtime_seconds)
            raise BudgetExhausted("runtime_seconds", limit, limit)
        return max(0.0, remaining)

    def clamp_timeout(self, timeout_seconds: float) -> float:
        return min(max(0.0, float(timeout_seconds)), self.remaining_seconds())
