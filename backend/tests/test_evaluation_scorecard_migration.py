import unittest

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.evaluation import EvalResult, EvalRun, EvalSample
from app.models.project import Project
from app.models.user import User


class EvaluationScorecardModelTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="scorecard-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        project = Project(user_id=user.id, name="scorecards", is_eval=True)
        self.db.add(project)
        self.db.flush()
        sample = EvalSample(project_id=project.id, title="登录", content="登录需求")
        run = EvalRun(project_id=project.id, label="dual-track")
        self.db.add_all([sample, run])
        self.db.flush()
        self.result = EvalResult(run_id=run.id, sample_id=sample.id)
        self.db.add(self.result)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_eval_result_has_one_immutable_scorecard(self):
        from app.models.evaluation import EvaluationScorecard

        card = EvaluationScorecard(
            result_id=self.result.id,
            ruleset_version="p1-2b-rules-v1",
            rule_score=82,
            rule_verdict="pass",
            assessment_status="judge_unavailable",
        )
        self.db.add(card)
        self.db.commit()

        stored = self.db.get(EvalResult, self.result.id)
        self.assertEqual(stored.scorecard.rule_score, 82)
        self.assertEqual(stored.scorecard.assessment_status, "judge_unavailable")

        self.db.add(EvaluationScorecard(result_id=self.result.id, ruleset_version="p1-2b-rules-v1"))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()


if __name__ == "__main__":
    unittest.main()
