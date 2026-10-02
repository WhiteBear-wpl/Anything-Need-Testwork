import json
from pathlib import Path

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def _migrate_multi_agent_schema(conn) -> None:
    """Add multi-agent provenance columns to existing SQLite installations."""
    tables = {
        row[0]
        for row in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "generated_case_drafts" in tables:
        draft_columns = {
            row[1]
            for row in conn.exec_driver_sql(
                "PRAGMA table_info(generated_case_drafts)"
            ).fetchall()
        }
        for column, ddl in [
            ("source_agents", "ALTER TABLE generated_case_drafts ADD COLUMN source_agents TEXT DEFAULT '[]'"),
            ("evidence_refs", "ALTER TABLE generated_case_drafts ADD COLUMN evidence_refs TEXT DEFAULT '[]'"),
            ("merge_reason", "ALTER TABLE generated_case_drafts ADD COLUMN merge_reason VARCHAR(100) DEFAULT ''"),
            ("agent_run_id", "ALTER TABLE generated_case_drafts ADD COLUMN agent_run_id INTEGER"),
        ]:
            if column not in draft_columns:
                conn.exec_driver_sql(ddl)
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_generated_case_drafts_agent_run_id "
            "ON generated_case_drafts (agent_run_id)"
        )

    if "generated_case_candidates" in tables:
        candidate_columns = {
            row[1]
            for row in conn.exec_driver_sql(
                "PRAGMA table_info(generated_case_candidates)"
            ).fetchall()
        }
        if "candidate_key" not in candidate_columns:
            conn.exec_driver_sql(
                "ALTER TABLE generated_case_candidates "
                "ADD COLUMN candidate_key VARCHAR(64) DEFAULT ''"
            )
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_generated_case_candidates_replay "
            "ON generated_case_candidates "
            "(agent_run_id, requirement_item_id, source_agent, candidate_key) "
            "WHERE agent_run_id IS NOT NULL AND candidate_key <> ''"
        )

    if "agent_runs" in tables:
        run_columns = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(agent_runs)").fetchall()
        }
        for column, ddl in [
            ("parent_run_id", "ALTER TABLE agent_runs ADD COLUMN parent_run_id INTEGER"),
            ("resume_from_run_id", "ALTER TABLE agent_runs ADD COLUMN resume_from_run_id INTEGER"),
            ("thread_id", "ALTER TABLE agent_runs ADD COLUMN thread_id INTEGER"),
            ("message_id", "ALTER TABLE agent_runs ADD COLUMN message_id INTEGER"),
            ("run_kind", "ALTER TABLE agent_runs ADD COLUMN run_kind VARCHAR(30) DEFAULT ''"),
            ("execution_mode", "ALTER TABLE agent_runs ADD COLUMN execution_mode VARCHAR(30) DEFAULT ''"),
            ("deadline_at", "ALTER TABLE agent_runs ADD COLUMN deadline_at DATETIME"),
            ("waiting_since", "ALTER TABLE agent_runs ADD COLUMN waiting_since DATETIME"),
            ("stop_reason", "ALTER TABLE agent_runs ADD COLUMN stop_reason VARCHAR(80) DEFAULT ''"),
            ("llm_calls_used", "ALTER TABLE agent_runs ADD COLUMN llm_calls_used INTEGER DEFAULT 0"),
            ("tool_calls_used", "ALTER TABLE agent_runs ADD COLUMN tool_calls_used INTEGER DEFAULT 0"),
            ("tokens_reserved", "ALTER TABLE agent_runs ADD COLUMN tokens_reserved INTEGER DEFAULT 0"),
            ("tokens_used", "ALTER TABLE agent_runs ADD COLUMN tokens_used INTEGER DEFAULT 0"),
            ("transport_retries_used", "ALTER TABLE agent_runs ADD COLUMN transport_retries_used INTEGER DEFAULT 0"),
            ("quality_repairs_used", "ALTER TABLE agent_runs ADD COLUMN quality_repairs_used INTEGER DEFAULT 0"),
            ("budget_warning_emitted", "ALTER TABLE agent_runs ADD COLUMN budget_warning_emitted BOOLEAN DEFAULT 0"),
            ("usage_accounting_version", "ALTER TABLE agent_runs ADD COLUMN usage_accounting_version INTEGER DEFAULT 0"),
        ]:
            if column not in run_columns:
                conn.exec_driver_sql(ddl)
        kind_cases = []
        if "evaluation_run_id" in run_columns:
            kind_cases.append("WHEN evaluation_run_id IS NOT NULL THEN 'evaluation' ")
        if "generation_task_id" in run_columns:
            kind_cases.append("WHEN generation_task_id IS NOT NULL THEN 'generation' ")
        conn.exec_driver_sql(
            "UPDATE agent_runs SET run_kind = CASE "
            + "".join(kind_cases)
            + "ELSE COALESCE(NULLIF(run_kind, ''), 'generation') END "
            "WHERE run_kind IS NULL OR run_kind = ''"
        )
        conn.exec_driver_sql(
            "UPDATE agent_runs SET execution_mode = 'worker' "
            "WHERE execution_mode IS NULL OR execution_mode = ''"
        )
        duplicate_tasks = conn.exec_driver_sql(
            "SELECT generation_task_id FROM agent_runs "
            "WHERE generation_task_id IS NOT NULL "
            "AND status IN ('queued', 'running', 'waiting_human') "
            "GROUP BY generation_task_id HAVING COUNT(*) > 1"
        ).fetchall()
        for (task_id,) in duplicate_tasks:
            keep_id = conn.exec_driver_sql(
                "SELECT MAX(id) FROM agent_runs WHERE generation_task_id = ? "
                "AND status IN ('queued', 'running', 'waiting_human')",
                (task_id,),
            ).scalar_one()
            conn.exec_driver_sql(
                "UPDATE agent_runs SET status = 'failed' "
                "WHERE generation_task_id = ? AND id <> ? "
                "AND status IN ('queued', 'running', 'waiting_human')",
                (task_id, keep_id),
            )
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_runs_active_task "
            "ON agent_runs (generation_task_id) "
            "WHERE generation_task_id IS NOT NULL "
            "AND status IN ('queued', 'running', 'waiting_human')"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_agent_runs_parent_run_id "
            "ON agent_runs (parent_run_id)"
        )
        if "created_at" in run_columns:
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_agent_runs_thread_created "
                "ON agent_runs (thread_id, created_at)"
            )
        if "updated_at" in run_columns:
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_agent_runs_inline_reconcile "
                "ON agent_runs (execution_mode, status, updated_at)"
            )


