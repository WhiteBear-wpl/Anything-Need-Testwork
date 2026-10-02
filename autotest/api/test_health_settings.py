"""健康检查与系统设置接口。"""

import pytest


@pytest.mark.smoke
def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_get_settings_fields(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.json()
    for field in ("llm_base_url", "llm_model", "llm_mock_mode", "use_mock_llm",
                  "eval_llm_model", "embedding_model", "rerank_model"):
        assert field in body


def test_update_llm_model_persists(client):
    resp = client.patch("/settings", json={"llm_model": "test-model-x"})
    assert resp.status_code == 200
    assert client.get("/settings").json()["llm_model"] == "test-model-x"


def test_update_does_not_clear_other_fields(client):
    before = client.get("/settings").json()
    resp = client.patch("/settings", json={
        "eval_llm_base_url": "https://api.deepseek.com/v1",
        "eval_llm_model": "judge-model",
        "eval_llm_api_key": "test-eval-key",
    })
    assert resp.status_code == 200
    after = client.get("/settings").json()
    assert after["eval_llm_model"] == "judge-model"
    assert after["llm_base_url"] == before["llm_base_url"]  # 未提交的字段保持不变
    # 清理：评测配置回退为复用生成模型
    client.patch("/settings", json={"eval_llm_base_url": "", "eval_llm_model": "", "eval_llm_api_key": ""})


def test_update_incomplete_eval_triple_rejected(client):
    resp = client.patch("/settings", json={"eval_llm_model": "judge-model-only"})
    assert resp.status_code == 400  # 三元组必须全填或全空


def test_rerank_config_roundtrip(client):
    # 不完整的三元组被拒绝
    resp = client.patch("/settings", json={"rerank_model": "BAAI/bge-reranker-v2-m3"})
    assert resp.status_code == 400

    # 完整配置可保存，Key 只返回掩码
    resp = client.patch("/settings", json={
        "rerank_base_url": "https://api.siliconflow.cn/v1",
        "rerank_model": "BAAI/bge-reranker-v2-m3",
        "rerank_api_key": "test-rerank-key",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["rerank_model"] == "BAAI/bge-reranker-v2-m3"
    assert body["rerank_api_key_set"] is True
    assert "test-rerank-key" not in body["rerank_api_key_masked"]

    # 清理：清空 Rerank 配置，避免后续知识检索用例尝试调用外部精排接口
    resp = client.patch("/settings", json={"rerank_base_url": "", "rerank_model": "", "rerank_api_key": ""})
    assert resp.status_code == 200
    assert resp.json()["rerank_api_key_set"] is False
