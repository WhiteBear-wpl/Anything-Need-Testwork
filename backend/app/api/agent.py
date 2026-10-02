"""测试助手 Agent 接口：持久会话、SSE 对话、LangGraph 中断确认与恢复。"""

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agent.checkpoint import delete_checkpoint
from app.agent.memory import maybe_update_summary
from app.agent.runner import AgentRuntimeError, run_agent
from app.agent_runtime.contracts import (
    BudgetExhausted,
    ExecutionBudget,
    RunContext,
    RunStatus,
    RuntimeCancelled,
)
from app.agent_runtime.harness import RuntimeHarness
from app.agent_runtime.inline import inline_agent_supervisor
from app.agent_runtime.repository import AgentRunRepository
from app.agent_runtime.service import create_assistant_run, is_unified_runtime_enabled
from app.api.deps import require_project_access
from app.api.agent_runs import stream_agent_run
from app.config import settings
from app.database import SessionLocal, get_db
from app.models.agent import AgentMessage, AgentThread
from app.models.agent_run import AgentRun
from app.models.project import Project
from app.models.requirement import RequirementDocument
from app.schemas import (
    AgentChatRequest,
    AgentMessageOut,
    AgentResumeRequest,
    AgentThreadStateOut,
)
from app.services.llm import LLMCallError
from app.services.redaction import redact_output
from app.services.settings_service import RuntimeModelConfig, get_project_runtime_config

router = APIRouter(
    prefix="/projects/{project_id}/agent",
    tags=["agent"],
    dependencies=[Depends(require_project_access)],
)

HISTORY_DISPLAY_LIMIT = 500
HISTORY_CONTEXT_LOAD_LIMIT = 200
_summary_tasks: set[asyncio.Task] = set()
logger = logging.getLogger(__name__)


def _json_dict(value: str) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _get_or_create_thread(db: Session, project_id: int) -> AgentThread:
    thread = db.query(AgentThread).filter(AgentThread.project_id == project_id).first()
    if thread:
        return thread
    thread = AgentThread(project_id=project_id, title="默认会话")
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def _parse_attachment(row: AgentMessage) -> dict | None:
    data = _json_dict(row.attachment)
    return data or None


def _serialize_message(row: AgentMessage) -> AgentMessageOut:
    try:
        tool_calls = json.loads(row.tool_calls or "[]")
    except json.JSONDecodeError:
        tool_calls = []
    return AgentMessageOut(
        id=row.id,
        role=row.role,
        content=row.content,
        tool_calls=tool_calls if isinstance(tool_calls, list) else [],
        attachment=_parse_attachment(row),
        created_at=row.created_at,
    )


def _history_content(row: AgentMessage) -> str:
    attachment = _parse_attachment(row)
    if attachment and attachment.get("document_id"):
        return (
            f"[附件：《{attachment.get('title', '')}》 document_id={attachment['document_id']}]\n"
            f"{row.content}"
        )
    return row.content


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _bounded_runtime_payload(payload: dict, limit: int = 1900) -> str:
    """Serialize bounded metadata; never persist raw Tool inputs or outputs."""
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    if "content" in payload:
        clipped = dict(payload)
        clipped["content"] = str(clipped["content"])[: max(0, limit - 100)]
        return json.dumps(clipped, ensure_ascii=False, default=str)[:limit]
    return json.dumps({"truncated": True}, ensure_ascii=False)


