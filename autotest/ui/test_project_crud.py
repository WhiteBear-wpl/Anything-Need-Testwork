"""项目管理页：新建、搜索、校验、删除。"""

import uuid

import pytest
from playwright.sync_api import expect

from ui.pages.project_list_page import ProjectListPage


def _name():
    return f"UI-{uuid.uuid4().hex[:8]}"


@pytest.mark.smoke
def test_create_project_via_modal(page, base_url, api):
    name = _name()
    plp = ProjectListPage(page)
    plp.goto()
    plp.create_project(name, "UI 自动化创建")
    expect(plp.card(name)).to_be_visible()

    created = next(p for p in api.get("/projects").json() if p["name"] == name)
    api.delete_project(created["id"])


def test_create_project_empty_name_blocked(page, base_url):
    plp = ProjectListPage(page)
    plp.goto()
    plp.open_create_modal()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="创 建").or_(
        dialog.get_by_role("button", name="创建")
    ).first.click()
    expect(dialog).to_be_visible()  # 校验失败，弹窗不应关闭
    expect(page.locator(".ant-form-item-explain-error").first).to_be_visible()


def test_search_filters_projects(page, base_url, seeded_project, api):
    other = api.create_project(_name(), "干扰项目")
    try:
        plp = ProjectListPage(page)
        plp.goto()
        expect(plp.card(seeded_project["name"])).to_be_visible()
        plp.search(seeded_project["name"])
        expect(plp.card(seeded_project["name"])).to_be_visible()
        expect(page.locator(".project-card", has_text=other["name"])).to_have_count(0)
    finally:
        api.delete_project(other["id"])


def test_delete_project_from_card_menu(page, base_url, api):
    name = _name()
    api.create_project(name, "待删除")
    plp = ProjectListPage(page)
    plp.goto()
    plp.delete_project(name)
    plp.expect_message("已删除")
    expect(page.locator(".project-card", has_text=name)).to_have_count(0)
