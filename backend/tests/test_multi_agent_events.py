import json
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent_runtime.contracts import ExecutionBudget, RunContext
from app.database import Base
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.project import Project
from app.models.user import User


class MultiAgentEventTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="multi-agent-event-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        project = Project(user_id=user.id, name="multi agent events")
        self.db.add(project)
        self.db.flush()
        self.run = AgentRun(
            project_id=project.id,
            agent_spec_snapshot="{}",
            budget_snapshot="{}",
        )
        self.db.add(self.run)
        self.db.commit()
        self.context = RunContext(
            run_id=self.run.id,
            project_id=project.id,
            task_id=0,
            spec_snapshot={"name": "case_writer"},
            budget=ExecutionBudget(),
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_agent_event_persists_only_bounded_redacted_summary(self):
        """Catches lifecycle events leaking provider credentials or arbitrary payload fields."""
        from app.agent_runtime.harness import RuntimeHarness

        harness = RuntimeHarness(self.db, self.context)
        harness.record_agent_event(
            "agent_warning",
            "security",
            candidate_count=-4,
            duration_ms=17,
            message="Authorization: Bearer secret-token provider failed",
        )

        event = self.db.scalar(
            select(AgentRunEvent).where(AgentRunEvent.agent_run_id == self.run.id)
        )
        payload = json.loads(event.payload_summary)
        self.assertEqual(event.stage, "specialist")
        self.assertEqual(set(payload), {"agent", "candidate_count", "duration_ms", "message"})
        self.assertEqual(payload["agent"], "security")
        self.assertEqual(payload["candidate_count"], 0)
        self.assertEqual(payload["duration_ms"], 17)
        self.assertIn("[REDACTED]", payload["message"])
        self.assertNotIn("secret-token", event.payload_summary)


if __name__ == "__main__":
    unittest.main()
