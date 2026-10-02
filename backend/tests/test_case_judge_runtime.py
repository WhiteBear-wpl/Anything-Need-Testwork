import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from pydantic import BaseModel

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent_runtime.contracts import RuntimeCancelled
from app.database import Base
from app.models.generation import GeneratedCaseDraft, GenerationTask
from app.models.project import Project
from app.models.requirement import RequirementDocument, RequirementItem
from app.models.user import User
from app.services.generation_service import run_judge_for_task
from app.services.settings_service import RuntimeModelConfig


class CaseJudgeRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_provider_call_uses_active_runtime_harness(self):
        """Catches structured chains calling the provider outside RuntimeHarness."""
        from app.agent_runtime.harness import active_runtime_harness
        from app.ai.chains import invoke_structured

        class FixtureOutput(BaseModel):
            answer: str

        class FakeClient:
            async def aclose(self):
                return None

        class FakeModel:
            http_async_client = FakeClient()

            async def ainvoke(self, messages):
                return AIMessage(
                    content='{"answer":"ok"}',
                    usage_metadata={
                        "input_tokens": 5,
                        "output_tokens": 2,
                        "total_tokens": 7,
                    },
                )

        class RecordingHarness:
            def __init__(self):
                self.calls = []

            async def call_llm(
                self,
                stage,
                skill_name,
                operation,
                *,
                input_value,
                max_output_tokens,
            ):
                self.calls.append((stage, skill_name, len(input_value), max_output_tokens))
                return await operation()

        runtime = RecordingHarness()
        with (
            active_runtime_harness(runtime),
            patch("app.ai.chains.create_chat_model", return_value=FakeModel()),
        ):
            result = await invoke_structured(
                "只输出 JSON",
                "给出答案",
                FixtureOutput,
                RuntimeModelConfig(),
            )

        self.assertEqual(result.answer, "ok")
        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(runtime.calls[0][0:2], ("structured_generation", "structured_output"))
        self.assertGreater(runtime.calls[0][2], 0)

    async def test_judge_receives_active_runtime_and_never_swallows_cancellation(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        user = User(username="judge-runtime-owner", password_hash="hash")
        db.add(user)
        db.flush()
        project = Project(user_id=user.id, name="judge runtime")
        db.add(project)
        db.flush()
        document = RequirementDocument(project_id=project.id, title="doc")
        db.add(document)
        db.flush()
        item = RequirementItem(document_id=document.id, feature="登录")
        db.add(item)
        db.flush()
        task = GenerationTask(project_id=project.id, document_id=document.id)
        db.add(task)
        db.flush()
        db.add(
            GeneratedCaseDraft(
                task_id=task.id,
                requirement_item_id=item.id,
                title="登录成功",
                steps='["提交"]',
                expected_result="成功",
            )
        )
        db.commit()

        active_runtime = object()

        class CancellingRegistry:
            def __init__(self):
                self.runtime = None

            async def run(self, name, inputs, context):
                self.runtime = context.runtime
                raise RuntimeCancelled("stop judge")

        registry = CancellingRegistry()
        try:
            with (
                patch("app.services.generation_service.get_registry", return_value=registry),
                patch(
                    "app.services.generation_service.get_project_runtime_config",
                    return_value=RuntimeModelConfig(),
                ),
                patch(
                    "app.agent_runtime.harness.get_active_runtime_harness",
                    return_value=active_runtime,
                ),
            ):
                with self.assertRaises(RuntimeCancelled):
                    await run_judge_for_task(db, task)
        finally:
            db.close()
            engine.dispose()

        self.assertIs(registry.runtime, active_runtime)


if __name__ == "__main__":
    unittest.main()
