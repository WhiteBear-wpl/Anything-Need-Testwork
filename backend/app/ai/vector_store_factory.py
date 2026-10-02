"""LangChain Chroma 向量库适配层。"""

import hashlib
import os
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

from app.ai.embedding_factory import uses_mock_embeddings
from app.config import BASE_DIR
from app.services.settings_service import RuntimeModelConfig


VECTOR_COLLECTION_VERSION = "lc_v1"
CHROMA_DIR = Path(os.environ.get("AITC_CHROMA_DIR", "") or BASE_DIR / "data" / "chroma")


def vector_collection_name(project_id: int, config: RuntimeModelConfig) -> str:
    """按项目和 Embedding 端点生成稳定 collection 名，避免不同维度混存。"""
    identity = "\0".join(
        (
            "mock" if uses_mock_embeddings(config) else "openai-compatible",
            config.embedding_base_url,
            config.embedding_model,
        )
    )
    fingerprint = hashlib.sha256(identity.encode()).hexdigest()[:12]
    return f"{VECTOR_COLLECTION_VERSION}_p{project_id}_{fingerprint}"


def _cosine_relevance(distance: float) -> float:
    return max(0.0, min(1.0, 1.0 - distance))


def create_vector_store(
    collection_name: str,
    embeddings: Embeddings | None = None,
    *,
    create_if_missing: bool = True,
) -> Chroma:
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=str(CHROMA_DIR),
        collection_metadata={"hnsw:space": "cosine"},
        relevance_score_fn=_cosine_relevance,
        create_collection_if_not_exists=create_if_missing,
    )
