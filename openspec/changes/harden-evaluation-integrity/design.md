## Context

AITC 当前由评测 Worker 创建生成任务，复用 LangGraph 生成链路，并在生成结束后写入规则轨和 `case_judge` 轨记分卡。`EvalRun.config_snapshot`、`EvaluationScorecard.input_fingerprint` 和 Runtime Harness 已存在，但执行路径仍会读取实时项目配置、覆盖既有记分卡，并由 Service 与 Skill Executor 重复记录 Skill 生命周期事件。参见 [proposal.md](./proposal.md) 与 [evaluation-integrity spec](./specs/evaluation-integrity/spec.md)。

现有 SQLite、Worker、Skill Registry 和前端双轨展示继续保留。本设计优先收紧行为边界，不引入外部队列、数据库或新的总分算法。

## Goals / Non-Goals

**Goals:**

- 让同一 EvalRun 在配置变化后仍可复现。
- 让 Judge 非法、缺项和部分响应无法进入完成或通过状态。
- 使规则轨按单用例与套件两个层级表达证据。
- 保证记分卡重试幂等，并让取消、脱敏和事件审计贯穿全链路。
- 尽量保持已有 API 结构和前端读取方式兼容。

**Non-Goals:**

- 不接入人工金标用例及其生命周期治理。
- 不把规则轨和 Judge 轨强制合成为一个总分。
- 不重写现有 LangGraph、多 Agent 或 Skill Registry。
- 不在本变更中实现 P1-2c 发布门禁或 P1-2d 人工反馈沉淀。

## Decisions

### 1. 使用完整的非敏感 Run Envelope 驱动执行

`EvalRun.config_snapshot` 作为运行信封的唯一事实来源，冻结模型供应商与模型名、生成策略、RAG 开关、Specialist Skill 列表及版本、Ruleset 版本、Judge Prompt 版本和必要的执行参数。Worker 不再用实时项目配置决定这些行为。

密钥不进入快照。执行时只根据快照中的供应商/凭据引用解析秘密值，并验证解析结果没有改变快照约束的模型与行为。旧的 pending/running 运行如果缺少必需字段，将明确失败为“不完整历史快照”，而不是读取实时配置补齐。

备选方案是继续读取实时配置并只冻结模型名；该方案无法保证 RAG、Skill 和策略实验可复现，因此拒绝。

### 2. Schema 校验与批次完整性校验分两层执行

Judge 的结构化响应模型采用必填字段、1–5 整数约束和 `extra=forbid`。结构校验通过后，再执行批次校验：返回数量等于候选数量，索引集合恰好为 `0..N-1`，并且索引唯一。

归一化逻辑只负责清理受限长度的文本字段，不再补默认分、截断非法分值或静默丢弃未知结果。只有两层校验都通过，才构造并持久化 `completed` Judge 轨。

备选方案是接受部分结果并对缺失用例标记 unavailable；这会让同一批次同时具备完成与未完成语义，增加门禁误判风险，因此采用整批全有或全无。

### 3. 重试由可恢复错误分类驱动

Judge 最多进行一次定向重试。可重试类型包括暂时性传输错误、JSON 解析失败和输出契约失败；认证、缺失配置、取消及其他确定性错误不重试。契约失败的重试提示只包含缺失维度、非法索引等结构化错误摘要，不回传敏感异常正文。

`RuntimeCancelled` 始终立即向上传播。所有尝试耗尽后，规则轨保持不变，Judge 轨写 `unavailable` 和脱敏摘要。

备选方案是对任意 Exception 统一重试；该方案会重复请求确定性错误并增加成本，因此拒绝。

### 4. 规则评分采用 case + suite 两层结果结构

单用例层保留完整性、步骤可执行性、预期可验证性和内部一致性。套件层计算检查点联合覆盖率和重复情况，并记录命中的检查点、未命中的检查点及重复用例对。

`rule_dimensions` 继续使用 JSON 字段，但升级为带 `schema_version` 的结构：

```json
{
  "schema_version": "2",
  "cases": {"<draft_id>": {"dimensions": {}}},
  "suite": {
    "checkpoint_coverage": {},
    "duplicate_rate": {}
  }
}
```

