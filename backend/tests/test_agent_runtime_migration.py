import unittest

from sqlalchemy import create_engine


class AgentRuntimeMigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.conn = self.engine.connect()
        self.conn.exec_driver_sql(
            "CREATE TABLE agent_runs ("
            "id INTEGER PRIMARY KEY, "
            "generation_task_id INTEGER, "
            "evaluation_run_id INTEGER, "
            "status VARCHAR(30), "
            "created_at DATETIME, "
            "updated_at DATETIME"
            ")"
        )
        self.conn.exec_driver_sql(
            "INSERT INTO agent_runs "
            "(id, generation_task_id, evaluation_run_id, status, created_at, updated_at) "
            "VALUES "
            "(1, 10, NULL, 'completed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "(2, NULL, 20, 'failed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.engine.dispose()

    def test_migration_adds_runtime_columns_and_backfills_historical_kind(self):
        """Catches create_all leaving existing SQLite installations without new columns."""
        from app.database import _migrate_multi_agent_schema

        _migrate_multi_agent_schema(self.conn)
        self.conn.commit()

        columns = {
            row[1] for row in self.conn.exec_driver_sql("PRAGMA table_info(agent_runs)").fetchall()
        }
        self.assertTrue(
            {
                "run_kind",
                "execution_mode",
                "parent_run_id",
                "resume_from_run_id",
                "thread_id",
                "message_id",
                "deadline_at",
                "waiting_since",
                "stop_reason",
                "llm_calls_used",
                "tool_calls_used",
                "tokens_reserved",
                "tokens_used",
                "transport_retries_used",
                "quality_repairs_used",
                "budget_warning_emitted",
                "usage_accounting_version",
            }.issubset(columns)
        )
        rows = self.conn.exec_driver_sql(
            "SELECT id, run_kind, execution_mode, usage_accounting_version "
            "FROM agent_runs ORDER BY id"
        ).fetchall()
        self.assertEqual(
            rows,
            [(1, "generation", "worker", 0), (2, "evaluation", "worker", 0)],
        )

    def test_migration_is_idempotent_and_creates_lookup_indexes(self):
        """Catches startup failing when the additive migration runs more than once."""
        from app.database import _migrate_multi_agent_schema

        _migrate_multi_agent_schema(self.conn)
        _migrate_multi_agent_schema(self.conn)
        self.conn.commit()

        indexes = {
            row[1] for row in self.conn.exec_driver_sql("PRAGMA index_list(agent_runs)").fetchall()
        }
        self.assertIn("ix_agent_runs_parent_run_id", indexes)
        self.assertIn("ix_agent_runs_thread_created", indexes)
        self.assertIn("ix_agent_runs_inline_reconcile", indexes)


if __name__ == "__main__":
    unittest.main()
