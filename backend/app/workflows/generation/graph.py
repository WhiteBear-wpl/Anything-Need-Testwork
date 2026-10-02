from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.workflows.generation.nodes import (
    build_task_report,
    detect_task_duplicates,
    finalize_task,
    generate_core_cases,
    generate_specialist_cases,
    merge_agent_candidates,
    load_task,
    persist_feature_cases,
    prepare_feature,
    record_feature_failure,
    retrieve_knowledge,
    retry_feature,
    route_after_generation,
    route_after_validation,
    route_next_feature,
    run_task_judge,
    validate_cases,
)
from app.workflows.generation.state import GenerationState


def with_runtime_lifecycle(
    stage: str,
    node: Callable[[GenerationState], Awaitable[dict[str, Any]]],
    runtime=None,
) -> Callable[[GenerationState], Awaitable[dict[str, Any]]]:
    """Decorate graph nodes only when a durable AgentRun supplied a runtime."""
    if runtime is None:
        return node

    async def instrumented_node(state: GenerationState) -> dict[str, Any]:
        runtime.check_cancelled()
        runtime.repository.append_event(runtime.context.run_id, "node_started", stage=stage)
        from app.agent_runtime.harness import active_runtime_harness

        with active_runtime_harness(runtime):
            result = await node(state)
        runtime.repository.append_event(runtime.context.run_id, "node_finished", stage=stage)
        return result

    return instrumented_node


def build_generation_graph(checkpointer=None, *, runtime=None):
    builder = StateGraph(GenerationState)
    builder.add_node("load_task", with_runtime_lifecycle("load_task", load_task, runtime))
    builder.add_node("prepare_feature", with_runtime_lifecycle("prepare_feature", prepare_feature, runtime))
    builder.add_node("retrieve_knowledge", with_runtime_lifecycle("retrieve_knowledge", retrieve_knowledge, runtime))
    builder.add_node("generate_core_cases", with_runtime_lifecycle("generate_core_cases", generate_core_cases, runtime))
    builder.add_node("generate_specialist_cases", with_runtime_lifecycle("generate_specialist_cases", generate_specialist_cases, runtime))
    builder.add_node("merge_agent_candidates", with_runtime_lifecycle("merge_agent_candidates", merge_agent_candidates, runtime))
    builder.add_node("validate_cases", with_runtime_lifecycle("validate_cases", validate_cases, runtime))
    builder.add_node("retry_feature", with_runtime_lifecycle("retry_feature", retry_feature, runtime))
    builder.add_node("record_feature_failure", with_runtime_lifecycle("record_feature_failure", record_feature_failure, runtime))
    builder.add_node("persist_feature_cases", with_runtime_lifecycle("persist_feature_cases", persist_feature_cases, runtime))
    builder.add_node("detect_duplicates", with_runtime_lifecycle("detect_duplicates", detect_task_duplicates, runtime))
    builder.add_node("run_judge", with_runtime_lifecycle("run_judge", run_task_judge, runtime))
    builder.add_node("build_report", with_runtime_lifecycle("build_report", build_task_report, runtime))
    builder.add_node("finalize_task", with_runtime_lifecycle("finalize_task", finalize_task, runtime))

    builder.add_edge(START, "load_task")
    builder.add_edge("load_task", "prepare_feature")
    builder.add_edge("prepare_feature", "retrieve_knowledge")
    builder.add_edge("retrieve_knowledge", "generate_core_cases")
    builder.add_conditional_edges(
        "generate_core_cases",
        route_after_generation,
        {
            "continue": "generate_specialist_cases",
            "retry": "retry_feature",
            "feature_failed": "record_feature_failure",
        },
    )
    builder.add_conditional_edges(
        "generate_specialist_cases",
        route_after_generation,
        {
            "continue": "merge_agent_candidates",
            "retry": "retry_feature",
        },
    )
    builder.add_edge("merge_agent_candidates", "validate_cases")
    builder.add_conditional_edges(
        "validate_cases",
        route_after_validation,
        {
            "retry": "retry_feature",
            "persist": "persist_feature_cases",
            "feature_failed": "record_feature_failure",
        },
    )
    builder.add_edge("retry_feature", "generate_core_cases")
    builder.add_conditional_edges(
        "record_feature_failure",
        route_next_feature,
        {"next": "prepare_feature", "quality": "detect_duplicates"},
    )
    builder.add_conditional_edges(
        "persist_feature_cases",
        route_next_feature,
        {"next": "prepare_feature", "quality": "detect_duplicates"},
    )
    builder.add_edge("detect_duplicates", "run_judge")
    builder.add_edge("run_judge", "build_report")
    builder.add_edge("build_report", "finalize_task")
    builder.add_edge("finalize_task", END)
    return builder.compile(checkpointer=checkpointer)
