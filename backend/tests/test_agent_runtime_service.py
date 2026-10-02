import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.agent import AgentMessage, AgentThread
from app.models.generation import GenerationTask
from app.models.project import Project
from app.models.requirement import RequirementDocument
from app.models.user import User


class AgentRuntimeServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="runtime-service-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        self.project = Project(
            user_id=user.id,
            name="runtime service",
            agent_runtime_v2_enabled=True,
            agent_specialist_allowlist='["security"]',
        )
        self.db.add(self.project)
        self.db.flush()
        document = RequirementDocument(project_id=self.project.id, title="doc")
        self.db.add(document)
        self.db.flush()
        self.task = GenerationTask(project_id=self.project.id, document_id=document.id, strategy_config='{"strategy":"full"}')
        self.db.add(self.task)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_v2_requires_global_and_project_flags(self):
        from app.agent_runtime.service import is_runtime_v2_enabled, is_unified_runtime_enabled

        self.assertFalse(is_runtime_v2_enabled(False, self.project))
        self.assertTrue(is_runtime_v2_enabled(True, self.project))
        self.project.agent_runtime_v2_enabled = False
        self.assertFalse(is_runtime_v2_enabled(True, self.project))
        self.assertFalse(is_unified_runtime_enabled(True, True, self.project))
        self.project.agent_runtime_v2_enabled = True
        self.assertFalse(is_unified_runtime_enabled(True, False, self.project))
        self.assertTrue(is_unified_runtime_enabled(True, True, self.project))

    def test_create_case_writer_run_snapshots_model_schema_and_budget(self):
        from app.agent_runtime.service import create_case_writer_run

        run = create_case_writer_run(
            self.db,
            self.task,
            model_snapshot={"model": "mock", "api_key": "must-not-persist"},
        )
        snapshot = json.loads(run.agent_spec_snapshot)

        self.assertEqual(snapshot["name"], "case_writer")
        self.assertEqual(snapshot["schema_version"], "case-list-v1")
        self.assertEqual(
            snapshot["skill_policy"],
            {"policy_revision": 0, "catalog_fingerprint": "", "specialists": {}},
        )
        self.assertNotIn("api_key", json.dumps(snapshot))
        self.assertEqual(json.loads(run.budget_snapshot)["max_transport_retries"], 2)

    def test_assistant_parent_freezes_chat_budget_and_links_message(self):
        from app.agent_runtime.service import create_assistant_run

        thread = AgentThread(project_id=self.project.id)
        self.db.add(thread)
        self.db.flush()
        message = AgentMessage(
            project_id=self.project.id,
            thread_id=thread.id,
            role="user",
            content="生成登录用例",
        )
        self.db.add(message)
        self.db.commit()

        run = create_assistant_run(
            self.db,
            project_id=self.project.id,
            thread_id=thread.id,
            message_id=message.id,
            model_snapshot={
                "model": "mock",
                "api_key": "must-not-persist",
                "base_url": "https://user:password@example.com/v1?token=secret",
            },
        )

        self.assertEqual((run.run_kind, run.execution_mode), ("chat", "inline"))
        self.assertEqual((run.thread_id, run.message_id), (thread.id, message.id))
        self.assertEqual(json.loads(run.budget_snapshot)["max_llm_calls"], 8)
        self.assertNotIn("must-not-persist", run.agent_spec_snapshot)
        self.assertNotIn("password", run.agent_spec_snapshot)
        self.assertNotIn("token=secret", run.agent_spec_snapshot)

    def test_run_snapshot_copies_task_policy_without_reading_live_project_allowlist(self):
        from app.agent_runtime.service import create_case_writer_run

        self.project.agent_specialist_allowlist = '["api_test", "security"]'
        self.task.strategy_config = (
            '{"strategy":"full","specialist_skills":["api_test","security"],'
            '"skill_policy":{"policy_revision":7,"catalog_fingerprint":"fixed",'
            '"specialists":{"api_test":{"enabled":true,"timeout_seconds":420,'
            '"max_cases":5,"execution_order":20,"prompt_version":"v1"}}}}'
        )
        self.db.commit()

        run = create_case_writer_run(
            self.db,
            self.task,
            model_snapshot={"model": "mock"},
        )

        self.assertEqual(json.loads(run.agent_spec_snapshot)["skill_policy"]["policy_revision"], 7)
        self.assertEqual(
            list(json.loads(run.agent_spec_snapshot)["skill_policy"]["specialists"]),
            ["api_test"],
        )

    def test_retry_run_snapshots_resume_execution_mode(self):
        from app.agent_runtime.service import create_case_writer_run

        run = create_case_writer_run(
            self.db,
            self.task,
            model_snapshot={"model": "mock"},
            resume=True,
        )

        self.assertEqual(json.loads(run.agent_spec_snapshot)["execution_mode"], "resume")

    def test_create_run_reuses_existing_active_task_run(self):
        """Catches duplicate retry requests enqueueing two graphs for one task."""
        from app.agent_runtime.service import create_case_writer_run
        from app.models.agent_run import AgentRun

        first = create_case_writer_run(
            self.db, self.task, model_snapshot={"model": "mock"}, resume=True
        )
        second = create_case_writer_run(
            self.db, self.task, model_snapshot={"model": "mock"}, resume=True
        )

        self.assertEqual(second.id, first.id)
        self.assertEqual(
            self.db.query(AgentRun).filter(AgentRun.generation_task_id == self.task.id).count(),
            1,
        )

    def test_resume_run_uses_fresh_budget_and_links_exhausted_run(self):
        """Catches retry mutating the exhausted audit row or losing resume lineage."""
        from app.agent_runtime.service import create_case_writer_run

        exhausted = create_case_writer_run(
            self.db,
            self.task,
            model_snapshot={"model": "mock"},
        )
        exhausted.status = "budget_exhausted"
        self.db.commit()

        resumed = create_case_writer_run(
            self.db,
            self.task,
            model_snapshot={"model": "mock"},
            resume=True,
            parent_run_id=7,
            resume_from_run_id=exhausted.id,
        )

        self.assertNotEqual(resumed.id, exhausted.id)
        self.assertEqual(resumed.parent_run_id, 7)
        self.assertEqual(resumed.resume_from_run_id, exhausted.id)
        self.assertEqual((resumed.run_kind, resumed.execution_mode), ("generation", "worker"))
        budget = json.loads(resumed.budget_snapshot)
        self.assertEqual(
            (budget["max_llm_calls"], budget["max_tokens"], budget["max_runtime_seconds"]),
            (32, 120_000, 900),
        )


if __name__ == "__main__":
    unittest.main()
