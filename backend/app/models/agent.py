from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AgentThread(Base):
    """测试助手在项目内的持久会话状态。

    MVP 阶段每个项目只有一个默认会话。原始消息保存在 AgentMessage，
    这里仅保存可恢复的流程状态、滚动摘要和待确认操作。
    """

    __tablename__ = "agent_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), nullable=False, unique=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="默认会话")
    summary: Mapped[str] = mapped_column(Text, default="")
    summary_until_message_id: Mapped[int] = mapped_column(Integer, default=0)
    workflow_state: Mapped[str] = mapped_column(Text, default="")
    pending_approval: Mapped[str] = mapped_column(Text, default="")
    checkpoint_thread_id: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="agent_thread")
    messages: Mapped[list["AgentMessage"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
    )


class AgentMessage(Base):
    """测试助手原始对话记录。tool_calls 存 JSON 数组 [{name, task_id?}]。"""

    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    thread_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_threads.id"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user / assistant
    content: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[str] = mapped_column(Text, default="")
    # 用户消息携带的需求文档附件，JSON: {document_id, title, source_type}
    attachment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    thread: Mapped[AgentThread | None] = relationship(back_populates="messages")
