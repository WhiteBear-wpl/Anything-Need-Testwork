from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RequirementDocument(Base):
    __tablename__ = "requirement_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), default="text")  # text, file
    raw_content: Mapped[str] = mapped_column(Text, default="")
    test_scope: Mapped[str] = mapped_column(Text, default="")  # JSON: in_scope/out_scope/risks
    status: Mapped[str] = mapped_column(String(20), default="uploaded")  # uploaded, structured, confirmed
    is_eval: Mapped[bool] = mapped_column(default=False)  # 评测运行产生的文档，业务列表默认过滤
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="requirements")
    items: Mapped[list["RequirementItem"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class RequirementItem(Base):
    __tablename__ = "requirement_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("requirement_documents.id"), nullable=False)
    module: Mapped[str] = mapped_column(String(100), default="")
    feature: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    acceptance_criteria: Mapped[str] = mapped_column(Text, default="")
    constraints: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(10), default="P1")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    confirmed: Mapped[bool] = mapped_column(default=False)

    document: Mapped["RequirementDocument"] = relationship(back_populates="items")
