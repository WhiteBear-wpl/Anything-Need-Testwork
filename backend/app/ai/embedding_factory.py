"""LangChain Embeddings 适配层。"""

import hashlib
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

import httpx
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from app.services.model_endpoint_security import validate_model_base_url
from app.services.settings_service import RuntimeModelConfig


EMBEDDING_BATCH_SIZE = 16
MOCK_EMBEDDING_DIMENSIONS = 64


def embedding_configured(config: RuntimeModelConfig) -> bool:
    return bool(config.embedding_base_url and config.embedding_api_key and config.embedding_model)


def uses_mock_embeddings(config: RuntimeModelConfig) -> bool:
    """Mock 生成模式且没有完整 Embedding 配置时，使用本地确定性向量。"""
    return config.use_mock_llm and not embedding_configured(config)


def normalize_embedding_error(exc: Exception) -> Exception:
    """把 OpenAI/httpx 调用错误转换为项目原有的可读中文错误。"""
    module = exc.__class__.__module__
    if isinstance(exc, (httpx.HTTPStatusError, httpx.RequestError)) or module.startswith(
        ("openai", "httpcore")
    ):
        # 延迟导入，避免 llm 的设置页 Embedding 连通性测试形成模块循环。
        from app.services.llm import _friendly_error

        return _friendly_error(exc, "Embedding 模型")
    return exc


class DeterministicMockEmbeddings(Embeddings):
    """供本地开发和自动化测试使用的确定性 64 维字符 trigram 向量。"""

    @staticmethod
    def _embed(text: str) -> list[float]:
        vector = [0.0] * MOCK_EMBEDDING_DIMENSIONS
        for index in range(len(text) - 2):
            trigram = text[index:index + 3]
            bucket = int(hashlib.md5(trigram.encode()).hexdigest(), 16) % MOCK_EMBEDDING_DIMENSIONS
            vector[bucket] += 1.0
        norm = sum(value * value for value in vector) ** 0.5 or 1.0
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)


@dataclass
class EmbeddingResources:
    embeddings: Embeddings
    http_client: httpx.Client | None = None
    http_async_client: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self.http_async_client is not None:
            await self.http_async_client.aclose()
        if self.http_client is not None:
            self.http_client.close()


def create_embedding_resources(config: RuntimeModelConfig) -> EmbeddingResources:
    """基于项目运行配置创建一次 LangChain Embeddings 调用所需资源。"""
    if uses_mock_embeddings(config):
        return EmbeddingResources(embeddings=DeterministicMockEmbeddings())
    if not embedding_configured(config):
        raise RuntimeError("未配置 Embedding 模型，请先在设置中填写 Embedding API 地址、模型和 Key")

    base_url = validate_model_base_url(config.embedding_base_url)
    http_client = httpx.Client(timeout=60.0, trust_env=False)
    http_async_client = httpx.AsyncClient(timeout=60.0, trust_env=False)
    embeddings = OpenAIEmbeddings(
        api_key=config.embedding_api_key,
        base_url=base_url,
        model=config.embedding_model,
        chunk_size=EMBEDDING_BATCH_SIZE,
        check_embedding_ctx_length=False,
        request_timeout=60.0,
        max_retries=0,
        http_client=http_client,
        http_async_client=http_async_client,
    )
    return EmbeddingResources(
        embeddings=embeddings,
        http_client=http_client,
        http_async_client=http_async_client,
    )


@asynccontextmanager
async def embedding_context(config: RuntimeModelConfig) -> AsyncIterator[Embeddings]:
    resources = create_embedding_resources(config)
    try:
        yield resources.embeddings
    finally:
        await resources.aclose()
