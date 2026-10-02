import json

from app.agent_runtime.contracts import BudgetExhausted, RunContext, RunStatus, RuntimeCancelled
from app.agent_runtime.harness import RuntimeHarness
from app.agent_runtime.repository import AgentRunRepository
from app.database import SessionLocal
from app.models.generation import GeneratedCaseDraft, GenerationTask
from app.models.requirement import RequirementItem
from app.services.llm import start_token_tracking, total_tokens
from app.workflows.generation.checkpoint import checkpoint_context
from app.workflows.generation.graph import build_generation_graph
from app.workflows.generation.failure_policy import redact_output


MIN_GENERATION_RECURSION_LIMIT = 25
GENERATION_STEPS_PER_FEATURE = 8
GENERATION_FIXED_STEPS = 8
MAX_GENERATION_RECURSION_LIMIT = 4096


def generation_recursion_limit(feature_count: int) -> int:
    """按图的确定性节点数分配预算，并为每个功能点预留一次结构重试。"""
    calculated = feature_count * GENERATION_STEPS_PER_FEATURE + GENERATION_FIXED_STEPS
    return min(
        MAX_GENERATION_RECURSION_LIMIT,
        max(MIN_GENERATION_RECURSION_LIMIT, calculated),
    )


def _confirmed_feature_count(task_id: int) -> int:
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        if not task:
            return 0
        return (
            db.query(RequirementItem)
            .filter(
                RequirementItem.document_id == task.document_id,
                RequirementItem.confirmed == True,  # noqa: E712
            )
            .count()
        )
    finally:
        db.close()


def _mark_agent_run_terminal(
    db,
    run_id: int,
    status: RunStatus,
    *,
    payload_summary: str = "{}",
) -> None:
    AgentRunRepository(db).mark_terminal(
        run_id,
        status,
        payload_summary=payload_summary,
    )


def _owns_agent_terminal(run_context: RunContext | None) -> bool:
    return bool(
        run_context is not None
        and run_context.spec_snapshot.get("name") != "evaluation_runner"
    )


async def run_generation_workflow(
    task_id: int,
    *,
    resume: bool = False,
    run_context: RunContext | None = None,
) -> None:
    """执行或恢复生成工作流，业务状态仍写回现有 GenerationTask。"""
    token_counter = start_token_tracking()
    feature_count = _confirmed_feature_count(task_id)
    config = {
        "configurable": {"thread_id": f"generation:{task_id}"},
        # 必须显式覆盖：Agent 工具在后台创建任务时会复制 ContextVar，
        # 否则生成图会错误继承 Agent 较小的 recursion_limit。
        "recursion_limit": generation_recursion_limit(feature_count),
    }

    if resume:
        db = SessionLocal()
        try:
            task = db.get(GenerationTask, task_id)
            if not task:
                raise RuntimeError("生成任务不存在")
            task.status = "generating"
            task.error_message = ""
            db.commit()
        finally:
            db.close()

    runtime_db = SessionLocal() if run_context is not None else None
    runtime = RuntimeHarness(runtime_db, run_context) if runtime_db is not None else None
    owns_agent_terminal = _owns_agent_terminal(run_context)

    try:
        async with checkpoint_context() as checkpointer:
            await checkpointer.setup()
            graph = build_generation_graph(checkpointer, runtime=runtime)
            inputs = None if resume else {"task_id": task_id}
            await graph.ainvoke(inputs, config=config)
    except BudgetExhausted as exc:
        db = SessionLocal()
        try:
            task = db.get(GenerationTask, task_id)
            if task:
                task.status = RunStatus.BUDGET_EXHAUSTED.value
                task.error_message = ""
                task.stage = ""
                task.tokens_used = total_tokens(token_counter)
                db.commit()
            if owns_agent_terminal:
                _mark_agent_run_terminal(
                    db,
                    run_context.run_id,
                    RunStatus.BUDGET_EXHAUSTED,
                    payload_summary=json.dumps(
                        {
                            "dimension": exc.dimension,
                            "used": exc.used,
                            "limit": exc.limit,
                        },
                        ensure_ascii=False,
                    ),
                )
        finally:
            db.close()
        if run_context is not None and not owns_agent_terminal:
            raise
    except RuntimeCancelled:
        db = SessionLocal()
        try:
            task = db.get(GenerationTask, task_id)
            if task:
                task.status = RunStatus.CANCELLED.value
                task.error_message = ""
                task.stage = ""
                task.tokens_used = total_tokens(token_counter)
                db.commit()
            if owns_agent_terminal:
                _mark_agent_run_terminal(
                    db,
                    run_context.run_id,
                    RunStatus.CANCELLED,
                )
        finally:
            db.close()
        if run_context is not None and not owns_agent_terminal:
            raise
    except Exception as exc:
        db = SessionLocal()
        try:
            task = db.get(GenerationTask, task_id)
            if task:
                task.status = "failed"
                task.error_message = redact_output(str(exc), limit=2000)
                task.stage = ""
                task.tokens_used = total_tokens(token_counter)
                db.commit()
            if owns_agent_terminal:
                _mark_agent_run_terminal(
                    db,
                    run_context.run_id,
                    RunStatus.FAILED,
                    payload_summary=json.dumps(
                        {"message": redact_output(str(exc), limit=500)}, ensure_ascii=False
                    ),
                )
        finally:
            db.close()
        raise
    else:
        db = SessionLocal()
        try:
            task = db.get(GenerationTask, task_id)
            if task:
                task.tokens_used = total_tokens(token_counter)
                if run_context is not None:
                    db.query(GeneratedCaseDraft).filter(
                        GeneratedCaseDraft.task_id == task_id
                    ).update(
                        {GeneratedCaseDraft.agent_run_id: run_context.run_id},
                        synchronize_session=False,
                    )
                db.commit()
            if owns_agent_terminal:
                _mark_agent_run_terminal(
                    db,
                    run_context.run_id,
                    RunStatus.COMPLETED,
                )
        finally:
            db.close()
    finally:
        if runtime_db is not None:
            runtime_db.close()


async def resume_generation_workflow(task_id: int) -> None:
    await run_generation_workflow(task_id, resume=True)
