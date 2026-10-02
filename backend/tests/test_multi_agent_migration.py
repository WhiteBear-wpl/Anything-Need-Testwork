import unittest

from sqlalchemy import create_engine


class MultiAgentMigrationTests(unittest.TestCase):
    def test_legacy_tables_gain_provenance_and_replay_identity(self):
        """Catches existing SQLite installs missing columns that create_all cannot add."""
        from app.database import _migrate_multi_agent_schema

        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE generated_case_drafts ("
                "id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, title VARCHAR(500) NOT NULL)"
            )
            conn.exec_driver_sql(
                "CREATE TABLE generated_case_candidates ("
                "id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, "
                "requirement_item_id INTEGER, agent_run_id INTEGER, "
                "source_agent VARCHAR(50) NOT NULL, payload TEXT DEFAULT '{}')"
            )
            conn.exec_driver_sql(
                "CREATE TABLE agent_runs ("
                "id INTEGER PRIMARY KEY, generation_task_id INTEGER, "
                "status VARCHAR(30) DEFAULT 'queued')"
            )
            _migrate_multi_agent_schema(conn)

            draft_columns = {
                row[1] for row in conn.exec_driver_sql(
                    "PRAGMA table_info(generated_case_drafts)"
                ).fetchall()
            }
            candidate_columns = {
                row[1] for row in conn.exec_driver_sql(
                    "PRAGMA table_info(generated_case_candidates)"
                ).fetchall()
            }
            candidate_indexes = {
                row[1] for row in conn.exec_driver_sql(
                    "PRAGMA index_list(generated_case_candidates)"
                ).fetchall()
            }
            run_indexes = {
                row[1] for row in conn.exec_driver_sql("PRAGMA index_list(agent_runs)").fetchall()
            }

        engine.dispose()
        self.assertTrue(
            {"source_agents", "evidence_refs", "merge_reason", "agent_run_id"}
            <= draft_columns
        )
        self.assertIn("candidate_key", candidate_columns)
        self.assertIn("uq_generated_case_candidates_replay", candidate_indexes)
        self.assertIn("uq_agent_runs_active_task", run_indexes)


if __name__ == "__main__":
    unittest.main()
