"""UI 自动化 conftest：拉起指向隔离后端的前端 dev server。"""

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
import requests

from api.client import ApiClient

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
WEB_DIR = ROOT_DIR / "web"
WEB_PORT = int(os.environ.get("AITC_TEST_WEB_PORT", "5273"))
# Windows 上 npm 是 npm.cmd，直接调 "npm" 会找不到可执行文件
NPM = "npm.cmd" if sys.platform == "win32" else "npm"


@pytest.fixture(scope="session")
def web_base_url(api_base_url):
    backend_origin = api_base_url.removesuffix("/api")
    env = {**os.environ, "VITE_API_TARGET": backend_origin}
    process = subprocess.Popen(
        [NPM, "run", "dev", "--", "--port", str(WEB_PORT), "--strictPort", "--host", "127.0.0.1"],
        cwd=WEB_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{WEB_PORT}"
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if requests.get(url, timeout=2, proxies={"http": None}).status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(0.5)
        else:
            raise RuntimeError("前端 dev server 60s 内未就绪")
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture(scope="session")
def base_url(web_base_url):
    """供 pytest-playwright 解析 page.goto 的相对路径。"""
    return web_base_url


@pytest.fixture(autouse=True)
def _seed_login(context, api):
    """预置由测试后端真实签发的登录态。"""
    context.add_init_script(
        f"localStorage.setItem('aitc_auth', JSON.stringify({{token: '{api.token}', username: 'autotest-admin'}}))"
    )


@pytest.fixture(scope="session")
def api(api_base_url, auth_credentials) -> ApiClient:
    """直连后端的 API 客户端：用接口造数据，UI 只验证交互。"""
    return ApiClient(api_base_url, *auth_credentials)


@pytest.fixture
def seeded_project(api):
    data = api.create_project(f"UI-{uuid.uuid4().hex[:8]}", "UI 自动化临时项目")
    yield data
    api.delete_project(data["id"])


@pytest.fixture
def project_with_cases(api, seeded_project):
    """已有入库用例的项目：生成 → 全部采纳。"""
    doc = api.prepare_confirmed_document(seeded_project["id"])
    task = api.run_generation(seeded_project["id"], doc["id"], strategy="quick")
    draft_ids = [d["id"] for d in task["drafts"]]
    api.post(
        f"/projects/{seeded_project['id']}/generations/{task['id']}/review",
        json={"draft_ids": draft_ids, "action": "adopt"},
    )
    return {"project": seeded_project, "task": task}
