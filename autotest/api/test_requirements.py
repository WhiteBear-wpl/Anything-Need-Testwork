"""需求文档接口：文本创建、文件上传（等价类）、结构化、确认、功能点编辑。"""

from io import BytesIO

import pytest
from docx import Document

REQ_TEXT = "用户登录：支持手机号+密码登录，连续错误 5 次锁定 30 分钟；支持验证码登录。"


def _docx_bytes(paragraphs: list[str]) -> bytes:
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.mark.smoke
def test_create_text_requirement(client, project):
    resp = client.post(
        f"/projects/{project['id']}/requirements",
        json={"title": "登录需求", "content": REQ_TEXT},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "uploaded"
    assert body["source_type"] == "text"


def test_create_requirement_nonexistent_project_404(client):
    resp = client.post("/projects/9999999/requirements", json={"title": "x", "content": "y"})
    assert resp.status_code == 404


def test_upload_markdown_file(client, project):
    resp = client.post(
        f"/projects/{project['id']}/requirements/upload",
        files={"file": ("需求.md", "# 登录模块\n\n支持手机号登录".encode(), "text/markdown")},
    )
    assert resp.status_code == 201
    assert resp.json()["source_type"] == "markdown"


def test_upload_docx_file(client, project):
    resp = client.post(
        f"/projects/{project['id']}/requirements/upload",
        files={"file": ("需求.docx", _docx_bytes(["登录模块", "支持手机号登录"]),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["source_type"] == "docx"
    assert body["status"] == "uploaded"


def test_upload_unsupported_extension_rejected(client, project):
    resp = client.post(
        f"/projects/{project['id']}/requirements/upload",
        files={"file": ("evil.exe", b"MZ......", "application/octet-stream")},
    )
    assert resp.status_code == 400  # 等价类：非法文件类型


def test_upload_legacy_doc_rejected_with_hint(client, project):
    resp = client.post(
        f"/projects/{project['id']}/requirements/upload",
        files={"file": ("old.doc", b"\xd0\xcf\x11\xe0", "application/msword")},
    )
    assert resp.status_code == 400
    assert ".docx" in resp.json()["detail"]  # 提示引导用户转存格式


def test_upload_uses_filename_as_default_title(client, project):
    resp = client.post(
        f"/projects/{project['id']}/requirements/upload",
        files={"file": ("支付需求文档.md", b"# pay", "text/markdown")},
    )
    assert resp.status_code == 201
    assert "支付需求文档" in resp.json()["title"]


@pytest.mark.smoke
def test_structure_creates_items(client, project):
    doc = client.create_requirement(project["id"], "登录需求", REQ_TEXT)
    structured = client.structure_requirement(project["id"], doc["id"])
    assert structured["status"] == "structured"
    assert len(structured["items"]) > 0
    first = structured["items"][0]
    for field in ("module", "feature", "priority", "confirmed"):
        assert field in first
    assert first["confirmed"] is False


def test_structure_nonexistent_doc_404(client, project):
    resp = client.post(f"/projects/{project['id']}/requirements/9999999/structure")
    assert resp.status_code == 404


@pytest.mark.smoke
def test_confirm_all_items(client, project):
    doc = client.create_requirement(project["id"], "登录需求", REQ_TEXT)
    client.structure_requirement(project["id"], doc["id"])
    confirmed = client.confirm_requirement(project["id"], doc["id"])
    assert confirmed["status"] == "confirmed"
    assert all(item["confirmed"] for item in confirmed["items"])


def test_confirm_subset_items(client, project):
    doc = client.create_requirement(project["id"], "登录需求", REQ_TEXT)
    structured = client.structure_requirement(project["id"], doc["id"])
    picked = [structured["items"][0]["id"]]
    confirmed = client.confirm_requirement(project["id"], doc["id"], item_ids=picked)
    flags = {item["id"]: item["confirmed"] for item in confirmed["items"]}
    assert flags[picked[0]] is True
    assert all(not v for k, v in flags.items() if k != picked[0])  # 未勾选的不确认


def test_edit_item_invalidates_confirmation(client, project, confirmed_doc):
    item = confirmed_doc["items"][0]
    resp = client.patch(
        f"/projects/{project['id']}/requirements/{confirmed_doc['id']}/items/{item['id']}",
        json={"feature": "修改后的功能点"},
    )
    assert resp.status_code == 200
    doc = client.get(f"/projects/{project['id']}/requirements").json()[0]
    assert doc["status"] == "structured"  # 已确认文档被修改后需重新确认


def test_add_and_delete_item(client, project, confirmed_doc):
    base = f"/projects/{project['id']}/requirements/{confirmed_doc['id']}/items"
    resp = client.post(base, json={
        "module": "登录", "feature": "新增功能点", "description": "手工补充",
        "acceptance_criteria": "", "constraints": "", "priority": "P1",
    })
    assert resp.status_code == 201
    item_id = resp.json()["id"]

    assert client.delete(f"{base}/{item_id}").status_code == 204
    doc = client.get(f"/projects/{project['id']}/requirements").json()[0]
    assert all(i["id"] != item_id for i in doc["items"])


def test_delete_nonexistent_item_404(client, project, confirmed_doc):
    resp = client.delete(
        f"/projects/{project['id']}/requirements/{confirmed_doc['id']}/items/9999999"
    )
    assert resp.status_code == 404


def test_save_and_generate_test_scope(client, project):
    doc = client.create_requirement(project["id"], "登录需求", REQ_TEXT)
    scope_json = '{"in_scope": ["登录"], "out_scope": ["注册"], "risks": ["锁定策略未明确"]}'
    resp = client.patch(
        f"/projects/{project['id']}/requirements/{doc['id']}/scope",
        json={"test_scope": scope_json},
    )
    assert resp.status_code == 200
    assert resp.json()["test_scope"] == scope_json

    resp = client.post(f"/projects/{project['id']}/requirements/{doc['id']}/scope/generate")
    assert resp.status_code == 200
    assert resp.json()["test_scope"]  # mock 模式也应返回非空范围建议
