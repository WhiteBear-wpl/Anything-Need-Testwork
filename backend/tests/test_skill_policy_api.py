import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.project import Project
from app.models.user import User


class SkillPolicyApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.owner = User(username="policy-api-owner", password_hash="hash")
        self.other = User(username="policy-api-other", password_hash="hash")
        self.db.add_all([self.owner, self.other])
        self.db.flush()
        self.project = Project(user_id=self.owner.id, name="policy project")
        self.db.add(self.project)
        self.db.commit()
        self.db.info["user_id"] = self.owner.id

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_get_then_put_returns_revision_and_effective_values_without_prompt_content(self):
        from app.api.projects import get_skill_policies, put_skill_policies
        from app.schemas import ProjectSkillPolicyOverrideIn, ProjectSkillPolicyWrite

        initial = get_skill_policies(self.project.id, self.db)
        self.assertEqual(initial.revision_no, 0)
        security = next(item for item in initial.specialists if item.skill_name == "security")
        self.assertFalse(security.resolved.enabled)
        self.assertEqual(security.defaults.prompt_versions, ["v1", "v2"])

        saved = put_skill_policies(
            self.project.id,
            ProjectSkillPolicyWrite(
                base_revision=0,
                overrides=[ProjectSkillPolicyOverrideIn(skill_name="security", enabled=True, timeout_seconds=180)],
            ),
            self.db,
        )
        self.assertEqual(saved.revision_no, 1)
        security = next(item for item in saved.specialists if item.skill_name == "security")
        self.assertEqual(security.resolved.timeout_seconds, 180)
        self.assertNotIn("安全专项提示词", saved.model_dump_json())

    def test_stale_invalid_and_foreign_write_are_mapped_to_http_errors(self):
        from app.api.projects import put_skill_policies
        from app.schemas import ProjectSkillPolicyOverrideIn, ProjectSkillPolicyWrite

        invalid = ProjectSkillPolicyWrite(
            base_revision=0,
            overrides=[ProjectSkillPolicyOverrideIn(skill_name="unknown", enabled=True)],
        )
        with self.assertRaises(HTTPException) as raised:
            put_skill_policies(self.project.id, invalid, self.db)
        self.assertEqual(raised.exception.status_code, 422)

        valid = ProjectSkillPolicyWrite(
            base_revision=0,
            overrides=[ProjectSkillPolicyOverrideIn(skill_name="security", enabled=True)],
        )
        put_skill_policies(self.project.id, valid, self.db)
        with self.assertRaises(HTTPException) as raised:
            put_skill_policies(self.project.id, valid, self.db)
        self.assertEqual(raised.exception.status_code, 409)

        self.db.info["user_id"] = self.other.id
        with self.assertRaises(HTTPException) as raised:
            put_skill_policies(self.project.id, valid, self.db)
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
