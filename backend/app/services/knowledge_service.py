"""知识库服务：分块、向量化入库、混合检索（向量 + BM25 + RRF 融合 + 可选 Rerank 精排）、删除。

向量通过 LangChain Chroma 存入本地文件，文本与元数据存 SQLite，两边用 chroma_id 对齐。
collection 按「项目 + embedding 模型」隔离，避免更换模型后新旧向量维度混杂。
"""

import math
import re

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.ai.embedding_factory import embedding_context, normalize_embedding_error
from app.ai.vector_store_factory import create_vector_store, vector_collection_name
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.services.llm import rerank_documents
from app.services.settings_service import RuntimeModelConfig, get_project_runtime_config

# 分块参数：每块目标 200~500 字，过长段落按句子切
MAX_CHUNK_CHARS = 500
MIN_CHUNK_CHARS = 20

# 检索参数
DEFAULT_TOP_K = 5
SIMILARITY_THRESHOLD = 0.35  # 余弦相似度低于该值的分块视为不相关，不注入
RECALL_TOP_K = 20  # 向量 / BM25 两路各自的召回条数（融合与精排前）
RRF_K = 60  # RRF 平滑常数，业界惯例取 60

# ---------- 分块 ----------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；!?;\n])")


def _split_long_text(text: str) -> list[str]:
    """把超长文本按句子边界切成不超过 MAX_CHUNK_CHARS 的片段。"""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    pieces, current = [], ""
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        if current and len(current) + len(sentence) > MAX_CHUNK_CHARS:
            pieces.append(current)
            current = sentence
        else:
            current += sentence
    if current.strip():
        pieces.append(current)
    return pieces


def chunk_markdown(text: str) -> list[dict]:
    """按 Markdown 标题层级分块，每块带标题路径。

    返回 [{"content": str, "heading": "一级 > 二级"}]。
    非 Markdown 的纯文本会整体按段落 + 句子切块（heading 为空）。
    """
    heading_stack: list[tuple[int, str]] = []  # [(level, title)]
    blocks: list[dict] = []
    buffer: list[str] = []

    def heading_path() -> str:
        return " > ".join(t for _, t in heading_stack)

    def flush():
        content = "\n".join(buffer).strip()
        buffer.clear()
        if len(content) < MIN_CHUNK_CHARS:
            return
        path = heading_path()
        for piece in _split_long_text(content):
            piece = piece.strip()
            if len(piece) >= MIN_CHUNK_CHARS:
                blocks.append({"content": piece, "heading": path})

    for line in text.split("\n"):
        match = _HEADING_RE.match(line.strip())
        if match:
            flush()
            level = len(match.group(1))
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, match.group(2).strip()))
        else:
            buffer.append(line)
    flush()
    return blocks


# ---------- 入库 / 删除 ----------

async def ingest_document(db: Session, doc: KnowledgeDocument) -> None:
    """分块 → LangChain 向量化入库 → 写入 SQLite。失败时置为 failed 并记录原因。"""
    vector_store = None
    ids: list[str] = []
    try:
        model_config = get_project_runtime_config(db, doc.project_id)
        chunks = chunk_markdown(doc.raw_content)
        if not chunks:
            raise ValueError("文档内容过短或无法分块")

        # 向量化时把标题路径拼进文本，提升检索区分度
        texts = [
            f"{c['heading']}\n{c['content']}" if c["heading"] else c["content"]
            for c in chunks
        ]
        ids = [f"doc{doc.id}_c{i}" for i in range(len(chunks))]
        collection_name = vector_collection_name(doc.project_id, model_config)
        documents = [
            Document(
                page_content=texts[index],
                metadata={
                    "chroma_id": ids[index],
                    "content": chunk["content"],
                    "document_id": doc.id,
                    "title": doc.title,
                    "source_type": doc.source_type,
                    "heading": chunk["heading"],
                },
            )
            for index, chunk in enumerate(chunks)
        ]
        async with embedding_context(model_config) as embeddings:
            vector_store = create_vector_store(collection_name, embeddings)
            await vector_store.aadd_documents(documents=documents, ids=ids)

        for i, c in enumerate(chunks):
            db.add(KnowledgeChunk(
                document_id=doc.id,
                content=c["content"],
                heading=c["heading"],
                chroma_id=ids[i],
            ))
        doc.vector_collection = collection_name
        doc.status = "ready"
        doc.chunk_count = len(chunks)
        doc.error_message = ""
        db.commit()
    except Exception as exc:
        db.rollback()
        if vector_store is not None and ids:
            try:
                vector_store.delete(ids=ids)
            except Exception:
                pass
        doc.status = "failed"
        normalized_error = normalize_embedding_error(exc)
        doc.error_message = str(normalized_error)[:500]
        db.commit()
        if normalized_error is exc:
            raise
        raise normalized_error from exc


