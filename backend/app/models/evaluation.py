from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EvalSample(Base):
    """离线评测样本：固化的需求内容 + 人工整理的标准测试点。"""

    __tablename__ = "eval_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")  # 需求内容快照，保证每次运行输入一致
    checkpoints: Mapped[str] = mapped_column(Text, default="[]")  # JSON: [{text, keywords[]}]
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    results: Mapped[list["EvalResult"]] = relationship(back_populates="sample")


class EvalRun(Base):
    """一次评测运行：对若干样本走完整生成链路并汇总指标。"""

    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)  # 如 baseline-no-rag
    config: Mapped[str] = mapped_column(Text, default="{}")  # JSON: strategy / model 快照
    config_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    sample_set_fingerprint: Mapped[str] = mapped_column(String(64), default="", index=True)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/running/completed/failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str] = mapped_column(String(100), default="")  # 当前阶段提示
    error_message: Mapped[str] = mapped_column(Text, default="")
    metrics: Mapped[str] = mapped_column(Text, default="{}")  # JSON: 运行级汇总指标
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    results: Mapped[list["EvalResult"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    samples: Mapped[list["EvalRunSample"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class EvalRunSample(Base):
    """An immutable evaluation input captured for one EvalRun."""

    __tablename__ = "eval_run_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("eval_runs.id"), nullable=False, index=True)
    source_sample_id: Mapped[int] = mapped_column(ForeignKey("eval_samples.id"), nullable=False)
    sample_version: Mapped[int] = mapped_column(Integer, nullable=False)
    title_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    content_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    checkpoints_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoints_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    run: Mapped["EvalRun"] = relationship(back_populates="samples")


class EvalResult(Base):
    """单个样本在一次运行中的结果。"""

    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("eval_runs.id"), nullable=False)
    sample_id: Mapped[int] = mapped_column(ForeignKey("eval_samples.id"), nullable=False)
    run_sample_id: Mapped[int | None] = mapped_column(ForeignKey("eval_run_samples.id"), nullable=True, index=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 关联的生成任务（可追溯）
    status: Mapped[str] = mapped_column(String(20), default="pending")
    metrics: Mapped[str] = mapped_column(Text, default="{}")  # JSON: 样本级指标
    error_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    run: Mapped["EvalRun"] = relationship(back_populates="results")
    sample: Mapped["EvalSample"] = relationship(back_populates="results")
    scorecard: Mapped["EvaluationScorecard | None"] = relationship(
        back_populates="result",
        uselist=False,
        cascade="all, delete-orphan",
    )


class EvaluationScorecard(Base):
    """Immutable dual-track assessment captured for one evaluation result."""

    __tablename__ = "evaluation_scorecards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    result_id: Mapped[int] = mapped_column(
        ForeignKey("eval_results.id"), nullable=False, unique=True, index=True
    )
    ruleset_version: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    judge_prompt_version: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    rule_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rule_verdict: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    rule_dimensions: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    judge_status: Mapped[str] = mapped_column(String(20), default="not_evaluated", nullable=False)
    judge_verdict: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    judge_dimensions: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    judge_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    golden_alignment: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    assessment_status: Mapped[str] = mapped_column(
        String(30), default="not_evaluated", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    result: Mapped["EvalResult"] = relationship(back_populates="scorecard")
