"""测试助手 Agent 运行器：LangGraph ReAct 循环，产出前端可流式消费的事件。

事件类型（dict 的 type 字段）：
- tool_start: {name, input}   开始调用某个工具
- tool_end:   {name}          工具调用结束
- token:      {content}       模型回答的增量文本
- done:       {content, tool_calls}  本轮结束，附完整回答与工具调用记录

模型/网络错误抛出 LLMCallError，由 API 层转成 error 事件。
Mock 模式（未配置生成模型 Key 或显式开启）走固定剧本，不调用真实接口。
"""

import json
import logging
import uuid
from typing import AsyncIterator, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.checkpoint import checkpoint_context
from app.agent_runtime.contracts import BudgetExhausted, RuntimeCancelled
from app.agent.memory import CONTEXT_MESSAGE_LIMIT, select_context
from app.agent.tools import build_agent_tools
from app.ai.model_factory import create_chat_model, normalize_chat_error
from app.models.testcase import TestCase
from app.services import knowledge_service
from app.services.llm import LLMCallError
from app.services.settings_service import RuntimeModelConfig

# recursion_limit 按 LangGraph 超步计：agent + tools 一轮占 2 步，
# 13 约等于最多 6 轮工具调用 + 最终回答，防止模型陷入循环取数。
MAX_GRAPH_STEPS = 13
HISTORY_LIMIT = CONTEXT_MESSAGE_LIMIT  # 兼容旧调用；实际还受 Token 预算约束
MUTATING_TOOLS = {"confirm_features", "start_generation", "review_generated_drafts"}
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是「测试助手」，嵌入在 AI 测试用例平台中的项目助手。
当前项目：{project_name}。

你有两类能力：
一、查询工具：知识库检索、测试用例、需求覆盖率、测试任务进度、缺陷记录。
二、用例生成流水线工具：解析需求文档（parse_requirement_document）、确认功能点（confirm_features）、
启动生成（start_generation）、查询生成进度（get_generation_status）、采纳/驳回候选用例（review_generated_drafts）。

查询规则：
1. 涉及项目数据的问题必须先调用工具取数，再基于返回结果回答，禁止编造数字或规则。
2. 工具没有查到相关结果时，直接告诉用户"没有查到"，并给出下一步建议（如补充知识库、调整关键词）。

流水线规则（必须严格遵守）：
1. 用户上传需求文档后（消息会附带 document_id），先调用 parse_requirement_document 解析，
   然后把功能点清单（模块/功能点/优先级）完整展示给用户，并询问是否确认、用什么策略生成。
2. 只有用户明确表示确认后，才能调用 confirm_features 和 start_generation；
   用户未确认前禁止启动生成。策略以用户指定为准（完整用例 full / 快速冒烟 quick，默认 full）。
3. 启动生成后告诉用户任务在后台执行、可随时追问进度；用户追问时用 get_generation_status 查询。
4. 采纳或驳回候选用例必须有用户的明确指令（如"采纳全部 P0"），禁止自行决定；
   操作后如实汇报数量。已采纳/已驳回的用例是终态，无法撤销。
5. 除上述流水线工具允许的操作外，不能修改任何数据；用户要求其他增删改时，指引到对应页面操作。
6. confirm_features、start_generation、review_generated_drafts 会由系统在执行前弹出结构化确认卡片。
   你只需根据用户意图正常发起工具调用，不要用普通文字替代系统确认，也不要声称已经执行尚未确认的操作。

用简体中文回答，简明扼要，数字与结论要能对应到工具返回的数据。"""


class AgentState(MessagesState):
    approved_actions: list[str]
    approval_decision: str


class MockApprovalState(TypedDict):
    payload: dict
    approved: bool


class AgentRuntimeError(RuntimeError):
    """非模型类的 Agent 执行错误，API 层应按业务错误提示。"""


def _message_text(content) -> str:
    """兼容 str 与分块 list 两种 content 形态。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content or "")


