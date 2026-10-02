import os
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import BASE_DIR, settings


CHECKPOINT_PATH = Path(
    settings.aitc_agent_checkpoint_path
    or os.environ.get("AITC_AGENT_CHECKPOINT_PATH", "")
    or BASE_DIR / "data" / "agent_checkpoints.sqlite"
)


def checkpoint_context():
    """为单次 Agent 运行提供可跨请求恢复的 SQLite Checkpointer。"""
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    return AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_PATH))


async def delete_checkpoint(thread_id: str) -> None:
    if not thread_id:
        return
    async with checkpoint_context() as checkpointer:
        await checkpointer.adelete_thread(thread_id)
