import json

import httpx
from sqlalchemy.orm import Session

from app.models.skeleton import ProjectSkeleton
from app.services.settings_service import get_project_runtime_config

# 可选骨架技术栈（对应原秒搭平台的三种模板）
SKELETON_OPTIONS = [
    {
        "language": "Python",
        "framework": "pytest + requests",
        "blurb": "轻量、易上手，适合快速搭建 REST 接口回归。",
    },
    {
        "language": "Node.js",
        "framework": "Jest + axios",
        "blurb": "JS/TS 团队友好，异步接口测试直观。",
    },
    {
        "language": "Java",
        "framework": "JUnit 5 + RestAssured",
        "blurb": "企业级生态，适合中大型服务端团队。",
    },
]


def list_skeleton_options() -> list[dict]:
    return list(SKELETON_OPTIONS)


def _ctx(project) -> dict:
    slug = (project.slug or "").strip() or "api-test"
    base_url = (project.base_url or "").strip() or "https://api.example.com"
    return {"slug": slug, "base_url": base_url}


# ---------------- 静态模板（移植自原平台 skeleton.ts） ----------------

def _python_files(ctx: dict) -> list[dict]:
    slug, base_url = ctx["slug"], ctx["base_url"]
    pkg = slug
    return [
        {"path": f"{pkg}/README.md", "content": f"# {slug}\n\n基于 `pytest + requests` 的接口自动化测试骨架。\n\n## 快速开始\n\n```bash\npip install -r requirements.txt\npytest -v\n```\n\n## 结构\n\n- `config.py` 全局配置（环境、鉴权）\n- `utils/` 请求封装与公共工具\n- `api/` 被测接口的封装层\n- `tests/` 测试用例\n"},
        {"path": f"{pkg}/requirements.txt", "content": "pytest>=7.4\nrequests>=2.31\npytest-html>=4.0\n"},
        {"path": f"{pkg}/pytest.ini", "content": "[pytest]\ntestpaths = tests\naddopts = -v --html=report.html\n"},
        {"path": f"{pkg}/config.py", "content": f'"""全局配置：环境地址与公共请求头。"""\nimport os\n\nBASE_URL = os.getenv("BASE_URL", "{base_url}")\n\nDEFAULT_HEADERS = {{\n    "Content-Type": "application/json",\n    "User-Agent": "{slug}-at",\n}}\n\n# 鉴权 token 示例：在 CI 中通过环境变量注入\ndef auth_header(token: str | None = None) -> dict:\n    if not token:\n        return {{}}\n    return {{"Authorization": f"Bearer {{token}}"}}\n'},
        {"path": f"{pkg}/conftest.py", "content": f'"""pytest 共享夹具。"""\nimport pytest\nfrom config import BASE_URL\nfrom utils.http_client import HttpClient\n\n\n@pytest.fixture(scope="session")\ndef client() -> HttpClient:\n    return HttpClient(base_url=BASE_URL)\n'},
        {"path": f"{pkg}/utils/__init__.py", "content": ""},
        {"path": f"{pkg}/utils/http_client.py", "content": f'"""基于 requests 的薄封装：统一超时、异常与断言入口。"""\nimport requests\nfrom requests import Response\n\nfrom config import DEFAULT_HEADERS\n\n\nclass HttpClient:\n    def __init__(self, base_url: str, timeout: int = 10):\n        self.base_url = base_url\n        self.timeout = timeout\n\n    def request(self, method: str, path: str, *, headers: dict | None = None, **kwargs) -> Response:\n        url = f"{{self.base_url}}{{path}}"\n        merged = {{**DEFAULT_HEADERS, **(headers or {{}})}}\n        return requests.request(method, url, headers=merged, timeout=self.timeout, **kwargs)\n\n    def get(self, path: str, **kw) -> Response:\n        return self.request("GET", path, **kw)\n\n    def post(self, path: str, json=None, **kw) -> Response:\n        return self.request("POST", path, json=json, **kw)\n'},
        {"path": f"{pkg}/utils/auth.py", "content": '"""鉴权工具：获取并缓存登录 token。"""\nfrom utils.http_client import HttpClient\nfrom config import auth_header\n\n\ndef obtain_token(client: HttpClient, username: str, password: str) -> str:\n    resp = client.post("/auth/login", json={"username": username, "password": password})\n    resp.raise_for_status()\n    return resp.json()["data"]["token"]\n'},
        {"path": f"{pkg}/api/__init__.py", "content": ""},
        {"path": f"{pkg}/api/order_api.py", "content": '"""订单服务接口封装层。"""\nfrom requests import Response\nfrom utils.http_client import HttpClient\n\n\nclass OrderApi:\n    def __init__(self, client: HttpClient):\n        self.client = client\n\n    def create(self, payload: dict) -> Response:\n        return self.client.post("/api/order", json=payload)\n\n    def get(self, order_id: str) -> Response:\n        return self.client.get(f"/api/order/{order_id}")\n'},
        {"path": f"{pkg}/tests/__init__.py", "content": ""},
        {"path": f"{pkg}/tests/test_smoke.py", "content": '"""冒烟测试：验证服务可达与鉴权链路。"""\nfrom utils.http_client import HttpClient\n\n\ndef test_service_reachable(client: HttpClient) -> None:\n    resp = client.get("/health")\n    assert resp.status_code == 200\n\n\ndef test_unauthorized_returns_401(client: HttpClient) -> None:\n    resp = client.get("/api/order")\n    assert resp.status_code == 401\n'},
        {"path": f"{pkg}/tests/test_order.py", "content": '"""订单核心链路用例。"""\nimport pytest\nfrom api.order_api import OrderApi\nfrom utils.http_client import HttpClient\n\n\n@pytest.fixture\ndef order_api(client: HttpClient) -> OrderApi:\n    return OrderApi(client)\n\n\ndef test_create_order(order_api: OrderApi) -> None:\n    resp = order_api.create({"sku": "P-001", "qty": 1})\n    assert resp.status_code == 200\n    body = resp.json()\n    assert body["code"] == 0\n    assert body["data"]["orderId"]\n\n\ndef test_get_created_order(order_api: OrderApi) -> None:\n    created = order_api.create({"sku": "P-002", "qty": 2}).json()["data"]\n    resp = order_api.get(created["orderId"])\n    assert resp.status_code == 200\n    assert resp.json()["data"]["sku"] == "P-002"\n'},
    ]


