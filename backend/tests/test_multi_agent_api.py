import asyncio
import unittest

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.agent_run import AgentRun
from app.models.generation import GeneratedCaseCandidate, GenerationTask
from app.models.project import Project
from app.models.requirement import RequirementDocument
from app.models.user import User
from app.schemas import GenerationTaskCreate, ProjectOut, ProjectUpdate


class MultiAgentApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="multi-agent-api-owner", password_hash="hash")
        self.db.add(user); self.db.flush()
        self.project = Project(user_id=user.id, name="multi agent api", agent_specialist_allowlist='["security"]')
        self.db.add(self.project); self.db.flush()
        doc = RequirementDocument(project_id=self.project.id, title="doc", status="confirmed")
        self.db.add(doc); self.db.flush()
        self.document = doc
        self.task = GenerationTask(project_id=self.project.id, document_id=doc.id)
        self.db.add(self.task); self.db.flush()
        run = AgentRun(project_id=self.project.id, generation_task_id=self.task.id, status="completed", agent_spec_snapshot="{}", budget_snapshot="{}")
        self.db.add(run); self.db.flush()
        self.run = run
        self.db.add(GeneratedCaseCandidate(task_id=self.task.id, agent_run_id=run.id, source_agent="security", payload='{"secret":"not for api"}', merge_disposition="merged", merge_reason="duplicate_normalized_steps"))
        self.db.commit()

    def tearDown(self):
        self.db.close(); self.engine.dispose()

    def test_project_schemas_expose_specialist_allowlist(self):
        updated = ProjectUpdate(agent_specialist_allowlist=["security"])
        output = ProjectOut.model_validate(self.project)
        self.assertEqual(updated.agent_specialist_allowlist, ["security"])
        self.assertEqual(output.agent_specialist_allowlist, ["security"])

    def test_project_schema_accepts_dynamic_string_but_api_rejects_unknown(self):
        from app.api.projects import update_project

        data = ProjectUpdate(agent_specialist_allowlist=["future_specialist"])
        self.db.info["user_id"] = self.project.user_id
        with self.assertRaises(HTTPException) as raised:
            update_project(self.project.id, data, self.db)
        self.assertEqual(raised.exception.status_code, 422)

    def test_generation_api_rejects_unknown_specialist_before_creating_task(self):
        from app.api.generations import create_task

        before = self.db.query(GenerationTask).count()
        data = GenerationTaskCreate(
            document_id=self.document.id,
            specialist_skills=["future_specialist"],
        )
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                create_task(
                    self.project.id,
                    data,
                    BackgroundTasks(),
                    self.db,
                )
            )
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(self.db.query(GenerationTask).count(), before)

    def test_skill_catalog_exposes_specialist_execution_order(self):
        from app.api.skills import list_skills

        catalog = list_skills()

        self.assertEqual(
            [(item.name, item.execution_order) for item in catalog.specialist],
            [("security", 10), ("api_test", 20)],
        )

    def test_collaboration_summary_exposes_metadata_without_payload(self):
        from app.api.generations import get_collaboration_summary

        summary = get_collaboration_summary(self.project.id, self.task.id, self.db)

        self.assertEqual(summary["candidate_count"], 1)
        self.assertEqual(summary["candidates"][0]["source_agent"], "security")
        self.assertEqual(summary["candidate_counts_by_agent"], {"security": 1})
        self.assertEqual(summary["disposition_counts"], {"merged": 1})
        self.assertNotIn("payload", summary["candidates"][0])

    def test_project_collaboration_report_exposes_fixed_rollout_target(self):
        """Catches the project endpoint drifting from the agreed 30-run rollout window."""
        from app.api.generations import get_project_collaboration_report

        report = get_project_collaboration_report(self.project.id, 30, self.db)

        self.assertEqual(report["sample_size"], 1)
        self.assertEqual(report["target_sample_size"], 30)
        self.assertFalse(report["gates"]["sample_complete"])

    def test_collaboration_summary_can_pin_a_specific_retry_run(self):
        """Catches run N status being combined with run N+1 collaboration data."""
        from app.api.generations import get_collaboration_summary

        newer_run = AgentRun(
            project_id=self.project.id,
            generation_task_id=self.task.id,
            status="completed",
            agent_spec_snapshot="{}",
            budget_snapshot="{}",
        )
        self.db.add(newer_run)
        self.db.flush()
        self.db.add(
            GeneratedCaseCandidate(
                task_id=self.task.id,
                agent_run_id=newer_run.id,
                source_agent="api_test",
                payload="{}",
            )
        )
        self.db.commit()

        summary = get_collaboration_summary(
            self.project.id,
            self.task.id,
            self.db,
            run_id=self.run.id,
        )

        self.assertEqual(summary["candidate_counts_by_agent"], {"security": 1})


if __name__ == "__main__":
    unittest.main()
