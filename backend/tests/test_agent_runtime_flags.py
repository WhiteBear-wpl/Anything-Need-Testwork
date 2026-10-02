import unittest
from datetime import datetime

from app.config import Settings
from app.schemas import ProjectOut, ProjectUpdate


class AgentRuntimeFlagSchemaTests(unittest.TestCase):
    def test_settings_exposes_v2_flag_disabled_by_default(self):
        self.assertFalse(Settings().agent_runtime_v2_enabled)
        self.assertTrue(Settings(agent_runtime_v2_enabled=True).agent_runtime_v2_enabled)

    def test_unified_runtime_and_budget_mode_have_safe_defaults(self):
        """Catches rollout accidentally enabling hard enforcement by default."""
        defaults = Settings()
        self.assertFalse(defaults.unified_agent_runtime_enabled)
        self.assertEqual(defaults.runtime_budget_mode, "observe")
        enabled = Settings(
            unified_agent_runtime_enabled=True,
            runtime_budget_mode="enforce",
        )
        self.assertTrue(enabled.unified_agent_runtime_enabled)
        self.assertEqual(enabled.runtime_budget_mode, "enforce")

    def test_invalid_budget_mode_is_rejected(self):
        """Catches a typo silently disabling the intended enforcement policy."""
        with self.assertRaises(ValueError):
            Settings(runtime_budget_mode="hard")

    def test_project_schemas_allow_runtime_v2_opt_in(self):
        update = ProjectUpdate(agent_runtime_v2_enabled=True)
        project = type(
            "ProjectView",
            (),
            {
                "id": 1,
                "name": "runtime flag",
                "description": "",
                "agent_runtime_v2_enabled": True,
                "created_at": datetime(2026, 8, 9),
                "updated_at": datetime(2026, 8, 9),
            },
        )()

        self.assertTrue(update.agent_runtime_v2_enabled)
        self.assertTrue(ProjectOut.model_validate(project).agent_runtime_v2_enabled)


if __name__ == "__main__":
    unittest.main()
