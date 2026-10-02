import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.embedding_factory import (
    DeterministicMockEmbeddings,
    create_embedding_resources,
)
from app.ai.vector_store_factory import VECTOR_COLLECTION_VERSION, vector_collection_name
from app.services.settings_service import RuntimeModelConfig


class EmbeddingFactoryTests(unittest.TestCase):
    def test_mock_embeddings_are_deterministic_and_normalized(self):
        embeddings = DeterministicMockEmbeddings()
        first = embeddings.embed_query("退款接口错误码 ERR_4003")
        second = embeddings.embed_documents(["退款接口错误码 ERR_4003"])[0]

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertAlmostEqual(sum(value * value for value in first), 1.0)

    @patch("app.ai.embedding_factory.OpenAIEmbeddings")
    @patch("app.ai.embedding_factory.httpx.AsyncClient")
    @patch("app.ai.embedding_factory.httpx.Client")
    def test_openai_embeddings_disable_proxy_and_tokenization(
        self,
        client_cls,
        async_client_cls,
        embeddings_cls,
    ):
        http_client = MagicMock()
        http_async_client = MagicMock()
        http_async_client.aclose = AsyncMock()
        client_cls.return_value = http_client
        async_client_cls.return_value = http_async_client
        embeddings_cls.return_value = MagicMock()
        config = RuntimeModelConfig(
            embedding_api_key="test-key",
            embedding_base_url="https://api.openai.com/v1",
            embedding_model="text-embedding-test",
        )

        resources = create_embedding_resources(config)
        asyncio.run(resources.aclose())

        client_cls.assert_called_once_with(timeout=60.0, trust_env=False)
        async_client_cls.assert_called_once_with(timeout=60.0, trust_env=False)
        kwargs = embeddings_cls.call_args.kwargs
        self.assertFalse(kwargs["check_embedding_ctx_length"])
        self.assertEqual(kwargs["chunk_size"], 16)
        self.assertEqual(kwargs["max_retries"], 0)
        self.assertIs(kwargs["http_client"], http_client)
        self.assertIs(kwargs["http_async_client"], http_async_client)
        http_client.close.assert_called_once_with()
        http_async_client.aclose.assert_awaited_once_with()

    def test_collection_identity_excludes_api_key(self):
        first = RuntimeModelConfig(
            embedding_api_key="secret-a",
            embedding_base_url="https://api.openai.com/v1",
            embedding_model="embedding-v1",
        )
        second = RuntimeModelConfig(
            embedding_api_key="secret-b",
            embedding_base_url="https://api.openai.com/v1",
            embedding_model="embedding-v1",
        )
        changed_model = RuntimeModelConfig(
            embedding_api_key="secret-a",
            embedding_base_url="https://api.openai.com/v1",
            embedding_model="embedding-v2",
        )

        name = vector_collection_name(7, first)
        self.assertEqual(name, vector_collection_name(7, second))
        self.assertNotEqual(name, vector_collection_name(7, changed_model))
        self.assertTrue(name.startswith(f"{VECTOR_COLLECTION_VERSION}_p7_"))
        self.assertNotIn("secret", name)


if __name__ == "__main__":
    unittest.main()
