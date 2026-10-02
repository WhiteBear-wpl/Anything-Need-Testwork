import unittest

from pydantic import ValidationError

import app.models  # noqa: F401  # 注册关系依赖的所有 ORM 模型
from app.models.generation import GenerationTask
from app.schemas import PromoteFailureCandidateRequest


class FailureCandidateModelTests(unittest.TestCase):
    def test_generation_task_exposes_attempt_and_candidate_relationships(self):
        task = GenerationTask(project_id=1, document_id=1)

        self.assertEqual(list(task.attempts), [])
        self.assertEqual(list(task.failure_candidates), [])

    def test_promote_request_requires_at_least_one_checkpoint(self):
        with self.assertRaises(ValidationError):
            PromoteFailureCandidateRequest(title="缺失步骤回归", checkpoints=[])


if __name__ == "__main__":
    unittest.main()
