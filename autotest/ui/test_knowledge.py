"""知识库页：上传入库、检索、删除。"""

import pytest
from playwright.sync_api import expect

from ui.pages.knowledge_page import KnowledgePage

KB_TEXT = """# 支付模块
## 退款规则
支付后 24 小时内可全额退款，超时收取 5% 手续费，已发货订单不支持退款。
"""


@pytest.mark.smoke
def test_upload_knowledge_doc(page, base_url, seeded_project, tmp_path):
    file_path = tmp_path / "支付规则.md"
    file_path.write_text(KB_TEXT, encoding="utf-8")

    kp = KnowledgePage(page)
    kp.goto_project(seeded_project["id"])
    kp.upload_file(str(file_path))
    expect(kp.doc_row("支付规则")).to_be_visible(timeout=15000)
    expect(kp.doc_row("支付规则").get_by_text("已入库")).to_be_visible(timeout=15000)


def test_search_knowledge_hits(page, base_url, api, seeded_project):
    api.create_knowledge_doc(seeded_project["id"], "支付规则", KB_TEXT)
    kp = KnowledgePage(page)
    kp.goto_project(seeded_project["id"])
    expect(kp.doc_row("支付规则")).to_be_visible()

    # 伪向量下用原文检索保证命中
    kp.search("支付后 24 小时内可全额退款，超时收取 5% 手续费，已发货订单不支持退款。")
    expect(page.get_by_text("支付模块 > 退款规则").first).to_be_visible(timeout=10000)


def test_delete_knowledge_doc(page, base_url, api, seeded_project):
    api.create_knowledge_doc(seeded_project["id"], "支付规则", KB_TEXT)
    kp = KnowledgePage(page)
    kp.goto_project(seeded_project["id"])
    expect(kp.doc_row("支付规则")).to_be_visible()

    kp.delete_doc("支付规则")
    kp.expect_message("已删除")
    expect(page.locator(".ant-table-tbody tr", has_text="支付规则")).to_have_count(0)
