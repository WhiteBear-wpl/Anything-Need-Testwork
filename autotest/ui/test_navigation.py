"""全局导航：侧边栏各入口可达，页面标题正确。"""

import pytest
from playwright.sync_api import expect

from ui.pages.base_page import BasePage


@pytest.mark.smoke
def test_sidebar_brand_visible(page, base_url):
    BasePage(page).goto("/")
    expect(page.get_by_text("AI用例管理平台")).to_be_visible()


def test_nav_to_testcases(page, base_url):
    base = BasePage(page)
    base.goto("/")
    base.sidebar_link("测试用例").click()
    expect(page).to_have_url(f"{base_url}/testcases")
    expect(page.locator(".page-title", has_text="测试用例")).to_be_visible()


def test_nav_to_knowledge(page, base_url):
    base = BasePage(page)
    base.goto("/")
    base.sidebar_link("知识库").click()
    expect(page).to_have_url(f"{base_url}/knowledge")
    expect(page.locator(".page-title", has_text="知识库")).to_be_visible()


def test_nav_to_evaluation(page, base_url):
    base = BasePage(page)
    base.goto("/")
    base.sidebar_link("AI 评测").click()
    expect(page).to_have_url(f"{base_url}/evaluation")
    expect(page.locator(".page-title", has_text="AI 评测")).to_be_visible()


def test_nav_to_settings(page, base_url):
    base = BasePage(page)
    base.goto("/")
    base.sidebar_link("设置").click()
    expect(page).to_have_url(f"{base_url}/settings")
    expect(page.locator(".page-title", has_text="设置")).to_be_visible()
