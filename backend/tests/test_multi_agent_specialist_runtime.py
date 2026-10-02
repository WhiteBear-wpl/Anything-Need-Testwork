import unittest
from unittest.mock import AsyncMock, patch

from app.services.settings_service import RuntimeModelConfig
from app.skills.api_test.handler import run as run_api_test
from app.skills.base import SkillContext
from app.skills.security.handler import run as run_security


class CapturingHarness:
    async def call_llm(self, stage, skill_name, operation):
        self.calls.append((stage, skill_name))
        return await operation()

    def __init__(self):
        self.calls = []


class MultiAgentSpecialistRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_security_forwards_context_runtime_to_llm_runner(self):
        harness = CapturingHarness()
        with patch(
            "app.skills.security.handler.call_for_cases",
            new=AsyncMock(return_value=[{"title": "越权访问"}]),
        ) as llm_runner:
            await run_security(
                {"feature_item": {"feature": "登录"}},
                SkillContext(model_config=RuntimeModelConfig(), runtime=harness),
            )

        self.assertIs(llm_runner.await_args.kwargs["runtime"], harness)

    async def test_api_test_forwards_context_runtime_to_llm_runner(self):
        harness = CapturingHarness()
        with patch(
            "app.skills.api_test.handler.call_for_cases",
            new=AsyncMock(return_value=[{"title": "令牌缺失"}]),
        ) as llm_runner:
            await run_api_test(
                {"feature_item": {"feature": "登录"}},
                SkillContext(model_config=RuntimeModelConfig(), runtime=harness),
            )

        self.assertIs(llm_runner.await_args.kwargs["runtime"], harness)


if __name__ == "__main__":
    unittest.main()
