from __future__ import annotations

from typing import Any


class MockLLMProvider:
    def __init__(self, model: str = 'mock-model') -> None:
        self.model = model

    def generate(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        return {
            'plan': [
                {'step': '打开登录页', 'type': 'UI'},
                {'step': '输入错误密码', 'type': 'UI'},
                {'step': '点击登录按钮', 'type': 'UI'},
                {'step': '断言提示文案', 'type': 'RULE'},
            ],
            'message': 'Mock LLM generated test plan successfully.',
            'model': self.model,
        }
