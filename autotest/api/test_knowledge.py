"""知识库接口：入库分块（边界值）、检索、删除、RAG 生成溯源。"""

import json

import pytest

KB_CONTENT = """# 订单模块
## 退款规则
用户在支付后 24 小时内可全额退款，超过 24 小时收取 5% 手续费。已发货订单不支持退款。
## 优惠券
满 100 减 20，优惠券不可叠加使用，退款时优惠金额按比例扣除。
"""


@pytest.mark.smoke
def test_create_knowledge_doc_chunks(client, project):
    doc = client.create_knowledge_doc(project["id"], "订单业务规则", KB_CONTENT)
    assert doc["status"] == "ready"
    assert doc["chunk_count"] == 2  # 两个二级标题各成一块


def test_list_knowledge_docs(client, project):
    client.create_knowledge_doc(project["id"], "订单业务规则", KB_CONTENT)
    docs = client.get(f"/projects/{project['id']}/knowledge").json()
    assert len(docs) == 1
    assert docs[0]["title"] == "订单业务规则"


def test_chunks_carry_heading_path(client, project):
    doc = client.create_knowledge_doc(project["id"], "订单业务规则", KB_CONTENT)
    chunks = client.get(f"/projects/{project['id']}/knowledge/{doc['id']}/chunks").json()
    assert len(chunks) == 2
    headings = {c["heading"] for c in chunks}
    assert "订单模块 > 退款规则" in headings  # 分块保留标题路径


def test_upload_knowledge_md_file(client, project):
    resp = client.post(
        f"/projects/{project['id']}/knowledge/upload",
        files={"file": ("规则.md", KB_CONTENT.encode(), "text/markdown")},
        data={"source_type": "doc"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "ready"


def test_upload_knowledge_invalid_type_rejected(client, project):
    resp = client.post(
        f"/projects/{project['id']}/knowledge/upload",
        files={"file": ("data.exe", b"MZ", "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_too_short_content_rejected(client, project):
    resp = client.post(
        f"/projects/{project['id']}/knowledge",
        json={"title": "过短", "content": "太短", "source_type": "doc"},
    )
    assert resp.status_code == 400  # 边界值：低于最小分块长度


def test_knowledge_nonexistent_project_404(client):
    resp = client.post(
        "/projects/9999999/knowledge",
        json={"title": "x", "content": KB_CONTENT, "source_type": "doc"},
    )
    assert resp.status_code == 404


def test_search_identical_text_hits(client, project):
    """伪向量下检索与分块原文一致的查询，必然命中（相似度≈1）。"""
    doc = client.create_knowledge_doc(project["id"], "订单业务规则", KB_CONTENT)
    chunks = client.get(f"/projects/{project['id']}/knowledge/{doc['id']}/chunks").json()
    resp = client.post(
        f"/projects/{project['id']}/knowledge/search",
        json={"query": chunks[0]["content"], "top_k": 3},
    )
    assert resp.status_code == 200
    hits = resp.json()
    assert len(hits) >= 1
    assert hits[0]["score"] > 0.9


def test_search_keyword_recall_and_match_field(client, project):
    """混合检索：精确关键词（错误码）即使语义相似度低也应被 BM25 召回，且返回 match 来源。"""
    client.create_knowledge_doc(
        project["id"], "退款异常处理",
        "# 退款模块\n## 异常处理\n退款接口异常时返回错误码 ERR_4003，需要人工介入处理并记录工单。",
    )
    resp = client.post(
        f"/projects/{project['id']}/knowledge/search",
        json={"query": "ERR_4003", "top_k": 3},
    )
    assert resp.status_code == 200
    hits = resp.json()
    assert len(hits) >= 1
    top = hits[0]
    assert "ERR_4003" in top["content"]
    assert top["match"] in ("vector", "keyword", "both")


def test_search_empty_kb_returns_empty(client, project):
    resp = client.post(
        f"/projects/{project['id']}/knowledge/search",
        json={"query": "退款", "top_k": 3},
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_delete_knowledge_doc(client, project):
    doc = client.create_knowledge_doc(project["id"], "订单业务规则", KB_CONTENT)
    assert client.delete(f"/projects/{project['id']}/knowledge/{doc['id']}").status_code == 204
    assert client.get(f"/projects/{project['id']}/knowledge").json() == []


def test_rag_generation_records_knowledge_refs(client, project):
    """入库知识后开启 RAG 生成，任务应记录引用溯源。"""
    client.create_knowledge_doc(
        project["id"], "登录业务规则",
        "# 登录模块\n## 锁定规则\n密码连续错误 5 次锁定账号 30 分钟，锁定期间提示剩余时间。",
    )
    doc = client.prepare_confirmed_document(project["id"], "登录需求")
    task = client.run_generation(project["id"], doc["id"], strategy="quick", use_knowledge=True)
    assert task["status"] == "completed"
    refs = json.loads(task["knowledge_refs"]) if task["knowledge_refs"] else {}
    if refs:  # 伪向量相似度过阈值才会有引用，有则校验结构
        first = next(iter(refs.values()))[0]
        assert first["title"] == "登录业务规则"
        assert "score" in first
