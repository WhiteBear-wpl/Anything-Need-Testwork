import asyncio
import unittest
from datetime import datetime, timedelta

from langchain_core.messages import AIMessage

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent_runtime.contracts import (
    BudgetExhausted,
    ExecutionBudget,
    RunContext,
    RuntimeCancelled,
)
from app.database import Base
from app.models.agent_run import AgentRun, AgentRunArtifact, AgentRunEvent
from app.models.project import Project
from app.models.user import User
from app.services.llm import LLMCallError


class RuntimeHarnessTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="runtime-harness-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        project = Project(user_id=user.id, name="runtime harness")
        self.db.add(project)
        self.db.flush()
        self.run = AgentRun(
            project_id=project.id,
            agent_spec_snapshot="{}",
            budget_snapshot="{}",
            status="running",
            started_at=datetime.now(),
            deadline_at=datetime.now() + timedelta(minutes=5),
        )
        self.db.add(self.run)
        self.db.commit()
        self.context = RunContext(
            run_id=self.run.id,
            project_id=project.id,
            task_id=0,
            spec_snapshot={"name": "case_writer"},
            budget=ExecutionBudget(max_transport_retries=2),
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_retries_transport_failure_twice_and_records_only_safe_evidence(self):
        from app.agent_runtime.harness import RuntimeHarness

        calls = 0

        async def eventually_returns_cases():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise TimeoutError("provider timeout with api_key=secret")
            return [{"title": "登录成功"}]

        harness = RuntimeHarness(self.db, self.context, sleep=lambda _: asyncio.sleep(0))
        result = asyncio.run(
            harness.call_llm(
                "generate_core_cases",
                "case_writer",
                eventually_returns_cases,
                input_value="登录需求",
                max_output_tokens=100,
            )
        )

        self.assertEqual(result, [{"title": "登录成功"}])
        self.assertEqual(calls, 3)
        events = self.db.scalars(
            select(AgentRunEvent).where(AgentRunEvent.agent_run_id == self.run.id)
        ).all()
        self.assertEqual(
            [event.event_type for event in events if event.event_type.startswith("llm_")],
            ["llm_retry", "llm_retry", "llm_succeeded"],
        )
        self.db.refresh(self.run)
        self.assertEqual(self.run.transport_retries_used, 2)
        self.assertEqual(self.run.llm_calls_used, 1)
        self.assertNotIn("secret", " ".join(event.payload_summary for event in events))
        artifacts = self.db.scalars(
            select(AgentRunArtifact).where(AgentRunArtifact.agent_run_id == self.run.id)
        ).all()
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].kind, "llm_output")

    def test_cancelled_run_stops_before_invoking_provider(self):
        from app.agent_runtime.harness import RuntimeHarness
        from app.agent_runtime.repository import AgentRunRepository

        AgentRunRepository(self.db).request_cancel(self.run.id)
        invoked = False

        async def should_not_run():
            nonlocal invoked
            invoked = True
            return []

        harness = RuntimeHarness(self.db, self.context, sleep=lambda _: asyncio.sleep(0))

        with self.assertRaises(RuntimeCancelled):
            asyncio.run(
                harness.call_llm(
                    "generate_core_cases",
                    "case_writer",
                    should_not_run,
                    input_value="cancelled",
                    max_output_tokens=10,
                )
            )

        self.assertFalse(invoked)

    def test_retries_wrapped_connection_error_but_not_provider_contract_errors(self):
        from app.agent_runtime.harness import RuntimeHarness

        calls = 0

        async def reconnects_once():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise LLMCallError("无法连接模型服务")
            return []

        harness = RuntimeHarness(self.db, self.context, sleep=lambda _: asyncio.sleep(0))
        self.assertEqual(
            asyncio.run(
                harness.call_llm(
                    "generate_core_cases",
                    "case_writer",
                    reconnects_once,
                    input_value="retry",
                    max_output_tokens=10,
                )
            ),
            [],
        )
        self.assertEqual(calls, 2)

        invalid_key_calls = 0

        async def invalid_key():
            nonlocal invalid_key_calls
            invalid_key_calls += 1
            raise LLMCallError("API Key 无效（401）")

        with self.assertRaises(LLMCallError):
            asyncio.run(
                harness.call_llm(
                    "generate_core_cases",
                    "case_writer",
                    invalid_key,
                    input_value="invalid key",
                    max_output_tokens=10,
                )
            )
        self.assertEqual(invalid_key_calls, 1)

    def test_enforced_llm_budget_blocks_before_provider_operation(self):
        """Catches Harness invoking a provider after the frozen call limit is exhausted."""
        from app.agent_runtime.harness import RuntimeHarness

        context = RunContext(
            run_id=self.run.id,
            project_id=self.context.project_id,
            task_id=0,
            budget=ExecutionBudget(
                max_llm_calls=0,
                max_tokens=100,
                max_runtime_seconds=300,
            ),
        )
        invoked = False

        async def provider():
            nonlocal invoked
            invoked = True
            return AIMessage(content="不应调用")

        with self.assertRaises(BudgetExhausted):
            asyncio.run(
                RuntimeHarness(self.db, context, budget_mode="enforce").call_llm(
                    "assistant",
                    "assistant",
                    provider,
                    input_value="问题",
                    max_output_tokens=10,
                )
            )
        self.assertFalse(invoked)

    def test_provider_usage_is_settled_and_reservation_released(self):
        """Catches Harness ignoring authoritative provider token metadata."""
        from app.agent_runtime.harness import RuntimeHarness

        async def provider():
            return AIMessage(
                content="回答",
                usage_metadata={
                    "input_tokens": 7,
                    "output_tokens": 3,
                    "total_tokens": 10,
                },
            )

        result = asyncio.run(
            RuntimeHarness(self.db, self.context, budget_mode="enforce").call_llm(
                "assistant",
                "assistant",
                provider,
                input_value="问题",
                max_output_tokens=20,
            )
        )

        self.assertEqual(result.content, "回答")
        self.db.refresh(self.run)
        self.assertEqual(self.run.tokens_used, 10)
        self.assertEqual(self.run.tokens_reserved, 0)

    def test_run_tool_records_bounded_events_without_raw_output(self):
        """Catches Agent Tool inputs or outputs leaking into the durable timeline."""
        from app.agent_runtime.harness import RuntimeHarness

        context = RunContext(
            run_id=self.run.id,
            project_id=self.context.project_id,
            task_id=0,
            budget=ExecutionBudget(max_tool_calls=2, max_runtime_seconds=300),
        )

        async def operation():
            return "customer secret api_key=tool-secret"

        result = asyncio.run(
            RuntimeHarness(self.db, context, budget_mode="enforce").run_tool(
                "list_testcases",
                operation,
                timeout_seconds=5,
            )
        )

        self.assertIn("tool-secret", result)
        events = self.db.scalars(
            select(AgentRunEvent)
            .where(AgentRunEvent.agent_run_id == self.run.id)
            .order_by(AgentRunEvent.sequence)
        ).all()
        self.assertEqual(
            [event.event_type for event in events],
            ["tool_call_started", "tool_call_completed"],
        )
        timeline = " ".join(event.payload_summary for event in events)
        self.assertNotIn("customer secret", timeline)
        self.assertNotIn("tool-secret", timeline)

    def test_run_tool_exposes_same_harness_to_nested_skills(self):
        from app.agent_runtime.harness import (
            RuntimeHarness,
            get_active_runtime_harness,
        )

        context = RunContext(
            run_id=self.run.id,
            project_id=self.context.project_id,
            task_id=0,
            budget=ExecutionBudget(max_tool_calls=2, max_runtime_seconds=300),
        )
        runtime = RuntimeHarness(self.db, context, budget_mode="enforce")

        async def nested_skill_boundary():
            self.assertIs(get_active_runtime_harness(), runtime)
            return "ok"

        result = asyncio.run(runtime.run_tool("parse_requirement_document", nested_skill_boundary))

        self.assertEqual(result, "ok")
        self.assertIsNone(get_active_runtime_harness())

    def test_redaction_masks_basic_bearer_url_credentials_and_tokens(self):
        from app.services.redaction import redact_output

        raw = (
            "Authorization: Basic dXNlcjpwYXNz\n"
            "Authorization: Bearer bearer-secret\n"
            "url=https://user:password@example.test/v1 "
            "api_key=key-secret token=token-secret sk-provider-secret"
        )
        redacted = redact_output(raw)

        for secret in (
            "dXNlcjpwYXNz",
            "bearer-secret",
            "password",
            "key-secret",
            "token-secret",
            "sk-provider-secret",
        ):
            self.assertNotIn(secret, redacted)
        self.assertIn("[REDACTED]", redacted)


if __name__ == "__main__":
    unittest.main()
