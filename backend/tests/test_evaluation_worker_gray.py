import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent_runtime.repository import AgentRunRepository
from app.agent_runtime.service import create_evaluation_runner_run
from app.database import Base
from app.models.evaluation import EvalResult, EvalRun, EvalRunSample, EvalSample
from app.models.generation import GeneratedCaseDraft, GenerationTask
from app.models.project import Project
from app.models.requirement import RequirementDocument, RequirementItem
from app.models.user import User
from app.services.evaluation_experiment_service import build_experiment_snapshot
from app.services.evaluation_rollout_metrics import build_evaluation_rollout_report
from app.services.evaluation_service import run_evaluation_workflow
from app.services.settings_service import RuntimeModelConfig
from app.skills.case_judge.handler import EVALUATION_PROMPT_VERSION
from app.skills.registry import get_registry
from app.worker import SQLiteAgentWorker


def _valid_judge_batch():
    return {
        "prompt_version": EVALUATION_PROMPT_VERSION,
        "judgements": [
            {
                "index": 0,
                "dimensions": {
                    "business_relevance": 4,
                    "executability": 4,
                    "verifiability": 4,
                    "scenario_completeness": 4,
                    "boundary_awareness": 4,
                    "coverage_reasonableness": 4,
                },
                "reason": "灰度结果稳定",
                "issue_tags": [],
                "golden_alignment": "",
            }
        ],
    }


class _ScenarioRegistry:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    async def run(self, name, inputs, context):
        runtime = context.runtime
        if runtime is not None:
            runtime.record_skill_event("skill_started", name, "1.0.0", "quality")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            if runtime is not None:
                runtime.record_skill_event(
                    "skill_failed",
                    name,
                    "1.0.0",
                    "quality",
                    error_type=type(outcome).__name__,
                    message="gray scenario failure",
                )
            raise outcome
        if runtime is not None:
            runtime.record_skill_event("skill_completed", name, "1.0.0", "quality")
        return outcome


class EvaluationWorkerGrayTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.session_factory = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)
        self.db = self.session_factory()
        user = User(username="evaluation-gray-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        self.project = Project(user_id=user.id, name="evaluation gray", is_eval=True)
        self.db.add(self.project)
        self.db.flush()
        self.sample = EvalSample(
            project_id=self.project.id,
            title="登录失败",
            content="错误密码登录时显示明确原因",
            checkpoints=json.dumps(
                [{"text": "错误密码提示", "keywords": ["密码错误"]}],
                ensure_ascii=False,
            ),
        )
        self.db.add(self.sample)
        self.db.commit()
        self.runtime = RuntimeModelConfig(llm_mock_mode=True)
        self.snapshot = build_experiment_snapshot(
            get_registry(), self.runtime, {"strategy": "full"}
        )
        self.task_by_run = {}
        self.label_by_run = {}
        for label in ("normal", "retry", "unavailable", "cancel"):
            self._seed_run(label)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _seed_run(self, label):
        run = EvalRun(
            project_id=self.project.id,
            label=label,
            config=json.dumps(self.snapshot, ensure_ascii=False),
            config_snapshot=json.dumps(self.snapshot, ensure_ascii=False, sort_keys=True),
            status="pending",
        )
        self.db.add(run)
        self.db.flush()
        frozen = EvalRunSample(
            run_id=run.id,
            source_sample_id=self.sample.id,
            sample_version=1,
            title_snapshot=self.sample.title,
            content_snapshot=self.sample.content,
            checkpoints_snapshot=self.sample.checkpoints,
            content_sha256=f"content-{label}",
            checkpoints_sha256=f"checkpoints-{label}",
        )
        self.db.add(frozen)
        self.db.flush()
        self.db.add(
            EvalResult(
                run_id=run.id,
                sample_id=self.sample.id,
                run_sample_id=frozen.id,
            )
        )
        document = RequirementDocument(
            project_id=self.project.id,
            title=f"gray-{label}",
            raw_content=self.sample.content,
            is_eval=True,
        )
        self.db.add(document)
        self.db.flush()
        item = RequirementItem(
            document_id=document.id,
            feature="错误密码登录",
            confirmed=True,
        )
        task = GenerationTask(
            project_id=self.project.id,
            document_id=document.id,
            strategy="full",
            strategy_config=json.dumps(self.snapshot, ensure_ascii=False, sort_keys=True),
            status="completed",
            is_eval=True,
        )
        self.db.add_all([item, task])
        self.db.flush()
        self.db.add(
            GeneratedCaseDraft(
                task_id=task.id,
                requirement_item_id=item.id,
                title="错误密码登录",
                precondition="已有账号",
                steps=json.dumps(["输入错误密码并点击登录"], ensure_ascii=False),
                expected_result="页面显示密码错误提示",
                judge_score=4.0,
            )
        )
        self.db.commit()
        create_evaluation_runner_run(self.db, run, model_snapshot={})
        self.task_by_run[run.id] = task.id
        self.label_by_run[run.id] = label

    async def _completed_generation(self, db, run, sample, snapshot, model_config, **kwargs):
        return {
            "task_id": self.task_by_run[run.id],
            "success": True,
            "error": "",
            "total_cases": 1,
            "usable_cases": 1,
            "usable_rate": 100.0,
            "recall": 100.0,
            "checkpoint_count": 1,
            "uncovered_checkpoints": [],
            "avg_judge_score": 4.0,
            "hallucination_count": 0,
            "duplicate_count": 0,
            "duplicate_rate": 0.0,
            "tokens": 0,
            "duration_sec": 0.01,
        }

    async def _evaluation_runner(self, run_id, *, run_context):
        label = self.label_by_run[run_id]
        if label == "normal":
            registry = _ScenarioRegistry([_valid_judge_batch()])
        elif label == "retry":
            registry = _ScenarioRegistry([
                {"prompt_version": EVALUATION_PROMPT_VERSION, "judgements": []},
                _valid_judge_batch(),
            ])
        elif label == "unavailable":
            registry = _ScenarioRegistry([
                TimeoutError("temporary Judge timeout"),
                TimeoutError("temporary Judge timeout"),
            ])
        else:
            cancel_db = self.session_factory()
            try:
                self.assertTrue(
                    AgentRunRepository(cancel_db).request_cancel(run_context.run_id)
                )
            finally:
                cancel_db.close()
            registry = _ScenarioRegistry([])

        with patch(
            "app.services.evaluation_service.get_project_runtime_config",
            return_value=self.runtime,
        ), patch(
            "app.services.evaluation_service.get_registry",
            return_value=registry,
        ), patch(
            "app.services.evaluation_service._eval_one_sample",
            side_effect=self._completed_generation,
        ):
            await run_evaluation_workflow(run_id, run_context=run_context)

    def test_isolated_worker_gray_run_records_all_integrity_metrics(self):
        worker = SQLiteAgentWorker(
            self.session_factory,
            worker_id="evaluation-gray-worker",
            evaluation_runner=self._evaluation_runner,
            heartbeat_interval_seconds=0.05,
        )
        with patch(
            "app.services.evaluation_service.SessionLocal",
            self.session_factory,
        ):
            for _ in range(4):
                self.assertTrue(worker.run_once())
            self.assertFalse(worker.run_once())

        self.db.expire_all()
        report = build_evaluation_rollout_report(self.db, self.project.id)
        self.assertEqual(report["terminal_run_count"], 4)
        self.assertEqual(report["judged_batch_count"], 3)
        self.assertEqual(report["judge_unavailable_rate"], 33.3)
        self.assertEqual(report["judge_retry_rate"], 66.7)
        self.assertEqual(report["cancellation_latency_ms"]["count"], 1)
        self.assertLess(report["cancellation_latency_ms"]["maximum"], 1000.0)
        self.assertEqual(report["duplicate_skill_lifecycle_event_count"], 0)
        print("GRAY_REPORT=" + json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
