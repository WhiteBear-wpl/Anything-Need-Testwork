import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.agent_run import AgentRun
from app.models.generation import GeneratedCaseDraft, GenerationTask
from app.models.project import Project
from app.models.requirement import RequirementDocument, RequirementItem
from app.models.user import User


class MultiAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="multi-agent-contract-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        self.project = Project(
            user_id=user.id,
            name="multi agent contracts",
            agent_specialist_allowlist='["security", "api_test"]',
        )
        self.db.add(self.project)
        self.db.flush()
        document = RequirementDocument(project_id=self.project.id, title="doc")
        self.db.add(document)
        self.db.flush()
        item = RequirementItem(document_id=document.id, feature="登录")
        self.db.add(item)
        self.db.flush()
        self.task = GenerationTask(project_id=self.project.id, document_id=document.id)
        self.db.add(self.task)
        self.db.flush()
        self.run = AgentRun(
            project_id=self.project.id,
            generation_task_id=self.task.id,
            agent_spec_snapshot="{}",
            budget_snapshot="{}",
        )
        self.db.add(self.run)
        self.db.flush()
        self.item = item
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_allowlist_intersects_requested_specialists_in_catalog_order(self):
        from app.skills.registry import get_registry

        resolved = get_registry().resolve_specialists(
            ["api_test", "security"],
            ["security", "unknown", "api_test"],
        )

        self.assertEqual(resolved, ["security", "api_test"])

    def test_candidate_and_final_draft_keep_agent_source_and_evidence(self):
        from app.models.generation import GeneratedCaseCandidate

        candidate = GeneratedCaseCandidate(
            task_id=self.task.id,
            requirement_item_id=self.item.id,
            agent_run_id=self.run.id,
            source_agent="security",
            payload='{"title":"登录令牌失效"}',
            evidence_refs='[{"title":"认证规则"}]',
        )
        draft = GeneratedCaseDraft(
            task_id=self.task.id,
            requirement_item_id=self.item.id,
            title="登录令牌失效",
            source_agents='["case_writer", "security"]',
            evidence_refs='[{"title":"认证规则"}]',
            merge_reason="duplicate_normalized_steps",
        )
        self.db.add_all([candidate, draft])
        self.db.commit()

        self.assertEqual(candidate.source_agent, "security")
        self.assertEqual(draft.source_agents, '["case_writer", "security"]')
        self.assertEqual(draft.merge_reason, "duplicate_normalized_steps")


if __name__ == "__main__":
    unittest.main()
