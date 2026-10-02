## Why

AITC 的双轨评测已经能够输出规则结果与 LLM Judge 结果，但当前仍可能接受缺维度、漏用例的 Judge 响应，并在运行中读取实时配置，导致“通过”结论和版本对比缺乏可信度。发布门禁、基线对比和后续金标治理都依赖稳定、可复现、可审计的评测底座，因此必须先收紧评测完整性。

## What Changes

- 将 Judge 输出改为严格契约：固定六个评分维度、整数范围 1–5、禁止未知字段，并要求候选用例索引完整、唯一且无越界。
- 将 Judge 批次处理改为全有或全无；不完整输出只允许定向重试，最终失败降级为 `judge_unavailable`，不得写成通过。
- 让评测 Worker 使用创建运行时冻结的模型、策略、RAG、Skill、Ruleset 与 Prompt 版本，而不是重新读取实时业务配置。
- 修正规则评分语义：单用例质量与套件级覆盖/重复分层计算，且只有规则通过和 Judge 通过同时满足时才标记 `dual_pass`。
- 建立记分卡幂等和不可变边界，防止重试覆盖已经完成的历史证据。
- 贯通 Runtime Harness 的取消、错误脱敏和事件职责，避免生命周期事件重复记录。
- 本变更不接入人工金标数据集；金标建模与治理保留为后续独立变更。

## Capabilities

### New Capabilities

- `evaluation-integrity`: 定义双轨评测的严格输入输出契约、冻结运行语义、规则/Judge 状态判定、幂等审计和 Runtime Harness 治理要求。

### Modified Capabilities

无。当前 `openspec/specs` 中尚无既有能力规范。

## Impact

- 后端评测模型、Schema、评测 Service、规则评分 Service、case_judge Skill、Runtime Harness 与 Worker 调用链。
- 评测状态和记分卡 API 输出；现有状态值尽量保持兼容，但 `warning + Judge pass` 将不再显示为 `dual_pass`。
- 前端评测详情中的状态展示和失败/不可用解释。
- 新增严格契约、冻结配置、取消、脱敏、幂等和套件级评分的回归测试。
- 不新增外部数据库或基础设施依赖，继续使用现有 SQLite 与 Worker 架构。