def backfill_legacy_skill_policies(conn) -> None:
    """One-time SQLite upgrade that preserves the old Specialist enablement state."""
    from app.skills.policy import PolicyResolver, ProjectSkillOverride
    from app.skills.registry import get_registry

    conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS app_schema_migrations "
        "(name VARCHAR(100) PRIMARY KEY, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    marker = conn.exec_driver_sql(
        "SELECT name FROM app_schema_migrations WHERE name = ?",
        ("project_skill_policy_v1_backfill",),
    ).first()
    if marker:
        return

    resolver = PolicyResolver(get_registry())
    projects = conn.exec_driver_sql(
        "SELECT id, agent_specialist_allowlist FROM projects"
    ).mappings().all()
    catalog = get_registry().list_selectable_specialists()
    for project in projects:
        try:
            allowlist = json.loads(project["agent_specialist_allowlist"] or "[]")
        except (json.JSONDecodeError, TypeError):
            allowlist = []
        if not isinstance(allowlist, list):
            allowlist = []
        selected = set(get_registry().validate_specialist_selection(allowlist, strict=False))
        overrides = [
            ProjectSkillOverride(skill.name, skill.name in selected)
            for skill in catalog
        ]
        resolved = resolver.resolve(overrides, revision_no=1)
        for override in overrides:
            conn.exec_driver_sql(
                "INSERT INTO project_skill_policies "
                "(project_id, skill_name, enabled, timeout_seconds, max_cases, execution_order, prompt_version) "
                "VALUES (?, ?, ?, NULL, NULL, NULL, NULL)",
                (project["id"], override.skill_name, int(override.enabled)),
            )
        resolved_snapshot = {
            "policy_revision": 1,
            "catalog_fingerprint": resolved.catalog_fingerprint,
            "specialists": {item.skill_name: item.to_dict() for item in resolved.specialists},
        }
        conn.exec_driver_sql(
            "INSERT INTO project_skill_policy_revisions "
            "(project_id, revision_no, source, overrides_snapshot, resolved_snapshot, catalog_fingerprint) "
            "VALUES (?, 1, 'legacy_backfill', ?, ?, ?)",
            (
                project["id"],
                json.dumps([item.to_dict() for item in overrides], ensure_ascii=False, sort_keys=True),
                json.dumps(resolved_snapshot, ensure_ascii=False, sort_keys=True),
                resolved.catalog_fingerprint,
            ),
        )
    conn.exec_driver_sql(
        "INSERT INTO app_schema_migrations (name) VALUES (?)",
        ("project_skill_policy_v1_backfill",),
    )


