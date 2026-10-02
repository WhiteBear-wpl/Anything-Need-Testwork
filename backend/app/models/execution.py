from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _summarize(cases: list) -> dict:
    """汇总执行进度：通过 / 失败 / 阻塞 / 未执行与通过率。"""
    total = len(cases)
    passed = sum(1 for c in cases if c.result == "passed")
    failed = sum(1 for c in cases if c.result == "failed")
    blocked = sum(1 for c in cases if c.result == "blocked")
    pending = total - passed - failed - blocked
    executed = passed + failed + blocked
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "blocked": blocked,
        "pending": pending,
        "executed": executed,
        "pass_rate": round(passed / total * 100, 1) if total else 0.0,
    }


class TestTask(Base):
    __tablename__ = "test_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="in_progress")  # in_progress, completed
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    batches: Mapped[list["TestBatch"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TestBatch.id"
    )

    @property
    def stats(self) -> dict:
        """任务级汇总：所有批次执行记录合并统计。"""
        all_cases = [bc for batch in (self.batches or []) for bc in (batch.batch_cases or [])]
        return _summarize(all_cases)


class TestBatch(Base):
    __tablename__ = "test_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("test_tasks.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # 线下测试 / 预发测试 / 线上测试 / 自定义
    status: Mapped[str] = mapped_column(String(20), default="in_progress")  # in_progress, completed
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    task: Mapped["TestTask"] = relationship(back_populates="batches")
    batch_cases: Mapped[list["TestBatchCase"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )

    @property
    def stats(self) -> dict:
        return _summarize(self.batch_cases or [])


class TestBatchCase(Base):
    __tablename__ = "test_batch_cases"
    __table_args__ = (UniqueConstraint("batch_id", "case_id", name="uq_batch_case"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("test_batches.id"), nullable=False, index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("testcases.id"), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(20), default="pending")  # pending, passed, failed, blocked
    note: Mapped[str] = mapped_column(Text, default="")  # 失败 / 阻塞原因等备注
    defect_ref: Mapped[str] = mapped_column(String(200), default="")  # 缺陷单号或链接
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    batch: Mapped["TestBatch"] = relationship(back_populates="batch_cases")
    case: Mapped["TestCase"] = relationship()
