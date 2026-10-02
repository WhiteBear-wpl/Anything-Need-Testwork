import unittest
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent_runtime.repository import AgentRunRepository
from app.database import Base
from app.models.agent import AgentThread
from app.models.agent_run import AgentRun
from app.models.project import Project
from app.models.user import User


class AgentRunApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="run-api", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        first = Project(user_id=user.id, name="first")
        second = Project(user_id=user.id, name="second")
        self.db.add_all([first, second])
        self.db.flush()
        self.thread = AgentThread(project_id=first.id, title="default")
        self.db.add(self.thread)
        self.db.flush()
        self.parent = AgentRun(
            project_id=first.id,
            thread_id=self.thread.id,
            run_kind="chat",
            execution_mode="inline",
            status="running",
        )
        self.foreign = AgentRun(project_id=second.id, status="running")
        self.db.add_all([self.parent, self.foreign])
        self.db.flush()
        self.child = AgentRun(
            project_id=first.id,
            parent_run_id=self.parent.id,
            run_kind="generation",
            execution_mode="worker",
            status="running",
        )
        self.db.add(self.child)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_detail_events_children_and_cancel_are_project_scoped(self):
        from app.api.agent_runs import (
            cancel_agent_run,
            get_agent_run,
            list_agent_run_children,
            list_agent_run_events,
        )

        AgentRunRepository(self.db).append_event(self.parent.id, "assistant_started")
        self.assertEqual(get_agent_run(self.parent.project_id, self.parent.id, self.db).id, self.parent.id)
        self.assertEqual(
            [event.event_type for event in list_agent_run_events(
                self.parent.project_id, self.parent.id, 0, self.db
            )],
            ["assistant_started"],
        )
        self.assertEqual(
            [run.id for run in list_agent_run_children(
                self.parent.project_id, self.parent.id, self.db
            )],
            [self.child.id],
        )
        cancelled = cancel_agent_run(self.parent.project_id, self.parent.id, self.db)
        self.assertEqual(cancelled.status, "running")
        self.assertTrue(cancelled.cancel_requested)
        self.db.refresh(self.child)
        self.assertEqual(self.child.status, "running")
        with self.assertRaises(HTTPException) as raised:
            get_agent_run(self.parent.project_id, self.foreign.id, self.db)
        self.assertEqual(raised.exception.status_code, 404)

    def test_waiting_parent_cancel_clears_pending_approval_without_touching_child(self):
        from app.api.agent_runs import cancel_agent_run

        self.parent.status = "waiting_human"
        self.parent.waiting_since = datetime.now()
        self.thread.pending_approval = '{"agent_run_id": %d}' % self.parent.id
        self.thread.checkpoint_thread_id = "checkpoint-secret"
        self.db.commit()

        cancelled = cancel_agent_run(self.parent.project_id, self.parent.id, self.db)

        self.assertEqual(cancelled.status, "cancelled")
        self.db.refresh(self.thread)
        self.db.refresh(self.child)
        self.assertEqual(self.thread.pending_approval, "")
        self.assertEqual(self.thread.checkpoint_thread_id, "")
        self.assertEqual(self.child.status, "running")

    def test_rollout_report_deduplicates_warning_and_would_exhaust_runs(self):
        from app.api.agent_runs import get_rollout_report

        self.parent.usage_accounting_version = 1
        self.child.usage_accounting_version = 1
        self.foreign.usage_accounting_version = 1
        historical = AgentRun(
            project_id=self.parent.project_id,
            run_kind="evaluation",
            status="completed",
            usage_accounting_version=0,
        )
        self.db.add(historical)
        self.db.commit()
        repo = AgentRunRepository(self.db)
        repo.append_event(self.parent.id, "budget_warning")
        repo.append_event(self.parent.id, "budget_warning")
        repo.append_event(self.child.id, "budget_would_exhaust")

        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.api.agent_runs.settings.runtime_budget_mode", "observe"
        ):
            report = get_rollout_report(self.parent.project_id, 100, self.db)

        self.assertEqual(report["mode"], "observe")
        self.assertEqual(report["runs"], 3)
        self.assertEqual(report["warnings"], 1)
        self.assertEqual(report["would_exhaust"], 1)
        self.assertEqual(report["usage_accounting_unknown"], 1)
        self.assertEqual(report["by_kind"]["chat"], {"runs": 1, "warnings": 1})


if __name__ == "__main__":
    unittest.main()