def _history_messages(history: list[tuple[str, str]]) -> list:
    messages = []
    for role, content in select_context(history):
        if not content:
            continue
        messages.append(HumanMessage(content) if role == "user" else AIMessage(content))
    return messages


def _tool_output_text(output) -> str:
    """astream_events 的工具输出可能是 str 或 ToolMessage，统一取文本。"""
    if output is None:
        return ""
    content = getattr(output, "content", output)
    return _message_text(content)


def _is_agent_model_stream(event: dict) -> bool:
    """只转发 ReAct 的 agent 节点，隔离工具内部及后台工作流的模型 token。"""
    metadata = event.get("metadata") or {}
    return metadata.get("langgraph_node") == "agent"


def _extract_task_id(name: str, output_text: str) -> int | None:
    """从 start_generation 的输出中提取 task_id，供前端渲染进度卡片。"""
    if name != "start_generation" or not output_text:
        return None
    try:
        data = json.loads(output_text)
    except json.JSONDecodeError:
        return None
    task_id = data.get("task_id") if isinstance(data, dict) else None
    return task_id if isinstance(task_id, int) else None


def _last_tool_calls(state: AgentState) -> list[dict]:
    messages = state.get("messages") or []
    last = messages[-1] if messages else None
    return list(getattr(last, "tool_calls", None) or [])


def _expanded_approval_calls(state: AgentState, tool_calls: list[dict]) -> list[dict]:
    """把“确认生成”的连续 confirm → start 两步合并为一次用户审批。"""
    expanded = list(tool_calls)
    names = {call.get("name") for call in tool_calls}
    if "confirm_features" not in names or "start_generation" in names:
        return expanded
    latest_question = ""
    for message in reversed(state.get("messages") or []):
        if isinstance(message, HumanMessage):
            latest_question = _message_text(message.content)
            break
    if not any(word in latest_question for word in ("生成", "开始")):
        return expanded
    confirm = next(call for call in tool_calls if call.get("name") == "confirm_features")
    args = confirm.get("args") if isinstance(confirm.get("args"), dict) else {}
    strategy = (
        "quick"
        if "冒烟" in latest_question or "quick" in latest_question.lower()
        else "full"
    )
    expanded.append({
        "name": "start_generation",
        "args": {"document_id": args.get("document_id"), "strategy": strategy},
    })
    return expanded


def _approval_payload(tool_calls: list[dict]) -> dict:
    actions = []
    for call in tool_calls:
        name = call.get("name", "")
        if name not in MUTATING_TOOLS:
            continue
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        actions.append({"name": name, "args": args})

    names = {action["name"] for action in actions}
    if "review_generated_drafts" in names:
        review = next(a for a in actions if a["name"] == "review_generated_drafts")
        action = review["args"].get("action")
        title = "确认采纳候选用例" if action == "adopt" else "确认驳回候选用例"
        description = (
            "采纳后会写入正式用例库，且候选用例将进入不可撤销的终态。"
            if action == "adopt"
            else "驳回后候选用例将进入不可撤销的终态。"
        )
        danger = True
    elif "start_generation" in names:
        start = next(a for a in actions if a["name"] == "start_generation")
        strategy = start["args"].get("strategy", "full")
        title = "确认并启动用例生成"
        description = (
            f"将确认功能点并按 {strategy} 策略创建后台生成任务。"
            "生成结果进入候选区，仍需评审后才会写入正式用例库。"
        )
        danger = False
    else:
        title = "确认功能点"
        description = "确认后这些功能点会成为后续用例生成的输入。"
        danger = False
    return {
        "type": "agent_action_approval",
        "title": title,
        "description": description,
        "danger": danger,
        "actions": actions,
    }


def _route_after_model(state: AgentState):
    tool_calls = _last_tool_calls(state)
    if not tool_calls:
        return END
    approved = set(state.get("approved_actions") or [])
    if any(
        call.get("name") in MUTATING_TOOLS and call.get("name") not in approved
        for call in tool_calls
    ):
        return "approval"
    return "tools"


