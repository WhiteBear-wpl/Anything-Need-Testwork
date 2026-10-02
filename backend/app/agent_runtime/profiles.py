from app.agent_runtime.contracts import ExecutionBudget, RunKind


_BUDGETS = {
    RunKind.CHAT.value: ExecutionBudget(
        max_transport_retries=1,
        max_quality_repairs=1,
        max_llm_calls=8,
        max_tool_calls=8,
        max_tokens=32_000,
        max_runtime_seconds=180,
    ),
    RunKind.GENERATION.value: ExecutionBudget(
        max_transport_retries=2,
        max_quality_repairs=2,
        max_llm_calls=32,
        max_tool_calls=0,
        max_tokens=120_000,
        max_runtime_seconds=900,
    ),
    RunKind.EVALUATION.value: ExecutionBudget(
        max_transport_retries=2,
        max_quality_repairs=2,
        max_llm_calls=64,
        max_tool_calls=0,
        max_tokens=240_000,
        max_runtime_seconds=1800,
    ),
}


def budget_for(run_kind: RunKind | str) -> ExecutionBudget:
    """Return the immutable backend-owned budget profile for one run kind."""
    value = run_kind.value if isinstance(run_kind, RunKind) else str(run_kind)
    try:
        return _BUDGETS[value]
    except KeyError as exc:
        raise ValueError(f"unsupported run kind: {value}") from exc
