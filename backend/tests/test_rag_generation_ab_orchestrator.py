import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from benchmarks.rag_generation_ab.orchestrator import build_experiments, resolve_eval_project


class ABOrchestratorTests(unittest.TestCase):
    def test_only_rag_flag_differs_between_experiments(self):
        baseline, treatment = build_experiments()
        self.assertFalse(baseline["use_knowledge"])
        self.assertTrue(treatment["use_knowledge"])
        self.assertEqual({k: v for k, v in baseline.items() if k != "use_knowledge"}, {k: v for k, v in treatment.items() if k != "use_knowledge"})

    def test_reuses_the_users_single_eval_project(self):
        existing = SimpleNamespace(id=7, user_id=3, is_eval=True)
        db = MagicMock()
        db.query.return_value.filter.return_value.one_or_none.return_value = existing

        resolved = resolve_eval_project(db, user_id=3)

        self.assertIs(resolved, existing)
        db.add.assert_not_called()
        db.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
