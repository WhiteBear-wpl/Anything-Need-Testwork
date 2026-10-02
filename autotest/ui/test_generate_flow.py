"""AI 生成五步流程：导入 → 确认 → 生成 → 评审 → 完成（mock 模式）。"""

import pytest
from playwright.sync_api import expect

from ui.pages.generate_flow_page import GenerateFlowPage

PRD = "用户登录功能：支持手机号+密码登录，密码连续错误 5 次锁定账号 30 分钟；支持短信验证码登录。"


@pytest.mark.smoke
def test_full_generate_and_adopt_flow(page, base_url, seeded_project):
    """核心 E2E：粘贴 PRD → 解析 → 确认 → 生成 → 全部采纳 → 完成页。"""
    flow = GenerateFlowPage(page)
    flow.goto_flow(seeded_project["id"])

    flow.import_text("登录模块 PRD", PRD)
    flow.expect_confirm_step()
    assert flow.feature_rows().count() > 0

    flow.confirm_items()
    expect(page.get_by_role("button", name="确认并开始生成")).to_be_visible()

    flow.start_generation()
    flow.wait_review_ready()
    assert flow.draft_rows().count() > 0

    flow.select_all_drafts()
    flow.adopt_selected()
    flow.expect_done_step()
    expect(page.get_by_role("button", name="查看测试用例")).to_be_visible()


def test_import_requires_title_and_content(page, base_url, seeded_project):
    flow = GenerateFlowPage(page)
    flow.goto_flow(seeded_project["id"])
    page.get_by_role("button", name="解析功能点").click()
    expect(page.locator(".ant-form-item-explain-error").first).to_be_visible()


def test_reject_flow_with_reason(page, base_url, api, seeded_project):
    """接口造好待评审任务，UI 验证驳回交互。"""
    doc = api.prepare_confirmed_document(seeded_project["id"])
    task = api.run_generation(seeded_project["id"], doc["id"], strategy="quick")

    flow = GenerateFlowPage(page)
    flow.goto(f"/projects/{seeded_project['id']}/generate?task={task['id']}")
    flow.wait_review_ready()

    page.locator(".ant-table-tbody .ant-checkbox-input").first.check()
    flow.reject_selected()
    expect(page.locator(".ant-table-tbody").get_by_text("已驳回").first).to_be_visible()