async def _run_and_persist_inline(*, agent_run_id: int, stream_kwargs: dict) -> None:
    """Own assistant execution independently from any one SSE consumer."""
    event_db = SessionLocal()
    repository = AgentRunRepository(event_db)
    token_buffer = ""

    def append(event_type: str, stage: str, payload: dict) -> None:
        repository.append_event(
            agent_run_id,
            event_type,
            stage=stage,
            payload_summary=_bounded_runtime_payload(payload),
        )

    def flush_tokens() -> None:
        nonlocal token_buffer
        while token_buffer:
            chunk, token_buffer = token_buffer[:1800], token_buffer[1800:]
            append(
                "assistant_output_delta",
                "assistant",
                {"content": redact_output(chunk, limit=1800)},
            )

    try:
        append("assistant_started", "assistant", {})
        async for frame in _agent_event_stream(
            agent_run_id=agent_run_id,
            **stream_kwargs,
        ):
            try:
                data = json.loads(frame.removeprefix("data: ").strip())
            except (json.JSONDecodeError, AttributeError):
                continue
            event_type = data.get("type")
            if event_type == "token":
                token_buffer += str(data.get("content") or "")
                if len(token_buffer) >= 512:
                    flush_tokens()
                continue
            flush_tokens()
            if event_type == "tool_start":
                append("tool_call_started", "tool", {"name": data.get("name", "")})
            elif event_type == "tool_end":
                metadata = {"name": data.get("name", "")}
                try:
                    output = json.loads(data.get("output") or "{}")
                except json.JSONDecodeError:
                    output = {}
                if isinstance(output, dict):
                    for key in ("task_id", "agent_run_id"):
                        if output.get(key) is not None:
                            metadata[key] = output[key]
                append("tool_call_completed", "tool", metadata)
            elif event_type == "approval_required":
                approval = data.get("approval") or {}
                append(
                    "approval_required",
                    "approval",
                    {
                        "title": approval.get("title", "操作需要确认"),
                        "description": approval.get("description", "请确认是否继续执行。"),
                        "danger": bool(approval.get("danger")),
                        "checkpoint_thread_id": approval.get("checkpoint_thread_id", ""),
                        "actions": [
                            {"name": action.get("name", "")}
                            for action in approval.get("actions", [])
                            if isinstance(action, dict)
                        ],
                    },
                )
            elif event_type == "done":
                append("assistant_completed", "assistant", {
                    "tool_calls": data.get("tool_calls") or [],
                })
            elif event_type == "error":
                current = event_db.get(AgentRun, agent_run_id, populate_existing=True)
                if current is not None and current.status not in {
                    RunStatus.COMPLETED.value,
                    RunStatus.FAILED.value,
                    RunStatus.CANCELLED.value,
                    RunStatus.BUDGET_EXHAUSTED.value,
                    RunStatus.INTERRUPTED.value,
                }:
                    append("assistant_failed", "assistant", {
                        "message": redact_output(
                            str(data.get("message") or ""), limit=500
                        ),
                    })
        flush_tokens()
    except Exception as exc:
        event_db.rollback()
        recovery_db = SessionLocal()
        try:
            AgentRunRepository(recovery_db).mark_terminal(
                agent_run_id,
                RunStatus.FAILED,
                payload_summary=json.dumps(
                    {"message": redact_output(str(exc), limit=500)},
                    ensure_ascii=False,
                ),
            )
        finally:
            recovery_db.close()
        logger.error(
            "Inline AgentRun %s failed outside the governed stream: %s",
            agent_run_id,
            redact_output(str(exc), limit=500),
        )
    finally:
        event_db.close()


def _update_workflow_state(
    thread: AgentThread,
    tool_name: str,
    tool_input: dict,
    output: str,
) -> None:
    state = _json_dict(thread.workflow_state)
    try:
        data = json.loads(output) if output else {}
    except json.JSONDecodeError:
        data = {}
    data = data if isinstance(data, dict) else {}

    if tool_name == "parse_requirement_document":
        state.update({
            "stage": "structured",
            "active_document_id": data.get("document_id") or tool_input.get("document_id"),
        })
        if data.get("item_count") is not None:
            state["feature_count"] = data["item_count"]
    elif tool_name == "confirm_features":
        state.update({
            "stage": "confirmed",
            "active_document_id": data.get("document_id") or tool_input.get("document_id"),
        })
    elif tool_name == "start_generation":
        state.update({
            "stage": "generating",
            "active_document_id": data.get("document_id") or tool_input.get("document_id"),
            "generation_task_id": data.get("task_id"),
            "generation_status": data.get("status", "pending"),
        })
    elif tool_name == "get_generation_status":
        state.update({
            "generation_task_id": data.get("task_id") or tool_input.get("task_id"),
            "generation_status": data.get("status"),
            "generation_progress": data.get("progress"),
        })
        if data.get("status") == "completed":
            state["stage"] = "reviewing"
    elif tool_name == "review_generated_drafts":
        state.update({
            "stage": "reviewed",
            "generation_task_id": data.get("task_id") or tool_input.get("task_id"),
            "last_review_action": data.get("action") or tool_input.get("action"),
            "last_review_count": data.get("count"),
        })
    thread.workflow_state = json.dumps(state, ensure_ascii=False)