def _approval_node(state: AgentState):
    tool_calls = _last_tool_calls(state)
    approval_calls = _expanded_approval_calls(state, tool_calls)
    decision = interrupt(_approval_payload(approval_calls))
    approved = decision.get("approved") if isinstance(decision, dict) else bool(decision)
    if approved:
        names = [
            call["name"]
            for call in approval_calls
            if call.get("name") in MUTATING_TOOLS
        ]
        return {
            "approved_actions": list(dict.fromkeys([
                *(state.get("approved_actions") or []),
                *names,
            ])),
            "approval_decision": "approved",
        }

    messages = [
        ToolMessage(
            content="用户在确认卡片中取消了本次操作，未执行任何工具。",
            tool_call_id=call.get("id", ""),
            name=call.get("name", ""),
        )
        for call in tool_calls
    ]
    return {"messages": messages, "approval_decision": "rejected"}


def _route_after_approval(state: AgentState):
    return END if state.get("approval_decision") == "rejected" else "tools"


def _build_serial_tool_runner(tools, runtime=None):
    """Agent 工具共享请求级 Session，必须串行执行，不能使用 ToolNode 的 gather。"""
    tool_map = {tool.name: tool for tool in tools}

    async def run_tools(state: AgentState, config: RunnableConfig):
        messages = []
        for call in _last_tool_calls(state):
            name = call.get("name", "")
            tool = tool_map.get(name)
            if tool is None:
                messages.append(ToolMessage(
                    content=f"未知工具：{name}",
                    tool_call_id=call.get("id", ""),
                    name=name,
                ))
                continue
            async def invoke_tool():
                return await tool.ainvoke(call.get("args") or {}, config=config)

            output = (
                await runtime.run_tool(name, invoke_tool, timeout_seconds=30.0)
                if runtime is not None
                else await invoke_tool()
            )
            content = (
                output
                if isinstance(output, str)
                else json.dumps(output, ensure_ascii=False, default=str)
            )
            messages.append(ToolMessage(
                content=content,
                tool_call_id=call.get("id", ""),
                name=name,
            ))
        return {"messages": messages}

    return run_tools


def _build_agent_graph(llm, tools, checkpointer, runtime=None):
    async def call_model(state: AgentState):
        try:
            async def invoke_model():
                return await llm.ainvoke(state["messages"])

            response = (
                await runtime.call_llm(
                    "assistant",
                    "assistant",
                    invoke_model,
                    input_value=state["messages"],
                    max_output_tokens=4096,
                )
                if runtime is not None
                else await invoke_model()
            )
        except Exception as exc:
            from app.agent_runtime.contracts import BudgetExhausted, RuntimeCancelled

            if isinstance(exc, (RuntimeCancelled, BudgetExhausted)):
                raise
            raise normalize_chat_error(exc, "generation") from exc
        return {"messages": [response], "approval_decision": ""}

    builder = StateGraph(AgentState)
    builder.add_node("agent", call_model)
    builder.add_node("approval", _approval_node)
    builder.add_node("tools", _build_serial_tool_runner(tools, runtime=runtime))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        _route_after_model,
        {"approval": "approval", "tools": "tools", END: END},
    )
    builder.add_conditional_edges(
        "approval",
        _route_after_approval,
        {"tools": "tools", END: END},
    )
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=checkpointer)


def _interrupt_payload(result: dict) -> dict | None:
    interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
    if not interrupts:
        return None
    item = interrupts[0]
    value = getattr(item, "value", item)
    return value if isinstance(value, dict) else None


