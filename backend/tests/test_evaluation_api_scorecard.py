import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.evaluations import _scorecard_to_out, list_runs
from app.database import Base
from app.models.evaluation import EvaluationScorecard, EvalResult, EvalRun, EvalSample
from app.models.project import Project
from app.models.user import User


class EvaluationScorecardApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="evaluation-api-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        self.project = Project(user_id=user.id, name="evaluation api", is_eval=True)
        self.db.add(self.project)
        self.db.flush()
        self.project_id = self.project.id
        run = EvalRun(project_id=self.project.id, label="run", status="completed")
        self.db.add(run)
        self.db.flush()
        for index in range(2):
            sample = EvalSample(project_id=self.project.id, title=f"sample-{index}", content="需求")
            self.db.add(sample)
            self.db.flush()
            result = EvalResult(run_id=run.id, sample_id=sample.id, status="completed")
            self.db.add(result)
            self.db.flush()
            self.db.add(EvaluationScorecard(
                result_id=result.id,
                ruleset_version="rules-v1",
                rule_score=100,
                rule_verdict="pass",
                rule_dimensions=json.dumps({
                    "schema_version": "2",
                    "cases": {},
                    "suite": {"checkpoint_coverage": {"score": 100}},
                }),
            ))
        self.db.commit()
        self.db.expunge_all()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_run_list_preloads_scorecards_without_per_result_queries(self):
        statements = []

        def before_execute(*args):
            statements.append(args[2])

        event.listen(self.engine, "before_cursor_execute", before_execute)
        try:
            with patch("app.api.evaluations._eval_project", return_value=SimpleNamespace(id=self.project_id)):
                output = list_runs(self.db)
        finally:
            event.remove(self.engine, "before_cursor_execute", before_execute)

        self.assertEqual(len(output[0].results), 2)
        self.assertLessEqual(len(statements), 2)

    def test_scorecard_serializer_preserves_legacy_and_version_two_rule_shapes(self):
        legacy = EvaluationScorecard(
            ruleset_version="rules-v1",
            rule_dimensions=json.dumps({"1": {"dimensions": {}}}),
        )
        current = EvaluationScorecard(
            ruleset_version="rules-v2",
            rule_dimensions=json.dumps({"schema_version": "2", "cases": {}, "suite": {}}),
        )

        self.assertIn("1", _scorecard_to_out(legacy)["rule_dimensions"])
        self.assertEqual(_scorecard_to_out(current)["rule_dimensions"]["schema_version"], "2")


if __name__ == "__main__":
    unittest.main()