def _schedule_summary(thread_id: int, model_config: RuntimeModelConfig) -> None:
    task = asyncio.create_task(maybe_update_summary(thread_id, model_config))
    _summary_tasks.add(task)
    task.add_done_callback(_summary_tasks.discard)


async def _agent_event_stream(
    *,
    project_id: int,
    project_name: str,
    thread_id: int,
    question: str,
    history: list[tuple[str, str]],
    model_config: RuntimeModelConfig,
    checkpoint_thread_id: str,
    document_id: int | None,
    resume_value: bool | None,
    prior_tool_calls: list[dict] | None = None,
    agent_run_id: int | None = None,
):
    session = SessionLocal()
    completed = False
    interrupted = False
    try:
        thread = session.get(AgentThread, thread_id)
        if not thread or thread.project_id != project_id:
            yield _sse({"type": "error", "message": "Agent 会话不存在"})
            return

        runtime = None
        if agent_run_id is not None:
            agent_run = session.get(AgentRun, agent_run_id)
            if agent_run is None or agent_run.project_id != project_id:
                yield _sse({"type": "error", "message": "Agent 运行不存在"})
                return
            repository = AgentRunRepository(session)
            transitioned = (
                repository.resume_inline(agent_run.id, datetime.now())
                if resume_value is not None
                else repository.start_inline(agent_run.id, datetime.now())
            )
            if not transitioned:
                yield _sse({"type": "error", "message": "Agent 运行状态已变化，请刷新后重试"})
                return
            agent_run = session.get(AgentRun, agent_run.id, populate_existing=True)
            try:
                spec_snapshot = json.loads(agent_run.agent_spec_snapshot or "{}")
                budget_snapshot = json.loads(agent_run.budget_snapshot or "{}")
                context = RunContext(
                    run_id=agent_run.id,
                    project_id=project_id,
                    task_id=0,
                    spec_snapshot=spec_snapshot,
                    budget=ExecutionBudget(**budget_snapshot),
                )
            except (json.JSONDecodeError, TypeError) as exc:
                repository.mark_terminal(
                    agent_run.id,
                    RunStatus.FAILED,
                    payload_summary=json.dumps({"message": "invalid runtime snapshot"}),
                )
                yield _sse({"type": "error", "message": "Agent 运行快照无效"})
                return
            runtime = RuntimeHarness(session, context)

        answer = ""
        tool_calls = list(prior_tool_calls or [])
        tool_inputs: dict[str, dict] = {}
        try:
            async for event in run_agent(
                session,
                project_id,
                project_name,
                question,
                history,
                model_config,
                document_id=document_id,
                checkpoint_thread_id=checkpoint_thread_id,
                resume_value=resume_value,
                summary=thread.summary or "",
                workflow_state=_json_dict(thread.workflow_state),
                runtime=runtime,
            ):
                if event["type"] == "tool_start":
                    tool_inputs[event["name"]] = event.get("input") or {}
                elif event["type"] == "tool_end":
                    _update_workflow_state(
                        thread,
                        event["name"],
                        tool_inputs.get(event["name"], {}),
                        event.get("output", ""),
                    )
                elif event["type"] == "approval_required":
                    interrupted = True
                    approval = event["approval"]
                    pending = {
                        **approval,
                        "question": question,
                        "document_id": document_id,
                        "tool_calls_so_far": tool_calls,
                        "agent_run_id": agent_run_id,
                    }
                    thread.pending_approval = json.dumps(pending, ensure_ascii=False)
                    thread.checkpoint_thread_id = checkpoint_thread_id
                    session.commit()
                    if agent_run_id is not None:
                        AgentRunRepository(session).mark_waiting_human(
                            agent_run_id, datetime.now()
                        )
                elif event["type"] == "done":
                    completed = True
                    answer = event["content"]
                    tool_calls.extend(event["tool_calls"])
                yield _sse(event)
        except BudgetExhausted as exc:
            if agent_run_id is not None:
                AgentRunRepository(session).mark_terminal(
                    agent_run_id,
                    RunStatus.BUDGET_EXHAUSTED,
                    payload_summary=json.dumps(
                        {"dimension": exc.dimension, "used": exc.used, "limit": exc.limit},
                        ensure_ascii=False,
                    ),
                )
            return
        except RuntimeCancelled:
            if agent_run_id is not None:
                AgentRunRepository(session).mark_terminal(
                    agent_run_id, RunStatus.CANCELLED
                )
            return
        except (LLMCallError, AgentRuntimeError) as exc:
            if agent_run_id is not None:
                AgentRunRepository(session).mark_terminal(
                    agent_run_id,
                    RunStatus.FAILED,
                    payload_summary=json.dumps(
                        {"message": redact_output(str(exc), limit=500)},
                        ensure_ascii=False,
                    ),
                )
            yield _sse({"type": "error", "message": str(exc)})
            return

        if interrupted or not completed:
            return
        thread.pending_approval = ""
        thread.checkpoint_thread_id = ""
        session.add(AgentMessage(
            project_id=project_id,
            thread_id=thread.id,
            role="assistant",
            content=answer,
            tool_calls=json.dumps(tool_calls, ensure_ascii=False),
        ))
        session.commit()
        if runtime is not None:
            try:
                await maybe_update_summary(thread.id, model_config, runtime=runtime)
            except BudgetExhausted as exc:
                AgentRunRepository(session).mark_terminal(
                    agent_run_id,
                    RunStatus.BUDGET_EXHAUSTED,
                    payload_summary=json.dumps(
                        {"dimension": exc.dimension, "used": exc.used, "limit": exc.limit},
                        ensure_ascii=False,
                    ),
                )
                return
            except RuntimeCancelled:
                AgentRunRepository(session).mark_terminal(
                    agent_run_id, RunStatus.CANCELLED
                )
                return
        else:
            _schedule_summary(thread.id, model_config)
        if agent_run_id is not None:
            AgentRunRepository(session).mark_terminal(
                agent_run_id, RunStatus.COMPLETED
            )
    finally:
        # 失败时保留待确认检查点供重试；普通错误产生的临时检查点及时清理。
        if not interrupted and not completed:
            await delete_checkpoint(checkpoint_thread_id)
        session.close()


