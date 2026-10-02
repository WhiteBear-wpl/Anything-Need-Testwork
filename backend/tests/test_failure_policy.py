import unittest
from datetime import datetime

from langchain_core.exceptions import OutputParserException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.generation import GenerationAttempt, GenerationFailureCandidate, GenerationTask
from app.models.project import Project
from app.models.requirement import RequirementDocument, RequirementItem
from app.models.user import User
from app.workflows.generation.failure_policy import (
    FailureCode,
    RetryKind,
    classify_failure,
    redact_output,
)
from app.services.failure_retention_service import purge_expired_generation_attempts
from app.skills.errors import SkillOutputError


class FailurePolicyTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        user = User(username="retention", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        project = Project(user_id=user.id, name="retention")
        self.db.add(project)
        self.db.flush()
        document = RequirementDocument(project_id=project.id, title="doc")
        self.db.add(document)
        self.db.flush()
        item = RequirementItem(document_id=document.id, feature="feature")
        self.db.add(item)
        self.db.flush()
        task = GenerationTask(project_id=project.id, document_id=document.id)
        self.db.add(task)
        self.db.flush()
        old = datetime(2026, 4, 1)
        self.expired_attempt = GenerationAttempt(
            task_id=task.id, requirement_item_id=item.id, attempt_no=1,
            skill_name="case_writer", status="failed", created_at=old,
        )
        self.promoted_attempt = GenerationAttempt(
            task_id=task.id, requirement_item_id=item.id, attempt_no=2,
            skill_name="case_writer", status="failed", created_at=old,
        )
        self.db.add_all([self.expired_attempt, self.promoted_attempt])
        self.db.flush()
        self.db.add(GenerationFailureCandidate(
            task_id=task.id, requirement_item_id=item.id,
            final_attempt_id=self.promoted_attempt.id, status="promoted",
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_schema_error_returns_one_repair_directive_with_json_path(self):
        decision = classify_failure(
            OutputParserException("bad output"),
            [{"path": "$.cases[2].test_steps", "message": "Field required"}],
            attempt_count=1,
        )

        self.assertEqual(decision.code, FailureCode.SCHEMA_MISSING_FIELD)
        self.assertEqual(decision.retry_kind, RetryKind.REPAIR)
        self.assertTrue(decision.recoverable)
        self.assertIn("$.cases[2].test_steps", decision.directive.message)

    def test_timeout_allows_only_two_transport_retries(self):
        second_attempt = classify_failure(TimeoutError(), [], attempt_count=2)
        third_attempt = classify_failure(TimeoutError(), [], attempt_count=3)

        self.assertTrue(second_attempt.recoverable)
        self.assertEqual(second_attempt.retry_kind, RetryKind.TRANSPORT)
        self.assertEqual(second_attempt.directive.delay_seconds, 2.0)
        self.assertFalse(third_attempt.recoverable)

    def test_skill_output_contract_error_uses_structured_repair_policy(self):
        decision = classify_failure(
            SkillOutputError(
                "case_writer",
                [{"path": "$.cases[0].steps", "message": "Field required"}],
            ),
            [],
            attempt_count=1,
        )

        self.assertEqual(decision.code, FailureCode.SCHEMA_MISSING_FIELD)
        self.assertEqual(decision.retry_kind, RetryKind.REPAIR)
        self.assertIn("$.cases[0].steps", decision.directive.message)

    def test_redact_output_masks_secrets_and_truncates(self):
        raw = 'Authorization: Bearer abcdef\n{"api_key":"secret"}' + "x" * 5000

        redacted = redact_output(raw, limit=100)

        self.assertNotIn("abcdef", redacted)
        self.assertNotIn("secret", redacted)
        self.assertLessEqual(len(redacted), 100)

    def test_redact_output_masks_unquoted_key_value_diagnostics(self):
        redacted = redact_output("provider timeout with api_key=secret-value")

        self.assertNotIn("secret-value", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_redact_output_masks_complete_basic_authorization_value(self):
        redacted = redact_output("Authorization: Basic dXNlcjpwYXNz")

        self.assertNotIn("dXNlcjpwYXNz", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_redact_output_masks_password_in_dsn(self):
        redacted = redact_output("database=postgresql://aitc:db-secret@db.internal/aitc")

        self.assertNotIn("db-secret", redacted)
        self.assertIn("postgresql://aitc:[REDACTED]@db.internal/aitc", redacted)

    def test_purge_keeps_candidate_attempt_and_removes_expired_unreferenced_attempt(self):
        expired_id = self.expired_attempt.id
        promoted_id = self.promoted_attempt.id
        deleted = purge_expired_generation_attempts(self.db, now=datetime(2026, 8, 9))

        self.assertEqual(deleted, 1)
        self.assertIsNone(self.db.get(GenerationAttempt, expired_id))
        self.assertIsNotNone(self.db.get(GenerationAttempt, promoted_id))


if __name__ == "__main__":
    unittest.main()
