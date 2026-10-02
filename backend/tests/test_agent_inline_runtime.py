import asyncio
import uuid
import unittest
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent_runtime.repository import AgentRunRepository
from app.database import Base
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.agent import AgentThread
from app.models.project import Project
from app.models.user import User


async def collect_stream(stream):
    return [event async for event in stream]


class AgentInlineRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).resolve().parents[1] / "data" / f"inline-{uuid.uuid4().hex}.sqlite"
        self.engine = create_engine(
            f"sqlite:///{self.path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.db = self.session_factory()
        user = User(username=f"inline-{uuid.uuid4().hex}", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        project = Project(user_id=user.id, name="inline")
        self.db.add(project)
        self.db.flush()
        self.run = AgentRun(
            project_id=project.id,
            run_kind="chat",
            execution_mode="inline",
            status="running",
        )
        self.db.add(self.run)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        for suffix in ("", "-shm", "-wal"):
            Path(f"{self.path}{suffix}").unlink(missing_ok=True)

    def test_sse_consumer_close_does_not_cancel_operation(self):
        from app.agent_runtime.inline import InlineAgentSupervisor, stream_run_events

        async def scenario():
            supervisor = InlineAgentSupervisor()
            release = asyncio.Event()

            async def operation():
                await release.wait()
                db = self.session_factory()
                try:
                    AgentRunRepository(db).mark_terminal(self.run.id, "completed")
                finally:
                    db.close()

            supervisor.start(self.run.id, operation)
            db = self.session_factory()
            try:
                AgentRunRepository(db).append_event(self.run.id, "assistant_started")
            finally:
                db.close()
            stream = stream_run_events(self.session_factory, self.run.id, poll_seconds=0.01)
            await anext(stream)
            await stream.aclose()
            release.set()
            await supervisor.wait(self.run.id)

        asyncio.run(scenario())
        self.db.expire_all()
        self.assertEqual(self.db.get(AgentRun, self.run.id).status, "completed")

    def test_reconnect_replays_only_missing_events_until_terminal(self):
        from app.agent_runtime.inline import stream_run_events

        repo = AgentRunRepository(self.db)
        for index in range(1, 4):
            repo.append_event(self.run.id, f"event_{index}")
        repo.mark_terminal(self.run.id, "completed")

        events = asyncio.run(collect_stream(
            stream_run_events(
                self.session_factory,
                self.run.id,
                after_sequence=1,
                poll_seconds=0.01,
            )
        ))
        self.assertEqual([event.sequence for event in events], [2, 3, 4])

    def test_waiting_human_drains_current_subscription_without_terminalizing_run(self):
        from app.agent_runtime.inline import stream_run_events

        AgentRunRepository(self.db).append_event(self.run.id, "approval_required")
        self.run.status = "waiting_human"
        self.db.commit()

        async def scenario():
            return await asyncio.wait_for(
                collect_stream(stream_run_events(
                    self.session_factory,
                    self.run.id,
                    poll_seconds=0.01,
                )),
                timeout=0.2,
            )

        events = asyncio.run(scenario())
        self.assertEqual([event.event_type for event in events], ["approval_required"])
        self.db.refresh(self.run)
        self.assertEqual(self.run.status, "waiting_human")

    def test_stale_inline_parent_is_interrupted_without_touching_child(self):
        parent = self.run
        parent.deadline_at = datetime(2026, 8, 15, 8, 0, 0)
        child = AgentRun(
            project_id=parent.project_id,
            parent_run_id=parent.id,
            run_kind="generation",
            execution_mode="worker",
            status="running",
        )
        self.db.add(child)
        self.db.commit()

        changed = AgentRunRepository(self.db).reconcile_stale_inline(
            datetime(2026, 8, 15, 9, 0, 0)
        )
        self.db.refresh(parent)
        self.db.refresh(child)
        self.assertEqual(changed, 1)
        self.assertEqual(parent.status, "interrupted")
        self.assertEqual(child.status, "running")

    def test_assistant_tokens_are_coalesced_and_tool_payload_is_bounded_metadata(self):
        from app.api.agent import _run_and_persist_inline

        async def fake_stream(**kwargs):
            for content in ("甲" * 300, "乙" * 300, "丙" * 300):
                yield "data: " + json.dumps({"type": "token", "content": content}) + "\n\n"
            yield "data: " + json.dumps({
                "type": "tool_end",
                "name": "start_generation",
                "output": json.dumps({
                    "task_id": 9,
                    "agent_run_id": 10,
                    "secret": "never-persist-this",
                }),
            }) + "\n\n"
            yield "data: " + json.dumps({
                "type": "error",
                "message": "Authorization: Bearer secret-token",
            }) + "\n\n"
            yield "data: " + json.dumps({"type": "done", "tool_calls": []}) + "\n\n"

        with (
            patch("app.api.agent.SessionLocal", self.session_factory),
            patch("app.api.agent._agent_event_stream", new=fake_stream),
        ):
            asyncio.run(_run_and_persist_inline(
                agent_run_id=self.run.id,
                stream_kwargs={},
            ))

        events = (
            self.db.query(AgentRunEvent)
            .filter_by(agent_run_id=self.run.id)
            .order_by("sequence")
            .all()
        )
        deltas = [event for event in events if event.event_type == "assistant_output_delta"]
        self.assertLess(len(deltas), 3)
        self.assertTrue(all(len(event.payload_summary) <= 1900 for event in events))
        self.assertNotIn("never-persist-this", "".join(event.payload_summary for event in events))
        self.assertNotIn("secret-token", "".join(event.payload_summary for event in events))

    def test_unexpected_inline_owner_error_terminalizes_run_with_safe_evidence(self):
        from app.api.agent import _run_and_persist_inline

        async def broken_stream(**kwargs):
            raise RuntimeError("Authorization: Bearer owner-secret")
            yield  # pragma: no cover

        with (
            patch("app.api.agent.SessionLocal", self.session_factory),
            patch("app.api.agent._agent_event_stream", new=broken_stream),
        ):
            asyncio.run(_run_and_persist_inline(
                agent_run_id=self.run.id,
                stream_kwargs={},
            ))

        self.db.expire_all()
        self.assertEqual(self.db.get(AgentRun, self.run.id).status, "failed")
        evidence = "".join(
            event.payload_summary
            for event in self.db.query(AgentRunEvent).filter_by(agent_run_id=self.run.id)
        )
        self.assertNotIn("owner-secret", evidence)

    def test_controlled_terminal_is_not_followed_by_generic_assistant_failed(self):
        from app.api.agent import _run_and_persist_inline

        async def controlled_stream(**kwargs):
            terminal_db = self.session_factory()
            try:
                AgentRunRepository(terminal_db).mark_terminal(
                    self.run.id, "budget_exhausted"
                )
            finally:
                terminal_db.close()
            yield "data: " + json.dumps({
                "type": "error", "message": "generic controlled error",
            }) + "\n\n"

        with (
            patch("app.api.agent.SessionLocal", self.session_factory),
            patch("app.api.agent._agent_event_stream", new=controlled_stream),
        ):
            asyncio.run(_run_and_persist_inline(
                agent_run_id=self.run.id,
                stream_kwargs={},
            ))

        event_types = [
            event.event_type
            for event in self.db.query(AgentRunEvent).filter_by(agent_run_id=self.run.id)
        ]
        self.assertIn("run_budget_exhausted", event_types)
        self.assertNotIn("assistant_failed", event_types)

    def test_summary_budget_exhaustion_terminalizes_parent_as_budget_exhausted(self):
        from app.agent_runtime.contracts import BudgetExhausted
        from app.api.agent import _agent_event_stream
        from app.services.settings_service import RuntimeModelConfig

        thread = AgentThread(project_id=self.run.project_id, title="runtime")
        self.db.add(thread)
        self.db.flush()
        self.run.thread_id = thread.id
        self.run.status = "queued"
        self.run.agent_spec_snapshot = "{}"
        self.run.budget_snapshot = "{}"
        self.db.commit()

        async def completed_agent(*args, **kwargs):
            yield {"type": "done", "content": "已完成主回答", "tool_calls": []}

        async def exhausted_summary(*args, **kwargs):
            raise BudgetExhausted("llm_calls", 2, 1)

        async def scenario():
            with (
                patch("app.api.agent.SessionLocal", self.session_factory),
                patch("app.api.agent.run_agent", new=completed_agent),
                patch("app.api.agent.maybe_update_summary", new=exhausted_summary),
                patch("app.api.agent.delete_checkpoint", new=__import__(
                    "unittest.mock", fromlist=["AsyncMock"]
                ).AsyncMock()),
            ):
                return [frame async for frame in _agent_event_stream(
                    project_id=self.run.project_id,
                    project_name="runtime",
                    thread_id=thread.id,
                    question="hello",
                    history=[],
                    model_config=RuntimeModelConfig(),
                    checkpoint_thread_id="runtime-summary",
                    document_id=None,
                    resume_value=None,
                    agent_run_id=self.run.id,
                )]

        frames = asyncio.run(scenario())
        self.assertTrue(frames)
        self.db.expire_all()
        self.assertEqual(self.db.get(AgentRun, self.run.id).status, "budget_exhausted")


if __name__ == "__main__":
    unittest.main()
