# AGENTS.md · AI Agent 开发指令

> **优先级最高**：照着这个来开发，不许跳 Phase，不许踩红线。
>
> 完整技术规格见仓库根目录 `SPEC.md`。

## 一、项目一句话定位

面向单个测试工程师的 AI 驱动一体化测试平台——从自然语言生成结构化用例，到三内核执行框架驱动 UI/API/数据/规则混合编排，失败自动 AI 根因诊断，覆盖「用例生成 → 执行 → 证据留痕 → 失败归因 → 报告回放」完整闭环。

## 二、开发顺序铁律（严格按这个来，不许跳）

```
Phase 0 环境骨架
  → Phase 1 三内核最小实现
    → Phase 2 适配器层
      → Phase 3 CLI 端到端跑通
        → Phase 4 AI 用例生成
          → Phase 5 证据链 + RCA 诊断
            → Phase 6 FastAPI 路由 + SSE + 前端页面
              → Phase 7 pytest 覆盖率 + CI + README + Demo
```

**不许跳 Phase。不许先写前端再接后端。不许先写 AI 生成器再接执行器。**

## 三、自研 vs 复用分界

| 必须自研（项目核心亮点） | 直接复用 pip / npm |
|---|---|
| Tool Registry（@register 装饰器） | Playwright |
| Tool Loop 状态机 | httpx |
| Event Bus（asyncio 原生） | SQLAlchemy 2.0 async |
| 语义定位压缩策略 | Pydantic V2 |
| 混合编排变量注入 | Faker |
| RCA 人机协同流程 | Element Plus + ECharts |
| Schema 约束用例生成 | Ruff |
| SSE 执行事件推送 | Docker Compose |

## 四、红线（踩了必须回滚）

1. **不引入 LangChain / LlamaIndex / 任何 Agent 框架**——一个 while 循环能讲清的事，引框架只会让调试和面试讲解都变复杂。LLM Provider 只做 prompt + JSON 解析。
2. **不做压测 / 安全测试 / 移动端 / K8s / 多租户**——明确写在 README 的 Non-Goal 里。
3. **不 fork 任何开源项目改**——用 pip install + 自己搭骨架的方式。GPL 系项目（TestHub / MeterSphere）只读文档不读源码。
4. **不在代码里写死 LLM API Key**——走 `.env`，`.env` 不入库。
5. **AI 诊断默认草稿状态**——必须人工确认才计入报告。

## 五、提交前自检

每个 Phase 完成后，写 commit 之前检查：

- [ ] 新增代码有单测（或在 `backend/tests/` 里有集成测试）
- [ ] `ruff check .` 0 error
- [ ] `mypy backend/app/` 0 error（核心模块）
- [ ] pytest 跑绿，覆盖率不低于 Phase 目标
- [ ] `.env` 没被误提交
- [ ] 没有复制任何参考项目的代码

## 六、证据优先

每个 Phase 完成后，在 `assets/evidence/` 下留下可核证据：

| Phase | 证据 |
|---|---|
| Phase 1 三内核 | `phase1_tool_loop_demo.png` 或最小执行日志 |
| Phase 2 适配器 | `phase2_api_test.png`（JSONPlaceholder 响应）|
| Phase 3 CLI 闭环 | `phase3_mixed_execution.log` |
| Phase 4 AI 用例生成 | `phase4_case_gen.json`（输入→输出对照）|
| Phase 5 RCA | `phase5_rca_demo.json`（真实失败诊断）|
| Phase 6 前端 | `phase6_frontend_screenshot.png` |
| Phase 7 完整交付 | `phase7_coverage_report.png` + CI 徽章截图 |

**没有证据 = 没完成。**

## 七、快速启动命令

```bash
# 后端开发
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000

# 前端开发
cd frontend
npm install
npm run dev  # http://localhost:5173

# Docker（一键启动所有服务）
docker compose up --build

# 跑测试 + 覆盖率
uv run pytest tests/ -v --cov=app --cov-report=html
```

## 八、AI Agent 开发 Checklist（按顺序勾）

- [ ] Phase 0：`docker-compose.yml` + `.env.example` + FastAPI 空项目能 `uvicorn app.main:app` 启动
- [ ] Phase 1.1：`core/tool_registry.py` + 单测 + 注册一个 mock 工具能 `execute_tool()` 跑通
- [ ] Phase 1.2：`core/event_bus.py` + 单测 + 两个 subscriber 能收到事件
- [ ] Phase 1.3：`core/tool_loop.py` + 单测 + 用 3 个 mock 工具跑通一条 TestPlan
- [ ] Phase 2.1：`adapters/api_adapter.py` 写 3 个工具（http_get / post + assert_response）+ JSONPlaceholder 验证
- [ ] Phase 2.2：`adapters/ui_adapter.py` 写 3 个工具（goto + click + screenshot）+ SauceDemo 验证
- [ ] Phase 2.3：`adapters/data_adapter.py` + `rule_adapter.py` 各写 2 个工具
- [ ] Phase 3：CLI 入口（`python -m app.cli "API 创建用户 → UI 登录"`）跑通 Demo 混合编排
- [ ] Phase 4：`ai/provider.py` + `ai/case_generator.py` + Mock LLM 能输出合法 TestPlan
- [ ] Phase 5：`ai/rca.py` + Event Bus 订阅 run_failed 事件自动触发 RCA
- [ ] Phase 6.1：FastAPI 路由（cases / execute / stream）+ SSE 能推事件到浏览器
- [ ] Phase 6.2：前端 4 个页面（CaseManagement / ExecutionConsole / DiagnosisView / ReportView）+ SSE 时间线
- [ ] Phase 7.1：pytest 覆盖率 ≥80% + GitHub Actions CI 跑绿
- [ ] Phase 7.2：README + Demo GIF + 证据截图 + License