def _mock_approval_payload(db: Session, project_id: int, question: str) -> dict | None:
    from app.models.generation import GeneratedCaseDraft, GenerationTask
    from app.models.requirement import RequirementDocument

    if "采纳" in question or "驳回" in question:
        task = (
            db.query(GenerationTask)
            .filter(
                GenerationTask.project_id == project_id,
                GenerationTask.status == "completed",
                GenerationTask.is_eval == False,  # noqa: E712
            )
            .order_by(GenerationTask.created_at.desc())
            .first()
        )
        if not task:
            return None
        pending_count = (
            db.query(GeneratedCaseDraft)
            .filter(
                GeneratedCaseDraft.task_id == task.id,
                GeneratedCaseDraft.review_status.notin_(["adopted", "rejected"]),
            )
            .count()
        )
        action = "reject" if "驳回" in question else "adopt"
        payload = _approval_payload([{
            "name": "review_generated_drafts",
            "args": {"task_id": task.id, "action": action},
        }])
        payload["description"] += f" 当前匹配 {pending_count} 条待评审用例。"
        return payload

    if any(word in question for word in ("确认", "生成", "开始")):
        doc = (
            db.query(RequirementDocument)
            .filter(
                RequirementDocument.project_id == project_id,
                RequirementDocument.status.in_(["structured", "confirmed"]),
                RequirementDocument.is_eval == False,  # noqa: E712
            )
            .order_by(RequirementDocument.created_at.desc())
            .first()
        )
        if not doc:
            return None
        strategy = "quick" if ("冒烟" in question or "quick" in question.lower()) else "full"
        return _approval_payload([
            {"name": "confirm_features", "args": {"document_id": doc.id}},
            {
                "name": "start_generation",
                "args": {"document_id": doc.id, "strategy": strategy},
            },
        ])
    return None


async def _mock_approval_checkpoint(
    payload: dict,
    checkpoint_thread_id: str,
    resume_value: bool | None,
) -> tuple[dict | None, bool | None]:
    """Mock 也经过 interrupt/Command，确保开发和真实模型使用同一恢复语义。"""

    def wait_for_decision(state: MockApprovalState):
        decision = interrupt(state["payload"])
        approved = decision.get("approved") if isinstance(decision, dict) else bool(decision)
        return {"approved": bool(approved)}

    async with checkpoint_context() as checkpointer:
        builder = StateGraph(MockApprovalState)
        builder.add_node("approval", wait_for_decision)
        builder.add_edge(START, "approval")
        builder.add_edge("approval", END)
        graph = builder.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": checkpoint_thread_id}}
        graph_input = (
            Command(resume={"approved": resume_value})
            if resume_value is not None
            else {"payload": payload, "approved": False}
        )
        result = await graph.ainvoke(graph_input, config=config)
        interrupted = _interrupt_payload(result)
        if interrupted is not None:
            interrupted["checkpoint_thread_id"] = checkpoint_thread_id
            return interrupted, None
        approved = bool(result.get("approved"))
        await checkpointer.adelete_thread(checkpoint_thread_id)
        return None, approved


