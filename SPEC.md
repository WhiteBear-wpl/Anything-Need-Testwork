# SPEC.md · 完整技术规格书

> **本文件给 AI Agent 用**——照着写就能完成项目。
> 开发铁律见 `AGENTS.md`。

---

## 0. 开发阶段总览

```
Phase 0：环境 + 骨架（先让项目能启动）
  → Phase 1：三内核最小实现（Tool Registry + Tool Loop + Event Bus）
    → Phase 2：UI / API / 数据 / 规则 四种适配器
      → Phase 3：CLI 端到端跑通一条混合用例
        → Phase 4：AI 用例生成（NL → 结构化计划）
          → Phase 5：证据链 + RCA 诊断
            → Phase 6：FastAPI 路由 + SSE + 前端 4 个页面
              → Phase 7：pytest 覆盖率 + CI + Docker Compose + README
```

---

## 1. 项目目录结构

```
AI智能测试一体化平台/
├── README.md
├── LICENSE                            # MIT
├── .gitignore
├── .pre-commit-config.yaml            # pre-commit：Ruff + mypy
├── AGENTS.md                          # AI Agent 开发指令
├── SPEC.md                            # 本文件
├── .env.example                       # 环境变量模板
├── docker-compose.yml                 # PostgreSQL + Redis + Backend + Frontend
│
├── backend/                           # FastAPI 后端
│   ├── pyproject.toml                 # 依赖（使用 uv 或 poetry）
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── alembic/
│   └── app/
│       ├── __init__.py
│       ├── main.py                    # FastAPI 入口：app = FastAPI(...)
│       ├── config.py                  # pydantic Settings（读 .env）
│       ├── logging_setup.py           # 日志配置
│       │
│       ├── core/                      # ⭐ 三内核
│       │   ├── __init__.py
│       │   ├── tool_registry.py       # Tool Registry
│       │   ├── tool_loop.py           # Tool Loop 状态机
│       │   ├── event_bus.py           # Event Bus
│       │   └── exceptions.py          # 自定义异常
│       │
│       ├── adapters/                  # ⭐ 适配器层
│       │   ├── __init__.py
│       │   ├── base.py                # Tool 基类 + 工具契约 Pydantic 模型
│       │   ├── ui_adapter.py          # Playwright 工具
│       │   ├── api_adapter.py         # httpx 工具
│       │   ├── data_adapter.py        # Faker + LLM 造数
│       │   └── rule_adapter.py        # 规则断言
│       │
│       ├── ai/                        # AI 智能中枢
│       │   ├── __init__.py
│       │   ├── provider.py            # LLM Provider 抽象层
│       │   ├── case_generator.py      # NL → 结构化测试计划
│       │   ├── rca.py                 # 失败根因诊断
│       │   └── prompts/               # Prompt 模板
│       │       ├── case_gen.txt
│       │       └── rca.txt
│       │
│       ├── models/                    # Pydantic V2 数据模型
│       │   ├── __init__.py
│       │   ├── enums.py               # AdapterType / StepStatus / RunStatus / DiagnosisType
│       │   ├── test_case.py           # TestCase / TestStep / TestPlan
│       │   ├── test_run.py            # TestRun / ExecutionEvent / StepResult
│       │   └── diagnosis.py           # FailureDiagnosis
│       │
│       ├── database/                  # SQLAlchemy async
│       │   ├── __init__.py
│       │   ├── session.py              # async_sessionmaker + get_db
│       │   └── tables/                 # SQLAlchemy ORM 表定义
│       │       ├── __init__.py
│       │       ├── test_case.py
│       │       ├── test_run.py
│       │       └── artifact.py
│       │
│       ├── routers/                   # FastAPI 路由
│       │   ├── __init__.py
│       │   ├── cases.py                # /api/v1/cases/* + /api/v1/generate
│       │   ├── execute.py              # /api/v1/execute/* + SSE /api/v1/stream/{run_id}
│       │   ├── rca.py                  # /api/v1/rca/*
│       │   ├── reports.py              # /api/v1/reports/*
│       │   └── artifacts.py            # /api/v1/artifacts/*
│       │
│       ├── services/                  # 业务编排层
│       │   ├── __init__.py
│       │   ├── execution_service.py    # 调 Tool Loop + 监听 Event Bus
│       │   ├── evidence_service.py     # 监听 Event Bus → 存证据
│       │   └── report_service.py       # 读 TestRun → 生成报告
│       │
│       └── utils/
│           ├── __init__.py
│           ├── variable_injector.py    # {{step1.user_id}} 自动回填
│           └── accessibility_compressor.py  # Playwright snapshot 压缩
│
│   └── tests/                         # pytest
│       ├── conftest.py                 # fixtures
│       ├── unit/
│       │   ├── test_tool_registry.py
│       │   ├── test_tool_loop.py
│       │   ├── test_event_bus.py
│       │   ├── test_variable_injector.py
│       │   ├── test_accessibility_compressor.py
│       │   └── test_ai_case_gen.py
│       └── integration/
│           └── test_e2e_mixed_flow.py
│
├── frontend/                          # Vue 3 + TS + TailwindCSS + Element Plus
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── Dockerfile
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── router/index.ts
│       ├── stores/
│       │   ├── cases.ts
│       │   ├── execution.ts           # 含 SSE EventSource
│       │   └── rca.ts
│       ├── components/
│       │   ├── CaseEditor.vue
│       │   ├── ExecutionTimeline.vue
│       │   ├── RCAPanel.vue
│       │   ├── ReportChart.vue
│       │   └── ScreenshotViewer.vue
│       ├── views/
│       │   ├── CaseManagement.vue
│       │   ├── ExecutionConsole.vue
│       │   ├── DiagnosisView.vue
│       │   └── ReportView.vue
│       └── types/api.ts               # TS 类型与后端 Pydantic 对齐
│
└── assets/
    ├── demo/                          # Demo GIF / 截图
    └── evidence/                      # Phase 完成证据
```

