import unittest
from unittest.mock import AsyncMock, patch

from app.services.settings_service import RuntimeModelConfig
from app.skills.base import SkillContext
from app.skills.case_writer.handler import run as run_case_writer
from app.skills.shared.llm_runner import call_for_cases


class CapturingHarness:
    def __init__(self):
        self.stage = ""
        self.skill_name = ""
        self.calls = 0

    async def call_llm(
        self,
        stage,
        skill_name,
        operation,
        *,
        input_value,
        max_output_tokens,
    ):
        self.calls += 1
        self.stage = stage
        self.skill_name = skill_name
        return await operation()


class CaseWriterRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_skill_context_keeps_runtime_optional_for_existing_skills(self):
        harness = CapturingHarness()

        context = SkillContext(model_config=RuntimeModelConfig(), runtime=harness)

        self.assertIs(context.runtime, harness)

    async def test_shared_runner_does_not_double_wrap_the_structured_provider_call(self):
        """Catches one Skill invocation consuming two logical LLM budget units."""
        harness = CapturingHarness()
        generated = [{"title": "登录成功"}]

        with patch(
            "app.skills.shared.llm_runner.generate_cases", new=AsyncMock(return_value=generated)
        ):
            result = await call_for_cases(
                "system", "user", "case_writer", RuntimeModelConfig(), runtime=harness
            )

        self.assertEqual(result, generated)
        self.assertEqual(harness.calls, 0)

    async def test_case_writer_forwards_context_runtime_to_llm_runner(self):
        harness = CapturingHarness()
        with patch(
            "app.skills.case_writer.handler.call_for_cases",
            new=AsyncMock(return_value=[{"title": "登录成功"}]),
        ) as call_for_cases_mock:
            result = await run_case_writer(
                {"feature_item": {"feature": "登录"}},
                SkillContext(model_config=RuntimeModelConfig(), runtime=harness),
            )

        self.assertEqual(result, {"cases": [{"title": "登录成功"}]})
        self.assertIs(call_for_cases_mock.await_args.kwargs["runtime"], harness)


if __name__ == "__main__":
    unittest.main()
