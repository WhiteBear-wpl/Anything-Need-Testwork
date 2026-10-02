import unittest

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.evaluation import EvalRun, EvalSample
from app.models.project import Project
from app.models.user import User


class EvaluationSnapshotModelTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(username="evaluation-snapshot-owner", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(user_id=self.user.id, name="evaluation snapshots", is_eval=True)
        self.db.add(self.project)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_snapshot_schema_links_runs_results_and_agent_queue(self):
        from app.models.evaluation import EvalRunSample, EvalResult
        from app.models.agent_run import AgentRun

        sample = EvalSample(project_id=self.project.id, title="登录", content="需求", checkpoints="[]")
        run = EvalRun(project_id=self.project.id, label="baseline")
        self.db.add_all([sample, run])
        self.db.flush()
        frozen = EvalRunSample(
            run_id=run.id,
            source_sample_id=sample.id,
            sample_version=1,
            title_snapshot=sample.title,
            content_snapshot=sample.content,
            checkpoints_snapshot=sample.checkpoints,
            content_sha256="content",
            checkpoints_sha256="checkpoints",
        )
        self.db.add(frozen)
        self.db.flush()
        result = EvalResult(run_id=run.id, sample_id=sample.id, run_sample_id=frozen.id)
        agent_run = AgentRun(project_id=self.project.id, evaluation_run_id=run.id)
        self.db.add_all([result, agent_run])
        self.db.commit()

        self.assertEqual(self.db.get(EvalResult, result.id).run_sample_id, frozen.id)
        self.assertEqual(self.db.get(AgentRun, agent_run.id).evaluation_run_id, run.id)
        self.assertTrue(self.db.get(EvalSample, sample.id).version >= 1)
        columns = {column["name"] for column in inspect(self.engine).get_columns("eval_runs")}
        self.assertTrue({"config_snapshot", "sample_set_fingerprint", "is_baseline", "agent_run_id"} <= columns)


if __name__ == "__main__":
    unittest.main()
