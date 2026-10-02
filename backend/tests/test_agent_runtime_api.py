import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.generations import create_task
from app.database import Base
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.generation import GenerationTask
from app.models.project import Project
from app.models.requirement import RequirementDocument
from app.models.user import User
from app.schemas import AgentChatRequest, GenerationTaskCreate
from app.services.settings_service import RuntimeModelConfig


class AgentRuntimeApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="runtime-api-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        self.project = Project(user_id=user.id, name="runtime api", agent_runtime_v2_enabled=True)
        self.db.add(self.project)
        self.db.flush()
        self.document = RequirementDocument(project_id=self.project.id, title="doc", status="confirmed")
        self.db.add(self.document)
        self.db.flush()
        self.task = GenerationTask(project_id=self.project.id, document_id=self.document.id)
        self.db.add(self.task)
        self.db.flush()
        self.run = AgentRun(
            project_id=self.project.id,
            generation_task_id=self.task.id,
            agent_spec_snapshot="{}",
            budget_snapshot="{}",
        )
        self.db.add(self.run)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_v2_flags_queue_durable_run_without_background_task(self):
        background_tasks = BackgroundTasks()
        with patch("app.api.generations.settings.agent_runtime_v2_enabled", True):
            task = asyncio.run(
                create_task(
                    self.project.id,
                    GenerationTaskCreate(document_id=self.document.id),
                    background_tasks,
                    self.db,
                )
            )

        run = self.db.query(AgentRun).filter(AgentRun.generation_task_id == task.id).one()
        self.assertEqual(run.status, "queued")
        self.assertEqual(background_tasks.tasks, [])

    def test_either_flag_off_preserves_existing_background_task_path(self):
        self.project.agent_runtime_v2_enabled = False
        self.db.commit()
        background_tasks = BackgroundTasks()
        with patch("app.api.generations.settings.agent_runtime_v2_enabled", True):
            asyncio.run(
                create_task(
                    self.project.id,
                    GenerationTaskCreate(document_id=self.document.id),
                    background_tasks,
                    self.db,
                )
            )

        self.assertEqual(
            self.db.query(AgentRun)
            .filter(AgentRun.generation_task_id != self.task.id)
            .count(),
            0,
        )
        self.assertEqual(len(background_tasks.tasks), 1)

    def test_run_detail_and_incremental_events_are_scoped_to_generation_task(self):
        from app.agent_runtime.repository import AgentRunRepository
        from app.api.generations import get_task_run, list_task_run_events

        repository = AgentRunRepository(self.db)
        repository.append_event(self.run.id, "run_queued", stage="queue")
        repository.append_event(self.run.id, "node_started", stage="load_task")

        detail = get_task_run(self.project.id, self.task.id, self.db)
        events = list_task_run_events(self.project.id, self.task.id, after_sequence=1, db=self.db)

        self.assertEqual(detail.id, self.run.id)
        self.assertEqual([event.sequence for event in events], [2])
        self.assertEqual(events[0].stage, "load_task")

    def test_cancel_queued_run_returns_cancelled_terminal_state(self):
        from app.api.generations import cancel_task_run

        cancelled = cancel_task_run(self.project.id, self.task.id, self.db)

        self.assertEqual(cancelled.status, "cancelled")
        self.assertTrue(cancelled.cancel_requested)
        self.assertEqual(
            [
                event.event_type
                for event in self.db.query(AgentRunEvent)
                .filter_by(agent_run_id=self.run.id)
                .order_by(AgentRunEvent.sequence)
                .all()
            ],
            ["run_cancel_requested", "run_cancelled"],
        )

    def test_retry_terminal_v2_run_creates_fresh_resume_run(self):
        from app.api.generations import retry_task_run

        self.run.status = "failed"
        self.db.commit()
        with patch("app.api.generations.settings.agent_runtime_v2_enabled", True):
            retry_run = retry_task_run(self.project.id, self.task.id, self.db)

        self.assertNotEqual(retry_run.id, self.run.id)
        self.assertEqual(retry_run.status, "queued")
        self.assertEqual(json.loads(retry_run.agent_spec_snapshot)["execution_mode"], "resume")

    def test_chat_creates_inline_parent_only_when_all_unified_flags_are_on(self):
        from app.api.agent import chat

        with (
            patch("app.api.agent.settings.agent_runtime_v2_enabled", True),
            patch("app.api.agent.settings.unified_agent_runtime_enabled", True),
            patch(
                "app.api.agent.get_project_runtime_config",
                return_value=RuntimeModelConfig(llm_mock_mode=True),
            ),
            patch("app.api.agent.inline_agent_supervisor.start") as start_inline,
        ):
            response = asyncio.run(
                chat(
                    self.project.id,
                    AgentChatRequest(question="有哪些用例"),
                    self.project,
                    self.db,
                )
            )

        self.assertEqual(response.media_type, "text/event-stream")
        parent = (
            self.db.query(AgentRun)
            .filter(AgentRun.project_id == self.project.id, AgentRun.run_kind == "chat")
            .one()
        )
        self.assertEqual(parent.execution_mode, "inline")
        self.assertEqual(parent.status, "queued")
        self.assertIsNotNone(parent.message_id)
        start_inline.assert_called_once()


if __name__ == "__main__":
    unittest.main()
