"""轻量 API 客户端：封装 requests.Session 与常用业务流。"""

import time

import requests

# 系统内不设代理，显式绕开本机代理避免连不上 127.0.0.1
_NO_PROXY = {"http": None, "https": None}


class ApiClient:
    def __init__(self, base_url: str, username: str | None = None, password: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.trust_env = False
        self.token: str | None = None
        if username is not None and password is not None:
            self.login(username, password)

    # ---- 基础 HTTP ----
    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        return self.session.request(
            method, f"{self.base_url}{path}", proxies=_NO_PROXY, timeout=30, **kwargs
        )

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs) -> requests.Response:
        return self.request("PATCH", path, **kwargs)

    def put(self, path: str, **kwargs) -> requests.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        return self.request("DELETE", path, **kwargs)

    def login(self, username: str, password: str) -> str:
        response = self.post("/auth/login", json={"username": username, "password": password})
        response.raise_for_status()
        self.token = response.json()["token"]
        self.session.headers["Authorization"] = f"Bearer {self.token}"
        return self.token

    # ---- 业务流封装 ----
    def create_project(self, name: str, description: str = "") -> dict:
        resp = self.post("/projects", json={"name": name, "description": description})
        resp.raise_for_status()
        return resp.json()

    def delete_project(self, project_id: int) -> None:
        self.delete(f"/projects/{project_id}")

    def create_requirement(self, project_id: int, title: str, content: str) -> dict:
        resp = self.post(
            f"/projects/{project_id}/requirements",
            json={"title": title, "content": content},
        )
        resp.raise_for_status()
        return resp.json()

    def structure_requirement(self, project_id: int, doc_id: int) -> dict:
        resp = self.post(f"/projects/{project_id}/requirements/{doc_id}/structure")
        resp.raise_for_status()
        return resp.json()

    def confirm_requirement(self, project_id: int, doc_id: int, item_ids: list | None = None) -> dict:
        resp = self.post(
            f"/projects/{project_id}/requirements/{doc_id}/confirm",
            json={"item_ids": item_ids},
        )
        resp.raise_for_status()
        return resp.json()

    def prepare_confirmed_document(self, project_id: int, title: str = "自动化测试需求") -> dict:
        """文本导入 → 结构化 → 全量确认，返回 confirmed 状态的文档。"""
        doc = self.create_requirement(
            project_id, title,
            "用户登录功能：支持手机号+密码登录，密码连续错误 5 次锁定账号 30 分钟。",
        )
        self.structure_requirement(project_id, doc["id"])
        return self.confirm_requirement(project_id, doc["id"])

    def run_generation(
        self,
        project_id: int,
        document_id: int,
        strategy: str = "quick",
        specialist_skills: list | None = None,
        use_knowledge: bool = False,
        timeout: float = 60.0,
    ) -> dict:
        """创建生成任务并轮询至终态（mock 模式下秒级完成）。"""
        resp = self.post(
            f"/projects/{project_id}/generations",
            json={
                "document_id": document_id,
                "strategy": strategy,
                "specialist_skills": specialist_skills or [],
                "use_knowledge": use_knowledge,
            },
        )
        resp.raise_for_status()
        task = resp.json()

        deadline = time.time() + timeout
        while time.time() < deadline:
            task = self.get(f"/projects/{project_id}/generations/{task['id']}").json()
            if task["status"] in ("completed", "failed"):
                return task
            time.sleep(0.3)
        raise TimeoutError(f"生成任务 {task['id']} 在 {timeout}s 内未完成，最后状态: {task['status']}")

    def create_knowledge_doc(self, project_id: int, title: str, content: str, source_type: str = "doc") -> dict:
        resp = self.post(
            f"/projects/{project_id}/knowledge",
            json={"title": title, "content": content, "source_type": source_type},
        )
        resp.raise_for_status()
        return resp.json()
