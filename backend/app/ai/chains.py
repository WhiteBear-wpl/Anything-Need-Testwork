from typing import TypeVar

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from app.ai.model_factory import ModelPurpose, create_chat_model, normalize_chat_error
from app.ai.schemas import (
    CaseJudgementBatch,
    CoverageDecision,
    EvaluationCaseJudgementBatch,
    GeneratedCaseBatch,
    RequirementFeatureBatch,
    TestProposal,
)
from app.services.llm import LLMCallError, record_token_usage
from app.services.settings_service import RuntimeModelConfig
from app.agent_runtime.harness import get_active_runtime_harness


SchemaT = TypeVar("SchemaT", bound=BaseModel)


def _message_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content or "")


async def invoke_structured(
    system_prompt: str,
    user_prompt: str,
    schema: type[SchemaT],
    config: RuntimeModelConfig,
    *,
    purpose: ModelPurpose = "generation",
) -> SchemaT:
    """使用 LangChain Prompt + ChatModel + Pydantic Parser 获得结构化结果。

    这里采用供应商兼容性更高的 PydanticOutputParser，而不是强制所有
    OpenAI-compatible 服务都支持 tool calling/json_schema。
    """
    parser = PydanticOutputParser(pydantic_object=schema)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "{system_prompt}"),
            (
                "human",
                "{user_prompt}\n\n请严格遵循以下结构化输出规范，只输出 JSON：\n{format_instructions}",
            ),
        ]
    )
    model = create_chat_model(config, purpose)
    messages = prompt.format_messages(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        format_instructions=parser.get_format_instructions(),
    )
    try:
        async def invoke_model():
            return await model.ainvoke(messages)

        runtime = get_active_runtime_harness()
        response = (
            await runtime.call_llm(
                f"structured_{purpose}",
                "structured_output",
                invoke_model,
                input_value=messages,
                max_output_tokens=8192,
            )
            if runtime is not None
            else await invoke_model()
        )
        record_token_usage(getattr(response, "usage_metadata", None))
        return parser.parse(_message_text(response.content))
    except Exception as exc:
        # Pydantic/JSON 错误保留原异常，交给 LangGraph 判断是否重试；
        # 网络、鉴权等模型异常继续转成项目原有的中文提示。
        if exc.__class__.__module__.startswith(("pydantic", "json")) or "OutputParser" in exc.__class__.__name__:
            raise
        if isinstance(exc, LLMCallError):
            raise
        raise normalize_chat_error(exc, purpose) from exc
    finally:
        # create_chat_model 为每次调用创建独立 AsyncClient；调用完成后及时释放连接。
        http_client = getattr(model, "http_async_client", None)
        if http_client is not None:
            await http_client.aclose()


async def parse_requirement_items(
    system_prompt: str,
    raw_content: str,
    config: RuntimeModelConfig,
) -> list[dict]:
    result = await invoke_structured(
        system_prompt,
        f"请分析以下需求文档并提取功能点：\n\n{raw_content}",
        RequirementFeatureBatch,
        config,
    )
    return [item.model_dump() for item in result.root]


async def generate_cases(
    system_prompt: str,
    user_prompt: str,
    skill_name: str,
    config: RuntimeModelConfig,
) -> list[dict]:
    result = await invoke_structured(
        system_prompt,
        user_prompt,
        GeneratedCaseBatch,
        config,
    )
    cases = [item.model_dump() for item in result.root]
    for case in cases:
        case["skill_name"] = skill_name
    return cases


async def generate_test_proposal(
    system_prompt: str,
    raw_content: str,
    config: RuntimeModelConfig,
) -> dict:
    result = await invoke_structured(
        system_prompt,
        f"请基于以下需求文档，输出测试范围与风险提案：\n\n{raw_content}",
        TestProposal,
        config,
    )
    return result.model_dump()


async def judge_cases(
    system_prompt: str,
    user_prompt: str,
    config: RuntimeModelConfig,
) -> list[dict]:
    result = await invoke_structured(
        system_prompt,
        user_prompt,
        CaseJudgementBatch,
        config,
        purpose="evaluation",
    )
    return [item.model_dump() for item in result.judgements]


async def judge_evaluation_cases(
    system_prompt: str,
    user_prompt: str,
    config: RuntimeModelConfig,
) -> list[dict]:
    result = await invoke_structured(
        system_prompt,
        user_prompt,
        EvaluationCaseJudgementBatch,
        config,
        purpose="evaluation",
    )
    return [item.model_dump() for item in result.judgements]


async def judge_checkpoint_coverage(
    system_prompt: str,
    user_prompt: str,
    config: RuntimeModelConfig,
) -> list[int]:
    result = await invoke_structured(
        system_prompt,
        user_prompt,
        CoverageDecision,
        config,
        purpose="evaluation",
    )
    return result.covered_indexes