def get_db(request: Request):
    db = SessionLocal()
    auth_session = getattr(request.state, "auth_session", None)
    if auth_session:
        db.info["user_id"] = auth_session.user_id
        db.info["username"] = auth_session.username
        db.info["is_admin"] = auth_session.is_admin
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app.models import agent, agent_run, evaluation, execution, generation, knowledge, project, requirement, skill_policy, skeleton, system_config, testcase, user, wiki  # noqa: F401
    from app.models.user import User
    from app.services.auth_service import ensure_bootstrap_admin
    from app.services.settings_service import ensure_bootstrap_admin_config, get_or_create_config

    if settings.database_url.startswith("sqlite"):
        database_path = engine.url.database
        if database_path and database_path != ":memory:":
            Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        admin = ensure_bootstrap_admin(db)
        _migrate_schema(admin.id)
        ensure_bootstrap_admin_config(db, admin.id)
        for (user_id,) in db.query(User.id).all():
            get_or_create_config(db, user_id)
    finally:
        db.close()


def _migrate_schema(admin_user_id: int):
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.connect() as conn:
        _migrate_multi_agent_schema(conn)
        conn.commit()
        cols = conn.exec_driver_sql("PRAGMA table_info(generation_tasks)").fetchall()
        col_names = {row[1] for row in cols}
        if "strategy_config" not in col_names:
            conn.exec_driver_sql("ALTER TABLE generation_tasks ADD COLUMN strategy_config TEXT DEFAULT ''")
            conn.commit()
        if "tokens_used" not in col_names:
            conn.exec_driver_sql("ALTER TABLE generation_tasks ADD COLUMN tokens_used INTEGER DEFAULT 0")
            conn.commit()
        if "is_eval" not in col_names:
            conn.exec_driver_sql("ALTER TABLE generation_tasks ADD COLUMN is_eval BOOLEAN DEFAULT 0")
            conn.commit()
        if "stage" not in col_names:
            conn.exec_driver_sql("ALTER TABLE generation_tasks ADD COLUMN stage VARCHAR(100) DEFAULT ''")
            conn.commit()
        if "knowledge_refs" not in col_names:
            conn.exec_driver_sql("ALTER TABLE generation_tasks ADD COLUMN knowledge_refs TEXT DEFAULT ''")
            conn.commit()

        eval_run_tables = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='eval_runs'"
        ).fetchall()
        if eval_run_tables:
            eval_run_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(eval_runs)").fetchall()}
            for col, ddl in [
                ("stage", "ALTER TABLE eval_runs ADD COLUMN stage VARCHAR(100) DEFAULT ''"),
                ("config_snapshot", "ALTER TABLE eval_runs ADD COLUMN config_snapshot TEXT DEFAULT '{}'"),
                ("sample_set_fingerprint", "ALTER TABLE eval_runs ADD COLUMN sample_set_fingerprint VARCHAR(64) DEFAULT ''"),
                ("is_baseline", "ALTER TABLE eval_runs ADD COLUMN is_baseline BOOLEAN DEFAULT 0"),
                ("agent_run_id", "ALTER TABLE eval_runs ADD COLUMN agent_run_id INTEGER"),
            ]:
                if col not in eval_run_cols:
                    conn.exec_driver_sql(ddl)
                    conn.commit()
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_eval_runs_sample_set_fingerprint "
                "ON eval_runs (sample_set_fingerprint)"
            )

        for table, additions in [
            ("eval_results", [
                ("run_sample_id", "ALTER TABLE eval_results ADD COLUMN run_sample_id INTEGER"),
                ("error_summary", "ALTER TABLE eval_results ADD COLUMN error_summary TEXT DEFAULT ''"),
            ]),
            ("eval_samples", [
                ("version", "ALTER TABLE eval_samples ADD COLUMN version INTEGER DEFAULT 1"),
            ]),
            ("agent_runs", [
                ("evaluation_run_id", "ALTER TABLE agent_runs ADD COLUMN evaluation_run_id INTEGER"),
            ]),
        ]:
            exists = conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchall()
            if not exists:
                continue
            cols = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
            for col, ddl in additions:
                if col not in cols:
                    conn.exec_driver_sql(ddl)
                    conn.commit()
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_runs_active_evaluation "
            "ON agent_runs (evaluation_run_id) WHERE evaluation_run_id IS NOT NULL "
            "AND status IN ('queued', 'running', 'waiting_human')"
        )
        conn.commit()

        scorecard_exists = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='evaluation_scorecards'"
        ).fetchall()
        if not scorecard_exists:
            from app.models.evaluation import EvaluationScorecard

            EvaluationScorecard.__table__.create(bind=conn, checkfirst=True)
        else:
            scorecard_cols = {
                row[1]
                for row in conn.exec_driver_sql("PRAGMA table_info(evaluation_scorecards)").fetchall()
            }
            for column, ddl in [
                ("ruleset_version", "ALTER TABLE evaluation_scorecards ADD COLUMN ruleset_version VARCHAR(100) DEFAULT ''"),
                ("judge_prompt_version", "ALTER TABLE evaluation_scorecards ADD COLUMN judge_prompt_version VARCHAR(100) DEFAULT ''"),
                ("input_fingerprint", "ALTER TABLE evaluation_scorecards ADD COLUMN input_fingerprint VARCHAR(64) DEFAULT ''"),
                ("rule_score", "ALTER TABLE evaluation_scorecards ADD COLUMN rule_score INTEGER"),
                ("rule_verdict", "ALTER TABLE evaluation_scorecards ADD COLUMN rule_verdict VARCHAR(20) DEFAULT ''"),
                ("rule_dimensions", "ALTER TABLE evaluation_scorecards ADD COLUMN rule_dimensions TEXT DEFAULT '{}'"),
                ("judge_status", "ALTER TABLE evaluation_scorecards ADD COLUMN judge_status VARCHAR(20) DEFAULT 'not_evaluated'"),
                ("judge_verdict", "ALTER TABLE evaluation_scorecards ADD COLUMN judge_verdict VARCHAR(20) DEFAULT ''"),
                ("judge_dimensions", "ALTER TABLE evaluation_scorecards ADD COLUMN judge_dimensions TEXT DEFAULT '{}'"),
                ("judge_reason", "ALTER TABLE evaluation_scorecards ADD COLUMN judge_reason TEXT DEFAULT ''"),
                ("golden_alignment", "ALTER TABLE evaluation_scorecards ADD COLUMN golden_alignment TEXT DEFAULT '{}'"),
                ("assessment_status", "ALTER TABLE evaluation_scorecards ADD COLUMN assessment_status VARCHAR(30) DEFAULT 'not_evaluated'"),
            ]:
                if column not in scorecard_cols:
                    conn.exec_driver_sql(ddl)
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_evaluation_scorecards_result_id "
            "ON evaluation_scorecards (result_id)"
        )
        conn.commit()

        draft_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(generated_case_drafts)").fetchall()}
        if "is_smoke" not in draft_cols:
            conn.exec_driver_sql("ALTER TABLE generated_case_drafts ADD COLUMN is_smoke BOOLEAN DEFAULT 0")
            conn.commit()
        if "was_edited" not in draft_cols:
            conn.exec_driver_sql("ALTER TABLE generated_case_drafts ADD COLUMN was_edited BOOLEAN DEFAULT 0")
            # 存量数据：当前状态为 edited 的草稿补标
            conn.exec_driver_sql("UPDATE generated_case_drafts SET was_edited = 1 WHERE review_status = 'edited'")
            conn.commit()
        for col, ddl in [
            ("reject_reason", "ALTER TABLE generated_case_drafts ADD COLUMN reject_reason VARCHAR(200) DEFAULT ''"),
            ("judge_score", "ALTER TABLE generated_case_drafts ADD COLUMN judge_score FLOAT"),
            ("judge_issues", "ALTER TABLE generated_case_drafts ADD COLUMN judge_issues TEXT DEFAULT ''"),
            ("generation_key", "ALTER TABLE generated_case_drafts ADD COLUMN generation_key VARCHAR(160)"),
        ]:
            if col not in draft_cols:
                conn.exec_driver_sql(ddl)
                conn.commit()
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_generated_case_drafts_generation_key "
            "ON generated_case_drafts (generation_key) WHERE generation_key IS NOT NULL"
        )
        conn.commit()

        config_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(system_config)").fetchall()}
        for col, ddl in [
            ("eval_llm_api_key", "ALTER TABLE system_config ADD COLUMN eval_llm_api_key VARCHAR(500) DEFAULT ''"),
            ("eval_llm_base_url", "ALTER TABLE system_config ADD COLUMN eval_llm_base_url VARCHAR(500) DEFAULT ''"),
            ("eval_llm_model", "ALTER TABLE system_config ADD COLUMN eval_llm_model VARCHAR(100) DEFAULT ''"),
            ("embedding_api_key", "ALTER TABLE system_config ADD COLUMN embedding_api_key VARCHAR(500) DEFAULT ''"),
            ("embedding_base_url", "ALTER TABLE system_config ADD COLUMN embedding_base_url VARCHAR(500) DEFAULT ''"),
            ("embedding_model", "ALTER TABLE system_config ADD COLUMN embedding_model VARCHAR(100) DEFAULT ''"),
            ("rerank_api_key", "ALTER TABLE system_config ADD COLUMN rerank_api_key VARCHAR(500) DEFAULT ''"),
            ("rerank_base_url", "ALTER TABLE system_config ADD COLUMN rerank_base_url VARCHAR(500) DEFAULT ''"),
            ("rerank_model", "ALTER TABLE system_config ADD COLUMN rerank_model VARCHAR(100) DEFAULT ''"),
        ]:
            if config_cols and col not in config_cols:
                conn.exec_driver_sql(ddl)
                conn.commit()
        if config_cols:
            # 旧版允许评测字段逐项回退。新版本为避免把生成 Key 发给另一域名，
            # 将历史不完整三元组清空，统一安全回退到生成模型。
            conn.exec_driver_sql(
                "UPDATE system_config SET "
                "eval_llm_api_key = '', eval_llm_base_url = '', eval_llm_model = '' "
                "WHERE ("
                "COALESCE(eval_llm_api_key, '') <> '' OR "
                "COALESCE(eval_llm_base_url, '') <> '' OR "
                "COALESCE(eval_llm_model, '') <> ''"
                ") AND NOT ("
                "COALESCE(eval_llm_api_key, '') <> '' AND "
                "COALESCE(eval_llm_base_url, '') <> '' AND "
                "COALESCE(eval_llm_model, '') <> ''"
                ")"
            )
            conn.commit()
        if config_cols and "user_id" not in config_cols:
            conn.exec_driver_sql("ALTER TABLE system_config ADD COLUMN user_id INTEGER")
        if config_cols:
            conn.exec_driver_sql(
                "UPDATE system_config SET user_id = ? WHERE user_id IS NULL",
                (admin_user_id,),
            )
            null_config_owner_count = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM system_config WHERE user_id IS NULL"
            ).scalar_one()
            if null_config_owner_count:
                raise RuntimeError("模型配置归属迁移失败：仍有配置未关联用户")
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_system_config_user_id "
                "ON system_config (user_id)"
            )
            conn.commit()

        report_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(quality_reports)").fetchall()}
        for col, ddl in [
            ("avg_judge_score", "ALTER TABLE quality_reports ADD COLUMN avg_judge_score FLOAT"),
            ("hallucination_count", "ALTER TABLE quality_reports ADD COLUMN hallucination_count INTEGER DEFAULT 0"),
            ("duplicate_count", "ALTER TABLE quality_reports ADD COLUMN duplicate_count INTEGER DEFAULT 0"),
        ]:
            if col not in report_cols:
                conn.exec_driver_sql(ddl)
                conn.commit()

        tc_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(testcases)").fetchall()}
        if "is_smoke" not in tc_cols:
            conn.exec_driver_sql("ALTER TABLE testcases ADD COLUMN is_smoke BOOLEAN DEFAULT 0")
            conn.commit()

        project_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(projects)").fetchall()}
        if "slug" not in project_cols:
            conn.exec_driver_sql("ALTER TABLE projects ADD COLUMN slug VARCHAR(100) DEFAULT ''")
            conn.commit()
        if "base_url" not in project_cols:
            conn.exec_driver_sql("ALTER TABLE projects ADD COLUMN base_url VARCHAR(300) DEFAULT ''")
            conn.commit()
        if "is_eval" not in project_cols:
            conn.exec_driver_sql("ALTER TABLE projects ADD COLUMN is_eval BOOLEAN DEFAULT 0")
            conn.commit()
        if "agent_runtime_v2_enabled" not in project_cols:
            conn.exec_driver_sql(
                "ALTER TABLE projects ADD COLUMN agent_runtime_v2_enabled BOOLEAN DEFAULT 0"
            )
            conn.commit()
        if "agent_specialist_allowlist" not in project_cols:
            conn.exec_driver_sql(
                "ALTER TABLE projects ADD COLUMN agent_specialist_allowlist TEXT DEFAULT '[]'"
            )
            conn.commit()
        if "user_id" not in project_cols:
            conn.exec_driver_sql("ALTER TABLE projects ADD COLUMN user_id INTEGER")
            conn.exec_driver_sql(
                "UPDATE projects SET user_id = ? WHERE user_id IS NULL",
                (admin_user_id,),
            )
        else:
            conn.exec_driver_sql(
                "UPDATE projects SET user_id = ? WHERE user_id IS NULL",
                (admin_user_id,),
            )
        null_owner_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM projects WHERE user_id IS NULL"
        ).scalar_one()
        if null_owner_count:
            raise RuntimeError("项目归属迁移失败：仍有项目未关联用户")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_projects_user_id ON projects (user_id)")
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_user_eval "
            "ON projects (user_id) WHERE is_eval = 1"
        )
        conn.commit()

        backfill_legacy_skill_policies(conn)
        conn.commit()

        # 「测试轮次」已升级为「测试任务 + 批次」，旧表按约定直接废弃
        conn.exec_driver_sql("DROP TABLE IF EXISTS test_run_cases")
        conn.exec_driver_sql("DROP TABLE IF EXISTS test_runs")
        conn.commit()

        doc_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(requirement_documents)").fetchall()}
        if "test_scope" not in doc_cols:
            conn.exec_driver_sql("ALTER TABLE requirement_documents ADD COLUMN test_scope TEXT DEFAULT ''")
            conn.commit()
        if "is_eval" not in doc_cols:
            conn.exec_driver_sql("ALTER TABLE requirement_documents ADD COLUMN is_eval BOOLEAN DEFAULT 0")
            conn.commit()

        agent_msg_cols = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(agent_messages)").fetchall()
        }
        if agent_msg_cols and "attachment" not in agent_msg_cols:
            conn.exec_driver_sql("ALTER TABLE agent_messages ADD COLUMN attachment TEXT DEFAULT ''")
            conn.commit()
        if agent_msg_cols and "thread_id" not in agent_msg_cols:
            conn.exec_driver_sql("ALTER TABLE agent_messages ADD COLUMN thread_id INTEGER")
            conn.commit()
        # create_all 已创建 agent_threads。为每个项目补一个默认会话，并把历史消息归入其中。
        agent_thread_tables = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_threads'"
        ).fetchall()
        if agent_thread_tables:
            conn.exec_driver_sql(
                "INSERT OR IGNORE INTO agent_threads "
                "(project_id, title, summary, summary_until_message_id, workflow_state, "
                "pending_approval, checkpoint_thread_id, created_at, updated_at) "
                "SELECT id, '默认会话', '', 0, '', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
                "FROM projects"
            )
            conn.exec_driver_sql(
                "UPDATE agent_messages SET thread_id = ("
                "SELECT agent_threads.id FROM agent_threads "
                "WHERE agent_threads.project_id = agent_messages.project_id"
                ") WHERE thread_id IS NULL"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_agent_messages_thread_id "
                "ON agent_messages (thread_id)"
            )
            conn.commit()

        knowledge_doc_cols = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(knowledge_documents)").fetchall()
        }
        if knowledge_doc_cols and "vector_collection" not in knowledge_doc_cols:
            conn.exec_driver_sql(
                "ALTER TABLE knowledge_documents ADD COLUMN vector_collection VARCHAR(120) DEFAULT ''"
            )
            conn.commit()
        if knowledge_doc_cols:
            # 本次不迁移旧 Chroma collection。保留原文，但明确标记需重新入库，
            # 避免旧文档继续显示 ready 却只有 BM25、没有新向量索引。
            conn.exec_driver_sql(
                "UPDATE knowledge_documents SET status = 'failed', "
                "error_message = '向量索引已升级，请删除后重新上传' "
                "WHERE status = 'ready' AND COALESCE(vector_collection, '') = ''"
            )
            conn.commit()
