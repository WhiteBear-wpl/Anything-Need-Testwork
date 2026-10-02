from typing import Literal

import httpx
from langchain_openai import ChatOpenAI

from app.services.llm import LLMCallError
from app.services.model_endpoint_security import ModelEndpointError, validate_model_base_url
from app.services.settings_service import RuntimeModelConfig


ModelPurpose = Literal["generation", "evaluation"]


def _resolve_chat_config(
    config: RuntimeModelConfig,
    purpose: ModelPurpose,
) -> tuple[str, str, str]:
    if purpose == "evaluation":
        eval_config = (
            config.eval_llm_base_url,
            config.eval_llm_api_key,
            config.eval_llm_model,
        )
        if any(eval_config):
            return eval_config
    return config.llm_base_url, config.llm_api_key, config.llm_model


def create_chat_model(
    config: RuntimeModelConfig,
    purpose: ModelPurpose = "generation",
    *,
    temperature: float = 0.3,
) -> ChatOpenAI:
    """基于现有项目配置创建 LangChain ChatModel。

    继续支持用户在设置页填写的 OpenAI-compatible base_url，不改变现有
    生成模型与评测模型的回退规则。
    """
    kind = "评测模型" if purpose == "evaluation" else "生成模型"
    base_url, api_key, model = _resolve_chat_config(config, purpose)
    if not (base_url and api_key and model):
        raise LLMCallError(f"未配置{kind}，请先到「设置」页填写 API 地址、模型和 Key")
    try:
        base_url = validate_model_base_url(base_url)
    except ModelEndpointError as exc:
        raise LLMCallError(str(exc)) from exc

    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        timeout=120.0,
        max_retries=0,
        http_socket_options=(),
        # 与项目原有 httpx 调用保持一致：模型请求不继承本机代理，
        # 避免设置页直连测试成功、实际 LangChain 调用却受代理状态影响。
        http_async_client=httpx.AsyncClient(timeout=120.0, trust_env=False),
    )


def normalize_chat_error(exc: Exception, purpose: ModelPurpose) -> LLMCallError:
    """把 LangChain/OpenAI SDK 异常转换成项目现有的中文错误。"""
    if isinstance(exc, LLMCallError):
        return exc
    kind = "评测模型" if purpose == "evaluation" else "生成模型"
    code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if code is None and response is not None:
        code = getattr(response, "status_code", None)
    if code in (401, 403):
        return LLMCallError(f"{kind}的 API Key 无效或已过期，请到「设置」页更新后重试")
    if code == 429:
        return LLMCallError(f"{kind}调用触发限流（429），请稍后重试")
    if code == 404:
        return LLMCallError(f"{kind}的接口地址或模型名有误（404），请检查「设置」页配置")
    if code:
        return LLMCallError(f"{kind}调用失败（HTTP {code}），请检查「设置」页配置")
    return LLMCallError(f"无法连接{kind}服务，请检查接口地址与网络：{exc}")
