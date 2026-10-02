import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.evaluation import EvalResult, EvalRun, EvalRunSample, EvalSample
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.generation import GeneratedCaseDraft, GenerationTask
from app.models.project import Project
from app.models.requirement import RequirementDocument, RequirementItem
from app.models.user import User
from app.services.settings_service import RuntimeModelConfig


class FailingJudgeRegistry:
    def __init__(self):
        self.calls = 0

    async def run(self, name, inputs, context):
        self.calls += 1
        raise TimeoutError("judge timed out")


class SequenceJudgeRegistry:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    async def run(self, name, inputs, context):
        self.calls.append(dict(inputs))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def valid_judge_result(index=0):
    return {
        "index": index,
        "dimensions": {
            "business_relevance": 4,
            "executability": 4,
            "verifiability": 4,
            "scenario_completeness": 4,
            "boundary_awareness": 4,
            "coverage_reasonableness": 4,
        },
        "reason": "质量稳定",
        "issue_tags": [],
        "golden_alignment": "",
    }


class CancellingHarness:
    def check_cancelled(self):
        from app.agent_runtime.contracts import RuntimeCancelled

        raise RuntimeCancelled("cancelled")


class CancelAfterJudgeHarness:
    def __init__(self):
        self.checks = 0

    def check_cancelled(self):
        from app.agent_runtime.contracts import RuntimeCancelled

        self.checks += 1
        if self.checks >= 3:
            raise RuntimeCancelled("cancelled after Judge returned")

    def record_evaluation_event(self, *args, **kwargs):
        return None


class RecordingRepairHarness:
    def __init__(self):
        self.quality_repairs = 0

    def check_cancelled(self):
        return None

    def consume_quality_repair(self, *, stage="quality_repair"):
        self.quality_repairs += 1

    def record_evaluation_event(self, *args, **kwargs):
        return None


class EvaluationDualTrackWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="dual-track-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        self.project = Project(user_id=user.id, name="dual track", is_eval=True)
        self.db.add(self.project)
        self.db.flush()
        sample = EvalSample(project_id=self.project.id, title="登录", content="实时内容")
        run = EvalRun(project_id=self.project.id, label="dual-track")
        self.db.add_all([sample, run])
        self.db.flush()
        self.frozen = EvalRunSample(
            run_id=run.id,
            source_sample_id=sample.id,
            sample_version=1,
            title_snapshot="登录",
            content_snapshot="冻结需求：错误密码必须显示原因",
            checkpoints_snapshot=json.dumps([{"text": "错误密码提示", "keywords": ["密码错误"]}], ensure_ascii=False),
            content_sha256="content",
            checkpoints_sha256="checkpoints",
        )
        self.db.add(self.frozen)
        self.db.flush()
        self.result = EvalResult(run_id=run.id, sample_id=sample.id, run_sample_id=self.frozen.id)
        self.db.add(self.result)
        self.db.flush()
        document = RequirementDocument(project_id=self.project.id, title="eval", raw_content="冻结需求")
        self.db.add(document)
        self.db.flush()
        item = RequirementItem(document_id=document.id, feature="登录")
        task = GenerationTask(project_id=self.project.id, document_id=document.id, is_eval=True)
        self.db.add_all([item, task])
        self.db.flush()
        self.draft = GeneratedCaseDraft(
            task_id=task.id,
            requirement_item_id=item.id,
            title="错误密码登录",
            precondition="已有账号",
            steps=json.dumps(["输入错误密码并点击登录按钮"], ensure_ascii=False),
            expected_result="页面显示密码错误提示",
        )
        self.db.add(self.draft)
        self.db.commit()

    async def asyncTearDown(self):
        self.db.close()
        self.engine.dispose()

    async def test_judge_failure_keeps_persisted_rule_track_and_marks_unavailable(self):
        from app.services.evaluation_service import evaluate_result_scorecard

        card = await evaluate_result_scorecard(
            self.db,
            self.result,
            self.frozen,
            [self.draft],
            RuntimeModelConfig(llm_mock_mode=True),
            registry=FailingJudgeRegistry(),
        )

        self.assertIsNotNone(card.rule_score)
        self.assertEqual(card.judge_status, "unavailable")
        self.assertEqual(card.assessment_status, "judge_unavailable")
        rule_dimensions = json.loads(card.rule_dimensions)
        self.assertEqual(rule_dimensions["schema_version"], "2")
        self.assertIn("cases", rule_dimensions)
        self.assertIn("suite", rule_dimensions)
        from app.services.evaluation_scorecard_service import scorecard_input_fingerprint

        expected_fingerprint = scorecard_input_fingerprint(
            "冻结需求：错误密码必须显示原因",
            [{"text": "错误密码提示", "keywords": ["密码错误"]}],
            {
                "cases": [
                    {
                        "title": "错误密码登录",
                        "precondition": "已有账号",
                        "steps": "[\"输入错误密码并点击登录按钮\"]",
                        "expected_result": "页面显示密码错误提示",
                    }
                ]
            },
            run_envelope={},
            ruleset_version="p1-2b-rules-v1",
            judge_prompt_version="p1-2b-judge-v1",
        )
        self.assertEqual(card.input_fingerprint, expected_fingerprint)

    async def test_budget_exhaustion_stops_judge_instead_of_becoming_unavailable(self):
        from app.agent_runtime.contracts import BudgetExhausted
        from app.services.evaluation_service import evaluate_result_scorecard

        with self.assertRaises(BudgetExhausted):
            await evaluate_result_scorecard(
                self.db,
                self.result,
                self.frozen,
                [self.draft],
                RuntimeModelConfig(llm_mock_mode=True),
                registry=SequenceJudgeRegistry(BudgetExhausted("llm_calls", 3, 3)),
            )

        self.db.refresh(self.result)
        self.assertEqual(self.result.scorecard.judge_status, "not_evaluated")

    async def test_partial_judge_batch_retries_once_then_stays_unavailable(self):
        from app.services.evaluation_service import evaluate_result_scorecard

        registry = SequenceJudgeRegistry(
            {"judgements": [], "prompt_version": "p1-2b-judge-v1"},
            {"judgements": [], "prompt_version": "p1-2b-judge-v1"},
        )
        card = await evaluate_result_scorecard(
            self.db,
            self.result,
            self.frozen,
            [self.draft],
            RuntimeModelConfig(llm_mock_mode=True),
            registry=registry,
        )

        self.assertEqual(len(registry.calls), 2)
        self.assertIn("contract_retry_feedback", registry.calls[1])
        self.assertEqual(card.judge_status, "unavailable")
        self.assertEqual(card.assessment_status, "judge_unavailable")
        self.assertIsNotNone(card.rule_score)

    async def test_authentication_error_is_not_retried(self):
        from app.services.evaluation_service import evaluate_result_scorecard
        from app.services.llm import LLMCallError

        registry = SequenceJudgeRegistry(LLMCallError("评测模型的 API Key 无效或已过期"))
        card = await evaluate_result_scorecard(
            self.db,
            self.result,
            self.frozen,
            [self.draft],
            RuntimeModelConfig(llm_mock_mode=True),
            registry=registry,
        )

        self.assertEqual(len(registry.calls), 1)
        self.assertEqual(card.judge_status, "unavailable")

    async def test_contract_failure_can_recover_on_single_directed_retry(self):
        from app.services.evaluation_service import evaluate_result_scorecard

        registry = SequenceJudgeRegistry(
            {"judgements": [], "prompt_version": "p1-2b-judge-v1"},
            {"judgements": [valid_judge_result()], "prompt_version": "p1-2b-judge-v1"},
        )
        card = await evaluate_result_scorecard(
            self.db,
            self.result,
            self.frozen,
            [self.draft],
            RuntimeModelConfig(llm_mock_mode=True),
            registry=registry,
        )

        self.assertEqual(len(registry.calls), 2)
        self.assertEqual(card.judge_status, "completed")
        self.assertEqual(card.judge_verdict, "pass")

    async def test_directed_judge_retry_consumes_quality_repair_budget(self):
        from app.services.evaluation_service import evaluate_result_scorecard

        registry = SequenceJudgeRegistry(
            {"judgements": [], "prompt_version": "p1-2b-judge-v1"},
            {"judgements": [valid_judge_result()], "prompt_version": "p1-2b-judge-v1"},
        )
        harness = RecordingRepairHarness()
        with patch(
            "app.agent_runtime.harness.get_active_runtime_harness",
            return_value=harness,
        ):
            card = await evaluate_result_scorecard(
                self.db,
                self.result,
                self.frozen,
                [self.draft],
                RuntimeModelConfig(llm_mock_mode=True),
                registry=registry,
            )

        self.assertEqual(card.judge_status, "completed")
        self.assertEqual(harness.quality_repairs, 1)

    async def test_completed_scorecard_is_idempotent_and_does_not_call_judge_again(self):
        from app.services.evaluation_service import evaluate_result_scorecard

        registry = SequenceJudgeRegistry(
            {"judgements": [valid_judge_result()], "prompt_version": "p1-2b-judge-v1"}
        )
        first = await evaluate_result_scorecard(
            self.db,
            self.result,
            self.frozen,
            [self.draft],
            RuntimeModelConfig(llm_mock_mode=True),
            registry=registry,
        )
        evidence = first.rule_dimensions
        fingerprint = first.input_fingerprint

        second = await evaluate_result_scorecard(
            self.db,
            self.result,
            self.frozen,
            [self.draft],
            RuntimeModelConfig(llm_mock_mode=True),
            registry=registry,
        )

        self.assertEqual(len(registry.calls), 1)
        self.assertEqual(second.id, first.id)
        self.assertEqual(second.input_fingerprint, fingerprint)
        self.assertEqual(second.rule_dimensions, evidence)

    async def test_unavailable_scorecard_resumes_only_judge_and_preserves_rule_evidence(self):
        from app.services.evaluation_service import evaluate_result_scorecard

        failed = await evaluate_result_scorecard(
            self.db,
            self.result,
            self.frozen,
            [self.draft],
            RuntimeModelConfig(llm_mock_mode=True),
            registry=FailingJudgeRegistry(),
        )
        evidence = failed.rule_dimensions
        registry = SequenceJudgeRegistry(
            {"judgements": [valid_judge_result()], "prompt_version": "p1-2b-judge-v1"}
        )

        resumed = await evaluate_result_scorecard(
            self.db,
            self.result,
            self.frozen,
            [self.draft],
            RuntimeModelConfig(llm_mock_mode=True),
            registry=registry,
        )

        self.assertEqual(resumed.judge_status, "completed")
        self.assertEqual(resumed.rule_dimensions, evidence)

    async def test_changed_scorecard_input_is_rejected_without_overwriting_history(self):
        from app.services.evaluation_service import evaluate_result_scorecard

        registry = SequenceJudgeRegistry(
            {"judgements": [valid_judge_result()], "prompt_version": "p1-2b-judge-v1"}
        )
        original = await evaluate_result_scorecard(
            self.db,
            self.result,
            self.frozen,
            [self.draft],
            RuntimeModelConfig(llm_mock_mode=True),
            registry=registry,
        )
        original_fingerprint = original.input_fingerprint
        self.frozen.content_snapshot = "已变化的冻结需求"

        with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            await evaluate_result_scorecard(
                self.db,
                self.result,
                self.frozen,
                [self.draft],
                RuntimeModelConfig(llm_mock_mode=True),
                registry=registry,
            )

        self.db.refresh(original)
        self.assertEqual(original.input_fingerprint, original_fingerprint)
        self.assertEqual(len(registry.calls), 1)

    async def test_runtime_records_one_authoritative_skill_lifecycle(self):
        from app.agent_runtime.contracts import RunContext
        from app.services.evaluation_service import evaluate_result_scorecard

        agent_run = AgentRun(
            project_id=self.project.id,
            evaluation_run_id=self.result.run_id,
            status="running",
            agent_spec_snapshot="{}",
            budget_snapshot="{}",
        )
        self.db.add(agent_run)
        self.db.commit()
        context = RunContext(
            run_id=agent_run.id,
            project_id=self.project.id,
            task_id=0,
            spec_snapshot={"name": "evaluation_runner"},
        )

        await evaluate_result_scorecard(
            self.db,
            self.result,
            self.frozen,
            [self.draft],
            RuntimeModelConfig(llm_mock_mode=True),
            run_context=context,
        )

        events = self.db.scalars(
            select(AgentRunEvent).where(AgentRunEvent.agent_run_id == agent_run.id)
        ).all()
        skill_events = [event.event_type for event in events if event.stage == "skill"]
        self.assertEqual(skill_events, ["skill_started", "skill_completed"])

    async def test_judge_error_summary_is_redacted_before_scorecard_persistence(self):
        from app.services.evaluation_service import evaluate_result_scorecard

        class SecretFailureRegistry:
            async def run(self, name, inputs, context):
                raise RuntimeError(
                    "Authorization: Basic dXNlcjpwYXNz api_key=secret-token "
                    "https://user:password@example.test/v1"
                )

        card = await evaluate_result_scorecard(
            self.db,
            self.result,
            self.frozen,
            [self.draft],
            RuntimeModelConfig(llm_mock_mode=True),
            registry=SecretFailureRegistry(),
        )

        self.assertIn("[REDACTED]", card.judge_reason)
        self.assertNotIn("dXNlcjpwYXNz", card.judge_reason)
        self.assertNotIn("secret-token", card.judge_reason)
        self.assertNotIn("password", card.judge_reason)

    async def test_cancellation_after_rule_persistence_stays_not_evaluated(self):
        from app.agent_runtime.contracts import RuntimeCancelled
        from app.models.evaluation import EvaluationScorecard
        from app.services.evaluation_service import evaluate_result_scorecard

        with patch("app.agent_runtime.harness.get_active_runtime_harness", return_value=CancellingHarness()):
            with self.assertRaises(RuntimeCancelled):
                await evaluate_result_scorecard(
                    self.db,
                    self.result,
                    self.frozen,
                    [self.draft],
                    RuntimeModelConfig(llm_mock_mode=True),
                    registry=SequenceJudgeRegistry(
                        {
                            "judgements": [valid_judge_result()],
                            "prompt_version": "p1-2b-judge-v1",
                        }
                    ),
                )

        card = self.db.query(EvaluationScorecard).filter_by(result_id=self.result.id).one()
        self.assertIsNotNone(card.rule_score)
        self.assertEqual(card.judge_status, "not_evaluated")
        self.assertEqual(card.assessment_status, "not_evaluated")

    async def test_cancellation_after_judge_response_cannot_commit_completed(self):
        from app.agent_runtime.contracts import RuntimeCancelled
        from app.models.evaluation import EvaluationScorecard
        from app.services.evaluation_service import evaluate_result_scorecard

        harness = CancelAfterJudgeHarness()
        with patch(
            "app.agent_runtime.harness.get_active_runtime_harness",
            return_value=harness,
        ):
            with self.assertRaises(RuntimeCancelled):
                await evaluate_result_scorecard(
                    self.db,
                    self.result,
                    self.frozen,
                    [self.draft],
                    RuntimeModelConfig(llm_mock_mode=True),
                    registry=SequenceJudgeRegistry(
                        {
                            "judgements": [valid_judge_result()],
                            "prompt_version": "p1-2b-judge-v1",
                        }
                    ),
                )

        card = self.db.query(EvaluationScorecard).filter_by(result_id=self.result.id).one()
        self.assertEqual(harness.checks, 3)
        self.assertEqual(card.judge_status, "not_evaluated")
        self.assertEqual(card.assessment_status, "not_evaluated")

    async def test_mock_run_evaluation_uses_frozen_config_and_emits_complete_timeline(self):
        from app.agent_runtime.contracts import RunContext
        from app.services.evaluation_experiment_service import build_experiment_snapshot
        from app.services.evaluation_service import run_evaluation
        from app.skills.registry import get_registry

        run = self.result.run
        frozen_runtime = RuntimeModelConfig(
            llm_mock_mode=True,
            llm_base_url="https://frozen.example/v1",
            llm_model="frozen-generation-model",
        )
        snapshot = build_experiment_snapshot(
            get_registry(),
            frozen_runtime,
            {"strategy": "full", "use_knowledge": False},
        )
        run.config = json.dumps(snapshot, ensure_ascii=False)
        run.config_snapshot = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        agent_run = AgentRun(
            project_id=self.project.id,
            evaluation_run_id=run.id,
            status="running",
            agent_spec_snapshot=json.dumps(
                {"name": "evaluation_runner", "evaluation_run_id": run.id},
                ensure_ascii=False,
            ),
            budget_snapshot="{}",
        )
        self.db.add(agent_run)
        self.db.commit()
        context = RunContext(
            run_id=agent_run.id,
            project_id=self.project.id,
            task_id=0,
            spec_snapshot={"name": "evaluation_runner", "evaluation_run_id": run.id},
        )
        observed_configs = []

        async def completed_generation(
            db,
            eval_run,
            sample,
            experiment_snapshot,
            model_config,
            **kwargs,
        ):
            observed_configs.append(model_config)
            return {
                "task_id": self.draft.task_id,
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
                "duration_sec": 0.1,
            }

        live_runtime = RuntimeModelConfig(
            llm_mock_mode=False,
            llm_api_key="rotated-secret",
            llm_base_url="https://changed-live.example/v1",
            llm_model="changed-live-model",
        )
        with patch(
            "app.services.evaluation_service.get_project_runtime_config",
            return_value=live_runtime,
        ), patch(
            "app.services.evaluation_service._eval_one_sample",
            side_effect=completed_generation,
        ):
            await run_evaluation(self.db, run.id, run_context=context)
            await run_evaluation(self.db, run.id, run_context=context)

        self.db.refresh(run)
        self.db.refresh(self.result)
        self.assertEqual(run.status, "completed")
        self.assertEqual(len(observed_configs), 1)
        self.assertEqual(observed_configs[0].llm_model, "frozen-generation-model")
        self.assertTrue(observed_configs[0].use_mock_llm)
        self.assertEqual(self.result.scorecard.judge_status, "completed")
        judge_cases = json.loads(self.result.scorecard.judge_dimensions)["cases"]
        self.assertEqual(len(judge_cases), 1)
        rule_dimensions = json.loads(self.result.scorecard.rule_dimensions)
        coverage = rule_dimensions["suite"]["checkpoint_coverage"]
        self.assertEqual(coverage["score"], 100)
        self.assertEqual(coverage["missing_checkpoints"], [])

        events = self.db.scalars(
            select(AgentRunEvent)
            .where(AgentRunEvent.agent_run_id == agent_run.id)
            .order_by(AgentRunEvent.sequence)
        ).all()
        event_types = [event.event_type for event in events]
        self.assertEqual(event_types.count("skill_started"), 1)
        self.assertEqual(event_types.count("skill_completed"), 1)
        self.assertIn("evaluation_rule_completed", event_types)
        self.assertIn("evaluation_judge_completed", event_types)


if __name__ == "__main__":
    unittest.main()