规则总判定由单用例和套件判定共同派生。内部一致性第一阶段使用确定性冲突规则并输出证据；无法可靠确定的语义冲突留给 Judge，不在规则轨伪造确定性结论。

### 5. 保持双轨输出，不新增综合总分

`dual_pass` 只对应 `rule_verdict=pass` 且已完成的 `judge_verdict=pass`。为降低 API 迁移成本，规则 warning 与规则 fail 均可映射到已有 `rule_issue`，但客户端必须结合 `rule_verdict` 区分告警和失败。Judge concern 继续映射 `judge_concern`，Judge unavailable 映射 `judge_unavailable`。

备选方案是新增大量组合状态；现阶段会放大 API/UI 迁移范围，而现有轨道字段已经能够表达详细原因，因此暂不采用。

### 6. 记分卡使用输入指纹实现幂等状态机

在任何写入前计算包含需求快照、检查点、候选用例、Run Envelope、Ruleset 和 Prompt 版本的输入指纹。

- 没有记分卡：写入规则轨，再尝试 Judge。
- 指纹相同且记分卡已经 completed：直接返回，不调用 Judge、不覆盖字段。
- 指纹相同且 Judge 未完成：保留规则轨，只继续 Judge。
- 指纹不同：拒绝修改当前 EvalResult，并要求通过新的 EvalRun/EvalResult 产生新历史记录。

该状态机在现有一对一 Scorecard 模型上实现，不立即新增 revision 表。每次 Judge 尝试的运行事件仍由 AgentRun/Event 保存；未来如果需要人工重跑历史 Judge，再独立引入 scorecard revision。

### 7. 统一 Runtime Harness 与事件所有权

评测入口把同一个 `run_context` 传入生成工作流和 Judge Skill。LangGraph、Specialist/RAG、规则阶段边界及 Judge 调用前均检查取消。

Skill Executor 是 `skill_started/completed/failed/cancelled` 的唯一生产者；评测 Service 只记录 `evaluation_*`、`rule_*`、`judge_retry` 等编排事件。所有落库错误先经过统一脱敏器，并限制长度与结构。

Prompt 版本从 `case_judge` 的单一常量/元数据来源获得，Judge 返回版本必须与冻结版本一致；Service 不再单独硬编码版本字符串。

## Risks / Trade-offs

- **[风险] 严格契约会提高早期 Judge unavailable 比例** → 在 UI 展示契约失败原因与重试次数，并用 Mock 和真实模型回归调优 Prompt，但不放宽完整性约束。
- **[风险] 旧 pending/running 运行缺少完整快照** → 部署前停止 Worker 并处理旧运行；部署后明确标记为不可复现失败，不静默回填。
- **[风险] 套件级规则结构变化影响前端展示** → 保留顶层现有字段，在 `rule_dimensions.schema_version` 下增量扩展，并让前端兼容旧结构。
- **[风险] 规则一致性检测可能产生误报** → 只实现可解释的确定性冲突规则，每条扣分必须包含证据；复杂语义判断交给 Judge。
- **[权衡] 不新增 scorecard revision 表限制了同一结果的多次 Judge 历史** → 本阶段优先保证完成结果不可覆盖；需要人工重评时创建新运行，后续再评估 revision 模型。

## Migration Plan

1. 部署前暂停 Evaluation Worker，等待或取消旧的 pending/running 评测运行。
2. 先上线严格 Schema、批次验证、状态机和回归测试，但保持前端兼容旧记分卡 JSON。
3. 扩展运行快照创建逻辑，并切换 Worker 为仅消费快照；使用 Mock 运行验证配置变更不影响运行中任务。
4. 切换套件级规则结构和状态映射，更新前端解释展示。
5. 贯通取消、统一事件所有权和脱敏后，恢复 Worker。
6. 观察 Judge unavailable、重试率、取消延迟和重复事件数量；确认稳定后移除旧的宽松兼容路径。

回滚时可恢复旧 Worker 代码和旧状态映射；本变更不依赖破坏性数据库迁移。新格式 `rule_dimensions` 保留于 JSON 字段，旧版本可忽略未知键。
