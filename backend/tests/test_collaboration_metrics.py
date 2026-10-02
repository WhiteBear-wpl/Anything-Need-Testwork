import json
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.generation import GeneratedCaseCandidate, GeneratedCaseDraft, GenerationTask
from app.models.project import Project
from app.models.requirement import RequirementDocument
from app.models.user import User


class CollaborationMetricFixture(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="collaboration-metric-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        self.project = Project(user_id=user.id, name="collaboration metrics")
        self.db.add(self.project)
        self.db.flush()
        self.document = RequirementDocument(project_id=self.project.id, title="doc")
        self.db.add(self.document)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_task_run(self, *, status="completed", created_at=None):
        task = GenerationTask(project_id=self.project.id, document_id=self.document.id)
        self.db.add(task)
        self.db.flush()
        run = AgentRun(
            project_id=self.project.id,
            generation_task_id=task.id,
            status=status,
            agent_spec_snapshot="{}",
            budget_snapshot="{}",
            created_at=created_at or datetime(2026, 8, 10),
        )
        self.db.add(run)
        self.db.flush()
        return task, run


class TaskCollaborationSummaryTests(CollaborationMetricFixture):
    def test_review_is_attributed_to_every_source_agent_without_candidate_payload(self):
        """Catches merged specialist influence being lost or raw candidate data leaking."""
        from app.services.collaboration_metrics import build_task_collaboration_summary

        task, run = self.add_task_run()
        other_run = AgentRun(
            project_id=self.project.id,
            generation_task_id=task.id,
            status="completed",
            agent_spec_snapshot="{}",
            budget_snapshot="{}",
            created_at=datetime(2026, 8, 11),
        )
        self.db.add(other_run)
        self.db.flush()
        self.db.add_all([
            GeneratedCaseCandidate(
                task_id=task.id,
                agent_run_id=run.id,
                source_agent="case_writer",
                payload='{"secret":"core raw"}',
                merge_disposition="selected",
            ),
            GeneratedCaseCandidate(
                task_id=task.id,
                agent_run_id=run.id,
                source_agent="security",
                payload='{"secret":"specialist raw"}',
                merge_disposition="merged_duplicate",
                merge_reason="duplicate_normalized_steps",
            ),
            GeneratedCaseDraft(
                task_id=task.id,
                agent_run_id=run.id,
                title="Merged login case",
                source_agents=json.dumps(["case_writer", "security"]),
                review_status="adopted",
                was_edited=True,
            ),
            GeneratedCaseDraft(
                task_id=task.id,
                agent_run_id=run.id,
                title="API rejection",
                source_agents=json.dumps(["api_test"]),
                review_status="rejected",
            ),
            AgentRunEvent(
                agent_run_id=run.id,
                sequence=1,
                event_type="agent_warning",
                stage="specialist",
                payload_summary=json.dumps({"agent": "api_test", "message": "timeout"}),
            ),
            GeneratedCaseDraft(
                task_id=task.id,
                agent_run_id=other_run.id,
                title="Retry-only draft",
                source_agents='["api_test"]',
                review_status="adopted",
            ),
        ])
        self.db.commit()

        summary = build_task_collaboration_summary(
            self.db, self.project.id, task.id, run.id
        )

        self.assertEqual(summary["candidate_count"], 2)
        self.assertEqual(
            summary["candidate_counts_by_agent"], {"case_writer": 1, "security": 1}
        )
        self.assertEqual(
            summary["disposition_counts"], {"merged_duplicate": 1, "selected": 1}
        )
        self.assertEqual(summary["warning_counts_by_agent"], {"api_test": 1})
        self.assertEqual(
            summary["draft_counts_by_agent"],
            {"api_test": 1, "case_writer": 1, "security": 1},
        )
        self.assertEqual(
            summary["adopted_participation_by_agent"],
            {"case_writer": 1, "security": 1},
        )
        self.assertEqual(
            summary["edited_participation_by_agent"],
            {"case_writer": 1, "security": 1},
        )
        self.assertNotIn("payload", summary["candidates"][0])
        self.assertNotIn("core raw", json.dumps(summary, default=str))

    def test_invalid_source_agents_falls_back_to_case_writer(self):
        """Catches malformed historic provenance making review counts disappear."""
        from app.services.collaboration_metrics import build_task_collaboration_summary

        task, run = self.add_task_run()
        self.db.add(
            GeneratedCaseDraft(
                task_id=task.id,
                agent_run_id=run.id,
                title="Historic draft",
                source_agents="not-json",
                review_status="adopted",
            )
        )
        self.db.commit()

        summary = build_task_collaboration_summary(
            self.db, self.project.id, task.id, run.id
        )

        self.assertEqual(summary["draft_counts_by_agent"], {"case_writer": 1})
        self.assertEqual(summary["adopted_participation_by_agent"], {"case_writer": 1})


class ProjectRolloutReportTests(CollaborationMetricFixture):
    def test_report_counts_each_generation_task_once_using_latest_terminal_run(self):
        """Catches retries consuming multiple slots in the thirty-task rollout window."""
        from app.services.collaboration_metrics import build_project_rollout_report

        first_task, first_run = self.add_task_run(
            status="completed", created_at=datetime(2026, 8, 8)
        )
        retry = AgentRun(
            project_id=self.project.id,
            generation_task_id=first_task.id,
            status="failed",
            agent_spec_snapshot="{}",
            budget_snapshot="{}",
            created_at=datetime(2026, 8, 10),
        )
        self.db.add(retry)
        self.add_task_run(status="completed", created_at=datetime(2026, 8, 9))
        self.db.add(
            AgentRun(
                project_id=self.project.id,
                generation_task_id=None,
                status="completed",
                agent_spec_snapshot="{}",
                budget_snapshot="{}",
                created_at=datetime(2026, 8, 11),
            )
        )
        self.db.commit()

        report = build_project_rollout_report(self.db, self.project.id)

        self.assertEqual(report["sample_size"], 2)
        self.assertEqual(report["completed_runs"], 1)
        self.assertEqual(report["failed_runs"], 1)
        self.assertNotIn(first_run.id, [retry.id])

    def test_preclaim_cancellation_has_a_complete_lifecycle(self):
        """Catches a legitimate queued cancellation permanently failing the event gate."""
        from app.services.collaboration_metrics import build_project_rollout_report

        _task, run = self.add_task_run(status="cancelled")
        self.db.add(
            AgentRunEvent(
                agent_run_id=run.id,
                sequence=1,
                event_type="run_cancelled",
                payload_summary="{}",
            )
        )
        self.db.commit()

        report = build_project_rollout_report(self.db, self.project.id)

        self.assertTrue(report["gates"]["events_present"])

    def test_event_gate_requires_claim_and_terminal_lifecycle(self):
        """Catches a lone specialist event being mistaken for a complete run timeline."""
        from app.services.collaboration_metrics import build_project_rollout_report

        _task, run = self.add_task_run(status="completed")
        self.db.add(
            AgentRunEvent(
                agent_run_id=run.id,
                sequence=1,
                event_type="agent_started",
                stage="specialist",
                payload_summary='{"agent":"security"}',
            )
        )
        self.db.commit()

        report = build_project_rollout_report(self.db, self.project.id)

        self.assertFalse(report["gates"]["events_present"])

    def test_report_uses_latest_thirty_runs_and_terminal_failure_denominator(self):
        """Catches old runs or queued work distorting the rollout gate."""
        from app.services.collaboration_metrics import build_project_rollout_report

        base = datetime(2026, 8, 1, 9, 0, 0)
        statuses = ["completed"] * 27 + ["failed", "cancelled", "queued"]
        latest = []
        for offset, status in enumerate(statuses, start=2):
            task, run = self.add_task_run(status=status, created_at=base + timedelta(days=offset))
            if status != "queued":
                run.started_at = run.created_at
                run.finished_at = run.created_at + timedelta(seconds=2)
            self.db.add(
                AgentRunEvent(
                    agent_run_id=run.id,
                    sequence=1,
                    event_type="agent_started",
                    stage="specialist",
                    payload_summary='{"agent":"security"}',
                )
            )
            latest.append((task, run))

        for offset in range(2):
            self.add_task_run(status="failed", created_at=base + timedelta(days=offset))

        adopted_task, adopted_run = latest[-2]
        self.db.add_all([
            GeneratedCaseCandidate(
                task_id=adopted_task.id,
                agent_run_id=adopted_run.id,
                source_agent="security",
                payload="{}",
                merge_disposition="selected",
            ),
            GeneratedCaseDraft(
                task_id=adopted_task.id,
                agent_run_id=adopted_run.id,
                title="Specialist-influenced case",
                source_agents='["case_writer","security"]',
                review_status="adopted",
            ),
        ])
        self.db.commit()

        report = build_project_rollout_report(self.db, self.project.id, limit=30)

        self.assertEqual(report["sample_size"], 30)
        self.assertEqual(report["completed_runs"], 27)
        self.assertEqual(report["failed_runs"], 2)
        self.assertEqual(report["cancelled_runs"], 1)
        self.assertEqual(report["system_failure_rate"], 6.67)
        self.assertEqual(report["average_duration_ms"], 2000)
        self.assertEqual(report["agent_started_count"], 29)
        self.assertEqual(report["specialist_influenced_adopted_count"], 1)
        self.assertTrue(report["gates"]["sample_complete"])
        self.assertFalse(report["gates"]["events_present"])
        self.assertFalse(report["gates"]["system_failure_rate_ok"])
        self.assertFalse(report["duration_baseline_available"])


if __name__ == "__main__":
    unittest.main()
