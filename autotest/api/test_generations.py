"""用例生成接口：策略组合（判定表）、任务生命周期、导出、AI 评分。"""

import pytest


@pytest.mark.smoke
def test_quick_strategy_generates_smoke_cases(client, project, confirmed_doc):
    task = client.run_generation(project["id"], confirmed_doc["id"], strategy="quick")
    assert task["status"] == "completed"
    assert task["progress"] == 100
    assert len(task["drafts"]) > 0
    assert all(d["is_smoke"] for d in task["drafts"])  # 快速冒烟：全部标记冒烟


@pytest.mark.smoke
def test_full_strategy_generates_mixed_types(client, project, confirmed_doc):
    task = client.run_generation(project["id"], confirmed_doc["id"], strategy="full")
    assert task["status"] == "completed"
    types = {d["case_type"] for d in task["drafts"]}
    assert {"functional", "boundary", "exception"} <= types  # 完整策略覆盖三类


def test_full_generates_more_than_quick(client, project, confirmed_doc):
    quick = client.run_generation(project["id"], confirmed_doc["id"], strategy="quick")
    full = client.run_generation(project["id"], confirmed_doc["id"], strategy="full")
    assert len(full["drafts"]) > len(quick["drafts"])


def test_specialist_skill_adds_cases(client, project, confirmed_doc):
    base = client.run_generation(project["id"], confirmed_doc["id"], strategy="quick")
    with_security = client.run_generation(
        project["id"], confirmed_doc["id"], strategy="quick", specialist_skills=["security"],
    )
    assert len(with_security["drafts"]) > len(base["drafts"])
    assert any(d["skill_name"] == "security" for d in with_security["drafts"])


def test_new_project_enables_selectable_specialists(client, project):
    policy = client.get(f"/projects/{project['id']}/skill-policies").json()

    assert policy["revision_no"] == 1
    assert {
        item["skill_name"]: item["resolved"]["enabled"]
        for item in policy["specialists"]
    } == {"security": True, "api_test": True}


def test_disabled_specialist_is_rejected(client, project, confirmed_doc):
    policy = client.get(f"/projects/{project['id']}/skill-policies").json()
    overrides = [
        {
            "skill_name": item["skill_name"],
            "enabled": item["skill_name"] != "security",
        }
        for item in policy["specialists"]
    ]
    saved = client.put(
        f"/projects/{project['id']}/skill-policies",
        json={"base_revision": policy["revision_no"], "overrides": overrides},
    )
    assert saved.status_code == 200

    response = client.post(
        f"/projects/{project['id']}/generations",
        json={
            "document_id": confirmed_doc["id"],
            "strategy": "quick",
            "specialist_skills": ["security"],
            "use_knowledge": False,
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "disabled specialist: security"


def test_generate_without_confirm_rejected(client, project):
    doc = client.create_requirement(project["id"], "未确认需求", "一些内容")
    resp = client.post(
        f"/projects/{project['id']}/generations",
        json={"document_id": doc["id"], "strategy": "quick"},
    )
    assert resp.status_code == 400  # 未确认功能点禁止生成


def test_generate_nonexistent_document_404(client, project):
    resp = client.post(
        f"/projects/{project['id']}/generations",
        json={"document_id": 9999999, "strategy": "quick"},
    )
    assert resp.status_code == 404


def test_task_has_quality_report(client, completed_task):
    report = completed_task["quality_report"]
    assert report is not None
    assert report["total_cases"] == len(completed_task["drafts"])
    assert 0 <= report["coverage_rate"] <= 100


def test_task_list_and_summary(client, project, completed_task):
    tasks = client.get(f"/projects/{project['id']}/generations").json()
    assert any(t["id"] == completed_task["id"] for t in tasks)

    summaries = client.get(f"/projects/{project['id']}/generations/summary").json()
    summary = next(s for s in summaries if s["id"] == completed_task["id"])
    assert summary["draft_count"] == len(completed_task["drafts"])
    assert summary["document_title"]  # 摘要带文档标题


def test_get_nonexistent_task_404(client, project):
    assert client.get(f"/projects/{project['id']}/generations/9999999").status_code == 404


def test_use_knowledge_with_empty_kb_still_completes(client, project, confirmed_doc):
    """知识库为空时开启 RAG 开关，不应阻塞生成（按无知识降级）。"""
    task = client.run_generation(
        project["id"], confirmed_doc["id"], strategy="quick", use_knowledge=True,
    )
    assert task["status"] == "completed"
    assert not task.get("knowledge_refs")


def test_export_drafts_xlsx_and_md(client, project, completed_task):
    base = f"/projects/{project['id']}/generations/{completed_task['id']}/export"
    xlsx = client.get(base, params={"format": "xlsx"})
    assert xlsx.status_code == 200
    assert "spreadsheetml" in xlsx.headers["content-type"]

    md = client.get(base, params={"format": "md"})
    assert md.status_code == 200
    assert completed_task["drafts"][0]["title"] in md.content.decode("utf-8")


def test_export_empty_task_rejected(client, project, completed_task):
    """smoke_only 过滤后为空时导出应报 400（构造：完整策略下仅非冒烟）。"""
    resp = client.get(
        f"/projects/{project['id']}/generations/9999999/export", params={"format": "xlsx"},
    )
    assert resp.status_code == 404


def test_rejudge_assigns_scores(client, project, completed_task):
    resp = client.post(f"/projects/{project['id']}/generations/{completed_task['id']}/judge")
    assert resp.status_code == 200
    task = resp.json()
    scored = [d for d in task["drafts"] if d["judge_score"] is not None]
    assert len(scored) == len(task["drafts"])  # mock judge 应覆盖全部草稿
    assert all(1 <= d["judge_score"] <= 5 for d in scored)


def test_rejudge_nonexistent_task_404(client, project):
    resp = client.post(f"/projects/{project['id']}/generations/9999999/judge")
    assert resp.status_code == 404
