"""设置页：模型配置卡片展示与保存。"""

import pytest
from playwright.sync_api import expect

from ui.pages.settings_page import SettingsPage


@pytest.mark.smoke
def test_settings_cards_visible(page, base_url):
    sp = SettingsPage(page)
    sp.goto()
    expect(sp.card("当前状态")).to_be_visible()
    expect(sp.card("用例生成模型")).to_be_visible()
    expect(sp.card("评测模型（AI Judge / 召回率判定）")).to_be_visible()
    expect(sp.card("Embedding 模型（知识库检索）")).to_be_visible()


def test_save_generation_model(page, base_url):
    sp = SettingsPage(page)
    sp.goto()
    sp.save_generation_model("ui-test-model")
    sp.expect_message("设置已保存")
