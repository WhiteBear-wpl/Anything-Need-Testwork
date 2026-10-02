from playwright.sync_api import expect

from .base_page import BasePage


class KnowledgePage(BasePage):
    path = "/knowledge"

    def goto_project(self, project_id: int):
        return self.goto(f"/knowledge?project={project_id}")

    def upload_file(self, file_path: str):
        self.page.locator(".ant-upload input[type='file']").set_input_files(file_path)

    def doc_row(self, title: str):
        return self.page.locator(".ant-table-tbody tr", has_text=title).first

    def search(self, query: str):
        self.page.get_by_placeholder("输入问题测试检索效果").fill(query)
        self.page.get_by_role("button", name="检索").click()

    def delete_doc(self, title: str):
        self.doc_row(title).get_by_role("button", name="删除").click()
        self.page.get_by_role("button", name="确 定").or_(
            self.page.get_by_role("button", name="确定")
        ).first.click()
