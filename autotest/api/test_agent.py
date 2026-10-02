"""测试助手 Agent 接口：SSE 对话流、历史持久化与清空、项目隔离、生成流水线。

服务端处于 mock 模式，对话走固定剧本（检索知识库 + 统计用例数），结果确定；
带 document_id 或含确认/采纳意图的问题走流水线剧本（解析/确认/生成/评审为真实链路）。
"""

import json
import time

import pytest


def _chat_events(client, project_id: int, question: str, document_id: int | None = None) -> list[dict]:
    """调用对话接口并解析 SSE 事件流。"""
    payload = {"question": question}
    if document_id is not None:
        payload["document_id"] = document_id
    resp = client.request(
        "POST",
        f"/projects/{project_id}/agent/chat",
        json=payload,
        stream=True,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = []
    for line in resp.iter_lines(decode_unicode=True):
        if line and line.startswith("data:"):
            events.append(json.loads(line[5:]))
    return events


def _resume_events(
    client,
    project_id: int,
    checkpoint_thread_id: str,
    approved: bool,
) -> list[dict]:
    resp = client.request(
        "POST",
        f"/projects/{project_id}/agent/resume",
        json={
            "checkpoint_thread_id": checkpoint_thread_id,
            "approved": approved,
        },
        stream=True,
    )
    assert resp.status_code == 200
    events = []
    for line in resp.iter_lines(decode_unicode=True):
        if line and line.startswith("data:"):
            events.append(json.loads(line[5:]))
    return events


@pytest.mark.smoke
def test_chat_stream_event_sequence(client, project):
    events = _chat_events(client, project["id"], "这个项目的通过率怎么样？")

    types = [e["type"] for e in events]
    assert types[0] == "tool_start"
    assert events[0]["name"] == "search_knowledge"
    assert "tool_end" in types
    assert "token" in types
    assert types[-1] == "done"

    done = events[-1]
    assert "Mock 模式" in done["content"]
    assert done["tool_calls"] == [{"name": "search_knowledge"}]


def test_chat_persists_history(client, project):
    _chat_events(client, project["id"], "第一个问题")

    rows = client.get(f"/projects/{project['id']}/agent/messages").json()
    assert len(rows) == 2
    assert rows[0]["role"] == "user"
    assert rows[0]["content"] == "第一个问题"
    assert rows[1]["role"] == "assistant"
    assert "Mock 模式" in rows[1]["content"]
    assert [t["name"] for t in rows[1]["tool_calls"]] == ["search_knowledge"]


def test_history_empty_initially(client, project):
    rows = client.get(f"/projects/{project['id']}/agent/messages").json()
    assert rows == []


def test_clear_messages(client, project):
    _chat_events(client, project["id"], "先聊一句")
    resp = client.delete(f"/projects/{project['id']}/agent/messages")
    assert resp.status_code == 204
    assert client.get(f"/projects/{project['id']}/agent/messages").json() == []


def test_history_isolated_between_projects(client, project):
    other = client.create_project("AT-agent-隔离", "隔离验证")
    try:
        _chat_events(client, project["id"], "只属于项目A的问题")
        assert client.get(f"/projects/{other['id']}/agent/messages").json() == []
    finally:
        client.delete_project(other["id"])


def test_chat_nonexistent_project_404(client):
    resp = client.post("/projects/9999999/agent/chat", json={"question": "在吗"})
    assert resp.status_code == 404


def test_chat_empty_question_rejected(client, project):
    resp = client.post(f"/projects/{project['id']}/agent/chat", json={"question": ""})
    assert resp.status_code == 422


def test_mock_answer_uses_knowledge(client, project):
    """有知识库时，Mock 回答应命中并引用最相关分块。"""
    client.create_knowledge_doc(
        project["id"], "退款规则",
        "# 退款规则\n用户在支付后 24 小时内可全额退款，超过 24 小时收取百分之五手续费。",
    )
    events = _chat_events(client, project["id"], "退款手续费是多少")
    done = events[-1]
    assert "命中" in done["content"]
    assert "退款规则" in done["content"]


REQUIREMENT_MD = """# 用户登录
## 密码登录
支持账号密码登录，连续失败 5 次锁定 15 分钟。
## 验证码登录
支持手机验证码登录，验证码 5 分钟内有效。
"""


def _wait_generation_done(client, project_id: int, task_id: int, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/projects/{project_id}/generations/{task_id}").json()
        if task["status"] in ("completed", "failed"):
            return task
        time.sleep(0.5)
    raise AssertionError(f"生成任务 {task_id} 在 {timeout}s 内未结束")


@pytest.mark.smoke
def test_agent_generation_pipeline(client, project):
    """全链路：上传需求 → 对话解析 → 确认生成 → 任务完成 → 对话采纳入库。"""
    doc = client.post(
        f"/projects/{project['id']}/requirements",
        json={"title": "登录需求", "content": REQUIREMENT_MD},
    ).json()

    # 1. 带 document_id 发起对话：解析并展示功能点
    events = _chat_events(client, project["id"], "请解析这份需求文档。", document_id=doc["id"])
    tool_names = [e["name"] for e in events if e["type"] == "tool_start"]
    assert "parse_requirement_document" in tool_names
    assert "功能点" in events[-1]["content"]

    # 用户消息应持久化附件信息，content 保留原话（不拼接前缀）
    rows = client.get(f"/projects/{project['id']}/agent/messages").json()
    user_msg = rows[-2]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "请解析这份需求文档。"
    assert user_msg["attachment"]["document_id"] == doc["id"]
    assert user_msg["attachment"]["title"] == "登录需求"

    # 2. 写操作先暂停并返回确认卡片，恢复后才真正启动生成
    events = _chat_events(client, project["id"], "确认生成")
    approval_event = events[-1]
    assert approval_event["type"] == "approval_required"
    approval = approval_event["approval"]
    assert approval["title"] == "确认并启动用例生成"
    assert [a["name"] for a in approval["actions"]] == [
        "confirm_features",
        "start_generation",
    ]
    state = client.get(f"/projects/{project['id']}/agent/state").json()
    assert state["pending_approval"]["checkpoint_thread_id"] == approval["checkpoint_thread_id"]

    events = _resume_events(
        client,
        project["id"],
        approval["checkpoint_thread_id"],
        approved=True,
    )
    done = events[-1]
    tool_names = [t["name"] for t in done["tool_calls"]]
    assert "confirm_features" in tool_names
    assert "start_generation" in tool_names
    task_id = next(t["task_id"] for t in done["tool_calls"] if t["name"] == "start_generation")

    # start_generation 的 tool_end 输出中也应携带 task_id（前端进度卡片依赖）
    end_event = next(
        e for e in events if e["type"] == "tool_end" and e["name"] == "start_generation"
    )
    assert json.loads(end_event["output"])["task_id"] == task_id

    # 3. 后台生成任务应正常完成并产出草稿（Mock 模式秒级）
    task = _wait_generation_done(client, project["id"], task_id)
    assert task["status"] == "completed"
    assert len(task["drafts"]) > 0

    # 4. 采纳同样需要确认，确认后草稿才入库为正式用例
    events = _chat_events(client, project["id"], "采纳全部用例")
    approval = events[-1]["approval"]
    assert approval["danger"] is True
    events = _resume_events(
        client,
        project["id"],
        approval["checkpoint_thread_id"],
        approved=True,
    )
    assert "已采纳" in events[-1]["content"]
    task = client.get(f"/projects/{project['id']}/generations/{task_id}").json()
    assert all(d["review_status"] == "adopted" for d in task["drafts"])


def test_agent_cancel_pending_action(client, project):
    doc = client.post(
        f"/projects/{project['id']}/requirements",
        json={"title": "取消确认需求", "content": REQUIREMENT_MD},
    ).json()
    _chat_events(client, project["id"], "请解析", document_id=doc["id"])
    approval = _chat_events(client, project["id"], "确认生成")[-1]["approval"]

    events = _resume_events(
        client,
        project["id"],
        approval["checkpoint_thread_id"],
        approved=False,
    )
    assert events[-1]["type"] == "done"
    assert "没有执行" in events[-1]["content"]
    state = client.get(f"/projects/{project['id']}/agent/state").json()
    assert state["pending_approval"] is None


def test_chat_with_invalid_document_404(client, project):
    resp = client.post(
        f"/projects/{project['id']}/agent/chat",
        json={"question": "解析一下", "document_id": 9999999},
    )
    assert resp.status_code == 404
