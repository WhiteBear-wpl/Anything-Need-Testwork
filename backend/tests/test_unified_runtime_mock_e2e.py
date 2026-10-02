import asyncio
import json
import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent.tools import build_agent_tools
from app.agent_runtime.budget import BudgetLedger
from app.agent_runtime.contracts import BudgetExhausted, BudgetMode, ExecutionBudget, RunContext
from app.agent_runtime.inline import stream_run_events
from app.agent_runtime.repository import AgentRunRepository
from app.agent_runtime.service import create_assistant_run, create_case_writer_run
from app.database import Base
from app.models.agent import AgentMessage, AgentThread
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.generation import GenerationTask
from app.models.project import Project
from app.models.requirement import RequirementDocument, RequirementItem
from app.models.user import User
from app.services.settings_service import RuntimeModelConfig


class UnifiedRuntimeMockE2E(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.db = self.session_factory()
        user = User(username="unified-e2e", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        self.project = Project(user_id=user.id, name="unified", agent_runtime_v2_enabled=True)
        self.db.add(self.project)
        self.db.flush()
        self.thread = AgentThread(project_id=self.project.id)
        self.db.add(self.thread)
        self.db.flush()
        self.message = AgentMessage(
            project_id=self.project.id,
            thread_id=self.thread.id,
            role="user",
            content="确认生成",
        )
        self.db.add(self.message)
        self.doc = RequirementDocument(
            project_id=self.project.id,
            title="登录",
            status="confirmed",
        )
        self.db.add(self.doc)
        self.db.flush()
        self.db.add(RequirementItem(
            document_id=self.doc.id,
            feature="密码登录",
            confirmed=True,
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_parent_child_replay_exhaustion_and_fresh_resume_lineage(self):
        parent = create_assistant_run(
            self.db,
            project_id=self.project.id,
            thread_id=self.thread.id,
            message_id=self.message.id,
            model_snapshot={"model": "mock"},
        )
        self.assertEqual((parent.run_kind, parent.execution_mode), ("chat", "inline"))
        AgentRunRepository(self.db).start_inline(parent.id, datetime.now())
        tools = {
            tool.name: tool for tool in build_agent_tools(
                self.db,
                self.project.id,
                RuntimeModelConfig(llm_mock_mode=True),
                parent_run_id=parent.id,
            )
        }
        output = json.loads(asyncio.run(tools["start_generation"].ainvoke({
            "document_id": self.doc.id,
        })))
        child = self.db.get(AgentRun, output["agent_run_id"])
        self.assertEqual(child.parent_run_id, parent.id)
        events = self.db.query(AgentRunEvent).filter_by(agent_run_id=parent.id).order_by(AgentRunEvent.sequence).all()
        self.assertIn("child_run_created", [event.event_type for event in events])

        AgentRunRepository(self.db).append_event(
            parent.id,
            "assistant_output_delta",
            payload_summary='{"content":"已完成部分"}',
        )
        cursor = events[-1].sequence
        AgentRunRepository(self.db).mark_terminal(parent.id, "budget_exhausted")
        replayed = asyncio.run(self._collect(parent.id, cursor))
        self.assertEqual(len({event.sequence for event in replayed}), len(replayed))
        self.assertTrue(all(event.sequence > cursor for event in replayed))

        tiny_run = create_assistant_run(
            self.db,
            project_id=self.project.id,
            thread_id=self.thread.id,
            message_id=self.message.id + 100,
            model_snapshot={"model": "mock"},
        )
        AgentRunRepository(self.db).start_inline(tiny_run.id, datetime.now())
        AgentRunRepository(self.db).append_event(
            tiny_run.id,
            "assistant_output_delta",
            payload_summary='{"content":"保留"}',
        )
        context = RunContext(
            run_id=tiny_run.id,
            project_id=self.project.id,
            task_id=0,
            budget=ExecutionBudget(max_llm_calls=0, max_tokens=1),
        )
        with self.assertRaises(BudgetExhausted):
            BudgetLedger(self.db, context, mode=BudgetMode.ENFORCE).reserve_llm(
                input_tokens=1,
                max_output_tokens=1,
            )
        preserved = self.db.query(AgentRunEvent).filter_by(
            agent_run_id=tiny_run.id,
            event_type="assistant_output_delta",
        ).one()
        self.assertIn("保留", preserved.payload_summary)

        child.status = "budget_exhausted"
        self.db.commit()
        resumed = create_case_writer_run(
            self.db,
            self.db.get(GenerationTask, child.generation_task_id),
            model_snapshot={"model": "mock"},
            resume=True,
            parent_run_id=parent.id,
            resume_from_run_id=child.id,
        )
        self.assertNotEqual(resumed.id, child.id)
        self.assertEqual(resumed.resume_from_run_id, child.id)

    async def _collect(self, run_id, cursor):
        return [event async for event in stream_run_events(
            self.session_factory,
            run_id,
            after_sequence=cursor,
            poll_seconds=0.01,
        )]


if __name__ == "__main__":
    unittest.main()
