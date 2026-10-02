import inspect
import tempfile
import unittest
from pathlib import Path

import yaml
from pydantic import BaseModel

from app.skills.errors import SkillDefinitionError
from app.skills.loader import discover_skills


def write_skill(
    root: Path,
    *,
    name: str = "fixture",
    entrypoint: str = "handler:run",
    handler_source: str = (
        "async def run(inputs, context):\n"
        "    return {'result': inputs['value']}\n"
    ),
    execution_order: int = 10,
    timeout_seconds: int = 420,
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": "1.0.0",
        "title": name,
        "description": "test specialist",
        "category": "specialist",
        "stage": "generation",
        "ui": {"selectable": True},
        "entrypoint": entrypoint,
        "input_model": "schemas:FixtureInput",
        "output_model": "schemas:FixtureOutput",
        "execution_order": execution_order,
        "timeout_seconds": timeout_seconds,
        "policy": {
            "max_cases": 5,
            "default_prompt_version": "v1",
            "prompt_versions": {"v1": "prompt.md"},
        },
    }
    (skill_dir / "skill.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True),
        encoding="utf-8",
    )
    (skill_dir / "handler.py").write_text(handler_source, encoding="utf-8")
    (skill_dir / "prompt.md").write_text("fixture prompt", encoding="utf-8")
    (skill_dir / "schemas.py").write_text(
        "from pydantic import BaseModel, ConfigDict\n"
        "class FixtureInput(BaseModel):\n"
        "    model_config = ConfigDict(extra='forbid')\n"
        "    value: int\n"
        "class FixtureOutput(BaseModel):\n"
        "    model_config = ConfigDict(extra='forbid')\n"
        "    result: int\n",
        encoding="utf-8",
    )
    return root


class SkillLoaderContractTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()

    def test_loader_builds_executable_definition(self):
        definitions = discover_skills(write_skill(self.temp_dir / "valid"))

        definition = definitions["fixture"]
        self.assertTrue(inspect.iscoroutinefunction(definition.handler))
        self.assertTrue(issubclass(definition.input_model, BaseModel))
        self.assertTrue(issubclass(definition.output_model, BaseModel))
        self.assertEqual(definition.meta.execution_order, 10)
        self.assertEqual(definition.meta.timeout_seconds, 420)

    def test_loader_rejects_external_module_and_non_async_handler(self):
        external = write_skill(
            self.temp_dir / "external",
            entrypoint="app.services.llm:run",
        )
        with self.assertRaisesRegex(SkillDefinitionError, "relative module"):
            discover_skills(external)

        sync_handler = write_skill(
            self.temp_dir / "sync",
            handler_source=(
                "def run(inputs, context):\n"
                "    return {'result': inputs['value']}\n"
            ),
        )
        with self.assertRaisesRegex(SkillDefinitionError, "async"):
            discover_skills(sync_handler)

    def test_loader_rejects_timeout_outside_contract(self):
        root = write_skill(self.temp_dir / "timeout", timeout_seconds=601)
        with self.assertRaisesRegex(SkillDefinitionError, "30.*600"):
            discover_skills(root)

    def test_loader_requires_version_and_selectable_specialist_order(self):
        missing_version = write_skill(self.temp_dir / "missing-version")
        version_manifest = missing_version / "fixture" / "skill.yaml"
        version_data = yaml.safe_load(version_manifest.read_text(encoding="utf-8"))
        version_data.pop("version")
        version_manifest.write_text(
            yaml.safe_dump(version_data, allow_unicode=True),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(SkillDefinitionError, "version"):
            discover_skills(missing_version)

        missing_order = write_skill(self.temp_dir / "missing-order")
        order_manifest = missing_order / "fixture" / "skill.yaml"
        order_data = yaml.safe_load(order_manifest.read_text(encoding="utf-8"))
        order_data.pop("execution_order")
        order_manifest.write_text(
            yaml.safe_dump(order_data, allow_unicode=True),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(SkillDefinitionError, "execution_order"):
            discover_skills(missing_order)

    def test_selectable_specialist_requires_valid_policy_block(self):
        missing_policy = write_skill(self.temp_dir / "missing-policy")
        missing_manifest_path = missing_policy / "fixture" / "skill.yaml"
        missing_manifest = yaml.safe_load(missing_manifest_path.read_text(encoding="utf-8"))
        missing_manifest.pop("policy")
        missing_manifest_path.write_text(yaml.safe_dump(missing_manifest), encoding="utf-8")
        with self.assertRaisesRegex(SkillDefinitionError, "policy"):
            discover_skills(missing_policy)

        invalid_prompt = write_skill(self.temp_dir / "invalid-prompt")
        manifest_path = invalid_prompt / "fixture" / "skill.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["policy"] = {
            "max_cases": 5,
            "default_prompt_version": "v2",
            "prompt_versions": {"v1": "../outside.md"},
        }
        manifest_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
        with self.assertRaisesRegex(SkillDefinitionError, "prompt"):
            discover_skills(invalid_prompt)

    def test_temporary_specialist_needs_no_central_enum(self):
        from app.skills.registry import SkillRegistry

        root = self.temp_dir / "dynamic"
        write_skill(root, name="security", execution_order=10)
        write_skill(root, name="performance", execution_order=15)
        write_skill(root, name="api_test", execution_order=20)
        registry = SkillRegistry(root=root)

        self.assertEqual(
            [item.name for item in registry.list_selectable_specialists()],
            ["security", "performance", "api_test"],
        )
        self.assertEqual(
            registry.resolve_specialists(
                ["performance", "security"],
                ["unknown", "performance", "security"],
            ),
            ["security", "performance"],
        )

    def test_specialist_selection_is_strict_for_writes_and_lenient_for_history(self):
        from app.skills.registry import SkillRegistry

        root = self.temp_dir / "validation"
        write_skill(root, name="security", execution_order=10)
        registry = SkillRegistry(root=root)

        with self.assertRaisesRegex(ValueError, "unknown"):
            registry.validate_specialist_selection(["unknown"], strict=True)
        self.assertEqual(
            registry.validate_specialist_selection(
                ["unknown", "security", "security"],
                strict=False,
            ),
            ["security"],
        )


if __name__ == "__main__":
    unittest.main()
