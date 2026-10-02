import asyncio
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.agent_run import AgentRun
from app.models.generation import GenerationTask
from app.models.project import Project
from app.models.requirement import RequirementDocument
from app.models.user import User


class AgentRuntimeWorkerTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.session_factory = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)
        self.db = self.session_factory()
        user = User(username="runtime-worker-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        project = Project(user_id=user.id, name="runtime worker")
        self.db.add(project)
        self.db.flush()
        document = RequirementDocument(project_id=project.id, title="doc")
        self.db.add(document)
        self.db.flush()
        task = GenerationTask(project_id=project.id, document_id=document.id)
        self.db.add(task)
        self.db.flush()
        self.run = AgentRun(
            project_id=project.id,
            generation_task_id=task.id,
            agent_spec_snapshot='{"name":"case_writer"}',
            budget_snapshot='{"max_transport_retries":2}',
        )
        self.db.add(self.run)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_worker_claims_one_run_and_invokes_existing_generation_runner_with_context(self):
        from app.worker import SQLiteAgentWorker

        calls = []

        async def fake_runner(task_id, *, run_context, resume=False):
            calls.append((task_id, run_context.run_id, run_context.budget.max_transport_retries, resume))

        worker = SQLiteAgentWorker(
            self.session_factory,
            worker_id="test-worker",
            runner=fake_runner,
        )

        self.assertTrue(worker.run_once(now=datetime(2026, 8, 9, 9, 0, 0)))
        self.assertEqual(calls, [(self.run.generation_task_id, self.run.id, 2, False)])
        self.assertFalse(worker.run_once(now=datetime(2026, 8, 9, 9, 0, 1)))

    def test_worker_passes_resume_mode_from_immutable_snapshot(self):
        from app.worker import SQLiteAgentWorker

        self.run.agent_spec_snapshot = '{"name":"case_writer","execution_mode":"resume"}'
        self.db.commit()
        calls = []

        async def fake_runner(task_id, *, run_context, resume=False):
            calls.append((task_id, resume))

        worker = SQLiteAgentWorker(self.session_factory, worker_id="test-worker", runner=fake_runner)

        self.assertTrue(worker.run_once(now=datetime(2026, 8, 9, 9, 0, 0)))
        self.assertEqual(calls, [(self.run.generation_task_id, True)])

    def test_long_running_runner_renews_its_lease(self):
        """Catches a healthy run being reclaimed while its graph is still executing."""
        from app.worker import SQLiteAgentWorker

        async def slow_runner(task_id, *, run_context, resume=False):
            await asyncio.sleep(0.04)

        claimed_at = datetime(2026, 8, 9, 9, 0, 0)
        worker = SQLiteAgentWorker(
            self.session_factory,
            worker_id="heartbeat-worker",
            runner=slow_runner,
            lease_seconds=1,
            heartbeat_interval_seconds=0.01,
        )

        self.assertTrue(worker.run_once(now=claimed_at))
        self.db.expire_all()
        refreshed = self.db.get(AgentRun, self.run.id)
        self.assertGreater(refreshed.lease_expires_at, claimed_at + timedelta(seconds=1))

    def test_worker_loop_continues_after_one_run_failure(self):
        """Catches one failed graph terminating the durable queue consumer."""
        from app.worker import SQLiteAgentWorker

        worker = SQLiteAgentWorker(self.session_factory, sleep=lambda _seconds: None)
        calls = 0

        def run_once():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("one run failed")
            raise KeyboardInterrupt()

        worker.run_once = run_once
        with self.assertLogs("app.worker", level="ERROR") as logs:
            with self.assertRaises(KeyboardInterrupt):
                worker.serve_forever()
        self.assertEqual(calls, 2)
        self.assertIn("continuing queue polling", logs.output[0])

    def test_heartbeat_accepts_runner_terminal_transition(self):
        """Catches normal terminal lease clearing being mistaken for stolen ownership."""
        from app.worker import SQLiteAgentWorker

        async def terminal_runner(task_id, *, run_context, resume=False):
            db = self.session_factory()
            try:
                run = db.get(AgentRun, run_context.run_id)
                run.status = "completed"
                run.lease_owner = ""
                run.lease_expires_at = None
                db.commit()
            finally:
                db.close()
            await asyncio.sleep(0.03)

        worker = SQLiteAgentWorker(
            self.session_factory,
            worker_id="terminal-worker",
            runner=terminal_runner,
            lease_seconds=1,
            heartbeat_interval_seconds=0.01,
        )

        self.assertTrue(worker.run_once(now=datetime(2026, 8, 9, 9, 0, 0)))

    def test_heartbeat_accepts_budget_exhausted_terminal_transition(self):
        """Catches Worker treating a legitimate budget stop as lost lease ownership."""
        from app.agent_runtime.repository import AgentRunRepository
        from app.worker import SQLiteAgentWorker

        async def budget_terminal_runner(task_id, *, run_context, resume=False):
            db = self.session_factory()
            try:
                AgentRunRepository(db).mark_terminal(
                    run_context.run_id,
                    "budget_exhausted",
                )
            finally:
                db.close()
            await asyncio.sleep(0.03)

        worker = SQLiteAgentWorker(
            self.session_factory,
            worker_id="budget-terminal-worker",
            runner=budget_terminal_runner,
            lease_seconds=1,
            heartbeat_interval_seconds=0.01,
        )

        self.assertTrue(worker.run_once(now=datetime(2026, 8, 9, 9, 0, 0)))

    def test_process_lock_rejects_a_second_worker(self):
        """Catches start.bat launches creating two SQLite queue consumers."""
        from app.worker import worker_process_lock

        lock_path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / f"agent-worker-test-{uuid.uuid4().hex}.lock"
        )
        try:
            with worker_process_lock(lock_path):
                with self.assertRaises(RuntimeError):
                    with worker_process_lock(lock_path):
                        pass
        finally:
            lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
