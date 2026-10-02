import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent_runtime.contracts import BudgetExhausted, RunContext, RuntimeCancelled
from app.database import Base
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.evaluation import EvalRun
from app.models.project import Project
from app.models.user import User


class EvaluationWorkerTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="evaluation-worker-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        project = Project(user_id=user.id, name="evaluation worker", is_eval=True)
        self.db.add(project)
        self.db.flush()
        self.run = EvalRun(project_id=project.id, label="candidate", config_snapshot='{"strategy":"full"}')
        self.db.add(self.run)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_evaluation_runner_is_queued_with_its_immutable_snapshot(self):
        from app.agent_runtime.service import create_evaluation_runner_run

        agent_run = create_evaluation_runner_run(self.db, self.run, model_snapshot={"api_key": "secret", "model": "mock"})
        snapshot = json.loads(agent_run.agent_spec_snapshot)

        self.assertEqual(agent_run.evaluation_run_id, self.run.id)
        self.assertEqual(snapshot["name"], "evaluation_runner")
        self.assertEqual(snapshot["evaluation_run_id"], self.run.id)
        self.assertNotIn("secret", agent_run.agent_spec_snapshot)

    def test_worker_dispatches_evaluation_runner_by_snapshot_name(self):
        from app.agent_runtime.service import create_evaluation_runner_run
        from app.worker import SQLiteAgentWorker

        queued = create_evaluation_runner_run(self.db, self.run, model_snapshot={})
        calls = []

        async def evaluation_runner(eval_run_id, *, run_context):
            calls.append((eval_run_id, run_context.run_id))

        worker = SQLiteAgentWorker(
            self.db.bind and sessionmaker(bind=self.engine),
            worker_id="evaluation-worker",
            evaluation_runner=evaluation_runner,
        )
        self.assertTrue(worker.run_once(now=datetime(2026, 8, 10, 9, 0, 0)))
        self.assertEqual(calls, [(self.run.id, queued.id)])

    def test_invalid_evaluation_snapshot_marks_both_runs_failed(self):
        from app.agent_runtime.service import create_evaluation_runner_run
        from app.services.evaluation_service import run_evaluation_workflow

        queued = create_evaluation_runner_run(self.db, self.run, model_snapshot={})
        queued.status = "running"
        queued.lease_owner = "evaluation-worker"
        self.db.commit()
        context = RunContext(
            run_id=queued.id,
            project_id=queued.project_id,
            task_id=0,
            spec_snapshot={"name": "evaluation_runner", "evaluation_run_id": self.run.id},
        )

        with patch("app.services.evaluation_service.SessionLocal", sessionmaker(bind=self.engine)):
            with self.assertRaisesRegex(ValueError, "incomplete immutable config snapshot"):
                asyncio.run(run_evaluation_workflow(self.run.id, run_context=context))

        self.db.refresh(self.run)
        self.db.refresh(queued)
        self.assertEqual(self.run.status, "failed")
        self.assertEqual(queued.status, "failed")
        events = self.db.scalars(
            select(AgentRunEvent).where(AgentRunEvent.agent_run_id == queued.id)
        ).all()
        self.assertEqual([event.event_type for event in events], ["run_failed"])

    def test_cancelled_event_uses_the_exact_worker_terminal_timestamp(self):
        from app.agent_runtime.service import create_evaluation_runner_run
        from app.services.evaluation_service import run_evaluation_workflow

        queued = create_evaluation_runner_run(self.db, self.run, model_snapshot={})
        queued.status = "running"
        self.db.commit()
        context = RunContext(
            run_id=queued.id,
            project_id=queued.project_id,
            task_id=0,
            spec_snapshot={"name": "evaluation_runner", "evaluation_run_id": self.run.id},
        )

        with patch(
            "app.services.evaluation_service.SessionLocal", sessionmaker(bind=self.engine)
        ), patch(
            "app.services.evaluation_service.run_evaluation",
            new=AsyncMock(side_effect=RuntimeCancelled("stop")),
        ):
            asyncio.run(run_evaluation_workflow(self.run.id, run_context=context))

        self.db.refresh(queued)
        event = self.db.scalars(
            select(AgentRunEvent).where(
                AgentRunEvent.agent_run_id == queued.id,
                AgentRunEvent.event_type == "run_cancelled",
            )
        ).one()
        self.assertEqual(event.created_at, queued.finished_at)

    def test_budget_exhaustion_marks_evaluation_and_agent_run_without_failure(self):
        """Catches Judge budget stops being collapsed into evaluation failure."""
        from app.agent_runtime.service import create_evaluation_runner_run
        from app.services.evaluation_service import run_evaluation_workflow

        queued = create_evaluation_runner_run(self.db, self.run, model_snapshot={})
        queued.status = "running"
        self.run.status = "running"
        self.db.commit()
        context = RunContext(
            run_id=queued.id,
            project_id=queued.project_id,
            task_id=0,
            spec_snapshot={"name": "evaluation_runner", "evaluation_run_id": self.run.id},
        )

        with patch(
            "app.services.evaluation_service.SessionLocal", sessionmaker(bind=self.engine)
        ), patch(
            "app.services.evaluation_service.run_evaluation",
            new=AsyncMock(side_effect=BudgetExhausted("tokens", 100, 100)),
        ):
            asyncio.run(run_evaluation_workflow(self.run.id, run_context=context))

        self.db.refresh(self.run)
        self.db.refresh(queued)
        self.assertEqual(self.run.status, "budget_exhausted")
        self.assertEqual(queued.status, "budget_exhausted")
        events = self.db.scalars(
            select(AgentRunEvent).where(AgentRunEvent.agent_run_id == queued.id)
        ).all()
        self.assertEqual([event.event_type for event in events], ["run_budget_exhausted"])


if __name__ == "__main__":
    unittest.main()
