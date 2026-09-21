from __future__ import annotations

from app.ai.provider import MockLLMProvider


class CaseGenerator:
    def __init__(self, provider: MockLLMProvider | None = None) -> None:
        self.provider = provider or MockLLMProvider()

    def generate(self, prompt: str) -> dict[str, object]:
        result = self.provider.generate(prompt)
        return {
            'prompt': prompt,
            'plan': result.get('plan', []),
            'message': result.get('message', 'Generated'),
            'model': result.get('model', 'mock-model'),
        }
