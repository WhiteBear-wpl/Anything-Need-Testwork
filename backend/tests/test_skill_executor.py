import asyncio
import json
import unittest
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent_runtime.contracts import (
    BudgetExhausted,
    ExecutionBudget,
    RunContext,
    RuntimeCancelled,
)
from app.agent_runtime.harness import RuntimeHarness
from app.agent_runtime.repository import AgentRunRepository
from app.database import Base
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.project import Project
from app.models.user import User
from app.services.settings_service import RuntimeModelConfig
from app.skills.base import SkillContext, SkillDefinition, SkillMeta
from app.skills.errors import SkillInputError, SkillOutputError, SkillTimeoutError
from app.skills.executor import SkillExecutor


class FixtureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


class FixtureOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: int


class SecretInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int
    knowledge: str


def definition_for(
    handler,
    *,
    timeout_seconds: float = 420,
    input_model: type[BaseModel] = FixtureInput,
) -> SkillDefinition:
    return SkillDefinition(
        meta=SkillMeta(
            name="fixture",
            version="1.0.0",
            title="Fixture",
            description="fixture",
            category="utility",
            stage="generation",
            timeout_seconds=timeout_seconds,
        ),
        handler=handler,
        input_model=input_model,
        output_model=FixtureOutput,
    )


class SkillExecutorTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="skill-executor-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        project = Project(user_id=user.id, name="skill executor")
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
        run_context = RunContext(
            run_id=self.run.id,
            project_id=project.id,
            task_id=0,
            spec_snapshot={"name": "fixture"},
            budget=ExecutionBudget(),
        )
        self.runtime = RuntimeHarness(self.db, run_context)
        self.executor = SkillExecutor()
        self.plain_context = SkillContext(model_config=RuntimeModelConfig())
        self.runtime_context = SkillContext(
            model_config=RuntimeModelConfig(),
            runtime=self.runtime,
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _events(self) -> list[AgentRunEvent]:
        return list(
            self.db.scalars(
                select(AgentRunEvent)
                .where(AgentRunEvent.agent_run_id == self.run.id)
                .order_by(AgentRunEvent.sequence)
            ).all()
        )

    def test_executor_validates_both_boundaries_and_passes_plain_dict(self):
        received_type = None

        async def doubles(inputs, context):
            nonlocal received_type
            received_type = type(inputs)
            return {"result": inputs["value"] * 2}

        result = asyncio.run(
            self.executor.execute(
                definition_for(doubles),
                {"value": 3},
                self.plain_context,
            )
        )
        self.assertEqual(result, {"result": 6})
        self.assertIs(received_type, dict)

        with self.assertRaises(SkillInputError):
            asyncio.run(
                self.executor.execute(
                    definition_for(doubles),
                    {"value": "bad"},
                    self.plain_context,
                )
            )

        async def bad_output(inputs, context):
            return {"result": "not-an-integer"}

        with self.assertRaises(SkillOutputError):
            asyncio.run(
                self.executor.execute(
                    definition_for(bad_output),
                    {"value": 3},
                    self.plain_context,
                )
            )

    def test_executor_records_safe_lifecycle_without_inputs_or_handler_message(self):
        async def fails(inputs, context):
            raise RuntimeError("private customer rule api_key=secret-value")

        with self.assertRaises(RuntimeError):
            asyncio.run(
                self.executor.execute(
                    definition_for(fails, input_model=SecretInput),
                    {"value": 3, "knowledge": "private customer rule"},
                    self.runtime_context,
                )
            )

        events = self._events()
        self.assertEqual(
            [event.event_type for event in events],
            ["skill_started", "skill_failed"],
        )
        raw = " ".join(event.payload_summary for event in events)
        self.assertNotIn("private customer rule", raw)
        self.assertNotIn("secret-value", raw)
        failed = json.loads(events[-1].payload_summary)
        self.assertEqual(failed["message"], "handler failed")
        self.assertEqual(failed["skill"], "fixture")

    def test_executor_times_out_with_skill_specific_error(self):
        async def slow(inputs, context):
            await asyncio.sleep(0.05)
            return {"result": inputs["value"]}

        with self.assertRaises(SkillTimeoutError):
            asyncio.run(
                self.executor.execute(
                    definition_for(slow, timeout_seconds=0.01),
                    {"value": 3},
                    self.plain_context,
                )
            )

    def test_executor_propagates_runtime_cancellation_without_calling_handler(self):
        AgentRunRepository(self.db).request_cancel(self.run.id)
        invoked = False

        async def should_not_run(inputs, context):
            nonlocal invoked
            invoked = True
            return {"result": inputs["value"]}

        with self.assertRaises(RuntimeCancelled):
            asyncio.run(
                self.executor.execute(
                    definition_for(should_not_run),
                    {"value": 3},
                    self.runtime_context,
                )
            )
        self.assertFalse(invoked)
        self.assertEqual(
            [event.event_type for event in self._events()],
            ["run_cancel_requested", "skill_cancelled"],
        )

    def test_executor_blocks_handler_when_run_time_is_exhausted(self):
        """Catches a Skill timeout ignoring the parent Runtime deadline."""
        self.run.deadline_at = datetime.now() - timedelta(seconds=1)
        self.db.commit()
        invoked = False

        async def should_not_run(inputs, context):
            nonlocal invoked
            invoked = True
            return {"result": inputs["value"]}

        with self.assertRaises(BudgetExhausted):
            asyncio.run(
                self.executor.execute(
                    definition_for(should_not_run),
                    {"value": 3},
                    self.runtime_context,
                )
            )

        self.assertFalse(invoked)
        self.assertEqual(
            [event.event_type for event in self._events()],
            ["skill_started", "skill_cancelled"],
        )


if __name__ == "__main__":
    unittest.main()
