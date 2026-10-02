import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.agent_run import AgentRun
from app.models.generation import GenerationTask
from app.models.project import Project
from app.models.requirement import RequirementDocument, RequirementItem
from app.models.user import User


class MultiAgentMergeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="multi-agent-merge-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        project = Project(user_id=user.id, name="multi agent merge")
        self.db.add(project)
        self.db.flush()
        document = RequirementDocument(project_id=project.id, title="doc")
        self.db.add(document)
        self.db.flush()
        item = RequirementItem(document_id=document.id, feature="登录")
        self.db.add(item)
        self.db.flush()
        self.task = GenerationTask(project_id=project.id, document_id=document.id)
        self.db.add(self.task)
        self.db.flush()
        self.run = AgentRun(
            project_id=project.id,
            generation_task_id=self.task.id,
            agent_spec_snapshot="{}",
            budget_snapshot="{}",
        )
        self.db.add(self.run)
        self.item = item
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_same_normalized_case_merges_sources_without_deleting_candidate(self):
        from app.services.multi_agent_service import CandidateCase, merge_candidates

        merged = merge_candidates([
            CandidateCase("case_writer", {"title": "登录成功", "case_type": "functional", "steps": ["输入账号", "点击登录"]}, []),
            CandidateCase("security", {"title": "登录成功", "case_type": "functional", "steps": "[\"输入账号\", \"点击登录\"]"}, [{"title": "认证规则"}]),
        ])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source_agents, ["case_writer", "security"])
        self.assertEqual(merged[0].merge_reason, "duplicate_normalized_steps")

    def test_persisted_specialist_candidate_keeps_payload_and_evidence(self):
        from app.services.multi_agent_service import persist_candidates

        persisted = persist_candidates(
            self.db,
            self.task.id,
            self.item.id,
            self.run.id,
            "api_test",
            [{"title": "登录接口缺少令牌"}],
            [{"title": "接口规范"}],
        )

        self.assertEqual(persisted[0].source_agent, "api_test")
        self.assertEqual(json.loads(persisted[0].payload)["title"], "登录接口缺少令牌")
        self.assertEqual(json.loads(persisted[0].evidence_refs)[0]["title"], "接口规范")


    def test_duplicate_candidate_is_persisted_with_merged_duplicate_disposition(self):
        """Catches duplicate specialist candidates being reported as independently selected."""
        from app.agent_runtime.collaboration import MergeDisposition
        from app.services.multi_agent_service import (
            CandidateCase,
            classify_candidate_dispositions,
            persist_candidate_cases,
        )

        candidates = [
            CandidateCase(
                "case_writer",
                {"title": "Login", "case_type": "functional", "steps": ["Submit"]},
                [],
            ),
            CandidateCase(
                "security",
                {"title": " Login ", "case_type": "functional", "steps": "[\"Submit\"]"},
                [],
            ),
        ]

        decisions = classify_candidate_dispositions(candidates)
        rows = persist_candidate_cases(
            self.db,
            self.task.id,
            self.item.id,
            self.run.id,
            candidates,
            decisions,
        )
        replayed = persist_candidate_cases(
            self.db,
            self.task.id,
            self.item.id,
            self.run.id,
            candidates,
            decisions,
        )

        self.assertEqual(decisions[0], (MergeDisposition.SELECTED, ""))
        self.assertEqual(
            decisions[1],
            (MergeDisposition.MERGED_DUPLICATE, "duplicate_normalized_steps"),
        )
        self.assertEqual(rows[0].merge_disposition, "selected")
        self.assertEqual(rows[1].merge_disposition, "merged_duplicate")
        self.assertEqual(rows[1].merge_reason, "duplicate_normalized_steps")
        self.assertEqual([row.id for row in replayed], [row.id for row in rows])
        from app.models.generation import GeneratedCaseCandidate
        self.assertEqual(self.db.query(GeneratedCaseCandidate).count(), 2)

    def test_same_agent_identical_occurrences_remain_distinct_but_replay_idempotent(self):
        """Catches replay identity collapsing two real duplicate emissions into one audit row."""
        from app.services.multi_agent_service import (
            CandidateCase,
            classify_candidate_dispositions,
            persist_candidate_cases,
        )
        from app.models.generation import GeneratedCaseCandidate

        duplicate = {"title": "Same", "case_type": "functional", "steps": ["Step"]}
        candidates = [
            CandidateCase("security", duplicate, []),
            CandidateCase("security", duplicate, []),
        ]
        decisions = classify_candidate_dispositions(candidates)

        first = persist_candidate_cases(
            self.db, self.task.id, self.item.id, self.run.id, candidates, decisions
        )
        replay = persist_candidate_cases(
            self.db, self.task.id, self.item.id, self.run.id, candidates, decisions
        )

        self.assertEqual(len({row.id for row in first}), 2)
        self.assertEqual([row.id for row in replay], [row.id for row in first])
        self.assertEqual(self.db.query(GeneratedCaseCandidate).count(), 2)

    def test_application_retry_gets_new_audit_rows_while_same_attempt_replay_is_idempotent(self):
        """Catches a real validation retry being collapsed into checkpoint replay rows."""
        from app.models.generation import GeneratedCaseCandidate
        from app.services.multi_agent_service import (
            CandidateCase,
            classify_candidate_dispositions,
            persist_candidate_cases,
        )

        candidates = [
            CandidateCase(
                "case_writer",
                {"title": "Retry case", "case_type": "functional", "steps": ["Step"]},
                [],
            )
        ]
        decisions = classify_candidate_dispositions(candidates)

        first = persist_candidate_cases(
            self.db,
            self.task.id,
            self.item.id,
            self.run.id,
            candidates,
            decisions,
            attempt_no=0,
        )
        replay = persist_candidate_cases(
            self.db,
            self.task.id,
            self.item.id,
            self.run.id,
            candidates,
            decisions,
            attempt_no=0,
        )
        retry = persist_candidate_cases(
            self.db,
            self.task.id,
            self.item.id,
            self.run.id,
            candidates,
            decisions,
            attempt_no=1,
        )

        self.assertEqual(replay[0].id, first[0].id)
        self.assertNotEqual(retry[0].id, first[0].id)
        self.assertEqual(self.db.query(GeneratedCaseCandidate).count(), 2)


if __name__ == "__main__":
    unittest.main()
