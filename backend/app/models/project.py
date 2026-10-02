from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index(
            "uq_projects_user_eval",
            "user_id",
            unique=True,
            sqlite_where=text("is_eval = 1"),
            postgresql_where=text("is_eval = true"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    slug: Mapped[str] = mapped_column(String(100), default="")
    base_url: Mapped[str] = mapped_column(String(300), default="")
    is_eval: Mapped[bool] = mapped_column(default=False)  # 评测专用隐藏项目，不出现在业务列表
    agent_runtime_v2_enabled: Mapped[bool] = mapped_column(default=False)
    agent_specialist_allowlist: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="projects")

    requirements: Mapped[list["RequirementDocument"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    generation_tasks: Mapped[list["GenerationTask"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    testcases: Mapped[list["TestCase"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    knowledge_documents: Mapped[list["KnowledgeDocument"]] = relationship(
        cascade="all, delete-orphan",
    )
    agent_thread: Mapped["AgentThread | None"] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        uselist=False,
    )
