import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.project import Project
from app.models.user import User


class AgentRuntimeModelTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(username="runtime-model-owner", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(user_id=self.user.id, name="runtime models")
        self.db.add(self.project)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_agent_run_defaults_to_queued_without_cancel_request(self):
        from app.agent_runtime.contracts import RunStatus
        from app.models.agent_run import AgentRun

        run = AgentRun(
            project_id=self.project.id,
            generation_task_id=None,
            agent_spec_snapshot='{"name":"case_writer","version":"v2"}',
            budget_snapshot='{"max_transport_retries":2}',
        )
        self.db.add(run)
        self.db.commit()

        self.assertEqual(run.status, RunStatus.QUEUED.value)
        self.assertFalse(run.cancel_requested)
        self.assertEqual(run.attempt_count, 0)

    def test_run_context_is_immutable(self):
        from app.agent_runtime.contracts import ExecutionBudget, RunContext

        context = RunContext(
            run_id=7,
            project_id=self.project.id,
            task_id=9,
            spec_snapshot={"name": "case_writer"},
            budget=ExecutionBudget(),
        )

        with self.assertRaises(FrozenInstanceError):
            context.run_id = 8

    def test_new_chat_run_persists_correlation_and_zeroed_usage(self):
        """Catches new assistant runs losing parent/thread audit or starting with phantom usage."""
        from app.models.agent import AgentMessage, AgentThread
        from app.models.agent_run import AgentRun

        thread = AgentThread(project_id=self.project.id)
        self.db.add(thread)
        self.db.flush()
        message = AgentMessage(
            project_id=self.project.id,
            thread_id=thread.id,
            role="user",
            content="检查登录用例",
        )
        self.db.add(message)
        self.db.flush()
        parent = AgentRun(
            project_id=self.project.id,
            run_kind="chat",
            execution_mode="inline",
            thread_id=thread.id,
            message_id=message.id,
            deadline_at=datetime(2026, 8, 15, 10, 3, 0),
            usage_accounting_version=1,
        )
        self.db.add(parent)
        self.db.flush()
        child = AgentRun(
            project_id=self.project.id,
            run_kind="generation",
            execution_mode="worker",
            parent_run_id=parent.id,
            resume_from_run_id=None,
            usage_accounting_version=1,
        )
        self.db.add(child)
        self.db.commit()

        self.assertEqual(child.parent_run_id, parent.id)
        self.assertEqual((parent.thread_id, parent.message_id), (thread.id, message.id))
        self.assertEqual(parent.run_kind, "chat")
        self.assertEqual(parent.execution_mode, "inline")
        self.assertEqual(
            (
                parent.llm_calls_used,
                parent.tool_calls_used,
                parent.tokens_reserved,
                parent.tokens_used,
                parent.transport_retries_used,
                parent.quality_repairs_used,
            ),
            (0, 0, 0, 0, 0, 0),
        )
        self.assertFalse(parent.budget_warning_emitted)
        self.assertEqual(parent.usage_accounting_version, 1)

    def test_budget_profiles_bound_each_workload_differently(self):
        """Catches chat accidentally inheriting the long evaluation allowance."""
        from app.agent_runtime.profiles import budget_for

        chat = budget_for("chat")
        generation = budget_for("generation")
        evaluation = budget_for("evaluation")

        self.assertEqual(
            (
                chat.max_transport_retries,
                chat.max_quality_repairs,
                chat.max_llm_calls,
                chat.max_tool_calls,
                chat.max_tokens,
                chat.max_runtime_seconds,
            ),
            (1, 1, 8, 8, 32_000, 180),
        )
        self.assertEqual(
            (
                generation.max_transport_retries,
                generation.max_quality_repairs,
                generation.max_llm_calls,
                generation.max_tool_calls,
                generation.max_tokens,
                generation.max_runtime_seconds,
            ),
            (2, 2, 32, 0, 120_000, 900),
        )
        self.assertEqual(
            (
                evaluation.max_transport_retries,
                evaluation.max_quality_repairs,
                evaluation.max_llm_calls,
                evaluation.max_tool_calls,
                evaluation.max_tokens,
                evaluation.max_runtime_seconds,
            ),
            (2, 2, 64, 0, 240_000, 1800),
        )
        with self.assertRaises(ValueError):
            budget_for("unknown")

    def test_runtime_contract_exposes_distinct_control_flow_outcomes(self):
        """Catches budget exhaustion being downgraded to ordinary failure."""
        from app.agent_runtime.contracts import (
            BudgetExhausted,
            BudgetMode,
            ExecutionMode,
            RunKind,
            RunStatus,
        )

        error = BudgetExhausted("tokens", 100, 100)
        self.assertEqual((error.dimension, error.used, error.limit), ("tokens", 100, 100))
        self.assertEqual(RunStatus.BUDGET_EXHAUSTED.value, "budget_exhausted")
        self.assertEqual(RunStatus.INTERRUPTED.value, "interrupted")
        self.assertEqual(RunKind.CHAT.value, "chat")
        self.assertEqual(ExecutionMode.WORKER.value, "worker")
        self.assertEqual(BudgetMode.ENFORCE.value, "enforce")

    def test_event_sequence_is_unique_per_run(self):
        from app.models.agent_run import AgentRun, AgentRunEvent

        run = AgentRun(
            project_id=self.project.id,
            agent_spec_snapshot='{}',
            budget_snapshot='{}',
        )
        self.db.add(run)
        self.db.flush()
        self.db.add_all([
            AgentRunEvent(agent_run_id=run.id, sequence=1, event_type="run_queued"),
            AgentRunEvent(agent_run_id=run.id, sequence=1, event_type="run_claimed"),
        ])

        with self.assertRaises(IntegrityError):
            self.db.commit()


if __name__ == "__main__":
    unittest.main()
