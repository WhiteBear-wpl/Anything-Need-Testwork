import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from benchmarks.rag.corpus import CorpusChunk
from benchmarks.rag.retrieval_variants import retrieve_variant
from app.services.settings_service import RuntimeModelConfig


CORPUS = [
    CorpusChunk("a#01", "errors", "错误", "退款接口异常返回错误码 ERR_4003，需要人工处理。"),
    CorpusChunk("b#01", "orders", "订单", "订单创建后可以查看订单详情。"),
]


async def fake_vector(_query: str, _top_n: int):
    return [("b#01", 0.9), ("a#01", 0.8)]


class RetrievalVariantTests(unittest.TestCase):
    def test_hybrid_rrf_promotes_chunk_found_by_both_routes(self):
        result = asyncio.run(
            retrieve_variant("hybrid_rrf", CORPUS, "ERR_4003", RuntimeModelConfig(), top_k=2, vector_search=fake_vector)
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.ranked_chunk_ids[0], "a#01")

    def test_missing_rerank_configuration_is_reported_not_executed(self):
        result = asyncio.run(
            retrieve_variant("hybrid_rerank", CORPUS, "退款", RuntimeModelConfig(), top_k=2, vector_search=fake_vector)
        )

        self.assertEqual(result.status, "not_executed")
        self.assertIn("Rerank", result.error)

    def test_rerank_transport_error_returns_hybrid_order_as_fallback(self):
        config = RuntimeModelConfig(rerank_api_key="key", rerank_base_url="https://example.com/v1", rerank_model="reranker")
        with patch("benchmarks.rag.retrieval_variants.rerank_documents", new=AsyncMock(side_effect=RuntimeError("down"))):
            result = asyncio.run(retrieve_variant("hybrid_rerank", CORPUS, "ERR_4003", config, top_k=2, vector_search=fake_vector))

        self.assertEqual(result.status, "completed")
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.ranked_chunk_ids[0], "a#01")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