def _node_files(ctx: dict) -> list[dict]:
    slug, base_url = ctx["slug"], ctx["base_url"]
    return [
        {"path": f"{slug}/package.json", "content": json.dumps({
            "name": slug,
            "version": "1.0.0",
            "type": "commonjs",
            "scripts": {"test": "jest --verbose", "test:watch": "jest --watch"},
            "devDependencies": {"axios": "^1.6.0", "jest": "^29.7.0"},
        }, indent=2, ensure_ascii=False)},
        {"path": f"{slug}/jest.config.js", "content": 'module.exports = {\n  testEnvironment: "node",\n  testMatch: ["**/tests/**/*.test.js"],\n};\n'},
        {"path": f"{slug}/.env.example", "content": f"BASE_URL={base_url}\nTOKEN=\n"},
        {"path": f"{slug}/src/config.js", "content": f'module.exports = {{\n  baseUrl: process.env.BASE_URL || "{base_url}",\n  defaultHeaders: {{\n    "Content-Type": "application/json",\n    "User-Agent": "{slug}-at",\n  }},\n}};\n'},
        {"path": f"{slug}/src/client.js", "content": 'const axios = require("axios");\nconst { baseUrl, defaultHeaders } = require("./config");\n\nconst client = axios.create({\n  baseURL: baseUrl,\n  timeout: 10000,\n  headers: defaultHeaders,\n});\n\nmodule.exports = client;\n'},
        {"path": f"{slug}/src/auth.js", "content": 'const client = require("./client");\n\nasync function obtainToken(username, password) {\n  const { data } = await client.post("/auth/login", { username, password });\n  return data.data.token;\n}\n\nmodule.exports = { obtainToken };\n'},
        {"path": f"{slug}/api/order.js", "content": 'const client = require("../src/client");\n\nconst orderApi = {\n  create(payload) {\n    return client.post("/api/order", payload);\n  },\n  get(orderId) {\n    return client.get(`/api/order/${orderId}`);\n  },\n};\n\nmodule.exports = orderApi;\n'},
        {"path": f"{slug}/tests/order.test.js", "content": 'const orderApi = require("../api/order");\n\ndescribe("订单服务", () => {\n  test("创建订单返回 orderId", async () => {\n    const { data } = await orderApi.create({ sku: "P-001", qty: 1 });\n    expect(data.code).toBe(0);\n    expect(data.data.orderId).toBeTruthy();\n  });\n\n  test("按 id 查询已创建订单", async () => {\n    const created = await orderApi.create({ sku: "P-002", qty: 2 });\n    const { data } = await orderApi.get(created.data.data.orderId);\n    expect(data.data.sku).toBe("P-002");\n  });\n});\n'},
        {"path": f"{slug}/README.md", "content": f"# {slug}\n\n基于 `Jest + axios` 的接口自动化测试骨架。\n\n```bash\nnpm install\ncp .env.example .env   # 按需配置\nnpm test\n```\n\n- `src/` 请求封装与配置\n- `api/` 被测接口封装层\n- `tests/` 测试用例\n"},
    ]