def delete_document_vectors(doc: KnowledgeDocument) -> None:
    if not doc.vector_collection:
        return
    ids = [chunk.chroma_id for chunk in doc.chunks if chunk.chroma_id]
    if not ids:
        return
    try:
        create_vector_store(doc.vector_collection, create_if_missing=False).delete(ids=ids)
    except Exception:
        pass  # 向量清理失败不阻塞文档删除（collection 可能已不存在）


# ---------- 检索 ----------

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")


def _tokenize(text: str) -> list[str]:
    """jieba 搜索粒度分词，过滤标点、空白与纯下划线，小写归一。"""
    import jieba

    tokens = []
    for word in jieba.cut_for_search(text.lower()):
        word = word.strip()
        if word and _TOKEN_RE.fullmatch(word) and word.strip("_"):
            tokens.append(word)
    return tokens


def _make_bm25(corpus: list[list[str]]):
    """BM25Okapi + Lucene 风格 IDF（log(1 + ...)，恒为正）。

    原生 Okapi IDF 在小语料下（词出现在一半以上文档时）会算出 0 或负值，
    导致几十条分块的小知识库全部零分。Lucene 公式保证命中词恒有正贡献。
    """
    from rank_bm25 import BM25Okapi

    class _LuceneBM25(BM25Okapi):
        def _calc_idf(self, nd):
            idf_sum = 0.0
            for word, freq in nd.items():
                idf = math.log(1 + (self.corpus_size - freq + 0.5) / (freq + 0.5))
                self.idf[word] = idf
                idf_sum += idf
            self.average_idf = idf_sum / max(len(nd), 1)

    return _LuceneBM25(corpus)


async def _vector_search(
    project_id: int,
    query: str,
    config: RuntimeModelConfig,
    top_n: int,
    threshold: float,
) -> list[dict]:
    """向量召回：返回 [{chroma_id, content, title, heading, source_type, score}]，按相似度降序。"""
    collection_name = vector_collection_name(project_id, config)
    try:
        async with embedding_context(config) as embeddings:
            vector_store = create_vector_store(collection_name, embeddings)
            results = await vector_store.asimilarity_search_with_relevance_scores(query, k=top_n)
    except Exception as exc:
        normalized_error = normalize_embedding_error(exc)
        if normalized_error is exc:
            raise
        raise normalized_error from exc

    hits = []
    for document, score in results:
        if score < threshold:
            continue
        meta = document.metadata or {}
        hits.append({
            "chroma_id": meta.get("chroma_id", ""),
            "content": meta.get("content", document.page_content),
            "title": meta.get("title", ""),
            "heading": meta.get("heading", ""),
            "source_type": meta.get("source_type", "doc"),
            "score": round(score, 3),
        })
    return hits