async def run_agent(
    db: Session,
    project_id: int,
    project_name: str,
    question: str,
    history: list[tuple[str, str]],
    model_config: RuntimeModelConfig,
    document_id: int | None = None,
    *,
    checkpoint_thread_id: str = "",
    resume_value: bool | None = None,
    summary: str = "",
    workflow_state: dict | None = None,
    runtime=None,
) -> AsyncIterator[dict]:
    """执行一轮问答，异步产出事件流。history 为 [(role, content)] 旧→新。

    document_id 为用户本轮上传的需求文档 ID（可选），文档上下文已由 API 层
    拼入 question，这里仅供 Mock 剧本分支使用。
    """
    checkpoint_thread_id = checkpoint_thread_id or f"agent:{project_id}:{uuid.uuid4().hex}"
    if model_config.use_mock_llm:
        payload = _mock_approval_payload(db, project_id, question)
        if payload is not None:
            interrupted, approved = await _mock_approval_checkpoint(
                payload,
                checkpoint_thread_id,
                resume_value,
            )
            if interrupted is not None:
                yield {"type": "approval_required", "approval": interrupted}
                return
            if not approved:
                note = "已取消，本次操作没有执行。"
                yield {"type": "token", "content": note}
                yield {"type": "done", "content": note, "tool_calls": []}
                return
        async for event in _run_mock(
            db,
            project_id,
            question,
            model_config,
            document_id,
            runtime=runtime,
        ):
            yield event
        return

    parent_run_id = runtime.context.run_id if runtime is not None else None
    tools = build_agent_tools(
        db,
        project_id,
        model_config,
        parent_run_id=parent_run_id,
    )
    model = create_chat_model(model_config, "generation")
    llm = model.bind_tools(tools)

    messages = [
        SystemMessage(SYSTEM_PROMPT.format(project_name=project_name)),
    ]
    if summary:
        messages.append(SystemMessage(f"以下是更早对话的滚动摘要，仅作长期记忆参考：\n{summary}"))
    if workflow_state:
        messages.append(SystemMessage(
            "当前可恢复的业务流程状态（以工具实时返回为准）：\n"
            f"{json.dumps(workflow_state, ensure_ascii=False)}"
        ))
    messages.extend([*_history_messages(history), HumanMessage(question)])

    answer_parts: list[str] = []
    tool_calls: list[dict] = []
    interrupted = False
    try:
        async with checkpoint_context() as checkpointer:
            graph = _build_agent_graph(llm, tools, checkpointer, runtime=runtime)
            config = {
                "configurable": {"thread_id": checkpoint_thread_id},
                "recursion_limit": MAX_GRAPH_STEPS,
            }
            graph_input = (
                Command(resume={"approved": resume_value})
                if resume_value is not None
                else {
                    "messages": messages,
                    "approved_actions": [],
                    "approval_decision": "",
                }
            )
            async for event in graph.astream_events(
                graph_input,
                config=config,
                version="v2",
            ):
                kind = event["event"]
                if kind == "on_chat_model_stream" and _is_agent_model_stream(event):
                    text = _message_text(event["data"]["chunk"].content)
                    if text:
                        answer_parts.append(text)
                        yield {"type": "token", "content": text}
                elif kind == "on_tool_start":
                    yield {
                        "type": "tool_start",
                        "name": event["name"],
                        "input": event["data"].get("input") or {},
                    }
                elif kind == "on_tool_end":
                    output_text = _tool_output_text(event["data"].get("output"))
                    call = {"name": event["name"]}
                    task_id = _extract_task_id(event["name"], output_text)
                    if task_id is not None:
                        call["task_id"] = task_id
                    tool_calls.append(call)
                    yield {"type": "tool_end", "name": event["name"], "output": output_text}
                elif kind == "on_chain_stream" and event.get("name") == "LangGraph":
                    chunk = event["data"].get("chunk")
                    payload = _interrupt_payload(chunk)
                    if payload is not None:
                        interrupted = True
                        payload["checkpoint_thread_id"] = checkpoint_thread_id
                        yield {"type": "approval_required", "approval": payload}
            if not interrupted:
                await checkpointer.adelete_thread(checkpoint_thread_id)
            if resume_value is False and not answer_parts:
                note = "已取消，本次操作没有执行。如需继续，请重新发起操作。"
                answer_parts.append(note)
                yield {"type": "token", "content": note}
    except GraphRecursionError:
        note = "本次查询涉及的步骤过多，我先停在这里。请把问题拆小一点再问我，比如按模块或按任务分别询问。"
        answer_parts.append(note)
        yield {"type": "token", "content": note}
    except (BudgetExhausted, RuntimeCancelled):
        raise
    except LLMCallError:
        raise
    except SQLAlchemyError as exc:
        logger.exception("Agent 数据库工具执行失败")
        raise AgentRuntimeError("测试助手读取项目数据失败，请稍后重试") from exc
    except AgentRuntimeError:
        raise
    except Exception as exc:
        logger.exception("Agent 工具或工作流执行失败")
        raise AgentRuntimeError(f"测试助手执行失败：{exc}") from exc
    finally:
        http_client = getattr(model, "http_async_client", None)
        if http_client is not None:
            await http_client.aclose()

    if interrupted:
        return
    yield {"type": "done", "content": "".join(answer_parts), "tool_calls": tool_calls}


