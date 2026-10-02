"""测试用例库：列表展示、脑图切换、用例编辑。"""

import pytest
from playwright.sync_api import expect

from ui.pages.library_page import LibraryPage


@pytest.mark.smoke
def test_adopted_cases_listed(page, base_url, project_with_cases):
    lib = LibraryPage(page)
    lib.goto_project(project_with_cases["project"]["id"])
    expect(lib.case_rows().first).to_be_visible()
    assert lib.case_rows().count() == len(project_with_cases["task"]["drafts"])


def test_switch_to_mindmap_view(page, base_url, project_with_cases):
    lib = LibraryPage(page)
    lib.goto_project(project_with_cases["project"]["id"])
    expect(lib.case_rows().first).to_be_visible()
    lib.switch_to_mindmap()
    expect(page.locator(".mm-wrap").first).to_be_visible()


def test_edit_case_title(page, base_url, project_with_cases):
    lib = LibraryPage(page)
    lib.goto_project(project_with_cases["project"]["id"])
    expect(lib.case_rows().first).to_be_visible()
    lib.open_edit_first_case()

    dialog = page.get_by_role("dialog")
    title_input = dialog.locator("#title")
    title_input.fill("UI 修改后的用例标题")
    dialog.get_by_role("button", name="保 存").or_(
        dialog.get_by_role("button", name="保存")
    ).first.click()
    lib.expect_message("用例已更新")
    expect(page.locator(".ant-table-tbody td[title='UI 修改后的用例标题']")).to_have_count(1)
