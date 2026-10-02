import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.project import Project
from app.models.user import User


class AgentRunRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="runtime-repository-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        project = Project(user_id=user.id, name="runtime repository")
        self.db.add(project)
        self.db.flush()
        self.run = AgentRun(project_id=project.id, agent_spec_snapshot="{}", budget_snapshot="{}")
        self.db.add(self.run)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_claim_next_run_claims_only_one_queued_run(self):
        from app.agent_runtime.repository import AgentRunRepository

        repo = AgentRunRepository(self.db, lease_seconds=90)
        now = datetime(2026, 8, 9, 9, 0, 0)

        first = repo.claim_next_run("worker-a", now)
        second = repo.claim_next_run("worker-b", now)

        self.assertEqual(first.id, self.run.id)
        self.assertIsNone(second)
        self.assertEqual(first.status, "running")
        self.assertEqual(first.lease_owner, "worker-a")
        events = self.db.scalars(
            select(AgentRunEvent).where(AgentRunEvent.agent_run_id == self.run.id)
        ).all()
        self.assertEqual([event.event_type for event in events], ["run_claimed"])

    def test_recover_expired_lease_requeues_only_running_run(self):
        from app.agent_runtime.repository import AgentRunRepository

        self.run.status = "running"
        self.run.lease_owner = "dead-worker"
        self.run.lease_expires_at = datetime(2026, 8, 9, 8, 59, 0)
        self.run.tokens_reserved = 123
        self.db.commit()
        repo = AgentRunRepository(self.db)

        recovered = repo.recover_expired_leases(datetime(2026, 8, 9, 9, 0, 0))

        self.db.refresh(self.run)
        self.assertEqual(recovered, 1)
        self.assertEqual(self.run.status, "queued")
        self.assertEqual(self.run.lease_owner, "")
        self.assertEqual(self.run.tokens_reserved, 0)

    def test_inline_waiting_time_pauses_the_runtime_deadline(self):
        """Catches human approval latency consuming the model execution budget."""
        from app.agent_runtime.repository import AgentRunRepository

        repo = AgentRunRepository(self.db)
        self.run.execution_mode = "inline"
        self.run.budget_snapshot = '{"max_runtime_seconds":180}'
        self.db.commit()
        started = datetime(2026, 8, 15, 9, 0, 0)
        self.assertTrue(repo.start_inline(self.run.id, started))
        self.assertTrue(repo.mark_waiting_human(self.run.id, started + timedelta(seconds=30)))
        self.assertTrue(repo.resume_inline(self.run.id, started + timedelta(seconds=90)))

        self.db.refresh(self.run)
        self.assertEqual(self.run.status, "running")
        self.assertIsNone(self.run.waiting_since)
        self.assertEqual(self.run.deadline_at, started + timedelta(seconds=240))

    def test_budget_exhausted_terminal_is_atomic_and_reports_to_parent(self):
        """Catches child exhaustion being stored as failure or disappearing from parent audit."""
        from app.agent_runtime.repository import AgentRunRepository

        parent = AgentRun(
            project_id=self.run.project_id,
            status="completed",
            run_kind="chat",
            execution_mode="inline",
            agent_spec_snapshot="{}",
            budget_snapshot="{}",
        )
        self.db.add(parent)
        self.db.flush()
        self.run.parent_run_id = parent.id
        self.run.status = "running"
        self.db.commit()

        changed = AgentRunRepository(self.db).mark_terminal(
            self.run.id,
            "budget_exhausted",
            payload_summary='{"dimension":"tokens"}',
        )

        self.assertTrue(changed)
        self.db.refresh(self.run)
        self.assertEqual(self.run.status, "budget_exhausted")
        self.assertEqual(self.run.stop_reason, "budget_exhausted")
        child_events = self.db.scalars(
            select(AgentRunEvent)
            .where(AgentRunEvent.agent_run_id == self.run.id)
            .order_by(AgentRunEvent.sequence)
        ).all()
        parent_events = self.db.scalars(
            select(AgentRunEvent)
            .where(AgentRunEvent.agent_run_id == parent.id)
            .order_by(AgentRunEvent.sequence)
        ).all()
        self.assertEqual([event.event_type for event in child_events], ["run_budget_exhausted"])
        self.assertEqual(
            [event.event_type for event in parent_events],
            ["child_run_budget_exhausted"],
        )

    def test_append_event_allocates_monotonic_sequence(self):
        from app.agent_runtime.repository import AgentRunRepository

        repo = AgentRunRepository(self.db)

        first = repo.append_event(self.run.id, "run_queued", now=datetime(2026, 8, 9, 9, 0, 0))
        second = repo.append_event(self.run.id, "run_claimed", now=datetime(2026, 8, 9, 9, 0, 1))

        self.assertEqual((first.sequence, second.sequence), (1, 2))

    def test_request_cancel_marks_run_without_reclaiming_lease(self):
        from app.agent_runtime.repository import AgentRunRepository

        repo = AgentRunRepository(self.db)
        self.assertTrue(repo.request_cancel(self.run.id))

        self.db.refresh(self.run)
        self.assertTrue(self.run.cancel_requested)
        self.assertEqual(self.run.status, "cancelled")
        self.assertIsNotNone(self.run.finished_at)
        events = self.db.scalars(
            select(AgentRunEvent).where(AgentRunEvent.agent_run_id == self.run.id)
        ).all()
        self.assertEqual(
            [event.event_type for event in events],
            ["run_cancel_requested", "run_cancelled"],
        )
        self.assertFalse(repo.request_cancel(self.run.id))
        self.assertEqual(
            self.db.query(AgentRunEvent).filter_by(agent_run_id=self.run.id).count(),
            2,
        )

    def test_waiting_human_cancel_is_immediately_terminal_and_audited(self):
        from app.agent_runtime.repository import AgentRunRepository

        repo = AgentRunRepository(self.db)
        self.run.status = "running"
        self.db.commit()
        self.assertTrue(repo.mark_waiting_human(self.run.id, datetime(2026, 8, 15, 9, 0, 0)))

        self.assertTrue(repo.request_cancel(self.run.id))

        self.db.refresh(self.run)
        self.assertEqual(self.run.status, "cancelled")
        self.assertIsNone(self.run.waiting_since)
        self.assertEqual(
            [event.event_type for event in self.db.scalars(
                select(AgentRunEvent)
                .where(AgentRunEvent.agent_run_id == self.run.id)
                .order_by(AgentRunEvent.sequence)
            ).all()],
            ["run_waiting_human", "run_cancel_requested", "run_cancelled"],
        )

    def test_queued_cancel_allocates_distinct_events_with_autoflush_disabled(self):
        from app.agent_runtime.repository import AgentRunRepository

        self.db.autoflush = False
        self.assertTrue(AgentRunRepository(self.db).request_cancel(self.run.id))

        events = self.db.scalars(
            select(AgentRunEvent)
            .where(AgentRunEvent.agent_run_id == self.run.id)
            .order_by(AgentRunEvent.sequence)
        ).all()
        self.assertEqual(
            [(event.sequence, event.event_type) for event in events],
            [(1, "run_cancel_requested"), (2, "run_cancelled")],
        )

    def test_running_cancel_records_request_until_worker_confirms_terminal(self):
        from app.agent_runtime.repository import AgentRunRepository

        repo = AgentRunRepository(self.db)
        repo.claim_next_run("worker-a", datetime(2026, 8, 15, 9, 0, 0))

        self.assertTrue(repo.request_cancel(self.run.id))

        self.db.refresh(self.run)
        self.assertEqual(self.run.status, "running")
        events = self.db.scalars(
            select(AgentRunEvent).where(AgentRunEvent.agent_run_id == self.run.id)
        ).all()
        self.assertEqual(
            [event.event_type for event in events],
            ["run_claimed", "run_cancel_requested"],
        )

    def test_request_cancel_rolls_back_state_when_audit_event_commit_fails(self):
        from app.agent_runtime.repository import AgentRunRepository

        repo = AgentRunRepository(self.db)
        original_commit = self.db.commit

        def fail_when_event_is_pending():
            if any(isinstance(item, AgentRunEvent) for item in self.db.new):
                raise RuntimeError("event persistence failed")
            original_commit()

        self.db.commit = fail_when_event_is_pending
        try:
            with self.assertRaisesRegex(RuntimeError, "event persistence failed"):
                repo.request_cancel(self.run.id)
        finally:
            self.db.commit = original_commit

        self.assertFalse(self.db.in_transaction())
        self.db.expire_all()
        run = self.db.get(AgentRun, self.run.id)
        self.assertEqual(run.status, "queued")
        self.assertFalse(run.cancel_requested)
        self.assertEqual(
            self.db.query(AgentRunEvent).filter_by(agent_run_id=self.run.id).count(),
            0,
        )

    def test_terminal_transition_rolls_back_state_when_audit_event_commit_fails(self):
        from app.agent_runtime.repository import AgentRunRepository

        self.run.status = "running"
        self.db.commit()
        repo = AgentRunRepository(self.db)
        original_commit = self.db.commit

        def fail_when_event_is_pending():
            if any(isinstance(item, AgentRunEvent) for item in self.db.new):
                raise RuntimeError("terminal event persistence failed")
            original_commit()

        self.db.commit = fail_when_event_is_pending
        try:
            with self.assertRaisesRegex(RuntimeError, "terminal event persistence failed"):
                repo.mark_terminal(
                    self.run.id,
                    "completed",
                    now=datetime(2026, 8, 15, 10, 0, 0),
                )
        finally:
            self.db.commit = original_commit

        self.assertFalse(self.db.in_transaction())
        self.db.expire_all()
        run = self.db.get(AgentRun, self.run.id)
        self.assertEqual(run.status, "running")
        self.assertIsNone(run.finished_at)
        self.assertEqual(
            self.db.query(AgentRunEvent).filter_by(agent_run_id=self.run.id).count(),
            0,
        )

    def test_heartbeat_extends_only_own_active_lease(self):
        from app.agent_runtime.repository import AgentRunRepository

        repo = AgentRunRepository(self.db, lease_seconds=90)
        now = datetime(2026, 8, 9, 9, 0, 0)
        repo.claim_next_run("worker-a", now)

        self.assertFalse(repo.heartbeat(self.run.id, "worker-b", now + timedelta(seconds=1)))
        self.assertTrue(repo.heartbeat(self.run.id, "worker-a", now + timedelta(seconds=1)))

    def test_store_artifact_redacts_payload_and_preview_centrally(self):
        from app.agent_runtime.repository import AgentRunRepository

        raw = (
            "Authorization: Bearer artifact-secret "
            "url=https://user:url-secret@example.test/v1 api_key=key-secret"
        )
        artifact = AgentRunRepository(self.db).store_artifact(
            self.run.id, "llm_output", raw, now=datetime(2026, 8, 9, 9, 0, 0)
        )

        for secret in ("artifact-secret", "url-secret", "key-secret"):
            self.assertNotIn(secret, artifact.payload)
            self.assertNotIn(secret, artifact.content_preview)
        self.assertIn("[REDACTED]", artifact.payload)
        self.assertIsNotNone(artifact.expires_at)

    def test_append_event_retries_a_real_sequence_collision(self):
        """Catches cancellation and Worker sessions allocating the same event sequence."""
        from app.agent_runtime.repository import AgentRunRepository

        db_path = Path(__file__).resolve().parents[1] / "data" / f"event-race-{uuid.uuid4().hex}.db"
        engine = create_engine(f"sqlite:///{db_path}")
        session_factory = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)
        setup = session_factory()
        user = User(username=f"event-race-{uuid.uuid4().hex}", password_hash="hash")
        setup.add(user)
        setup.flush()
        project = Project(user_id=user.id, name="event race")
        setup.add(project)
        setup.flush()
        run = AgentRun(project_id=project.id, agent_spec_snapshot="{}", budget_snapshot="{}")
        setup.add(run)
        setup.commit()
        run_id = run.id
        setup.close()

        primary = session_factory()
        original_commit = primary.commit
        inject_collision = True

        def commit_with_collision():
            nonlocal inject_collision
            if inject_collision:
                inject_collision = False
                competitor = session_factory()
                competitor.add(
                    AgentRunEvent(
                        agent_run_id=run_id,
                        sequence=1,
                        event_type="run_cancel_requested",
                    )
                )
                competitor.commit()
                competitor.close()
            original_commit()

        primary.commit = commit_with_collision
        try:
            event = AgentRunRepository(primary).append_event(run_id, "node_finished")
            self.assertEqual(event.sequence, 2)
        finally:
            primary.close()
            engine.dispose()
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