@router.get("/messages", response_model=list[AgentMessageOut])
def list_messages(project_id: int, db: Session = Depends(get_db)):
    thread = _get_or_create_thread(db, project_id)
    rows = (
        db.query(AgentMessage)
        .filter(AgentMessage.thread_id == thread.id)
        .order_by(AgentMessage.id.desc())
        .limit(HISTORY_DISPLAY_LIMIT)
        .all()
    )
    return [_serialize_message(row) for row in reversed(rows)]


@router.get("/state", response_model=AgentThreadStateOut)
def get_state(project_id: int, db: Session = Depends(get_db)):
    thread = _get_or_create_thread(db, project_id)
    return AgentThreadStateOut(
        thread_id=thread.id,
        workflow_state=_json_dict(thread.workflow_state),
        pending_approval=_json_dict(thread.pending_approval) or None,
    )


@router.delete("/messages", status_code=204)
async def clear_messages(project_id: int, db: Session = Depends(get_db)):
    thread = _get_or_create_thread(db, project_id)
    checkpoint_thread_id = thread.checkpoint_thread_id
    db.query(AgentMessage).filter(AgentMessage.thread_id == thread.id).delete()
    thread.summary = ""
    thread.summary_until_message_id = 0
    thread.workflow_state = ""
    thread.pending_approval = ""
    thread.checkpoint_thread_id = ""
    db.commit()
    await delete_checkpoint(checkpoint_thread_id)


