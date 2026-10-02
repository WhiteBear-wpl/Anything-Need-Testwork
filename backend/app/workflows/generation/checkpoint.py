import os
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import BASE_DIR, settings


CHECKPOINT_PATH = Path(
    settings.aitc_langgraph_checkpoint_path
    or os.environ.get("AITC_LANGGRAPH_CHECKPOINT_PATH", "")
    or BASE_DIR / "data" / "langgraph_checkpoints.sqlite"
)


def checkpoint_context():
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    return AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_PATH))
