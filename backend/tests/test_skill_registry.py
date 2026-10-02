import asyncio
import unittest

from pydantic import BaseModel

from app.services.settings_service import RuntimeModelConfig
from app.skills.base import SkillContext
from app.skills.errors import SkillInputError
from app.skills.registry import get_registry


class SkillRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = get_registry()

    def test_discovers_core_and_specialist_skills(self):
        names = {s.name for s in self.registry.list_skills()}
        self.assertIn("requirement_parser", names)
        self.assertIn("case_writer", names)
        self.assertIn("security", names)
        self.assertIn("api_test", names)

    def test_list_selectable_specialists(self):
        names = [s.name for s in self.registry.list_selectable_specialists()]
        self.assertEqual(names, ["security", "api_test"])

    def test_all_builtin_skills_declare_executable_contracts(self):
        for meta in self.registry.list_skills():
            definition = self.registry.get_definition(meta.name)
            self.assertTrue(issubclass(definition.input_model, BaseModel))
            self.assertTrue(issubclass(definition.output_model, BaseModel))
            self.assertGreaterEqual(meta.timeout_seconds, 30)

    def test_specialists_are_sorted_by_execution_order(self):
        self.assertEqual(
            [s.name for s in self.registry.list_selectable_specialists()],
            ["security", "api_test"],
        )

    def test_legacy_api_alias(self):
        self.assertEqual(self.registry.resolve_skill_name("api"), "api_test")
        validated = self.registry.validate_specialist_skills(["api", "security"])
        self.assertEqual(validated, ["security", "api_test"])

    def test_list_strategies_from_manifest(self):
        keys = [s["key"] for s in self.registry.list_strategies()]
        self.assertEqual(keys, ["full", "quick"])

    def test_run_case_writer_mock(self):
        async def _run():
            ctx = SkillContext(model_config=RuntimeModelConfig(), use_mock=True, strategy="quick")
            result = await self.registry.run(
                "case_writer",
                {"feature_item": {"feature": "登录"}, "strategy": "quick"},
                ctx,
            )
            return result

        result = asyncio.run(_run())
        self.assertGreaterEqual(len(result["cases"]), 2)
        self.assertEqual(result["cases"][0]["skill_name"], "case_writer")

    def test_all_builtin_skills_run_through_declared_mock_contracts(self):
        async def _run_all():
            ctx = SkillContext(model_config=RuntimeModelConfig(), use_mock=True)
            feature = {"feature": "登录"}
            cases = [{"title": "登录成功", "steps": ["提交"], "expected_result": "成功"}]
            return {
                "requirement_parser": await self.registry.run(
                    "requirement_parser", {"raw_content": "登录需求"}, ctx
                ),
                "test_proposal": await self.registry.run(
                    "test_proposal", {"raw_content": "登录需求"}, ctx
                ),
                "case_writer": await self.registry.run(
                    "case_writer", {"feature_item": feature}, ctx
                ),
                "security": await self.registry.run(
                    "security", {"feature_item": feature, "core_cases": cases}, ctx
                ),
                "api_test": await self.registry.run(
                    "api_test", {"feature_item": feature, "core_cases": cases}, ctx
                ),
                "case_judge": await self.registry.run(
                    "case_judge", {"feature_item": feature, "cases": cases}, ctx
                ),
            }

        results = asyncio.run(_run_all())
        self.assertEqual(len(results["requirement_parser"]["items"]), 2)
        self.assertIn("in_scope", results["test_proposal"]["scope"])
        for name in ("case_writer", "security", "api_test"):
            self.assertTrue(results[name]["cases"])
            self.assertEqual(results[name]["cases"][0]["skill_name"], name)
        self.assertEqual(results["case_judge"]["judgements"][0]["overall"], 4.3)

    def test_case_writer_rejects_undeclared_top_level_input(self):
        ctx = SkillContext(model_config=RuntimeModelConfig(), use_mock=True)
        with self.assertRaises(SkillInputError):
            asyncio.run(
                self.registry.run(
                    "case_writer",
                    {"feature_item": {"feature": "登录"}, "unexpected": "value"},
                    ctx,
                )
            )


if __name__ == "__main__":
    unittest.main()
