from playwright.sync_api import expect

from .base_page import BasePage


class ProjectListPage(BasePage):
    path = "/"

    def open_create_modal(self):
        # 空态与非空态的入口文案不同
        button = self.page.get_by_role("button", name="新建项目")
        if not button.count():
            button = self.page.get_by_role("button", name="创建第一个项目")
        button.first.click()
        expect(self.page.get_by_role("dialog")).to_be_visible()

    def create_project(self, name: str, description: str = ""):
        self.open_create_modal()
        dialog = self.page.get_by_role("dialog")
        dialog.get_by_placeholder("例如：电商系统 v2.0").fill(name)
        if description:
            dialog.get_by_placeholder("简要描述项目背景与测试范围").fill(description)
        dialog.get_by_role("button", name="创 建").or_(
            dialog.get_by_role("button", name="创建")
        ).first.click()

    def card(self, name: str):
        return self.page.locator(".project-card", has_text=name).first

    def search(self, keyword: str):
        self.page.get_by_placeholder("搜索项目").fill(keyword)

    def delete_project(self, name: str):
        self.card(name).locator(".project-card-more").click()
        self.page.get_by_role("menuitem", name="删除项目").click()
        confirm = self.page.locator(".ant-modal-confirm")
        confirm.get_by_role("button", name="删 除").or_(
            confirm.get_by_role("button", name="删除")
        ).first.click()