async def _run_mock(
    db: Session,
    project_id: int,
    question: str,
    model_config: RuntimeModelConfig,
    document_id: int | None = None,
    *,
    runtime=None,
) -> AsyncIterator[dict]:
    """Mock 剧本：离线开发与自动化测试用。

    - 带 document_id：走真实解析链路（底层 Skill 支持 Mock），展示功能点并等待确认
    - 问题含确认/生成意图：确认最近解析的文档并启动真实生成工作流（Mock 模式秒级完成）
    - 问题含采纳意图：采纳最近完成任务的全部待评审用例
    - 其他：检索知识库 + 统计用例数的固定剧本
    """
    from app.agent import tools as agent_tools
    from app.models.generation import GeneratedCaseDraft, GenerationTask
    from app.models.requirement import RequirementDocument
    from app.services.generation_service import (
        adopt_drafts,
        build_strategy_config,
        confirm_requirements,
        reject_drafts,
        structure_requirements,
    )

    async def governed_tool(name, operation):
        if runtime is not None:
            return await runtime.run_tool(name, operation)
        return await operation()

    if document_id is not None:
        yield {"type": "tool_start", "name": "parse_requirement_document", "input": {"document_id": document_id}}

        async def parse_document():
            doc = (
                db.query(RequirementDocument)
                .filter(
                    RequirementDocument.id == document_id,
                    RequirementDocument.project_id == project_id,
                )
                .first()
            )
            items = []
            if doc and (doc.raw_content or "").strip():
                try:
                    items = await structure_requirements(db, doc)
                except (BudgetExhausted, RuntimeCancelled):
                    raise
                except Exception:
                    items = []
            elif doc:
                items = sorted(doc.items, key=lambda x: x.sort_order)
            return doc, items

        doc, items = await governed_tool("parse_requirement_document", parse_document)
        yield {"type": "tool_end", "name": "parse_requirement_document", "output": ""}

        if not doc:
            note = "（Mock 模式）没有找到这份需求文档，请重新上传。"
            yield {"type": "token", "content": note}
            yield {"type": "done", "content": note, "tool_calls": [{"name": "parse_requirement_document"}]}
            return

        lines = [f"（Mock 模式）已解析《{doc.title}》，共 {len(items)} 个功能点："]
        for it in items[:10]:
            lines.append(f"- [{it.priority}] {it.module} / {it.feature}")
        lines.append("请确认后回复「确认生成」，可指定策略（完整用例 / 快速冒烟）。")
        content = "\n".join(lines)
        for piece in lines:
            yield {"type": "token", "content": piece + "\n"}
        yield {"type": "done", "content": content + "\n", "tool_calls": [{"name": "parse_requirement_document"}]}
        return

    if "采纳" in question or "驳回" in question:
        db.expire_all()
        task = (
            db.query(GenerationTask)
            .filter(
                GenerationTask.project_id == project_id,
                GenerationTask.status == "completed",
                GenerationTask.is_eval == False,  # noqa: E712
            )
            .order_by(GenerationTask.created_at.desc())
            .first()
        )
        if task:
            pending_ids = [
                d.id
                for d in db.query(GeneratedCaseDraft)
                .filter(
                    GeneratedCaseDraft.task_id == task.id,
                    GeneratedCaseDraft.review_status.notin_(["adopted", "rejected"]),
                )
                .all()
            ]
            action = "reject" if "驳回" in question else "adopt"
            yield {
                "type": "tool_start",
                "name": "review_generated_drafts",
                "input": {"task_id": task.id, "action": action},
            }

            async def review_drafts():
                if action == "adopt":
                    return len(adopt_drafts(db, task.id, pending_ids)) if pending_ids else 0
                reject_drafts(db, task.id, pending_ids)
                return len(pending_ids)

            changed = await governed_tool("review_generated_drafts", review_drafts)
            yield {"type": "tool_end", "name": "review_generated_drafts", "output": ""}
            verb = "采纳并入库" if action == "adopt" else "驳回"
            note = f"（Mock 模式）已{verb}生成任务 #{task.id} 的 {changed} 条候选用例。"
            yield {"type": "token", "content": note}
            yield {
                "type": "done",
                "content": note,
                "tool_calls": [{"name": "review_generated_drafts"}],
            }
            return

    if any(word in question for word in ("确认", "生成", "开始")):
        doc = (
            db.query(RequirementDocument)
            .filter(
                RequirementDocument.project_id == project_id,
                RequirementDocument.status.in_(["structured", "confirmed"]),
                RequirementDocument.is_eval == False,  # noqa: E712
            )
            .order_by(RequirementDocument.created_at.desc())
            .first()
        )
        if doc:
            strategy = "quick" if ("冒烟" in question or "quick" in question.lower()) else "full"
            yield {"type": "tool_start", "name": "confirm_features", "input": {"document_id": doc.id}}

            async def confirm_features_tool():
                return confirm_requirements(db, doc.id, None)

            await governed_tool("confirm_features", confirm_features_tool)
            yield {"type": "tool_end", "name": "confirm_features", "output": ""}

            yield {
                "type": "tool_start",
                "name": "start_generation",
                "input": {"document_id": doc.id, "strategy": strategy},
            }
            async def start_generation_tool():
                task = GenerationTask(
                    project_id=project_id,
                    document_id=doc.id,
                    strategy=strategy,
                    strategy_config=json.dumps(
                        build_strategy_config(strategy=strategy, model_config=model_config),
                        ensure_ascii=False,
                    ),
                    status="pending",
                )
                db.add(task)
                db.commit()
                db.refresh(task)
                output_data = {"task_id": task.id, "status": "pending"}
                if runtime is not None:
                    from dataclasses import asdict
                    from app.agent_runtime.service import create_case_writer_run

                    child = create_case_writer_run(
                        db,
                        task,
                        model_snapshot=asdict(model_config),
                        parent_run_id=runtime.context.run_id,
                    )
                    output_data["agent_run_id"] = child.id
                else:
                    agent_tools.start_generation_background(task.id)
                return task, output_data

            task, output_data = await governed_tool(
                "start_generation", start_generation_tool
            )
            output = json.dumps(output_data, ensure_ascii=False)
            yield {"type": "tool_end", "name": "start_generation", "output": output}

            note = (
                f"（Mock 模式）已确认《{doc.title}》的功能点并启动生成任务 #{task.id}（策略：{strategy}），"
                "可以在对话里追问进度，或到「AI 生成」页查看与评审。"
            )
            yield {"type": "token", "content": note}
            yield {
                "type": "done",
                "content": note,
                "tool_calls": [
                    {"name": "confirm_features"},
                    {"name": "start_generation", "task_id": task.id},
                ],
            }
            return

    yield {"type": "tool_start", "name": "search_knowledge", "input": {"query": question}}

    async def search_project():
        try:
            hits = await knowledge_service.retrieve(db, project_id, question, top_k=3)
        except (BudgetExhausted, RuntimeCancelled):
            raise
        except Exception:
            hits = []
        case_count = db.query(TestCase).filter(TestCase.project_id == project_id).count()
        return hits, case_count

    hits, case_count = await governed_tool("search_knowledge", search_project)
    yield {"type": "tool_end", "name": "search_knowledge"}
    lines = [
        f"（Mock 模式）我检索了项目知识库，命中 {len(hits)} 条相关内容；当前项目共有 {case_count} 条测试用例。",
    ]
    if hits:
        top = hits[0]
        source = f"《{top['title']}》" + (f" · {top['heading']}" if top["heading"] else "")
        lines.append(f"最相关的知识来自 {source}：{top['content'][:120]}")
    lines.append("配置真实生成模型后，我可以基于这些数据直接回答你的问题。")

    for piece in lines:
        yield {"type": "token", "content": piece + "\n"}
    yield {
        "type": "done",
        "content": "\n".join(lines) + "\n",
        "tool_calls": [{"name": "search_knowledge"}],
    }
