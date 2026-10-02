import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.generation import GenerationTask
from app.models.project import Project
from app.models.requirement import RequirementDocument
from app.models.user import User
from app.services.settings_service import RuntimeModelConfig


class MultiAgentCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_merges_specialist_candidates_before_validation(self):
        from app.workflows.generation.graph import build_generation_graph
        from app.workflows.generation.nodes import merge_agent_candidates

        merged = await merge_agent_candidates({
            "core_cases": [{"title": "登录成功", "case_type": "functional", "steps": ["输入账号"]}],
            "specialist_cases": {"security": [{"title": "登录成功", "case_type": "functional", "steps": ["输入账号"]}]},
            "knowledge": [{"title": "认证规则"}],
        })

        self.assertEqual(len(merged["current_cases"]), 1)
        self.assertEqual(merged["current_cases"][0]["source_agents"], ["case_writer", "security"])
        edges = {
            (edge.source, edge.target)
            for edge in build_generation_graph().get_graph().edges
        }
        self.assertIn(("generate_specialist_cases", "merge_agent_candidates"), edges)

    async def test_two_specialists_run_concurrently_and_keep_each_result(self):
        from app.services.multi_agent_service import run_specialists

        started = asyncio.Event()
        release = asyncio.Event()
        active = 0
        max_active = 0

        async def invoke(role):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            if active == 2:
                started.set()
            await release.wait()
            active -= 1
            return [{"title": role}]

        task = asyncio.create_task(run_specialists(["security", "api_test"], invoke))
        await asyncio.wait_for(started.wait(), timeout=0.2)
        release.set()
        cases, warnings = await task

        self.assertEqual(max_active, 2)
        self.assertEqual(cases, {"security": [{"title": "security"}], "api_test": [{"title": "api_test"}]})
        self.assertEqual(warnings, [])

    async def test_specialist_failure_is_a_warning_and_does_not_drop_other_result(self):
        from app.services.multi_agent_service import run_specialists

        async def invoke(role):
            if role == "security":
                raise TimeoutError("security provider timeout")
            return [{"title": "接口鉴权"}]

        cases, warnings = await run_specialists(["security", "api_test"], invoke)

        self.assertEqual(cases, {"api_test": [{"title": "接口鉴权"}]})
        self.assertEqual(warnings, [{"agent": "security", "message": "security provider timeout"}])


    async def test_specialist_lifecycle_records_success_and_degraded_failure(self):
        """Catches concurrent specialist calls becoming invisible to the runtime timeline."""
        from app.services.multi_agent_service import run_specialists

        recorded = []

        class RecordingRuntime:
            def record_agent_event(self, event_type, agent, **summary):
                recorded.append((event_type, agent, summary))

        async def invoke(role):
            if role == "security":
                return [{"title": "Security case"}]
            raise TimeoutError("Bearer private-token provider timeout")

        cases, warnings = await run_specialists(
            ["security", "api_test"], invoke, runtime=RecordingRuntime()
        )

        self.assertEqual(cases, {"security": [{"title": "Security case"}]})
        self.assertEqual(warnings[0]["agent"], "api_test")
        self.assertNotIn("private-token", warnings[0]["message"])
        self.assertIn("[REDACTED]", warnings[0]["message"])
        self.assertEqual(
            [(event_type, agent) for event_type, agent, _ in recorded],
            [
                ("agent_started", "security"),
                ("agent_completed", "security"),
                ("agent_started", "api_test"),
                ("agent_warning", "api_test"),
            ],
        )
        self.assertEqual(recorded[1][2]["candidate_count"], 1)
        self.assertGreaterEqual(recorded[1][2]["duration_ms"], 0)
        self.assertIn("private-token", recorded[3][2]["message"])

    async def test_runtime_cancellation_is_never_downgraded_to_specialist_warning(self):
        """Catches a user cancellation being converted into a non-blocking warning."""
        from app.agent_runtime.contracts import RuntimeCancelled
        from app.services.multi_agent_service import run_specialists

        async def invoke(_role):
            raise RuntimeCancelled("stop now")

        with self.assertRaises(RuntimeCancelled):
            await run_specialists(["security"], invoke)

    async def test_budget_exhaustion_is_never_downgraded_to_specialist_warning(self):
        from app.agent_runtime.contracts import BudgetExhausted
        from app.services.multi_agent_service import run_specialists

        async def invoke(_role):
            raise BudgetExhausted("llm_calls", 3, 3)

        with self.assertRaises(BudgetExhausted):
            await run_specialists(["security"], invoke)

    async def test_generation_node_invokes_all_selected_specialists(self):
        from app.workflows.generation.nodes import generate_specialist_cases

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        user = User(username="three-specialists", password_hash="hash")
        db.add(user)
        db.flush()
        project = Project(user_id=user.id, name="three specialists")
        db.add(project)
        db.flush()
        document = RequirementDocument(project_id=project.id, title="doc")
        db.add(document)
        db.flush()
        task = GenerationTask(project_id=project.id, document_id=document.id)
        db.add(task)
        db.commit()
        task_id = task.id
        db.close()

        class RecordingRegistry:
            def __init__(self):
                self.calls = []

            async def run(self, name, inputs, context):
                self.calls.append(name)
                return {"cases": [{"title": name}]}

        registry = RecordingRegistry()
        state = {
            "task_id": task_id,
            "strategy": "full",
                "specialist_skills": ["security", "performance", "api_test"],
                "specialist_policy": {
                    "security": {"timeout_seconds": 420, "max_cases": 5, "execution_order": 10, "prompt_version": "v1"},
                    "performance": {"timeout_seconds": 420, "max_cases": 5, "execution_order": 15, "prompt_version": "v1"},
                    "api_test": {"timeout_seconds": 420, "max_cases": 5, "execution_order": 20, "prompt_version": "v1"},
                },
            "current_feature": {"feature": "登录"},
            "scope": None,
            "knowledge": [],
            "core_cases": [],
        }
        try:
            with (
                patch("app.workflows.generation.nodes.SessionLocal", new=Session),
                patch(
                    "app.workflows.generation.nodes.get_project_runtime_config",
                    return_value=RuntimeModelConfig(),
                ),
                patch("app.workflows.generation.nodes.get_registry", return_value=registry),
            ):
                result = await generate_specialist_cases(state)
        finally:
            engine.dispose()

        self.assertEqual(
            registry.calls,
            ["security", "performance", "api_test"],
        )
        self.assertEqual(set(result["specialist_cases"]), set(registry.calls))

    async def test_runtime_node_never_falls_back_to_live_project_allowlist(self):
        from app.workflows.generation.nodes import generate_specialist_cases

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        user = User(username="snapshot-only", password_hash="hash")
        db.add(user)
        db.flush()
        project = Project(
            user_id=user.id,
            name="snapshot only",
            agent_specialist_allowlist='["security"]',
        )
        db.add(project)
        db.flush()
        document = RequirementDocument(project_id=project.id, title="doc")
        db.add(document)
        db.flush()
        task = GenerationTask(project_id=project.id, document_id=document.id)
        db.add(task)
        db.commit()
        task_id = task.id
        db.close()

        class SnapshotRegistry:
            def __init__(self):
                self.allowlists = []
                self.calls = []

            def resolve_specialists(self, allowlist, requested):
                self.allowlists.append(list(allowlist))
                return [name for name in requested if name in allowlist]

            async def run(self, name, inputs, context):
                self.calls.append(name)
                return {"cases": []}

        class SnapshotRuntime:
            context = SimpleNamespace(spec_snapshot={})

            def record_agent_event(self, *args, **kwargs):
                pass

        registry = SnapshotRegistry()
        state = {
            "task_id": task_id,
            "strategy": "full",
            "specialist_skills": ["security"],
            "current_feature": {"feature": "登录"},
            "scope": None,
            "knowledge": [],
            "core_cases": [],
        }
        try:
            with (
                patch("app.workflows.generation.nodes.SessionLocal", new=Session),
                patch(
                    "app.workflows.generation.nodes.get_project_runtime_config",
                    return_value=RuntimeModelConfig(),
                ),
                patch("app.workflows.generation.nodes.get_registry", return_value=registry),
                patch(
                    "app.agent_runtime.harness.get_active_runtime_harness",
                    return_value=SnapshotRuntime(),
                ),
            ):
                await generate_specialist_cases(state)
        finally:
            engine.dispose()

        self.assertEqual(registry.allowlists, [])
        self.assertEqual(registry.calls, [])


if __name__ == "__main__":
    unittest.main()
