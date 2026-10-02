import unittest

from app.skills.base import SkillMeta, SkillPolicyDefaults, SkillUIConfig
from app.skills.policy import PolicyResolver, ProjectSkillOverride


class StubRegistry:
    def __init__(self):
        self._skills = [
            SkillMeta(
                name="security",
                version="1.0.0",
                title="Security",
                description="",
                category="specialist",
                stage="generation",
                ui=SkillUIConfig(selectable=True),
                execution_order=10,
                timeout_seconds=420,
                policy=SkillPolicyDefaults(
                    max_cases=5,
                    default_prompt_version="v1",
                    prompt_versions={"v1": "prompt.md", "v2": "prompts/v2.md"},
                ),
            ),
            SkillMeta(
                name="api_test",
                version="1.0.0",
                title="API",
                description="",
                category="specialist",
                stage="generation",
                ui=SkillUIConfig(selectable=True),
                execution_order=20,
                timeout_seconds=300,
                policy=SkillPolicyDefaults(
                    max_cases=4,
                    default_prompt_version="v1",
                    prompt_versions={"v1": "prompt.md"},
                ),
            ),
        ]

    def list_selectable_specialists(self):
        return list(self._skills)

    def resolve_skill_name(self, name):
        return {"api": "api_test"}.get(name, name)


class SkillPolicyResolverTests(unittest.TestCase):
    def setUp(self):
        self.resolver = PolicyResolver(StubRegistry())

    def test_resolver_inherits_manifest_defaults_and_orders_ties_by_name(self):
        resolved = self.resolver.resolve(
            [
                ProjectSkillOverride("security", True, timeout_seconds=180, execution_order=10),
                ProjectSkillOverride("api_test", True, max_cases=2, execution_order=10),
            ],
            revision_no=4,
        )

        self.assertEqual(resolved.revision_no, 4)
        self.assertEqual(
            [item.skill_name for item in resolved.enabled_specialists],
            ["api_test", "security"],
        )
        self.assertEqual(resolved.by_name["security"].timeout_seconds, 180)
        self.assertEqual(resolved.by_name["security"].max_cases, 5)
        self.assertEqual(resolved.by_name["api_test"].prompt_version, "v1")
        self.assertEqual(resolved.by_name["api_test"].max_cases, 2)

    def test_missing_override_is_disabled_and_requested_disabled_skill_is_rejected(self):
        resolved = self.resolver.resolve([], revision_no=0)
        self.assertFalse(resolved.by_name["security"].enabled)
        self.assertFalse(resolved.by_name["api_test"].enabled)

        with self.assertRaisesRegex(ValueError, "disabled.*security"):
            self.resolver.resolve_requested([], ["security"], revision_no=0)

    def test_resolver_rejects_duplicate_unknown_budget_and_prompt_overrides(self):
        invalid_cases = [
            ([ProjectSkillOverride("security", True), ProjectSkillOverride("security", False)], "duplicate"),
            ([ProjectSkillOverride("unknown", True)], "unknown"),
            ([ProjectSkillOverride("security", True, timeout_seconds=421)], "timeout_seconds"),
            ([ProjectSkillOverride("security", True, max_cases=6)], "max_cases"),
            ([ProjectSkillOverride("security", True, prompt_version="v9")], "prompt_version"),
            ([ProjectSkillOverride("security", True, execution_order=10001)], "execution_order"),
        ]
        for overrides, message in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.resolver.resolve(overrides, revision_no=1)

    def test_snapshot_is_json_safe_and_catalog_changes_change_fingerprint(self):
        first = self.resolver.resolve(
            [ProjectSkillOverride("security", True, prompt_version="v2")],
            revision_no=2,
        )
        snapshot = first.to_snapshot()
        self.assertEqual(snapshot["policy_revision"], 2)
        self.assertEqual(snapshot["specialists"]["security"]["prompt_version"], "v2")
        self.assertNotIn("prompt.md", str(snapshot))

        self.resolver.registry._skills[0].version = "2.0.0"
        second = self.resolver.resolve(
            [ProjectSkillOverride("security", True, prompt_version="v2")],
            revision_no=2,
        )
        self.assertNotEqual(first.catalog_fingerprint, second.catalog_fingerprint)


if __name__ == "__main__":
    unittest.main()
