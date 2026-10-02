from playwright.sync_api import Page, expect


class BasePage:
    """POM 基类：提供导航与通用断言。"""

    path = "/"

    def __init__(self, page: Page):
        self.page = page

    def goto(self, path: str | None = None):
        self.page.goto(path or self.path)
        return self

    def expect_message(self, text: str):
        """等待 antd 全局 message 提示出现。"""
        expect(self.page.locator(".ant-message").get_by_text(text)).to_be_visible()

    def sidebar_link(self, name: str):
        return self.page.locator(".sidebar-link", has_text=name).first
