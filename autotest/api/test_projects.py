"""项目管理接口：CRUD、参数校验（等价类/边界值）。"""

import uuid

import pytest


def _name():
    return f"AT-{uuid.uuid4().hex[:8]}"


@pytest.mark.smoke
def test_create_project_success(client):
    name = _name()
    resp = client.post("/projects", json={"name": name, "description": "描述"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == name
    assert body["id"] > 0
    client.delete_project(body["id"])


def test_create_project_empty_name_rejected(client):
    resp = client.post("/projects", json={"name": "", "description": ""})
    assert resp.status_code == 422  # 等价类：空名称非法


def test_create_project_name_boundary_200_ok(client):
    resp = client.post("/projects", json={"name": "长" * 200})
    assert resp.status_code == 201  # 边界值：上限 200 字符合法
    client.delete_project(resp.json()["id"])


def test_create_project_name_boundary_201_rejected(client):
    resp = client.post("/projects", json={"name": "长" * 201})
    assert resp.status_code == 422  # 边界值：201 字符越界


def test_create_project_missing_name_rejected(client):
    resp = client.post("/projects", json={"description": "只有描述"})
    assert resp.status_code == 422


@pytest.mark.smoke
def test_list_projects_contains_created(client, project):
    resp = client.get("/projects")
    assert resp.status_code == 200
    assert any(p["id"] == project["id"] for p in resp.json())


def test_get_project_detail(client, project):
    resp = client.get(f"/projects/{project['id']}")
    assert resp.status_code == 200
    assert resp.json()["name"] == project["name"]


def test_get_nonexistent_project_404(client):
    assert client.get("/projects/9999999").status_code == 404


def test_update_project(client, project):
    resp = client.patch(f"/projects/{project['id']}", json={"name": "更新后的名称", "description": "新描述"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "更新后的名称"
    assert body["description"] == "新描述"


def test_update_nonexistent_project_404(client):
    assert client.patch("/projects/9999999", json={"name": "x"}).status_code == 404


def test_delete_project_then_404(client):
    created = client.create_project(_name())
    assert client.delete(f"/projects/{created['id']}").status_code == 204
    assert client.get(f"/projects/{created['id']}").status_code == 404


def test_delete_nonexistent_project_404(client):
    assert client.delete("/projects/9999999").status_code == 404


def test_home_overview_structure(client, project):
    resp = client.get("/projects/overview")
    assert resp.status_code == 200
    body = resp.json()
    for field in ("total_projects", "total_testcases", "total_generations", "projects"):
        assert field in body
    assert body["total_projects"] >= 1
