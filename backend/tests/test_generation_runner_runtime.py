import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent_runtime.contracts import BudgetExhausted, RunContext, RuntimeCancelled
from app.database import Base
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.generation import GeneratedCaseDraft, GenerationTask
from app.models.project import Project
from app.models.requirement import RequirementDocument
from app.models.user import User
from app.workflows.generation.runner import run_generation_workflow


class _FakeCheckpointer:
    async def setup(self):
        return None


@asynccontextmanager
async def _fake_checkpoint_context():
    yield _FakeCheckpointer()


class _SuccessfulGraph:
    async def ainvoke(self, _inputs, *, config):
        self.config = config


class _CancelledGraph:
    async def ainvoke(self, _inputs, *, config):
        raise RuntimeCancelled("cancelled in graph")


class _FailedGraph:
    async def ainvoke(self, _inputs, *, config):
        raise ConnectionError("provider unavailable token=secret-token password=hunter2")


class _BudgetExhaustedGraph:
    async def ainvoke(self, _inputs, *, config):
        raise BudgetExhausted("llm_calls", 1, 1)


class GenerationRunnerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.session_factory = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)
        self.db = self.session_factory()
        user = User(username="generation-runner-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        project = Project(user_id=user.id, name="generation runner")
        self.db.add(project)
        self.db.flush()
        document = RequirementDocument(project_id=project.id, title="doc")
        self.db.add(document)
        self.db.flush()
        self.task = GenerationTask(project_id=project.id, document_id=document.id)
        self.db.add(self.task)
        self.db.flush()
        self.run = AgentRun(
            project_id=project.id,
            generation_task_id=self.task.id,
            agent_spec_snapshot="{}",
            budget_snapshot="{}",
        )
        self.db.add(self.run)
        self.db.commit()
        self.context = RunContext(
            run_id=self.run.id,
            project_id=project.id,
            task_id=self.task.id,
            spec_snapshot={"name": "case_writer"},
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_runtime_success_marks_agent_run_completed_and_keeps_existing_graph_owner(self):
        inherited_draft = GeneratedCaseDraft(
            task_id=self.task.id,
            title="Draft persisted before checkpoint resume",
            agent_run_id=None,
        )
        self.db.add(inherited_draft)
        self.db.commit()
        graph = _SuccessfulGraph()

        def build_with_runtime(checkpointer, *, runtime):
            self.assertIsInstance(checkpointer, _FakeCheckpointer)
            self.assertEqual(runtime.context.run_id, self.run.id)
            return graph

        with (
            patch("app.workflows.generation.runner.SessionLocal", self.session_factory),
            patch("app.workflows.generation.runner.checkpoint_context", _fake_checkpoint_context),
            patch("app.workflows.generation.runner.build_generation_graph", side_effect=build_with_runtime),
        ):
            asyncio.run(run_generation_workflow(self.task.id, run_context=self.context))

        self.db.refresh(self.run)
        self.db.refresh(inherited_draft)
        self.assertEqual(self.run.status, "completed")
        self.assertEqual(inherited_draft.agent_run_id, self.run.id)
        self.assertIsNotNone(self.run.finished_at)
        events = self.db.scalars(
            select(AgentRunEvent).where(AgentRunEvent.agent_run_id == self.run.id)
        ).all()
        self.assertEqual([event.event_type for event in events], ["run_completed"])

    def test_runtime_cancellation_marks_task_and_run_cancelled_without_failed_terminal(self):
        with (
            patch("app.workflows.generation.runner.SessionLocal", self.session_factory),
            patch("app.workflows.generation.runner.checkpoint_context", _fake_checkpoint_context),
            patch("app.workflows.generation.runner.build_generation_graph", return_value=_CancelledGraph()),
        ):
            asyncio.run(run_generation_workflow(self.task.id, run_context=self.context))

        self.db.refresh(self.task)
        self.db.refresh(self.run)
        self.assertEqual(self.task.status, "cancelled")
        self.assertEqual(self.run.status, "cancelled")
        events = self.db.scalars(
            select(AgentRunEvent).where(AgentRunEvent.agent_run_id == self.run.id)
        ).all()
        self.assertEqual([event.event_type for event in events], ["run_cancelled"])

    def test_nested_evaluation_cancellation_propagates_to_outer_runner(self):
        context = RunContext(
            run_id=self.run.id,
            project_id=self.context.project_id,
            task_id=self.task.id,
            spec_snapshot={"name": "evaluation_runner"},
        )
        self.run.status = "running"
        self.db.commit()
        with (
            patch("app.workflows.generation.runner.SessionLocal", self.session_factory),
            patch("app.workflows.generation.runner.checkpoint_context", _fake_checkpoint_context),
            patch("app.workflows.generation.runner.build_generation_graph", return_value=_CancelledGraph()),
        ):
            with self.assertRaises(RuntimeCancelled):
                asyncio.run(run_generation_workflow(self.task.id, run_context=context))

        self.db.refresh(self.task)
        self.db.refresh(self.run)
        self.assertEqual(self.task.status, "cancelled")
        self.assertEqual(self.run.status, "running")
        events = self.db.scalars(
            select(AgentRunEvent).where(AgentRunEvent.agent_run_id == self.run.id)
        ).all()
        self.assertEqual(events, [])

    def test_runtime_error_marks_agent_run_failed(self):
        with (
            patch("app.workflows.generation.runner.SessionLocal", self.session_factory),
            patch("app.workflows.generation.runner.checkpoint_context", _fake_checkpoint_context),
            patch("app.workflows.generation.runner.build_generation_graph", return_value=_FailedGraph()),
        ):
            with self.assertRaises(ConnectionError):
                asyncio.run(run_generation_workflow(self.task.id, run_context=self.context))

        self.db.refresh(self.run)
        self.db.refresh(self.task)
        self.assertEqual(self.run.status, "failed")
        self.assertIn("[REDACTED]", self.task.error_message)
        self.assertNotIn("secret-token", self.task.error_message)
        self.assertNotIn("hunter2", self.task.error_message)
        events = self.db.scalars(
            select(AgentRunEvent).where(AgentRunEvent.agent_run_id == self.run.id)
        ).all()
        self.assertEqual([event.event_type for event in events], ["run_failed"])

    def test_runtime_budget_exhaustion_preserves_a_distinct_terminal(self):
        """Catches expected budget stops being reported as provider/system failures."""
        with (
            patch("app.workflows.generation.runner.SessionLocal", self.session_factory),
            patch("app.workflows.generation.runner.checkpoint_context", _fake_checkpoint_context),
            patch(
                "app.workflows.generation.runner.build_generation_graph",
                return_value=_BudgetExhaustedGraph(),
            ),
        ):
            asyncio.run(
                run_generation_workflow(self.task.id, run_context=self.context)
            )

        self.db.refresh(self.task)
        self.db.refresh(self.run)
        self.assertEqual(self.task.status, "budget_exhausted")
        self.assertEqual(self.run.status, "budget_exhausted")
        self.assertEqual(self.run.stop_reason, "budget_exhausted")
        events = self.db.scalars(
            select(AgentRunEvent).where(AgentRunEvent.agent_run_id == self.run.id)
        ).all()
        self.assertEqual(
            [event.event_type for event in events],
            ["run_budget_exhausted"],
        )


if __name__ == "__main__":
    unittest.main()
