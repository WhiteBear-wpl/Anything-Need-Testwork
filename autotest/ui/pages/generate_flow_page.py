from playwright.sync_api import expect

from .base_page import BasePage


class GenerateFlowPage(BasePage):
    """AI 生成五步流程页。"""

    def goto_flow(self, project_id: int):
        return self.goto(f"/projects/{project_id}/generate")

    # ---- 第 1 步：导入需求 ----
    def import_text(self, title: str, content: str):
        self.page.get_by_placeholder("例如：用户登录模块 PRD").fill(title)
        self.page.get_by_placeholder("粘贴 PRD 内容...").fill(content)
        self.page.get_by_role("button", name="解析功能点").click()

    def expect_confirm_step(self):
        expect(self.page.get_by_text("确认功能点").first).to_be_visible(timeout=30000)

    def feature_rows(self):
        return self.page.locator(".ant-table-tbody tr.ant-table-row")

    # ---- 第 2 步：确认功能点 ----
    def confirm_items(self):
        self.page.get_by_role("button", name="确认并继续").click()

    # ---- 第 3 步：策略与生成 ----
    def start_generation(self):
        self.page.get_by_role("button", name="确认并开始生成").click()
        dialog = self.page.get_by_role("dialog")
        expect(dialog.get_by_text("确认生成配置")).to_be_visible()
        dialog.get_by_role("button", name="开始生成").click()

    # ---- 第 4 步：评审 ----
    def wait_review_ready(self, timeout: int = 60000):
        """等生成任务完成且草稿行渲染出来（按钮常驻，不能作为完成信号）。"""
        expect(self.page.locator(".ant-table-tbody tr.ant-table-row").first).to_be_visible(timeout=timeout)

    def draft_rows(self):
        return self.page.locator(".ant-table-tbody tr.ant-table-row")

    def select_all_drafts(self):
        # 表格有分页，表头复选框只选当前页；「一键全选」跨页选中全部待评审草稿
        self.page.get_by_role("button", name="一键全选").click()

    def adopt_selected(self):
        self.page.get_by_role("button", name="采纳选中").click()

    def reject_selected(self, reason_confirm: bool = True):
        self.page.get_by_role("button", name="驳回选中").click()
        dialog = self.page.get_by_role("dialog")
        expect(dialog).to_be_visible()
        dialog.get_by_role("button", name="确认驳回").or_(
            dialog.get_by_role("button", name="确 定")
        ).first.click()

    # ---- 第 5 步：完成 ----
    def expect_done_step(self):
        expect(self.page.get_by_role("button", name="查看测试用例")).to_be_visible(timeout=15000)
