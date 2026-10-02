import asyncio
import unittest
from pathlib import Path

from pydantic import BaseModel

from app.services.settings_service import RuntimeModelConfig
from app.skills.base import SkillContext, SkillDefinition, SkillMeta
from app.skills.errors import SkillSnapshotDependencyError, SkillTimeoutError
from app.skills.executor import SkillExecutor
from app.skills.shared.prompt_loader import load_versioned_prompt


class SpecialistInput(BaseModel):
    feature_item: dict


class SpecialistOutput(BaseModel):
    cases: list[dict]


def specialist_definition(handler, timeout_seconds=420):
    return SkillDefinition(
        meta=SkillMeta(
            name="policy_fixture",
            version="1.0.0",
            title="Policy fixture",
            description="",
            category="specialist",
            stage="generation",
            timeout_seconds=timeout_seconds,
        ),
        handler=handler,
        input_model=SpecialistInput,
        output_model=SpecialistOutput,
    )


class SkillPolicyRuntimeTests(unittest.TestCase):
    def test_executor_uses_snapshot_timeout_and_caps_valid_specialist_cases(self):
        async def slow(inputs, context):
            await asyncio.sleep(0.05)
            return {"cases": []}

        with self.assertRaises(SkillTimeoutError):
            asyncio.run(SkillExecutor().execute(
                specialist_definition(slow),
                {"feature_item": {"feature": "login"}},
                SkillContext(model_config=RuntimeModelConfig(), timeout_seconds=0.01),
            ))

        async def many_cases(inputs, context):
            return {"cases": [{"id": index} for index in range(5)]}

        result = asyncio.run(SkillExecutor().execute(
            specialist_definition(many_cases),
            {"feature_item": {"feature": "login"}},
            SkillContext(model_config=RuntimeModelConfig(), max_cases=2),
        ))
        self.assertEqual(result["cases"], [{"id": 0}, {"id": 1}])

    def test_versioned_prompt_uses_exact_version_and_never_falls_back(self):
        security_dir = Path(__file__).resolve().parents[1] / "app" / "skills" / "security"
        prompt = load_versioned_prompt("security", security_dir, "v2")
        self.assertIn("POLICY_PROMPT_V2", prompt)

        with self.assertRaises(SkillSnapshotDependencyError):
            load_versioned_prompt("security", security_dir, "removed-version")


if __name__ == "__main__":
    unittest.main()
