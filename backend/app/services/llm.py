import contextvars

import httpx

from app.services.model_endpoint_security import ModelEndpointError, validate_model_base_url
from app.services.settings_service import RuntimeModelConfig

# 按异步上下文累计 token 用量：LangGraph 生成工作流开始时创建计数器，
# 期间所有 LLM 调用（生成 + 专项 + Judge）都会累加到同一个计数器。
_token_counter: contextvars.ContextVar[dict | None] = contextvars.ContextVar("token_counter", default=None)


def start_token_tracking() -> dict:
    counter = {"prompt_tokens": 0, "completion_tokens": 0}
    _token_counter.set(counter)
    return counter


def total_tokens(counter: dict) -> int:
    return counter.get("prompt_tokens", 0) + counter.get("completion_tokens", 0)


def _record_usage(usage: dict | None) -> None:
    counter = _token_counter.get()
    if counter is None or not isinstance(usage, dict):
        return
    counter["prompt_tokens"] += usage.get("prompt_tokens", 0) or 0
    counter["completion_tokens"] += usage.get("completion_tokens", 0) or 0


def record_token_usage(usage: dict | None) -> None:
    """记录 LangChain / OpenAI 两种口径的 token 用量。

    LangChain ``AIMessage.usage_metadata`` 使用 input/output_tokens，原始
    OpenAI 兼容响应使用 prompt/completion_tokens。统一写入现有任务计数器，
    保持生成记录与离线评测中的 tokens_used 口径不变。
    """
    if not isinstance(usage, dict):
        return
    normalized = {
        "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0,
        "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0,
    }
    _record_usage(normalized)


def _resolve_chat_settings(config: RuntimeModelConfig, use_eval_model: bool) -> tuple[str, str, str]:
    """返回 (base_url, api_key, model)。评测三项全部留空时整体复用生成配置。"""
    if use_eval_model:
        eval_config = (config.eval_llm_base_url, config.eval_llm_api_key, config.eval_llm_model)
        if any(eval_config):
            return eval_config
    return config.llm_base_url, config.llm_api_key, config.llm_model


class LLMCallError(RuntimeError):
    """LLM 调用失败，message 为面向用户的中文提示。"""


def _friendly_error(exc: Exception, kind: str) -> LLMCallError:
    code = None
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
    else:
        code = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        if code is None and response is not None:
            code = getattr(response, "status_code", None)
    if code is not None:
        if code in (401, 403):
            return LLMCallError(f"{kind}的 API Key 无效或已过期，请到「设置」页更新后重试")
        if code == 429:
            return LLMCallError(f"{kind}调用触发限流（429），请稍后重试")
        if code == 404:
            return LLMCallError(f"{kind}的接口地址或模型名有误（404），请检查「设置」页配置")
        return LLMCallError(f"{kind}调用失败（HTTP {code}），请检查「设置」页配置")
    return LLMCallError(f"无法连接{kind}服务，请检查接口地址与网络：{exc}")


async def rerank_documents(
    query: str,
    documents: list[str],
    config: RuntimeModelConfig,
    top_n: int | None = None,
) -> list[tuple[int, float]]:
    """调用 Rerank 接口对候选文档精排，返回 [(原始下标, relevance_score)]，按分数降序。

    请求体为 Jina / SiliconFlow / Cohere 兼容格式：{model, query, documents, top_n}。
    未配置 Rerank 模型时抛出 RuntimeError，调用方应提前用 config.rerank_configured 判断。
    """
    if not config.rerank_configured:
        raise RuntimeError("未配置 Rerank 模型")
    base_url = validate_model_base_url(config.rerank_base_url)

    payload: dict = {
        "model": config.rerank_model,
        "query": query,
        "documents": documents,
        "return_documents": False,
    }
    if top_n is not None:
        payload["top_n"] = top_n

    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/rerank",
                headers={"Authorization": f"Bearer {config.rerank_api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        raise _friendly_error(exc, "Rerank 模型") from exc

    results = data.get("results") or []
    ranked = [
        (int(item["index"]), float(item.get("relevance_score", 0.0)))
        for item in results
        if isinstance(item, dict) and "index" in item
    ]
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    return ranked


async def test_model_connection(config: RuntimeModelConfig, target: str) -> dict:
    """对指定模型配置发起一次最小化调用，验证地址、模型与 Key 是否可用。

    target: generation | eval | embedding | rerank。返回 {ok, message, model, base_url}。
    """
    if target == "embedding":
        base_url = config.embedding_base_url
        api_key = config.embedding_api_key
        model = config.embedding_model
        kind = "Embedding 模型"
    elif target == "rerank":
        if not any((config.rerank_base_url, config.rerank_api_key, config.rerank_model)):
            return {
                "ok": True,
                "message": "Rerank 模型未配置，知识检索将只做混合检索融合排序",
                "model": "",
                "base_url": "",
            }
        base_url = config.rerank_base_url
        api_key = config.rerank_api_key
        model = config.rerank_model
        kind = "Rerank 模型"
    else:
        use_eval = target == "eval"
        kind = "评测模型" if use_eval else "生成模型"
        if use_eval and not any(
            (config.eval_llm_base_url, config.eval_llm_api_key, config.eval_llm_model)
        ):
            return {
                "ok": True,
                "message": "评测模型未单独配置，将复用生成模型",
                "model": config.llm_model,
                "base_url": config.llm_base_url,
            }
        base_url, api_key, model = _resolve_chat_settings(config, use_eval)

    if target == "generation" and config.use_mock_llm:
        return {
            "ok": True,
            "message": "当前为 Mock 模式，生成不会调用真实接口",
            "model": model or "",
            "base_url": base_url or "",
        }

    if not (base_url and api_key and model):
        return {
            "ok": False,
            "message": f"{kind}的 API 地址、模型和 Key 尚未配置完整",
            "model": model or "",
            "base_url": base_url or "",
        }

    try:
        base_url = validate_model_base_url(base_url)
    except ModelEndpointError as exc:
        return {"ok": False, "message": str(exc), "model": model, "base_url": base_url}

    if target == "embedding":
        from app.ai.embedding_factory import embedding_context

        try:
            async with embedding_context(config) as embeddings:
                vector = await embeddings.aembed_query("连通性测试")
            if not vector:
                raise RuntimeError("Embedding 模型返回了空向量")
        except Exception as exc:
            return {
                "ok": False,
                "message": str(_friendly_error(exc, kind)),
                "model": model,
                "base_url": base_url,
            }
        return {"ok": True, "message": "连接成功", "model": model, "base_url": base_url}
    if target == "rerank":
        path = "/rerank"
        payload = {
            "model": model,
            "query": "连通性测试",
            "documents": ["连通性测试文档"],
            "top_n": 1,
            "return_documents": False,
        }
    else:
        path = "/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 4,
            "temperature": 0,
        }

    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}{path}",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            response.raise_for_status()
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        return {
            "ok": False,
            "message": str(_friendly_error(exc, kind)),
            "model": model,
            "base_url": base_url,
        }

    return {"ok": True, "message": "连接成功", "model": model, "base_url": base_url}
