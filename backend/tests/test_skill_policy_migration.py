import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.project import Project
from app.models.user import User


class SkillPolicyMigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(username="policy-migration-user", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.legacy_enabled = Project(
            user_id=self.user.id,
            name="legacy enabled",
            agent_specialist_allowlist='["security"]',
        )
        self.legacy_empty = Project(
            user_id=self.user.id,
            name="legacy empty",
            agent_specialist_allowlist="[]",
        )
        self.db.add_all([self.legacy_enabled, self.legacy_empty])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _policy_rows(self, project_id):
        from app.models.skill_policy import ProjectSkillPolicy

        return (
            self.db.query(ProjectSkillPolicy)
            .filter(ProjectSkillPolicy.project_id == project_id)
            .order_by(ProjectSkillPolicy.skill_name)
            .all()
        )

    def _revision_count(self, project_id):
        from app.models.skill_policy import ProjectSkillPolicyRevision

        return self.db.query(ProjectSkillPolicyRevision).filter(
            ProjectSkillPolicyRevision.project_id == project_id
        ).count()

    def test_legacy_allowlist_backfills_once_and_preserves_enablement(self):
        from app.database import backfill_legacy_skill_policies

        with self.engine.begin() as conn:
            backfill_legacy_skill_policies(conn)
        with self.engine.begin() as conn:
            backfill_legacy_skill_policies(conn)
        self.db.expire_all()

        enabled_rows = {row.skill_name: row for row in self._policy_rows(self.legacy_enabled.id)}
        empty_rows = {row.skill_name: row for row in self._policy_rows(self.legacy_empty.id)}
        self.assertTrue(enabled_rows["security"].enabled)
        self.assertFalse(enabled_rows["api_test"].enabled)
        self.assertFalse(empty_rows["security"].enabled)
        self.assertEqual(self._revision_count(self.legacy_enabled.id), 1)
        self.assertEqual(self._revision_count(self.legacy_empty.id), 1)

    def test_new_project_initializes_enabled_default_specialists(self):
        from app.database import backfill_legacy_skill_policies
        from app.services.skill_policy_service import initialize_project_skill_policies

        with self.engine.begin() as conn:
            backfill_legacy_skill_policies(conn)
        new_project = Project(user_id=self.user.id, name="created after migration")
        self.db.add(new_project)
        self.db.commit()

        state = initialize_project_skill_policies(
            self.db, new_project.id, actor_id=self.user.id
        )
        self.assertEqual(state.revision_no, 1)
        self.assertEqual(
            {row.skill_name: row.enabled for row in self._policy_rows(new_project.id)},
            {"api_test": True, "security": True},
        )
        self.assertTrue(all(item.enabled for item in state.resolved.specialists))
        self.assertEqual(self._revision_count(new_project.id), 1)

    def test_save_appends_revision_and_rejects_stale_base_revision(self):
        from app.database import backfill_legacy_skill_policies
        from app.services.skill_policy_service import (
            StaleSkillPolicyRevision,
            replace_project_policy,
        )
        from app.skills.policy import ProjectSkillOverride

        with self.engine.begin() as conn:
            backfill_legacy_skill_policies(conn)
        state = replace_project_policy(
            self.db,
            self.legacy_enabled.id,
            [ProjectSkillOverride("security", True, timeout_seconds=180)],
            base_revision=1,
            actor_id=self.user.id,
        )
        self.assertEqual(state.revision_no, 2)
        self.assertEqual(state.resolved.by_name["security"].timeout_seconds, 180)

        with self.assertRaises(StaleSkillPolicyRevision):
            replace_project_policy(
                self.db,
                self.legacy_enabled.id,
                [],
                base_revision=1,
                actor_id=self.user.id,
            )
        self.assertEqual(self._revision_count(self.legacy_enabled.id), 2)


if __name__ == "__main__":
    unittest.main()
