from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AgentSpec(Base):
    __tablename__ = "agent_specs"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_agent_specs_name_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    definition: Mapped[str] = mapped_column(Text, default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index(
            "uq_agent_runs_active_task",
            "generation_task_id",
            unique=True,
            sqlite_where=text(
                "generation_task_id IS NOT NULL AND "
                "status IN ('queued', 'running', 'waiting_human')"
            ),
        ),
        Index(
            "uq_agent_runs_active_evaluation",
            "evaluation_run_id",
            unique=True,
            sqlite_where=text(
                "evaluation_run_id IS NOT NULL AND "
                "status IN ('queued', 'running', 'waiting_human')"
            ),
        ),
        Index("ix_agent_runs_parent_run_id", "parent_run_id"),
        Index("ix_agent_runs_thread_created", "thread_id", "created_at"),
        Index(
            "ix_agent_runs_inline_reconcile",
            "execution_mode",
            "status",
            "updated_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    generation_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("generation_tasks.id"), nullable=True, index=True
    )
    evaluation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("eval_runs.id"), nullable=True, index=True
    )
    agent_spec_id: Mapped[int | None] = mapped_column(ForeignKey("agent_specs.id"), nullable=True)
    parent_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id"), nullable=True
    )
    resume_from_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id"), nullable=True
    )
    thread_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_threads.id"), nullable=True
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_messages.id"), nullable=True
    )
    run_kind: Mapped[str] = mapped_column(String(30), default="generation")
    execution_mode: Mapped[str] = mapped_column(String(30), default="worker")
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_owner: Mapped[str] = mapped_column(String(120), default="")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    agent_spec_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    budget_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    waiting_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stop_reason: Mapped[str] = mapped_column(String(80), default="")
    llm_calls_used: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls_used: Mapped[int] = mapped_column(Integer, default=0)
    tokens_reserved: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    transport_retries_used: Mapped[int] = mapped_column(Integer, default=0)
    quality_repairs_used: Mapped[int] = mapped_column(Integer, default=0)
    budget_warning_emitted: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_accounting_version: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    events: Mapped[list["AgentRunEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentRunEvent.sequence"
    )
    artifacts: Mapped[list["AgentRunArtifact"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AgentRunEvent(Base):
    __tablename__ = "agent_run_events"
    __table_args__ = (
        UniqueConstraint("agent_run_id", "sequence", name="uq_agent_run_events_run_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(100), default="")
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_summary: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    run: Mapped["AgentRun"] = relationship(back_populates="events")


class AgentRunArtifact(Base):
    __tablename__ = "agent_run_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    content_preview: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    protected_from_purge: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    run: Mapped["AgentRun"] = relationship(back_populates="artifacts")


class KnowledgeCandidate(Base):
    __tablename__ = "knowledge_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    evidence: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(30), default="pending")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
