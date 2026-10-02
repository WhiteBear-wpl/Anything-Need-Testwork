"""评审入库与用例库：采纳/驳回/编辑（状态迁移法）、用例 CRUD、目录重命名。"""

import json

import pytest


def _draft_ids(task, count=None):
    ids = [d["id"] for d in task["drafts"]]
    return ids if count is None else ids[:count]


def _get_task(client, project_id, task_id):
    return client.get(f"/projects/{project_id}/generations/{task_id}").json()


@pytest.mark.smoke
def test_adopt_drafts_creates_testcases(client, project, completed_task):
    ids = _draft_ids(completed_task, 2)
    resp = client.post(
        f"/projects/{project['id']}/generations/{completed_task['id']}/review",
        json={"draft_ids": ids, "action": "adopt"},
    )
    assert resp.status_code == 200
    testcases = resp.json()
    assert len(testcases) == 2
    assert all(tc["source"] == "ai_generated" for tc in testcases)

    task = _get_task(client, project["id"], completed_task["id"])
    adopted = {d["id"]: d for d in task["drafts"]}
    assert all(adopted[i]["review_status"] == "adopted" for i in ids)


@pytest.mark.smoke
def test_reject_drafts_with_reason(client, project, completed_task):
    ids = _draft_ids(completed_task, 1)
    resp = client.post(
        f"/projects/{project['id']}/generations/{completed_task['id']}/review",
        json={"draft_ids": ids, "action": "reject", "reject_reason": "重复场景"},
    )
    assert resp.status_code == 200

    task = _get_task(client, project["id"], completed_task["id"])
    draft = next(d for d in task["drafts"] if d["id"] == ids[0])
    assert draft["review_status"] == "rejected"
    assert draft["reject_reason"] == "重复场景"


def test_invalid_review_action_rejected(client, project, completed_task):
    resp = client.post(
        f"/projects/{project['id']}/generations/{completed_task['id']}/review",
        json={"draft_ids": _draft_ids(completed_task, 1), "action": "destroy"},
    )
    assert resp.status_code == 422  # action 由 Pydantic Literal 校验


def test_edit_draft_marks_was_edited(client, project, completed_task):
    draft_id = _draft_ids(completed_task, 1)[0]
    resp = client.patch(
        f"/projects/{project['id']}/generations/{completed_task['id']}/drafts/{draft_id}",
        json={"title": "人工修订后的标题", "priority": "P0"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "人工修订后的标题"
    assert body["priority"] == "P0"
    assert body["was_edited"] is True
    assert body["review_status"] == "edited"


def test_edit_nonexistent_draft_404(client, project, completed_task):
    resp = client.patch(
        f"/projects/{project['id']}/generations/{completed_task['id']}/drafts/9999999",
        json={"title": "x"},
    )
    assert resp.status_code == 404


def test_review_stats_after_mixed_review(client, project, completed_task):
    """采纳 1 条、驳回 1 条后，评审信号统计应准确。"""
    ids = _draft_ids(completed_task)
    base = f"/projects/{project['id']}/generations/{completed_task['id']}/review"
    client.post(base, json={"draft_ids": [ids[0]], "action": "adopt"})
    client.post(base, json={"draft_ids": [ids[1]], "action": "reject", "reject_reason": "其他"})

    stats = _get_task(client, project["id"], completed_task["id"])["review_stats"]
    assert stats["adopted"] == 1
    assert stats["rejected"] == 1
    assert stats["pending"] == len(ids) - 2
    assert stats["reviewed"] is True


def _adopt_all(client, project, task):
    client.post(
        f"/projects/{project['id']}/generations/{task['id']}/review",
        json={"draft_ids": _draft_ids(task), "action": "adopt"},
    )


def test_project_testcase_list(client, project, completed_task):
    _adopt_all(client, project, completed_task)
    resp = client.get(f"/projects/{project['id']}/testcases")
    assert resp.status_code == 200
    assert len(resp.json()) == len(completed_task["drafts"])


def test_global_testcase_list_filter_by_project(client, project, completed_task):
    _adopt_all(client, project, completed_task)
    resp = client.get("/testcases", params={"project_id": project["id"]})
    assert resp.status_code == 200
    cases = resp.json()
    assert len(cases) == len(completed_task["drafts"])
    assert all(c["project_id"] == project["id"] for c in cases)


def test_update_testcase_fields(client, project, completed_task):
    _adopt_all(client, project, completed_task)
    case = client.get(f"/projects/{project['id']}/testcases").json()[0]
    resp = client.patch(
        f"/projects/{project['id']}/testcases/{case['id']}",
        json={"title": "库内修订标题", "priority": "P0",
              "steps": json.dumps(["步骤1", "步骤2"], ensure_ascii=False)},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "库内修订标题"


def test_rename_catalog_module(client, project, completed_task):
    _adopt_all(client, project, completed_task)
    case = client.get(f"/projects/{project['id']}/testcases").json()[0]
    old_module = case["module"]
    resp = client.patch(
        f"/projects/{project['id']}/testcases/catalog/rename",
        json={"type": "module", "old_module": old_module, "new_name": "重命名模块"},
    )
    assert resp.status_code == 200
    assert resp.json()["updated_items"] > 0
    cases = client.get(f"/projects/{project['id']}/testcases").json()
    assert all(c["module"] != old_module for c in cases)


def test_delete_testcase(client, project, completed_task):
    _adopt_all(client, project, completed_task)
    case = client.get(f"/projects/{project['id']}/testcases").json()[0]
    assert client.delete(f"/projects/{project['id']}/testcases/{case['id']}").status_code == 204
    remaining = client.get(f"/projects/{project['id']}/testcases").json()
    assert all(c["id"] != case["id"] for c in remaining)
