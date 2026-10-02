# 自动化测试工程

针对 AI 用例管理平台的接口自动化与 UI 自动化测试，基于 pytest 驱动。

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 接口自动化 | pytest + requests | 74 条用例，覆盖 6 大模块 |
| UI 自动化 | pytest + Playwright（POM 模式） | 20 条用例，覆盖核心用户旅程 |
| 报告 | pytest-html | 自包含 HTML 报告，失败自动截图 |

## 目录结构

```
autotest/
├── conftest.py          # 全局 fixture：拉起隔离后端（临时库 + mock 模式）
├── pytest.ini           # markers（smoke/regression）与默认参数
├── run_tests.sh         # 一键运行入口
├── api/                 # 接口自动化
│   ├── client.py        # ApiClient：HTTP 封装 + 业务流（导入→结构化→确认→生成轮询）
│   ├── conftest.py      # project / confirmed_doc / completed_task 等数据 fixture
│   └── test_*.py        # 健康检查、项目、需求、功能清单、生成、评审入库、知识库
└── ui/                  # UI 自动化
    ├── conftest.py      # 拉起 vite dev server（代理指向隔离后端）+ 接口造数 fixture
    ├── pages/           # Page Object：项目列表 / 生成流程 / 用例库 / 知识库 / 设置
    └── test_*.py        # 导航、项目 CRUD、生成五步流程 E2E、用例库、知识库、设置
```

## 运行方式

```bash
cd autotest
./run_tests.sh api     # 仅接口自动化（约 3s）
./run_tests.sh ui      # 仅 UI 自动化（约 30s）
./run_tests.sh smoke   # 仅冒烟用例
./run_tests.sh all     # 全量，报告在 reports/
```

Windows 使用 `run_tests.bat`，参数相同（api / ui / smoke / all）。

首次运行会自动创建虚拟环境、安装依赖和 Chromium。

## 设计要点

- **环境隔离**：session 级 fixture 用临时目录里的 SQLite 与 Chroma 启动独立后端（端口 8100），
  测试结束自动销毁，绝不污染开发数据；UI 测试另起 vite dev server（端口 5273）并将
  `/api` 代理指向该后端。
- **确定性**：强制 `LLM_MOCK_MODE=true` 且清空所有真实 API Key，生成/评分/向量化均走
  mock 路径，用例可离线秒级运行。
- **数据隔离**：每条用例使用函数级 `project` fixture（随机名项目），用后即删。
- **分层造数**：UI 用例只验证交互，前置数据（已确认文档、已完成任务、已入库用例）
  一律通过接口 fixture 准备，避免用例间的 UI 级联依赖。
- **用例设计方法**：等价类（文件类型、非法参数）、边界值（名称 200/201 字符、分块最小长度）、
  判定表（生成策略 × 专项 Skill 组合）、状态迁移（草稿 pending → adopted/rejected/edited）。
- **失败排障**：UI 用例失败自动截图到 `ui/artifacts/`，报告见 `reports/*.html`。

## 已知产物

这套用例在首跑时发现并推动修复了一个真实缺陷：删除项目时知识库文档与 Chroma 向量
不会级联清理，SQLite 复用项目 ID 后新项目会看到旧项目的知识文档、RAG 检索命中旧向量
（修复见 `backend/app/api/projects.py` 与 `Project` 模型的级联配置）。