@router.post("/chat")
async def chat(
    project_id: int,
    data: AgentChatRequest,
    project: Project = Depends(require_project_access),
    db: Session = Depends(get_db),
):
    model_config = get_project_runtime_config(db, project_id)
    thread = _get_or_create_thread(db, project_id)
    if _json_dict(thread.pending_approval):
        raise HTTPException(409, "当前有待确认操作，请先确认或取消")

    document_id = data.document_id
    question = data.question
    attachment_json = ""
    if document_id is not None:
        doc = (
            db.query(RequirementDocument)
            .filter(
                RequirementDocument.id == document_id,
                RequirementDocument.project_id == project_id,
            )
            .first()
        )
        if not doc:
            raise HTTPException(404, "需求文档不存在")
        attachment_json = json.dumps(
            {"document_id": doc.id, "title": doc.title, "source_type": doc.source_type},
            ensure_ascii=False,
        )
        question = f"[用户上传了需求文档《{doc.title}》(document_id={doc.id})]\n{data.question}"
        state = _json_dict(thread.workflow_state)
        state.update({"stage": "uploaded", "active_document_id": doc.id})
        thread.workflow_state = json.dumps(state, ensure_ascii=False)

    history_rows = (
        db.query(AgentMessage)
        .filter(AgentMessage.thread_id == thread.id)
        .order_by(AgentMessage.id.desc())
        .limit(HISTORY_CONTEXT_LOAD_LIMIT)
        .all()
    )
    history = [(row.role, _history_content(row)) for row in reversed(history_rows)]

    user_message = AgentMessage(
        project_id=project_id,
        thread_id=thread.id,
        role="user",
        content=data.question,
        attachment=attachment_json,
    )
    db.add(user_message)
    db.commit()
    db.refresh(user_message)
    checkpoint_thread_id = f"agent:{project_id}:{thread.id}:{user_message.id}"
    agent_run_id = None
    if is_unified_runtime_enabled(
        settings.agent_runtime_v2_enabled,
        settings.unified_agent_runtime_enabled,
        project,
    ):
        agent_run_id = create_assistant_run(
            db,
            project_id=project_id,
            thread_id=thread.id,
            message_id=user_message.id,
            model_snapshot=asdict(model_config),
        ).id

    stream_kwargs = {
        "project_id": project_id,
        "project_name": project.name,
        "thread_id": thread.id,
        "question": question,
        "history": history,
        "model_config": model_config,
        "checkpoint_thread_id": checkpoint_thread_id,
        "document_id": document_id,
        "resume_value": None,
    }
    if agent_run_id is not None:
        inline_agent_supervisor.start(
            agent_run_id,
            lambda: _run_and_persist_inline(
                agent_run_id=agent_run_id,
                stream_kwargs=stream_kwargs,
            ),
        )
        return stream_agent_run(
            project_id,
            agent_run_id,
            data.after_sequence,
            db,
        )
    return StreamingResponse(
        _agent_event_stream(**stream_kwargs),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/resume")
async def resume(
    project_id: int,
    data: AgentResumeRequest,
    project: Project = Depends(require_project_access),
    db: Session = Depends(get_db),
):
    thread = _get_or_create_thread(db, project_id)
    pending = _json_dict(thread.pending_approval)
    if not pending:
        raise HTTPException(409, "当前没有待确认操作")
    if (
        data.checkpoint_thread_id != thread.checkpoint_thread_id
        or data.checkpoint_thread_id != pending.get("checkpoint_thread_id")
    ):
        raise HTTPException(409, "确认操作已过期，请刷新后重试")

    model_config = get_project_runtime_config(db, project_id)
    agent_run_id = pending.get("agent_run_id")
    stream_kwargs = {
        "project_id": project_id,
        "project_name": project.name,
        "thread_id": thread.id,
        "question": pending.get("question", ""),
        "history": [],
        "model_config": model_config,
        "checkpoint_thread_id": data.checkpoint_thread_id,
        "document_id": pending.get("document_id"),
        "resume_value": data.approved,
        "prior_tool_calls": pending.get("tool_calls_so_far") or [],
    }
    if agent_run_id is not None:
        inline_agent_supervisor.start(
            agent_run_id,
            lambda: _run_and_persist_inline(
                agent_run_id=agent_run_id,
                stream_kwargs=stream_kwargs,
            ),
        )
        return stream_agent_run(
            project_id,
            agent_run_id,
            data.after_sequence,
            db,
        )
    return StreamingResponse(
        _agent_event_stream(**stream_kwargs),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