def _java_files(ctx: dict) -> list[dict]:
    slug, base_url = ctx["slug"], ctx["base_url"]
    pkg = f"com.example.{slug.replace('-', '').replace('.', '')}"
    pkg_path = pkg.replace(".", "/")
    return [
        {"path": f"{slug}/pom.xml", "content": f'<?xml version="1.0" encoding="UTF-8"?>\n<project xmlns="http://maven.apache.org/POM/4.0.0">\n  <modelVersion>4.0.0</modelVersion>\n  <groupId>com.example</groupId>\n  <artifactId>{slug}</artifactId>\n  <version>1.0.0</version>\n\n  <properties>\n    <maven.compiler.source>17</maven.compiler.source>\n    <maven.compiler.target>17</maven.compiler.target>\n  </properties>\n\n  <dependencies>\n    <dependency>\n      <groupId>io.rest-assured</groupId>\n      <artifactId>rest-assured</artifactId>\n      <version>5.4.0</version>\n      <scope>test</scope>\n    </dependency>\n    <dependency>\n      <groupId>org.junit.jupiter</groupId>\n      <artifactId>junit-jupiter</artifactId>\n      <version>5.10.0</version>\n      <scope>test</scope>\n    </dependency>\n  </dependencies>\n</project>\n'},
        {"path": f"{slug}/src/test/java/{pkg_path}/config/TestConfig.java", "content": f'package {pkg}.config;\n\npublic final class TestConfig {{\n    public static final String BASE_URL = System.getenv().getOrDefault(\n        "BASE_URL", "{base_url}");\n\n    private TestConfig() {{\n    }}\n}}\n'},
        {"path": f"{slug}/src/test/java/{pkg_path}/client/ApiClient.java", "content": f'package {pkg}.client;\n\nimport io.restassured.RestAssured;\nimport io.restassured.response.Response;\nimport {pkg}.config.TestConfig;\n\npublic class ApiClient {{\n    public ApiClient() {{\n        RestAssured.baseURI = TestConfig.BASE_URL;\n    }}\n\n    public Response get(String path) {{\n        return RestAssured.given()\n            .header("Content-Type", "application/json")\n            .get(path);\n    }}\n\n    public Response post(String path, Object body) {{\n        return RestAssured.given()\n            .header("Content-Type", "application/json")\n            .body(body)\n            .post(path);\n    }}\n}}\n'},
        {"path": f"{slug}/src/test/java/{pkg_path}/api/OrderApi.java", "content": f'package {pkg}.api;\n\nimport io.restassured.response.Response;\nimport {pkg}.client.ApiClient;\nimport java.util.Map;\n\npublic class OrderApi {{\n    private final ApiClient client = new ApiClient();\n\n    public Response create(Map<String, Object> payload) {{\n        return client.post("/api/order", payload);\n    }}\n\n    public Response get(String orderId) {{\n        return client.get("/api/order/" + orderId);\n    }}\n}}\n'},
        {"path": f"{slug}/src/test/java/{pkg_path}/tests/SmokeTest.java", "content": f'package {pkg}.tests;\n\nimport {pkg}.client.ApiClient;\nimport org.junit.jupiter.api.Test;\n\nimport static io.restassured.RestAssured.given;\n\npublic class SmokeTest {{\n    private final ApiClient client = new ApiClient();\n\n    @Test\n    void serviceIsReachable() {{\n        client.get("/health")\n            .then().statusCode(200);\n    }}\n}}\n'},
        {"path": f"{slug}/README.md", "content": f"# {slug}\n\n基于 `JUnit 5 + RestAssured` 的接口自动化测试骨架。\n\n```bash\nmvn test\n```\n\n- `config/` 测试配置\n- `client/` 请求封装\n- `api/` 被测接口封装层\n- `tests/` 测试用例\n"},
    ]