---

## 2. 环境配置

### `.env.example`（后端用，根目录提供）

```env
# LLM Provider
LLM_PROVIDER=mock                     # deepseek | ollama | mock
LLM_API_KEY=
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_TEMPERATURE=0.3
LLM_MAX_TOKENS=4096

# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_test_workbench

# Redis
REDIS_URL=redis://localhost:6379/0

# Playwright
PLAYWRIGHT_HEADLESS=true
PLAYWRIGHT_SLOW_MO=0
PLAYWRIGHT_DEFAULT_TIMEOUT=30000

# Evidence
EVIDENCE_DIR=./assets/evidence
EVIDENCE_VIDEO=true
EVIDENCE_TRACE=true
EVIDENCE_SCREENSHOT=true

# Tool Loop
MAX_TURNS=50
TOOL_CALL_TIMEOUT=30
AUTO_RETRY_ON_TOOL_ERROR=true
MAX_RETRY_ATTEMPTS=1
```

### `backend/pyproject.toml`

```toml
[project]
name = "ai-test-workbench"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.5.0",
    "sqlalchemy>=2.0.35",
    "asyncpg>=0.29.0",
    "alembic>=1.13.0",
    "redis>=5.0.0",
    "playwright>=1.47.0",
    "httpx>=0.27.0",
    "faker>=24.0.0",
    "jsonpath-ng>=1.6.0",
    "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=5.0.0",
    "ruff>=0.6.0",
    "mypy>=1.11.0",
    "pre-commit>=3.8.0",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "A"]
ignore = ["E501"]

[tool.mypy]
python_version = "3.12"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.coverage.run]
source = ["app"]
omit = ["tests/*"]

[tool.coverage.report]
show_missing = true
fail_under = 80
```

