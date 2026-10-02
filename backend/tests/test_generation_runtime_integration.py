import asyncio
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent_runtime.contracts import RunContext, RuntimeCancelled
from app.agent_runtime.harness import RuntimeHarness
from app.agent_runtime.repository import AgentRunRepository
from app.database import Base
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.project import Project
from app.models.user import User


class GenerationRuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="generation-runtime-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        project = Project(user_id=user.id, name="generation runtime")
        self.db.add(project)
        self.db.flush()
        self.run = AgentRun(project_id=project.id, agent_spec_snapshot="{}", budget_snapshot="{}")
        self.db.add(self.run)
        self.db.commit()
        self.harness = RuntimeHarness(
            self.db,
            RunContext(
                run_id=self.run.id,
                project_id=project.id,
                task_id=0,
                spec_snapshot={"name": "case_writer"},
            ),
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_instrumented_node_records_boundaries_and_exposes_runtime_to_skill_context(self):
        from app.agent_runtime.harness import get_active_runtime_harness
        from app.workflows.generation.graph import with_runtime_lifecycle

        async def node(state):
            self.assertIs(get_active_runtime_harness(), self.harness)
            return {"task_id": state["task_id"], "current_cases": []}

        result = asyncio.run(with_runtime_lifecycle("load_task", node, self.harness)({"task_id": 7}))

        self.assertEqual(result["task_id"], 7)
        events = self.db.scalars(
            select(AgentRunEvent).where(AgentRunEvent.agent_run_id == self.run.id)
        ).all()
        self.assertEqual([event.event_type for event in events], ["node_started", "node_finished"])
        self.assertEqual([event.stage for event in events], ["load_task", "load_task"])

    def test_instrumented_node_honours_cancellation_before_running_node(self):
        from app.workflows.generation.graph import with_runtime_lifecycle

        AgentRunRepository(self.db).request_cancel(self.run.id)
        invoked = False

        async def node(_state):
            nonlocal invoked
            invoked = True
            return {}

        with self.assertRaises(RuntimeCancelled):
            asyncio.run(with_runtime_lifecycle("load_task", node, self.harness)({"task_id": 7}))

        self.assertFalse(invoked)


if __name__ == "__main__":
    unittest.main()