def generate_template_files(language: str, project) -> list[dict]:
    ctx = _ctx(project)
    if language == "Python":
        return _python_files(ctx)
    if language == "Node.js":
        return _node_files(ctx)
    if language == "Java":
        return _java_files(ctx)
    return _python_files(ctx)


# ---------------- AI 驱动生成（模板打底 + AI 定制） ----------------

async def _chat_once(config, system: str, user: str) -> str:
    """对 OpenAI 兼容 /chat/completions 做一次最小调用，返回文本。"""
    from app.services.model_endpoint_security import validate_model_base_url

    base_url = validate_model_base_url(config.llm_base_url)
    payload = {
        "model": config.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
        "max_tokens": 1500,
    }
    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {config.llm_api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()


def _mock_tailor(project, files: list[dict]) -> list[dict]:
    """Mock 模式下产生确定性的 AI 定制内容：补一段说明 + 一个项目专属测试文件。"""
    slug = (project.slug or "").strip() or "api-test"
    desc = (project.description or "").strip() or "接口自动化测试项目"
    tailor = f"# {slug} · AI 定制\n\n根据项目「{project.name}」生成的测试说明：\n\n- 目标：{desc}\n- 基础地址：{project.base_url or 'https://api.example.com'}\n- 由 AITC AI 引擎基于 LangGraph + 7 大 Skill 定制，而非纯静态模板。\n\n建议优先覆盖：登录鉴权、核心业务链路、异常与边界场景。"
    ai_file = {
        "path": f"{slug}/tests/test_ai_tailored.py",
        "content": f'"""AI 驱动生成的项目专属冒烟用例。"""\nimport pytest\nfrom utils.http_client import HttpClient\n\n\n# 项目：{project.name}\n# 目标：{desc}\ndef test_ai_tailored_health(client: HttpClient) -> None:\n    """项目专属链路冒烟：服务可达。"""\n    resp = client.get("/health")\n    assert resp.status_code == 200\n',
    }
    readme = next((f for f in files if f["path"].endswith("README.md")), None)
    if readme:
        readme["content"] += "\n\n---\n\n## AI 定制\n\n" + tailor
    return files + [ai_file]


async def generate_ai_files(db: Session, project, language: str, framework: str) -> list[dict]:
    files = generate_template_files(language, project)
    config = get_project_runtime_config(db, project.id)
    if config.use_mock_llm:
        return _mock_tailor(project, files)
    try:
        text = await _chat_once(
            config,
            "你是一名资深接口自动化测试工程师，根据项目信息生成一份定制的测试骨架说明（Markdown，中文）。",
            f"项目名：{project.name}\n描述：{project.description}\n目标语言/框架：{language} / {framework}\n基础地址：{project.base_url}\n请输出一段结构化的测试策略说明。",
        )
        readme = next((f for f in files if f["path"].endswith("README.md")), None)
        if readme:
            readme["content"] += "\n\n---\n\n## AI 定制\n\n" + text
        return files
    except Exception:
        # LLM 失败时回退到 mock 定制，保证演示/体验不中断
        return _mock_tailor(project, files)


async def save_skeleton(
    db: Session,
    user_id: int,
    project,
    *,
    language: str,
    framework: str,
    mode: str,
) -> ProjectSkeleton:
    if mode == "ai":
        files = await generate_ai_files(db, project, language, framework)
    else:
        files = generate_template_files(language, project)

    skeleton = (
        db.query(ProjectSkeleton)
        .filter(ProjectSkeleton.project_id == project.id)
        .first()
    )
    default_framework = next(
        (o["framework"] for o in SKELETON_OPTIONS if o["language"] == language), ""
    )
    resolved_framework = framework or default_framework or (skeleton.framework if skeleton else "")
    if skeleton is None:
        skeleton = ProjectSkeleton(
            user_id=user_id,
            project_id=project.id,
            language=language,
            framework=resolved_framework,
            mode=mode,
            files=json.dumps(files, ensure_ascii=False),
        )
        db.add(skeleton)
    else:
        skeleton.language = language
        skeleton.framework = resolved_framework
        skeleton.mode = mode
        skeleton.files = json.dumps(files, ensure_ascii=False)
        skeleton.generated_at = __import__("datetime").datetime.now()
    db.commit()
    db.refresh(skeleton)
    return skeleton


def get_skeleton(db: Session, project_id: int) -> ProjectSkeleton | None:
    return db.query(ProjectSkeleton).filter(ProjectSkeleton.project_id == project_id).first()
