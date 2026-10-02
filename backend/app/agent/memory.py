"""测试助手上下文记忆：原始消息永久保留，模型上下文按 Token 窗口 + 滚动摘要组装。"""

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent_runtime.budget import estimate_tokens
from app.agent_runtime.contracts import BudgetExhausted, RuntimeCancelled
from app.ai.model_factory import create_chat_model
from app.database import SessionLocal
from app.models.agent import AgentMessage, AgentThread
from app.services.settings_service import RuntimeModelConfig


CONTEXT_TOKEN_BUDGET = 6000
CONTEXT_MESSAGE_LIMIT = 50
# 摘要保留 40 条原文，和 50 条上下文窗口形成 10 条重叠缓冲；
# 每累计 10 条再压缩一次，不会在两次摘要之间出现“既不在窗口也不在摘要”的空档。
SUMMARY_KEEP_RECENT = 40
SUMMARY_TRIGGER_COUNT = 10
SUMMARY_BATCH_LIMIT = 40
SUMMARY_MAX_CHARS = 1600


def select_context(
    history: list[tuple[str, str]],
    token_budget: int = CONTEXT_TOKEN_BUDGET,
    message_limit: int = CONTEXT_MESSAGE_LIMIT,
) -> list[tuple[str, str]]:
    """从最新消息向前装入上下文，原始历史不删除。"""
    selected: list[tuple[str, str]] = []
    used = 0
    for role, content in reversed(history):
        if not content:
            continue
        cost = estimate_tokens(content) + 6
        if selected and (used + cost > token_budget or len(selected) >= message_limit):
            break
        # 单条超长消息仍保留末尾，避免上下文完全丢失。
        if not selected and cost > token_budget:
            content = content[-token_budget * 2 :]
            cost = estimate_tokens(content) + 6
        selected.append((role, content))
        used += cost
    return list(reversed(selected))


def _plain_summary(rows: list[AgentMessage], previous: str) -> str:
    """Mock/模型失败时的确定性摘要，保证记忆链路仍可工作。"""
    parts = [previous.strip()] if previous.strip() else []
    for row in rows:
        label = "用户" if row.role == "user" else "助手"
        content = " ".join((row.content or "").split())
        if content:
            parts.append(f"{label}：{content[:240]}")
    return "\n".join(parts)[-SUMMARY_MAX_CHARS:]


def _message_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else str(block.get("text", ""))
            for block in content
            if isinstance(block, (str, dict))
        )
    return str(content or "")


async def maybe_update_summary(
    thread_id: int,
    model_config: RuntimeModelConfig,
    force: bool = False,
    runtime=None,
) -> bool:
    """把已离开短期窗口的消息折叠进摘要；异常只降级，不影响主对话。"""
    db = SessionLocal()
    model = None
    try:
        thread = db.get(AgentThread, thread_id)
        if not thread:
            return False
        rows = (
            db.query(AgentMessage)
            .filter(AgentMessage.thread_id == thread_id)
            .order_by(AgentMessage.id.asc())
            .all()
        )
        # 除固定消息数缓冲外，也识别 Token 预算已经挤出的旧消息，及时写入摘要。
        used_tokens = 0
        context_start = len(rows)
        selected_count = 0
        for index in range(len(rows) - 1, -1, -1):
            content = rows[index].content or ""
            if not content:
                continue
            cost = estimate_tokens(content) + 6
            if selected_count and (
                used_tokens + cost > CONTEXT_TOKEN_BUDGET
                or selected_count >= CONTEXT_MESSAGE_LIMIT
            ):
                break
            context_start = index
            selected_count += 1
            used_tokens += cost
        cutoff = max(0, len(rows) - SUMMARY_KEEP_RECENT, context_start)
        eligible = [
            row
            for row in rows[:cutoff]
            if row.id > (thread.summary_until_message_id or 0)
        ][:SUMMARY_BATCH_LIMIT]
        token_window_requires_summary = any(
            row.id > (thread.summary_until_message_id or 0)
            for row in rows[:context_start]
        )
        if not eligible or (
            not force
            and not token_window_requires_summary
            and len(eligible) < SUMMARY_TRIGGER_COUNT
        ):
            return False

        summary = ""
        if not model_config.use_mock_llm:
            transcript = "\n".join(
                f"{'用户' if row.role == 'user' else '助手'}：{row.content}" for row in eligible
            )
            model = create_chat_model(model_config, "generation", temperature=0.1)
            messages = [
                SystemMessage(
                    "你负责维护测试项目助手的长期记忆。合并旧摘要和新增对话，"
                    "只保留稳定事实：用户目标、已确认决定、需求文档/生成任务等业务对象、"
                    "未完成事项。不要保留会变化的统计数字，不要编造。输出简洁中文纯文本，"
                    f"不超过 {SUMMARY_MAX_CHARS} 字。"
                ),
                HumanMessage(
                    f"旧摘要：\n{thread.summary or '（无）'}\n\n新增对话：\n{transcript}"
                ),
            ]

            async def invoke_model():
                return await model.ainvoke(messages)

            response = (
                await runtime.call_llm(
                    "assistant_memory",
                    "assistant_memory",
                    invoke_model,
                    input_value=messages,
                    max_output_tokens=2048,
                )
                if runtime is not None
                else await invoke_model()
            )
            summary = _message_text(response.content).strip()[:SUMMARY_MAX_CHARS]

        if not summary:
            summary = _plain_summary(eligible, thread.summary or "")
        thread.summary = summary
        thread.summary_until_message_id = eligible[-1].id
        db.commit()
        return True
    except (BudgetExhausted, RuntimeCancelled):
        db.rollback()
        raise
    except Exception:
        db.rollback()
        return False
    finally:
        if model is not None:
            http_client = getattr(model, "http_async_client", None)
            if http_client is not None:
                await http_client.aclose()
        db.close()
