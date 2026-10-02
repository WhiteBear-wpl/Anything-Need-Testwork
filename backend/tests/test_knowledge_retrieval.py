"""混合检索单测：分词、BM25 召回、RRF 融合与 Rerank 降级路径。

BM25 / RRF 为纯本地计算，不依赖外部 API；Rerank 用 mock 验证成功与降级两条路径。
"""

import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from langchain_core.documents import Document
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  确保所有表注册到 Base.metadata
from app.database import Base
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.services.knowledge_service import _bm25_search, _rerank, _rrf_fuse, _tokenize, _vector_search
from app.services.settings_service import RuntimeModelConfig


class TokenizeTests(unittest.TestCase):
    def test_chinese_and_ascii_tokens(self):
        # jieba 会把 ERR_4003 切成 err / 4003，查询与语料两侧口径一致，不影响匹配
        tokens = _tokenize("退款手续费规则 ERR_4003！")
        self.assertIn("退款", tokens)
        self.assertIn("手续费", tokens)
        self.assertIn("err", tokens)
        self.assertIn("4003", tokens)
        self.assertNotIn("！", tokens)
        self.assertNotIn("_", tokens)

    def test_empty_query(self):
        self.assertEqual(_tokenize("，。！？"), [])


class BM25SearchTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

        doc = KnowledgeDocument(id=1, project_id=1, title="退款规则", source_type="doc", status="ready")
        failed_doc = KnowledgeDocument(id=2, project_id=1, title="未就绪文档", source_type="doc", status="failed")
        self.db.add_all([
            doc,
            failed_doc,
            KnowledgeChunk(
                document_id=1,
                content="退款接口异常时返回错误码 ERR_4003，需要人工介入处理",
                heading="退款模块 > 异常处理",
                chroma_id="doc1_c0",
            ),
            KnowledgeChunk(
                document_id=1,
                content="订单创建后三十分钟未支付将自动关闭",
                heading="订单模块 > 超时规则",
                chroma_id="doc1_c1",
            ),
            KnowledgeChunk(
                document_id=2,
                content="失败文档里也有 ERR_4003 错误码",
                heading="",
                chroma_id="doc2_c0",
            ),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_exact_keyword_ranks_first(self):
        hits = _bm25_search(self.db, 1, "ERR_4003 错误码", top_n=5)
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0]["chroma_id"], "doc1_c0")
        self.assertEqual(hits[0]["title"], "退款规则")
        self.assertEqual(hits[0]["heading"], "退款模块 > 异常处理")

    def test_only_ready_documents_are_searched(self):
        hits = _bm25_search(self.db, 1, "ERR_4003", top_n=5)
        self.assertTrue(all(h["chroma_id"] != "doc2_c0" for h in hits))

    def test_no_match_returns_empty(self):
        self.assertEqual(_bm25_search(self.db, 1, "登录验证码", top_n=5), [])

    def test_other_project_returns_empty(self):
        self.assertEqual(_bm25_search(self.db, 99, "退款", top_n=5), [])


def _hit(chroma_id: str, score: float = 0.0) -> dict:
    return {
        "chroma_id": chroma_id,
        "content": f"content-{chroma_id}",
        "title": "t",
        "heading": "",
        "source_type": "doc",
        "score": score,
    }


class RRFFuseTests(unittest.TestCase):
    def test_both_hit_ranks_first(self):
        # A 在两路都出现（向量第 2、关键词第 1），应压过各自单路第一
        vector_hits = [_hit("B", 0.9), _hit("A", 0.8)]
        keyword_hits = [_hit("A"), _hit("C")]
        fused = _rrf_fuse(vector_hits, keyword_hits)
        self.assertEqual([f["chroma_id"] for f in fused], ["A", "B", "C"])
        self.assertEqual(fused[0]["match"], "both")
        self.assertEqual(fused[1]["match"], "vector")
        self.assertEqual(fused[2]["match"], "keyword")

    def test_both_hit_keeps_vector_score(self):
        fused = _rrf_fuse([_hit("A", 0.8)], [_hit("A", 0.0)])
        self.assertEqual(len(fused), 1)
        self.assertEqual(fused[0]["score"], 0.8)

    def test_empty_inputs(self):
        self.assertEqual(_rrf_fuse([], []), [])


class VectorSearchTests(unittest.TestCase):
    def test_langchain_results_keep_original_chunk_content_and_threshold(self):
        embeddings = object()

        @asynccontextmanager
        async def fake_embedding_context(config):
            yield embeddings

        store = unittest.mock.MagicMock()
        store.asimilarity_search_with_relevance_scores = AsyncMock(return_value=[
            (
                Document(
                    page_content="退款模块 > 规则\n用于向量化的正文",
                    metadata={
                        "chroma_id": "doc1_c0",
                        "content": "用于提示词的原始正文",
                        "title": "退款规则",
                        "heading": "退款模块 > 规则",
                        "source_type": "doc",
                    },
                ),
                0.88,
            ),
            (Document(page_content="低分内容", metadata={"chroma_id": "doc1_c1"}), 0.2),
        ])
        config = RuntimeModelConfig(llm_mock_mode=True)

        with (
            patch("app.services.knowledge_service.embedding_context", fake_embedding_context),
            patch("app.services.knowledge_service.create_vector_store", return_value=store) as factory,
        ):
            hits = asyncio.run(_vector_search(1, "退款", config, top_n=20, threshold=0.35))

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["content"], "用于提示词的原始正文")
        self.assertEqual(hits[0]["score"], 0.88)
        self.assertIs(factory.call_args.args[1], embeddings)
        store.asimilarity_search_with_relevance_scores.assert_awaited_once_with("退款", k=20)


class RerankTests(unittest.TestCase):
    def setUp(self):
        self.config = RuntimeModelConfig(
            rerank_api_key="key",
            rerank_base_url="https://api.siliconflow.cn/v1",
            rerank_model="BAAI/bge-reranker-v2-m3",
        )
        self.candidates = [_hit("A", 0.5), _hit("B", 0.4), _hit("C", 0.3)]

    def test_rerank_reorders_and_scores(self):
        with patch(
            "app.services.knowledge_service.rerank_documents",
            new=AsyncMock(return_value=[(2, 0.95), (0, 0.60)]),
        ):
            hits = asyncio.run(_rerank("q", self.candidates, self.config, top_k=2))
        self.assertEqual([h["chroma_id"] for h in hits], ["C", "A"])
        self.assertEqual(hits[0]["score"], 0.95)
        self.assertEqual(hits[1]["score"], 0.6)

    def test_rerank_failure_falls_back_to_fused_order(self):
        with patch(
            "app.services.knowledge_service.rerank_documents",
            new=AsyncMock(side_effect=RuntimeError("api down")),
        ):
            hits = asyncio.run(_rerank("q", self.candidates, self.config, top_k=2))
        self.assertEqual([h["chroma_id"] for h in hits], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
