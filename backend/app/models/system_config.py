from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

class SystemConfig(Base):
    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    llm_api_key: Mapped[str] = mapped_column(String(500), default="")
    llm_base_url: Mapped[str] = mapped_column(String(500), default="")
    llm_model: Mapped[str] = mapped_column(String(100), default="")
    llm_mock_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    # 评测专用 LLM，留空则复用生成模型配置
    eval_llm_api_key: Mapped[str] = mapped_column(String(500), default="")
    eval_llm_base_url: Mapped[str] = mapped_column(String(500), default="")
    eval_llm_model: Mapped[str] = mapped_column(String(100), default="")
    # Embedding 模型（知识库检索），不与 Chat 配置回退互通
    embedding_api_key: Mapped[str] = mapped_column(String(500), default="")
    embedding_base_url: Mapped[str] = mapped_column(String(500), default="")
    embedding_model: Mapped[str] = mapped_column(String(100), default="")
    # Rerank 模型（知识库检索精排），留空则只做混合检索 RRF 融合
    rerank_api_key: Mapped[str] = mapped_column(String(500), default="")
    rerank_base_url: Mapped[str] = mapped_column(String(500), default="")
    rerank_model: Mapped[str] = mapped_column(String(100), default="")

    user: Mapped["User"] = relationship(back_populates="system_config")