def _bm25_search(db: Session, project_id: int, query: str, top_n: int) -> list[dict]:
    """BM25 关键词召回：对项目内 ready 文档的全部分块即时建索引打分。

    项目级分块量在几千以内，内存计算毫秒级完成，暂不做索引缓存。
    只返回得分为正（至少命中一个查询词）的前 top_n 条。
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    rows = (
        db.query(KnowledgeChunk, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .filter(
            KnowledgeDocument.project_id == project_id,
            KnowledgeDocument.status == "ready",
        )
        .all()
    )
    if not rows:
        return []

    # 标题路径拼进正文参与打分，与向量化时的文本口径一致
    corpus = [
        _tokenize(f"{chunk.heading}\n{chunk.content}" if chunk.heading else chunk.content)
        for chunk, _ in rows
    ]
    if not any(corpus):
        return []

    scores = _make_bm25(corpus).get_scores(query_tokens)
    ranked = sorted(zip(rows, scores), key=lambda pair: pair[1], reverse=True)

    hits = []
    for (chunk, doc), score in ranked[:top_n]:
        if score <= 0:
            break
        hits.append({
            "chroma_id": chunk.chroma_id,
            "content": chunk.content,
            "title": doc.title,
            "heading": chunk.heading,
            "source_type": doc.source_type,
            "score": 0.0,  # BM25 分数与向量相似度不可比，展示分以向量/精排为准
        })
    return hits


def _rrf_fuse(vector_hits: list[dict], keyword_hits: list[dict], k: int = RRF_K) -> list[dict]:
    """RRF 倒数排名融合：融合分 = sum(1 / (k + 名次))，双路命中的候选自然靠前。

    返回按融合分降序的去重候选，附加 match 字段（vector / keyword / both）。
    """
    candidates: dict[str, dict] = {}
    for source, hits in (("vector", vector_hits), ("keyword", keyword_hits)):
        for rank, hit in enumerate(hits, start=1):
            key = hit["chroma_id"] or f"{source}:{rank}"
            entry = candidates.get(key)
            if entry is None:
                entry = {**hit, "match": source, "rrf_score": 0.0}
                candidates[key] = entry
            else:
                entry["match"] = "both"
                # 双路命中时保留向量相似度作为展示分
                entry["score"] = max(entry["score"], hit["score"])
            entry["rrf_score"] += 1.0 / (k + rank)
    return sorted(candidates.values(), key=lambda c: c["rrf_score"], reverse=True)


async def _rerank(query: str, candidates: list[dict], config: RuntimeModelConfig, top_k: int) -> list[dict]:
    """外部 Rerank API 精排，失败时降级为 RRF 融合顺序，不阻塞调用方。"""
    try:
        ranked = await rerank_documents(
            query,
            [c["content"] for c in candidates],
            config,
            top_n=top_k,
        )
    except Exception:
        return candidates[:top_k]

    hits = []
    for index, relevance_score in ranked[:top_k]:
        if index >= len(candidates):
            continue
        hit = candidates[index]
        hit["score"] = round(relevance_score, 3)
        hits.append(hit)
    return hits or candidates[:top_k]


async def retrieve(
    db: Session,
    project_id: int,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    recall_top_k: int = RECALL_TOP_K,
    threshold: float = SIMILARITY_THRESHOLD,
    rrf_k: int = RRF_K,
    model_config: RuntimeModelConfig | None = None,
) -> list[dict]:
    """混合检索项目知识库：向量 + BM25 双路召回 → RRF 融合 → 可选 Rerank 精排。

    返回 [{content, title, heading, source_type, score, match}]。
    知识库为空或未命中时返回空列表，调用方按"无知识"继续，不应视为错误。
    """
    ready_count = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.project_id == project_id, KnowledgeDocument.status == "ready")
        .count()
    )
    if not ready_count:
        return []

    model_config = model_config or get_project_runtime_config(db, project_id)
    vector_hits = await _vector_search(project_id, query, model_config, recall_top_k, threshold)
    keyword_hits = _bm25_search(db, project_id, query, recall_top_k)
    if not vector_hits and not keyword_hits:
        return []

    fused = _rrf_fuse(vector_hits, keyword_hits, k=rrf_k)
    if model_config.rerank_configured:
        hits = await _rerank(query, fused[:recall_top_k], model_config, top_k)
    else:
        hits = fused[:top_k]

    for hit in hits:
        hit.pop("rrf_score", None)
        hit.pop("chroma_id", None)
    return hits


def has_ready_knowledge(db: Session, project_id: int) -> bool:
    return (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.project_id == project_id, KnowledgeDocument.status == "ready")
        .count()
        > 0
    )
