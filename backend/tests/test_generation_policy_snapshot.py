import asyncio
import json
import unittest

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.project import Project
from app.models.requirement import RequirementDocument
from app.models.user import User
from app.schemas import GenerationTaskCreate
from app.services.skill_policy_service import replace_project_policy
from app.skills.policy import ProjectSkillOverride


class GenerationPolicySnapshotTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="generation-policy-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        self.project = Project(user_id=user.id, name="policy generation")
        self.db.add(self.project)
        self.db.flush()
        self.doc = RequirementDocument(project_id=self.project.id, title="doc", status="confirmed")
        self.db.add(self.doc)
        self.db.commit()
        replace_project_policy(
            self.db,
            self.project.id,
            [ProjectSkillOverride("security", True, timeout_seconds=180, max_cases=2)],
            base_revision=0,
            actor_id=user.id,
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_new_task_and_agent_run_copy_resolved_policy_without_live_allowlist(self):
        from app.api.generations import create_task
        from app.agent_runtime.service import create_case_writer_run

        task = asyncio.run(create_task(
            self.project.id,
            GenerationTaskCreate(document_id=self.doc.id, specialist_skills=["security"]),
            BackgroundTasks(),
            self.db,
        ))
        policy = json.loads(task.strategy_config)["skill_policy"]
        self.assertEqual(policy["policy_revision"], 1)
        self.assertEqual(policy["specialists"]["security"]["timeout_seconds"], 180)
        self.assertEqual(policy["specialists"]["security"]["max_cases"], 2)

        run = create_case_writer_run(self.db, task, model_snapshot={"api_key": "secret"})
        snapshot = json.loads(run.agent_spec_snapshot)
        self.assertEqual(snapshot["skill_policy"], policy)
        self.assertNotIn("secret", run.agent_spec_snapshot)

    def test_disabled_catalog_skill_is_rejected_before_task_is_created(self):
        from app.api.generations import create_task
        from app.models.generation import GenerationTask

        before = self.db.query(GenerationTask).count()
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(create_task(
                self.project.id,
                GenerationTaskCreate(document_id=self.doc.id, specialist_skills=["api_test"]),
                BackgroundTasks(),
                self.db,
            ))
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(self.db.query(GenerationTask).count(), before)


if __name__ == "__main__":
    unittest.main()
