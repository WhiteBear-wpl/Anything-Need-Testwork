from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8", extra="ignore")

    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-v4-flash"
    llm_mock_mode: bool = True

    # 评测专用 LLM（AI Judge / 召回率判定），留空则复用上面的生成模型配置
    eval_llm_api_key: str = ""
    eval_llm_base_url: str = ""
    eval_llm_model: str = ""

    # Embedding 模型（知识库检索用），与 Chat 接口类型不同，需单独配置
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = ""

    # Rerank 模型（知识库检索精排），留空则只做混合检索 RRF 融合
    rerank_api_key: str = ""
    rerank_base_url: str = ""
    rerank_model: str = ""

    # 生产环境额外允许的自建 OpenAI 兼容接口域名（逗号分隔，不包含协议或路径）
    model_api_extra_hosts: str = ""

    # 登录账号（演示用，可通过环境变量覆盖）
    auth_username: str = "admin"
    auth_password: str = "nini123456"
    auth_token_ttl_hours: int = 24
    auth_max_attempts: int = 5
    auth_lockout_minutes: int = 15
    allow_registration: bool = True
    registration_max_per_hour: int = 5

    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'app.db'}"
    # LangGraph 运行检查点与业务库分开保存，便于失败任务恢复。
    aitc_langgraph_checkpoint_path: str = ""
    # 测试助手的人机确认检查点单独保存，避免与批量生成任务互相影响。
    aitc_agent_checkpoint_path: str = ""
    # Runtime V2 requires both this global kill switch and a project-level opt-in.
    agent_runtime_v2_enabled: bool = False
    unified_agent_runtime_enabled: bool = False
    runtime_budget_mode: Literal["observe", "enforce"] = "observe"
    agent_worker_poll_seconds: float = 1.0
    agent_run_lease_seconds: int = 90
    agent_raw_retention_days: int = 30
    debug: bool = True
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def use_mock_llm(self) -> bool:
        return self.llm_mock_mode or not self.llm_api_key


settings = Settings()
