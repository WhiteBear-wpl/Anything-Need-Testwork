import json
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.evaluation import EvaluationScorecard, EvalResult, EvalRun, EvalSample
from app.models.project import Project
from app.models.user import User


class EvaluationRolloutMetricsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="evaluation-rollout-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        self.project = Project(user_id=user.id, name="evaluation rollout", is_eval=True)
        self.db.add(self.project)
        self.db.flush()
        self.sample = EvalSample(project_id=self.project.id, title="登录", content="需求")
        self.db.add(self.sample)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _run(self, label, *, judge_status=None, status="completed"):
        eval_run = EvalRun(project_id=self.project.id, label=label, status=status)
        self.db.add(eval_run)
        self.db.flush()
        agent_run = AgentRun(
            project_id=self.project.id,
            evaluation_run_id=eval_run.id,
            status=status,
            agent_spec_snapshot="{}",
            budget_snapshot="{}",
        )
        self.db.add(agent_run)
        self.db.flush()
        eval_run.agent_run_id = agent_run.id
        if judge_status is not None:
            result = EvalResult(
                run_id=eval_run.id,
                sample_id=self.sample.id,
                status="completed",
            )
            self.db.add(result)
            self.db.flush()
            self.db.add(
                EvaluationScorecard(
                    result_id=result.id,
                    judge_status=judge_status,
                    rule_verdict="pass",
                    assessment_status=(
                        "judge_unavailable" if judge_status == "unavailable" else "dual_pass"
                    ),
                )
            )
        self.db.commit()
        return agent_run

    def _events(self, run, rows):
        for sequence, (event_type, created_at, payload) in enumerate(rows, start=1):
            self.db.add(
                AgentRunEvent(
                    agent_run_id=run.id,
                    sequence=sequence,
                    event_type=event_type,
                    stage="skill" if event_type.startswith("skill_") else "judge",
                    payload_summary=json.dumps(payload, ensure_ascii=False),
                    created_at=created_at,
                )
            )
        self.db.commit()

    def test_report_calculates_rates_latency_and_duplicate_lifecycle_events(self):
        from app.services.evaluation_rollout_metrics import build_evaluation_rollout_report

        base = datetime(2026, 8, 15, 9, 0, 0)
        normal = self._run("normal", judge_status="completed")
        retry = self._run("retry", judge_status="completed")
        unavailable = self._run("unavailable", judge_status="unavailable")
        cancelled = self._run(
            "cancelled",
            judge_status="not_evaluated",
            status="cancelled",
        )

        self._events(normal, [
            ("skill_started", base, {"skill": "case_judge"}),
            ("skill_completed", base + timedelta(milliseconds=20), {"skill": "case_judge"}),
            ("evaluation_judge_completed", base + timedelta(milliseconds=21), {}),
        ])
        self._events(retry, [
            ("evaluation_judge_retry", base, {"attempt": 1}),
            ("skill_started", base + timedelta(milliseconds=1), {"skill": "case_judge"}),
            ("skill_started", base + timedelta(milliseconds=2), {"skill": "case_judge"}),
            ("skill_completed", base + timedelta(milliseconds=3), {"skill": "case_judge"}),
            ("evaluation_judge_completed", base + timedelta(milliseconds=4), {}),
        ])
        self._events(unavailable, [
            ("evaluation_judge_retry", base, {"attempt": 1}),
            ("evaluation_judge_unavailable", base + timedelta(milliseconds=5), {}),
        ])
        self._events(cancelled, [
            ("run_cancel_requested", base, {}),
            ("run_cancelled", base + timedelta(milliseconds=125), {}),
        ])

        report = build_evaluation_rollout_report(self.db, self.project.id)

        self.assertEqual(report["terminal_run_count"], 4)
        self.assertEqual(report["judged_batch_count"], 3)
        self.assertEqual(report["judge_unavailable_count"], 1)
        self.assertEqual(report["judge_unavailable_rate"], 33.3)
        self.assertEqual(report["judge_retry_batch_count"], 2)
        self.assertEqual(report["judge_retry_rate"], 66.7)
        self.assertEqual(report["cancellation_latency_ms"], {
            "count": 1,
            "average": 125.0,
            "maximum": 125.0,
        })
        self.assertEqual(report["duplicate_skill_lifecycle_event_count"], 1)

    def test_retry_rate_counts_unique_attempted_batches_including_cancelled(self):
        from app.services.evaluation_rollout_metrics import build_evaluation_rollout_report

        base = datetime(2026, 8, 15, 10, 0, 0)
        retry = self._run("retry-once", judge_status="completed")
        normal = self._run("normal-once", judge_status="completed")
        cancelled = self._run(
            "cancel-after-retry",
            judge_status="not_evaluated",
            status="cancelled",
        )
        legacy_cancelled = self._run(
            "legacy-cancel-after-retry",
            judge_status="not_evaluated",
            status="cancelled",
        )
        retry_result_id = self.db.scalar(
            select(EvalResult.id).where(EvalResult.run_id == retry.evaluation_run_id)
        )
        normal_result_id = self.db.scalar(
            select(EvalResult.id).where(EvalResult.run_id == normal.evaluation_run_id)
        )
        cancelled_result_id = self.db.scalar(
            select(EvalResult.id).where(EvalResult.run_id == cancelled.evaluation_run_id)
        )

        self._events(retry, [
            ("evaluation_judge_started", base, {"result_id": retry_result_id}),
            ("evaluation_judge_retry", base, {"result_id": retry_result_id, "attempt": 1}),
            ("evaluation_judge_retry", base, {"result_id": retry_result_id, "attempt": 1}),
            ("evaluation_judge_completed", base, {"result_id": retry_result_id}),
        ])
        self._events(normal, [
            ("evaluation_judge_started", base, {"result_id": normal_result_id}),
            ("evaluation_judge_completed", base, {"result_id": normal_result_id}),
        ])
        self._events(cancelled, [
            ("evaluation_judge_started", base, {"result_id": cancelled_result_id}),
            ("evaluation_judge_retry", base, {"result_id": cancelled_result_id, "attempt": 1}),
            ("run_cancel_requested", base, {}),
            ("run_cancelled", base + timedelta(milliseconds=10), {}),
        ])
        self._events(legacy_cancelled, [
            ("evaluation_judge_retry", base, {"attempt": 1}),
            ("run_cancel_requested", base, {}),
            ("run_cancelled", base + timedelta(milliseconds=20), {}),
        ])

        report = build_evaluation_rollout_report(self.db, self.project.id)

        self.assertEqual(report["judged_batch_count"], 2)
        self.assertEqual(report["judge_attempted_batch_count"], 3)
        self.assertEqual(report["judge_retry_batch_count"], 2)
        self.assertEqual(report["judge_retry_rate"], 66.7)


if __name__ == "__main__":
    unittest.main()
