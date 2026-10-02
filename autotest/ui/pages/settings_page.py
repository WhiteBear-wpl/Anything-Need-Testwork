from .base_page import BasePage


class SettingsPage(BasePage):
    path = "/settings"

    def card(self, title: str):
        return self.page.locator(".ant-card", has_text=title).first

    def save_generation_model(self, model: str):
        card = self.card("用例生成模型")
        card.locator("#llm_model").fill(model)
        card.get_by_role("button", name="保存设置").click()
