"""自动化测试全局 conftest：拉起隔离的后端服务。

- 独立 SQLite 数据库与 Chroma 目录（临时目录，会话结束自动清理）
- 强制 mock 模式：不依赖外部 LLM / Embedding API，结果确定、可离线运行
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
API_PORT = int(os.environ.get("AITC_TEST_API_PORT", "8100"))
IS_WINDOWS = sys.platform == "win32"
TEST_AUTH_USERNAME = "autotest-admin"
TEST_AUTH_PASSWORD = "autotest-only-password"


def backend_python() -> Path:
    """后端虚拟环境中的 Python（避免复制虚拟环境后 uvicorn shebang 失效）。"""
    if IS_WINDOWS:
        return BACKEND_DIR / "venv" / "Scripts" / "python.exe"
    return BACKEND_DIR / "venv" / "bin" / "python"


def _wait_for(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=2).status_code == 200:
                return
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(0.3)
    raise RuntimeError(f"后端服务在 {timeout}s 内未就绪: {last_error}")


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="session")
def api_base_url():
    """启动一个使用独立数据库、mock 模式的后端实例，返回 API base url。"""
    if _port_in_use(API_PORT):
        raise RuntimeError(f"端口 {API_PORT} 已被占用，请先停止旧的测试服务")

    tmp_dir = Path(tempfile.mkdtemp(prefix="aitc-autotest-"))
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{tmp_dir / 'autotest.db'}",
        "AITC_CHROMA_DIR": str(tmp_dir / "chroma"),
        "AITC_LANGGRAPH_CHECKPOINT_PATH": str(tmp_dir / "langgraph-checkpoints.db"),
        "LLM_MOCK_MODE": "true",
        "LLM_API_KEY": "",
        "EVAL_LLM_API_KEY": "",
        "EVAL_LLM_BASE_URL": "",
        "EVAL_LLM_MODEL": "",
        "EMBEDDING_API_KEY": "",
        "EMBEDDING_BASE_URL": "",
        "EMBEDDING_MODEL": "",
        "AUTH_USERNAME": TEST_AUTH_USERNAME,
        "AUTH_PASSWORD": TEST_AUTH_PASSWORD,
    }
    process = subprocess.Popen(
        [str(backend_python()), "-m", "uvicorn", "app.main:app", "--port", str(API_PORT)],
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{API_PORT}/api"
    try:
        _wait_for(f"{base_url}/health")
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def auth_credentials():
    return TEST_AUTH_USERNAME, TEST_AUTH_PASSWORD
