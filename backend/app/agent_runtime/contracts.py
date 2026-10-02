from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INTERRUPTED = "interrupted"


class RunKind(StrEnum):
    CHAT = "chat"
    GENERATION = "generation"
    EVALUATION = "evaluation"


class ExecutionMode(StrEnum):
    INLINE = "inline"
    WORKER = "worker"


class BudgetMode(StrEnum):
    OBSERVE = "observe"
    ENFORCE = "enforce"


class RunEventType(StrEnum):
    RUN_QUEUED = "run_queued"
    RUN_CLAIMED = "run_claimed"
    RUN_CANCEL_REQUESTED = "run_cancel_requested"
    RUN_CANCELLED = "run_cancelled"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_BUDGET_EXHAUSTED = "run_budget_exhausted"
    RUN_INTERRUPTED = "run_interrupted"


class RuntimeCancelled(Exception):
    """Raised when a durable run has been cancelled cooperatively."""


class BudgetExhausted(Exception):
    """Raised before a governed side effect would exceed its frozen budget."""

    def __init__(self, dimension: str, used: int, limit: int):
        self.dimension = str(dimension)
        self.used = int(used)
        self.limit = int(limit)
        super().__init__(
            f"Execution budget exhausted: {self.dimension} {self.used}/{self.limit}"
        )


@dataclass(frozen=True)
class ExecutionBudget:
    max_transport_retries: int = 2
    max_quality_repairs: int = 2
    max_llm_calls: int = 32
    max_tool_calls: int = 0
    max_tokens: int = 120_000
    max_runtime_seconds: int = 900


@dataclass(frozen=True)
class RunContext:
    run_id: int
    project_id: int
    task_id: int
    spec_snapshot: Mapping[str, Any] = field(default_factory=dict)
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)

    def __post_init__(self):
        object.__setattr__(self, "spec_snapshot", MappingProxyType(dict(self.spec_snapshot)))
