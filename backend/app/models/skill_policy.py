from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProjectSkillPolicy(Base):
    """The current sparse project override for one selectable Specialist."""

    __tablename__ = "project_skill_policies"
    __table_args__ = (
        UniqueConstraint("project_id", "skill_name", name="uq_project_skill_policy"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    timeout_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_cases: Mapped[int | None] = mapped_column(Integer, nullable=True)
    execution_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ProjectSkillPolicyRevision(Base):
    """Immutable audit record of one successful Policy save or legacy backfill."""

    __tablename__ = "project_skill_policy_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "revision_no", name="uq_project_skill_policy_revision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    overrides_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    catalog_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
