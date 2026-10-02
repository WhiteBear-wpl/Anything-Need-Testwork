import json
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent_runtime.contracts import BudgetExhausted, ExecutionBudget, RunContext
from app.database import Base
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.project import Project
from app.models.user import User


class AgentRuntimeBudgetTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        user = User(username="budget-ledger-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        self.project = Project(user_id=user.id, name="budget ledger")
        self.db.add(self.project)
        self.db.flush()
        self.run = AgentRun(
            project_id=self.project.id,
            run_kind="chat",
            execution_mode="inline",
            status="running",
            started_at=datetime.now(),
            deadline_at=datetime.now() + timedelta(minutes=5),
            budget_snapshot="{}",
        )
        self.db.add(self.run)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _ledger(self, budget: ExecutionBudget, mode: str = "enforce"):
        from app.agent_runtime.budget import BudgetLedger

        context = RunContext(
            run_id=self.run.id,
            project_id=self.project.id,
            task_id=0,
            budget=budget,
        )
        return BudgetLedger(self.db, context, mode=mode)

    def test_enforce_blocks_the_next_llm_reservation(self):
        """Catches a configured LLM-call limit that never stops an external call."""
        ledger = self._ledger(
            ExecutionBudget(max_llm_calls=1, max_tokens=100, max_runtime_seconds=300)
        )
        reservation = ledger.reserve_llm(input_tokens=20, max_output_tokens=30)
        ledger.settle_llm(
            reservation,
            {"input_tokens": 18, "output_tokens": 12},
            output="完成",
        )

        with self.assertRaises(BudgetExhausted) as caught:
            ledger.reserve_llm(input_tokens=1, max_output_tokens=1)

        self.assertEqual(caught.exception.dimension, "llm_calls")
        self.db.refresh(self.run)
        self.assertEqual(self.run.llm_calls_used, 1)
        self.assertEqual(self.run.tokens_used, 30)
        self.assertEqual(self.run.tokens_reserved, 0)

    def test_enforce_blocks_token_overcommit_before_reservation(self):
        """Catches parallel/provider output allowance overspending the frozen token limit."""
        ledger = self._ledger(
            ExecutionBudget(max_llm_calls=5, max_tokens=10, max_runtime_seconds=300)
        )

        with self.assertRaises(BudgetExhausted) as caught:
            ledger.reserve_llm(input_tokens=6, max_output_tokens=5)

        self.assertEqual(caught.exception.dimension, "tokens")
        self.db.refresh(self.run)
        self.assertEqual((self.run.llm_calls_used, self.run.tokens_reserved), (0, 0))

    def test_observe_records_overage_without_blocking(self):
        """Catches gray observe mode accidentally enforcing production limits."""
        ledger = self._ledger(
            ExecutionBudget(max_tool_calls=1, max_runtime_seconds=300),
            mode="observe",
        )

        ledger.reserve_tool("first")
        ledger.reserve_tool("second")

        self.db.refresh(self.run)
        self.assertEqual(self.run.tool_calls_used, 2)
        event_types = [
            event.event_type
            for event in self.db.query(AgentRunEvent)
            .filter(AgentRunEvent.agent_run_id == self.run.id)
            .order_by(AgentRunEvent.sequence)
        ]
        self.assertEqual(event_types, ["budget_warning", "budget_would_exhaust"])

    def test_missing_provider_usage_uses_deterministic_estimate(self):
        """Catches providers without usage metadata being recorded as zero cost."""
        ledger = self._ledger(
            ExecutionBudget(max_llm_calls=2, max_tokens=100, max_runtime_seconds=300)
        )
        reservation = ledger.reserve_llm(input_tokens=4, max_output_tokens=20)

        usage = ledger.settle_llm(reservation, None, output="测试完成")

        self.assertEqual(usage.source, "estimated")
        self.assertEqual(usage.input_tokens, 4)
        self.assertEqual(usage.output_tokens, 4)
        self.db.refresh(self.run)
        self.assertEqual(self.run.tokens_used, 8)
        self.assertEqual(self.run.tokens_reserved, 0)

    def test_expired_deadline_is_a_runtime_budget_exhaustion(self):
        """Catches runtime deadlines being advisory instead of a hard pre-call guard."""
        self.run.deadline_at = datetime.now() - timedelta(seconds=1)
        self.db.commit()
        ledger = self._ledger(ExecutionBudget(max_tool_calls=2, max_runtime_seconds=300))

        with self.assertRaises(BudgetExhausted) as caught:
            ledger.reserve_tool("late")

        self.assertEqual(caught.exception.dimension, "runtime_seconds")
        self.db.refresh(self.run)
        self.assertEqual(self.run.tool_calls_used, 0)


class ConcurrentBudgetWarningTests(unittest.TestCase):
    def test_parallel_reservations_emit_one_warning_and_never_overspend(self):
        """Catches two Specialists both consuming the final budget unit."""
        db_path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / f"budget-race-{uuid.uuid4().hex}.db"
        )
        engine = create_engine(f"sqlite:///{db_path}")
        factory = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)
        setup = factory()
        try:
            user = User(username=f"budget-race-{uuid.uuid4().hex}", password_hash="hash")
            setup.add(user)
            setup.flush()
            project = Project(user_id=user.id, name="budget race")
            setup.add(project)
            setup.flush()
            run = AgentRun(
                project_id=project.id,
                status="running",
                run_kind="generation",
                execution_mode="worker",
                llm_calls_used=3,
                started_at=datetime.now(),
                deadline_at=datetime.now() + timedelta(minutes=5),
                budget_snapshot=json.dumps({"max_llm_calls": 5}),
            )
            setup.add(run)
            setup.commit()
            run_id = run.id
            project_id = project.id

            def reserve_one(_index):
                from app.agent_runtime.budget import BudgetLedger

                db = factory()
                try:
                    context = RunContext(
                        run_id=run_id,
                        project_id=project_id,
                        task_id=0,
                        budget=ExecutionBudget(
                            max_llm_calls=5,
                            max_tokens=1_000,
                            max_runtime_seconds=300,
                        ),
                    )
                    BudgetLedger(db, context, mode="enforce").reserve_llm(
                        input_tokens=1,
                        max_output_tokens=1,
                    )
                    return "reserved"
                except BudgetExhausted:
                    return "blocked"
                finally:
                    db.close()

            with ThreadPoolExecutor(max_workers=3) as pool:
                results = list(pool.map(reserve_one, range(3)))

            setup.expire_all()
            refreshed = setup.get(AgentRun, run_id)
            warning_count = (
                setup.query(AgentRunEvent)
                .filter_by(agent_run_id=run_id, event_type="budget_warning")
                .count()
            )
            self.assertEqual(sorted(results), ["blocked", "reserved", "reserved"])
            self.assertEqual(refreshed.llm_calls_used, 5)
            self.assertEqual(warning_count, 1)
        finally:
            setup.close()
            engine.dispose()
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