### `docker-compose.yml`

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: ai_test_workbench
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  backend:
    build: ./backend
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/ai_test_workbench
      - REDIS_URL=redis://redis:6379/0
      - LLM_PROVIDER=${LLM_PROVIDER:-mock}
      - LLM_API_KEY=${LLM_API_KEY:-}
      - LLM_BASE_URL=${LLM_BASE_URL:-https://api.deepseek.com/v1}
      - LLM_MODEL=${LLM_MODEL:-deepseek-chat}
      - EVIDENCE_DIR=/app/assets/evidence
    ports:
      - "8000:8000"
    depends_on:
      - db
      - redis
    volumes:
      - ./assets:/app/assets

  frontend:
    build: ./frontend
    ports:
      - "5173:80"
    depends_on:
      - backend

volumes:
  pgdata:
```

---

## 3. 数据模型（Pydantic V2 + SQLAlchemy）

### 枚举（`models/enums.py`）

```python
from enum import Enum

class AdapterType(str, Enum):
    UI = "ui"
    API = "api"
    DATA = "data"
    RULE = "rule"

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"

class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"

class DiagnosisType(str, Enum):
    SCRIPT_ERROR = "script_error"    # 脚本/用例本身的问题
    ENV_ERROR = "env_error"          # 环境/配置/网络问题
    REAL_BUG = "real_bug"            # 被测系统的真实 Bug

class ToolCallStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    RETRY = "retry"
```

### TestCase / TestStep / TestPlan（`models/test_case.py`）

```python
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Any
from .enums import AdapterType

class TestStep(BaseModel):
    """执行单元：一个 Step = 一个工具调用"""
    step_id: str                           # 唯一 ID，如 "s1", "s2"
    adapter: AdapterType                   # ui / api / data / rule
    tool: str                              # 工具名，如 "goto", "http_post", "gen_boundary"
    target: str                            # 操作目标：URL / 元素语义描述 / 接口路径 / 规则名
    value: Optional[dict | str] = None     # 输入参数（可能含 {{变量}}）
    expect: Optional[dict] = None          # 断言期望值
    timeout_ms: int = 30000

class TestPlan(BaseModel):
    """一条可执行的测试计划"""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    name: str
    description: Optional[str] = None
    steps: list[TestStep]
    metadata: Optional[dict[str, Any]] = None

class TestCase(BaseModel):
    """测试用例：自然语言描述 + 生成的测试计划"""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: Optional[str] = None
    name: str
    scenario: str                           # 中文自然语言场景描述
    plan: Optional[TestPlan] = None         # AI 生成的可执行计划
    tags: list[str] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
```

### TestRun / ExecutionEvent（`models/test_run.py`）

```python
from pydantic import BaseModel, Field
from typing import Optional, Any
from .enums import StepStatus, RunStatus

class ToolCallRecord(BaseModel):
    """一次工具调用的完整记录"""
    turn: int
    tool_name: str
    adapter: str
    input_args: dict
    output: Optional[Any] = None
    status: str                             # success / error / retry
    error_message: Optional[str] = None
    duration_ms: int

class StepResult(BaseModel):
    """一个 Step 的执行结果"""
    step_id: str
    status: StepStatus
    tool_call: Optional[ToolCallRecord] = None
    screenshot_path: Optional[str] = None
    trace_path: Optional[str] = None
    error_message: Optional[str] = None
    started_at: str
    finished_at: str
    duration_ms: int

class TestRun(BaseModel):
    """一次测试执行"""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    run_id: str
    case_id: Optional[str] = None
    case_name: str
    status: RunStatus
    steps: list[StepResult] = []
    tool_calls: list[ToolCallRecord] = []
    variables: dict[str, Any] = {}
    total_duration_ms: int = 0
    started_at: str
    finished_at: Optional[str] = None
    diagnosis_ids: list[str] = []

class ExecutionEvent(BaseModel):
    """Event Bus 事件"""
    event_type: str                         # step_start / step_end / tool_call / screenshot / error / run_start / run_end / run_failed
    run_id: str
    step_id: Optional[str] = None
    timestamp: str
    payload: Optional[dict] = None
```

### FailureDiagnosis（`models/diagnosis.py`）

```python
from pydantic import BaseModel, ConfigDict
from typing import Optional
from .enums import DiagnosisType

class FailureDiagnosis(BaseModel):
    """AI 失败根因诊断结果"""
    model_config = ConfigDict(extra="forbid")
    diagnosis_id: Optional[str] = None
    run_id: str
    step_id: str
    root_cause: DiagnosisType               # SCRIPT_ERROR / ENV_ERROR / REAL_BUG
    confidence: float                       # 0.0 - 1.0
    evidence: list[str]                     # 支撑证据
    suggestion: str                         # 修复建议
    references: list[str] = []
    # 人机协同：默认草稿，必须人工确认
    needs_human_confirm: bool = True
    human_confirmed: bool = False
    human_note: Optional[str] = None
    created_at: Optional[str] = None
```

---

## 4. ⭐ 三内核核心实现规格

### 4.1 Tool Registry（`core/tool_registry.py`）

**设计目标**：`@register` 装饰器自动发现工具，按 adapter 分组，自动从函数签名提取参数类型生成 Pydantic input_schema。

**核心接口**：

| 函数 | 签名 | 说明 |
|---|---|---|
| `register(adapter)` | 装饰器工厂 | 给函数打上 adapter 标签，注册到 `_TOOLS` 字典 |
| `get_tool(adapter, tool_name)` | `-> Callable \| None` | 获取工具函数 |
| `get_tool_info(adapter, tool_name)` | `-> dict \| None` | 获取完整信息（含 input_schema / doc / signature）|
| `list_tools(adapter=None)` | `-> list[dict]` | 列出所有工具（返回给 LLM 做 tool_calls）|
| `list_adapters()` | `-> list[str]` | 列出已注册的适配器 |
| `execute_tool(adapter, tool_name, args)` | `-> Any` | 校验 args → 执行 → 返回结果 |

**存储结构**：`_TOOLS: dict[str, dict[str, dict]] = {adapter: {tool_name: {"func": callable, "input_schema": Pydantic model, "signature": str, "doc": str}}}`

**自定义异常**：`ToolNotFoundError`、`ToolValidationError`

### 4.2 Tool Loop（`core/tool_loop.py`）

**设计目标**：协议无关的 LLM 工具调用循环。UI/API/数据/规则四种适配器都通过它驱动。不绑定 Playwright，不绑定 LangChain。

**状态机**：

```
IDLE → RUNNING → (PAUSED) → SUCCESS / FAILED / ERROR
```

**核心接口**：

| 方法 | 签名 | 说明 |
|---|---|---|
| `__init__` | `(max_turns=50, auto_retry=True, max_retry_attempts=1)` | 初始化 |
| `execute_plan` | `(run_id, plan: TestPlan, variables=None) -> TestRun` | 入口：执行完整 TestPlan |
| `_execute_step` | `(run_id, step, test_run) -> StepResult` | 执行单个 Step（含变量注入 + 回灌变量池）|

**执行流程**：

```
for step in plan.steps:
    1. 变量注入：inject_variables(step, test_run.variables)
    2. publish("step_start")
    3. execute_tool(step.adapter, step.tool, args)
       - 捕获异常 → FAILED
    4. publish("tool_call")
    5. 回灌变量池：test_run.variables[step.step_id] = output
    6. 断言检查（如果有 step.expect）
    7. publish("step_end")
    
失败处理：
  - FAILED 且不重试 → 终止后续步骤
  - 全部跑完 → 统计 PASSED / FAILED
  - 异常 → ERROR
  
最后：
  publish("run_end")
  如果 FAILED/ERROR → publish("run_failed") 触发 RCA
```

**断言格式**：`{"status_code": 200, "jsonpath": "$.data.user_id", "equals": "U001"}`

### 4.3 Event Bus（`core/event_bus.py`）

**设计目标**：asyncio 原生事件总线。执行过程发事件，SSE/证据/RCA 都是订阅者。单例模式。

**核心接口**：

| 方法 | 签名 | 说明 |
|---|---|---|
| `instance()` | `-> EventBus` | 获取单例 |
| `subscribe(event_type, handler)` | `handler: Callable[[ExecutionEvent], Awaitable[None]]` | 订阅事件 |
| `publish(event: ExecutionEvent)` | `async` | 发布事件，所有订阅者并行处理（`asyncio.gather`），异常不阻塞 |
| `create_sse_queue(run_id)` | `-> asyncio.Queue` | 创建 SSE 队列，FastAPI StreamingResponse 消费 |
| `remove_sse_queue(run_id)` | | 执行结束清理 |

**事件类型清单**：

| event_type | 触发时机 | 典型 payload |
|---|---|---|
| `run_start` | 执行开始 | plan_name, total_steps |
| `step_start` | 每个 step 开始 | step_id, adapter, tool, target |
| `tool_call` | 工具执行完毕 | ToolCallRecord 完整 dump |
| `step_end` | 每个 step 结束 | step_id, status, error |
| `screenshot` | 截图产出 | step_id, path |
| `run_end` | 执行结束 | status, total_steps |
| `run_failed` | 执行失败（触发 RCA）| failed_steps 列表 |

---

## 5. 适配器工具清单

### UI 适配器（`adapters/ui_adapter.py`）—— 5 个工具

| 工具名 | 入参 | 出参 | 说明 |
|---|---|---|---|
| `goto` | `{target: "URL"}` | `{"status": "ok", "title": "..."}` | 打开页面 |
| `click` | `{target: "语义描述（如'登录按钮'）"}` | `{"status": "ok"}` | 语义定位点击 |
| `type` | `{target: "语义描述", value: "要输入的文本"}` | `{"status": "ok"}` | 语义定位输入 |
| `screenshot` | `{value: {"filename": "xxx.png"}}` | `{"path": "./assets/.../xxx.png"}` | 截图 |
| `assert_text` | `{target: "页面上应该出现的文本"}` | `{"status": "ok"/"failed"}` | 页面文本断言 |

> **语义定位流程**：Playwright `accessibility.snapshot()` → `accessibility_compressor.py` 压缩 → 喂 LLM → LLM 返回元素 role+name → Playwright `page.get_by_role(role, name).click()`。

### API 适配器（`adapters/api_adapter.py`）—— 5 个工具

| 工具名 | 入参 | 出参 | 说明 |
|---|---|---|---|
| `http_get` | `{target: "URL", value: {"headers": {...}}}` | `{"status_code": 200, "headers": {...}, "data": {...}}` | GET |
| `http_post` | `{target: "URL", value: {"json": {...}, "headers": {...}}}` | 同上 | POST |
| `http_put` | `{target: "URL", value: {"json": {...}}}` | 同上 | PUT |
| `http_delete` | `{target: "URL"}` | `{"status_code": 204}` | DELETE |
| `assert_response` | `{value: {"status_code": 200, "jsonpath": "...", "equals": "..."}}` | `{"status": "ok"/"failed"}` | 响应断言 |

### 数据适配器（`adapters/data_adapter.py`）—— 3 个工具

| 工具名 | 入参 | 出参 | 说明 |
|---|---|---|---|
| `gen_boundary` | `{target: "字段名", value: {"field_type": "string", "cases": [...]}}` | `{"generated": [...]}` | 生成边界值 |
| `gen_user` | `{value: {"count": 1, "with_address": true}}` | `{"users": [...]}` | Faker 造测试用户 |
| `gen_via_api` | `{target: "API 路径", value: {...}}` | `{"created_id": "..."}` | 通过 API 造数据 |

### 规则适配器（`adapters/rule_adapter.py`）—— 2 个工具

| 工具名 | 入参 | 出参 | 说明 |
|---|---|---|---|
| `assert_state` | `{target: "规则名", value: {...}}` | `{"status": "ok"/"failed"}` | 业务规则断言 |
| `assert_trade_rule` | `{target: "交易规则名", value: {...}}` | `{"status": "ok"/"failed"}` | 交易类规则断言 |

---

## 6. AI 模块规格

### 6.1 LLM Provider 抽象层（`ai/provider.py`）

统一接口：

```python
class LLMProvider(ABC):
    async def chat(self, messages: list[dict], response_format: str | None = None) -> str: ...
    async def chat_json(self, messages: list[dict], json_schema: dict | None = None) -> dict: ...
```

三个实现：
- `DeepSeekProvider`：调 `https://api.deepseek.com/v1/chat/completions`
- `OllamaProvider`：调本地 `http://localhost:11434/api/chat`
- `MockProvider`：返回固定响应，用于测试和开发

### 6.2 CaseGenerator（`ai/case_generator.py`）

**核心接口**：`async def generate(scenario: str, prefer_adapters: list[str] | None = None) -> TestPlan`

**Prompt 模板**（`ai/prompts/case_gen.txt`）：

```
你是一个专业的测试用例生成器。根据以下测试场景描述，生成严格符合 JSON Schema 的测试计划。

## 输入
{scenario}

## 可用工具清单
{tool_list_json}

## 输出格式（严格 JSON）
{
  "name": "测试计划名称",
  "steps": [
    {
      "step_id": "s1",
      "adapter": "ui|api|data|rule",
      "tool": "工具名（必须从上面的工具清单中选）",
      "target": "操作目标",
      "value": {"key": "value"},
      "expect": {"status_code": 200}
    }
  ]
}

## 要求
1. 必须覆盖：正常路径 + 关键异常/边界场景
2. 步骤之间要连贯，前一步的输出可以用 {{sX.field}} 在后续步骤中引用
3. 断言要具体：状态码、JSONPath 字段、业务状态都可以
4. 输出必须是严格有效的 JSON，不要加 markdown 代码块标记
```

### 6.3 RCA（`ai/rca.py`）

**触发方式**：Event Bus 订阅 `run_failed` 事件 → 自动触发。

**核心接口**：`async def diagnose(run_id: str, step_id: str) -> FailureDiagnosis`

**Prompt 模板**（`ai/prompts/rca.txt`）：

```
你是一个专业的失败根因诊断专家。根据以下失败上下文，判断失败原因。

## 失败步骤信息
{step_info_json}

## 执行错误
{error_message}

## 前 3 步执行上下文
{context_json}

## 输出格式（严格 JSON）
{
  "root_cause": "script_error|env_error|real_bug",
  "confidence": 0.85,
  "evidence": ["证据1", "证据2"],
  "suggestion": "修复建议",
  "references": ["相关文档或可能相关的配置"]
}

## 三类根因说明
- script_error: 用例本身的问题（selector 错、参数错、Schema 错）
- env_error: 环境问题（网络、服务未启动、浏览器配置、跨域）
- real_bug: 被测系统的真实 Bug（业务逻辑错、状态机非法流转）

## 要求
1. 必须基于给出的证据判断，不要脑补
2. confidence 低于 0.7 时，evidence 里必须说明不确定的地方
3. 输出必须是严格有效的 JSON
```

---

## 7. FastAPI 路由定义

| 路径 | 方法 | Request | Response | 说明 |
|---|---|---|---|---|
| `/api/v1/cases` | POST | `{name, scenario, tags}` | `TestCase` | 创建用例 |
| `/api/v1/cases` | GET | query: tag / search | `list[TestCase]` | 列出用例 |
| `/api/v1/cases/{case_id}` | GET | — | `TestCase` | 用例详情 |
| `/api/v1/cases/{case_id}` | PUT | `TestCase` | `TestCase` | 更新用例 |
| `/api/v1/generate` | POST | `{scenario: str, prefer_adapters: list[str]?}` | `TestPlan` | AI 生成测试计划 |
| `/api/v1/execute` | POST | `{case_id: str?}` 或 `{plan: TestPlan}` | `{"run_id": "..."}` | 触发执行 |
| `/api/v1/execute/{run_id}` | GET | — | `TestRun` | 查询执行状态 |
| `/api/v1/stream/{run_id}` | GET | — | **SSE 流** | 订阅执行事件 |
| `/api/v1/rca/{run_id}/{step_id}` | POST | — | `FailureDiagnosis` | 触发失败诊断 |
| `/api/v1/rca/{diagnosis_id}/confirm` | POST | `{human_confirmed: bool, human_note: str?}` | `FailureDiagnosis` | 人工确认诊断 |
| `/api/v1/reports` | GET | query: start_date / end_date | `list[RunSummary]` | 报告列表 |
| `/api/v1/reports/{run_id}` | GET | — | `ReportDetail` | 报告详情 |
| `/api/v1/artifacts/{run_id}` | GET | — | `list[Artifact]` | 证据清单 |
| `/api/v1/artifacts/{run_id}/files/{filename}` | GET | — | 文件流 | 下载证据 |
| `/docs` | GET | — | Swagger UI | OpenAPI 自动生成 |

**SSE 推送格式**：`Event Bus` 的 `ExecutionEvent` → JSON 序列化 → `data: {json}\n\n`

---

## 8. 适配器实现模板

每个 `@register(adapter="xxx")` 的工具函数签名统一：

```python
@register(adapter="api")
async def http_post(target: str, value: dict | None = None, expect: dict | None = None) -> dict:
    """工具说明文档字符串——会被 Tool Registry 提取给 LLM"""
    # 实现逻辑
    ...
```

**UI 适配器语义定位模板**：

```python
@register(adapter="ui")
async def click(target: str, value: dict | None = None, expect: dict | None = None) -> dict:
    """语义定位点击。target: 用户描述的语义（如'登录按钮'）"""
    from ..utils.accessibility_compressor import compress_snapshot
    # Step 1: 抓 accessibility snapshot
    snapshot = await page.accessibility.snapshot()
    # Step 2: 压缩成极简上下文
    compressed = compress_snapshot(snapshot)
    # Step 3: 喂 LLM 让它找到目标元素的 locator 策略
    element_ref = await _ask_llm_for_element(compressed, target)
    # Step 4: 用 Playwright locator 执行
    locator = page.get_by_role(element_ref["role"], name=element_ref["name"])
    await locator.click()
    return {"status": "ok"}
```

---

## 9. Utility 实现规格

### 变量注入（`utils/variable_injector.py`）

把 TestStep 里的 `{{step_id.field}}` 替换成 variables 里的实际值。支持嵌套：`{{s1.data.user_id}}` → 逐层取值。

### accessibility snapshot 压缩（`utils/accessibility_compressor.py`）

**目标**：把 Playwright `accessibility.snapshot()` 从 3000-5000 token 压到 500-1000 token。

**策略**：
- 只保留可交互元素（button / link / textbox / combobox / checkbox / radio 等）
- 保留 role + name + depth（层级）
- 过滤装饰性 div / span / p / img（除非有 alt）
- 截断过长文本到 80 字符
- 输出极简 Markdown 表格格式给 LLM

---

## 10. 测试验证站点

| 站点 | 用途 | URL |
|---|---|---|
| **JSONPlaceholder** | API 适配器验证（免费、无需注册） | `https://jsonplaceholder.typicode.com` |
| **SauceDemo** | UI 回归验证（电商演示站，固定账号） | `https://www.saucedemo.com`（user: standard_user / pass: secret_sauce）|
| **OWASP Juice Shop** | RCA 真 Bug 验证 | Docker 起本地版本 |
| **httpbin** | HTTP 各种状态码验证 | `https://httpbin.org` |

---

## 11. Demo 场景（必须跑通）

### Demo 1：纯 API 流程

```
输入: "测试用户注册接口：正常注册一个、空邮箱边界、SQL注入名字"
↓ AI 生成
s1: api → http_post /users {name: "测试用户", email: "test@example.com"} expect {status_code: 201}
s2: data → gen_boundary target=email expect {generated: [...]}
s3: api → http_post /users {email: "{{s2.case1}}"} expect {status_code: [400, 422]}
s4: api → http_post /users {name: "' OR 1=1 --"} expect {status_code: [400, 422]}
↓ 执行 → 报告
```

### Demo 2：混合编排（API 造数 + UI 验证）

```
输入: "API 创建一个边界值用户 → UI 登录 → 规则断言用户状态"
↓ AI 生成
s1: api → http_post /users {name: "a"*100, email: "long@test.com"} expect {status_code: 201}
s2: ui → goto https://saucedemo.com
s3: ui → type target="用户名输入框" value="{{s1.data.user_id}}"
s4: ui → type target="密码输入框" value="secret_sauce"
s5: ui → click target="登录按钮"
s6: rule → assert_state target="登录后用户可见" expect {...}
↓ 执行 → 故意失败触发 RCA → 诊断为 script_error → 人工确认 → 报告
```

---

## 12. pytest 覆盖率目标

| 模块 | 测试文件 | 覆盖目标 |
|---|---|---|
| `core/tool_registry.py` | `test_tool_registry.py` | ≥95% |
| `core/tool_loop.py` | `test_tool_loop.py` | ≥90% |
| `core/event_bus.py` | `test_event_bus.py` | ≥95% |
| `utils/variable_injector.py` | `test_variable_injector.py` | ≥95% |
| `utils/accessibility_compressor.py` | `test_accessibility_compressor.py` | ≥90% |
| `ai/case_generator.py` | `test_ai_case_gen.py` | ≥80% |
| **总计** | | **≥80%** |

---

## 13. 前端规格

### 技术栈
- Vue 3 + TypeScript + Vite
- TailwindCSS + Element Plus
- Pinia（状态管理）
- ECharts（图表）
- EventSource（SSE 实时订阅）

### 4 个页面

| 页面 | 路由 | 核心组件 | 说明 |
|---|---|---|---|
| 用例管理 | `/cases` | CaseEditor.vue | 列表 + 新建/编辑 + AI 生成入口 |
| 执行控制台 | `/execute` | ExecutionTimeline.vue, ScreenshotViewer.vue | SSE 实时时间线 + 截图回放 |
| 诊断视图 | `/diagnosis` | RCAPanel.vue | AI RCA 结果展示 + 人工确认 |
| 报告视图 | `/report` | ReportChart.vue | 通过率图表 + 失败明细 |

### 核心交互
- 执行控制台：点击执行 → SSE 连接 → 时间线实时渲染每个 step 的状态 + tool_call 详情
- 失败 step → 自动触发 RCA → 诊断结果默认折叠（草稿）→ 人工点确认后计入报告
- 报告页：双视图通过率（用例级 + 步骤级），失败明细可点击进入证据回放

---

## 14. 后端 Dockerfile 规格

```dockerfile
# backend/Dockerfile
FROM python:3.12-slim
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 安装 Playwright 浏览器
RUN uv pip install playwright && playwright install chromium

# 复制依赖文件
COPY pyproject.toml ./
RUN uv sync --frozen --no-dev

# 复制源码
COPY . .

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 15. 前端 Dockerfile 规格

```dockerfile
# frontend/Dockerfile (开发时用 vite dev，生产用 nginx)
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

nginx.conf 需要配置 `/api` 反向代理到 `backend:8000`。

---

## 16. alembic.ini（数据库迁移配置）

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
sqlalchemy.url = postgresql+asyncpg://postgres:postgres@localhost:5432/ai_test_workbench

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```
