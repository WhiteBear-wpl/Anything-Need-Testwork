from playwright.sync_api import expect

from .base_page import BasePage


class LibraryPage(BasePage):
    path = "/testcases"

    def goto_project(self, project_id: int):
        return self.goto(f"/testcases?project={project_id}")

    def case_rows(self):
        return self.page.locator(".ant-table-tbody tr.ant-table-row")

    def switch_to_mindmap(self):
        self.page.get_by_text("脑图", exact=True).click()

    def open_edit_first_case(self):
        self.page.get_by_role("button", name="编辑").first.click()
        expect(self.page.get_by_role("dialog")).to_be_visible()
