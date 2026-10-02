## 1. 测试基线与严格 Judge 契约

- [x] 1.1 补齐后端测试依赖，使 Python 3.12 环境能够运行现有 evaluation、case_judge 与 Runtime Harness 测试。
- [x] 1.2 先新增失败测试，覆盖 Judge 缺任一维度、未知字段、非整数分值、越界分值、空批次、漏索引、重复索引和越界索引。
- [x] 1.3 将 Evaluation Judge Schema 改为六维必填、整数 1–5、禁止额外字段，并移除归一化阶段的默认 3 分与截断行为。
- [x] 1.4 增加批次完整性验证器，保证返回索引集合与候选用例索引集合完全一致后才允许持久化。
- [x] 1.5 运行 case_judge 和 scorecard 定向测试，确认完整合法响应仍保持兼容。

## 2. 定向重试与双轨状态

- [x] 2.1 先新增失败测试，覆盖可恢复契约错误重试一次、认证/配置错误不重试、取消立即传播和重试耗尽降级。
- [x] 2.2 将 Judge 重试改为显式错误分类，并把结构化契约错误反馈给唯一一次定向重试。
- [x] 2.3 保证所有 Judge 失败路径保留规则轨，将 Judge 标记为 unavailable，且不生成 pass 或 completed。
- [x] 2.4 修正 assessment 状态映射，使 `dual_pass` 只接受规则 pass 与 Judge pass，规则 warning 映射为 `rule_issue` 并保留 `rule_verdict=warning`。
- [x] 2.5 增加状态矩阵测试，覆盖 rule pass/warning/fail 与 Judge pass/concern/fail/unavailable 的组合。

## 3. 冻结 Run Envelope

- [x] 3.1 先新增失败测试：运行创建后修改实时项目模型、RAG 和 Skill 配置，已创建运行的实际生成行为不得变化。
- [x] 3.2 扩展评测运行快照，冻结模型供应商与模型名、生成策略、RAG、Specialist Skill 及版本、Ruleset、Judge Prompt 和必要执行参数，且排除 API Key 等秘密值。
- [x] 3.3 实现从 config_snapshot 构造评测 Runtime 配置的单一适配入口，只允许按冻结供应商/凭据引用解析秘密值。
- [x] 3.4 修改 Evaluation Worker 和生成任务构造逻辑，删除影响实验行为的实时配置读取与固定关闭 RAG/Specialist 的覆盖。
- [x] 3.5 对缺少必需快照字段的历史 pending/running 运行返回可诊断失败，不得静默回退实时配置。

## 4. case/suite 两层规则评分

- [x] 4.1 先新增失败测试：三条互补用例联合覆盖三个检查点时，套件覆盖率应为 100%，不要求每条用例覆盖全部检查点。
- [x] 4.2 将完整性、步骤可执行性、预期可验证性和内部一致性保留在单用例层，将检查点覆盖和重复情况移动到套件层。
- [x] 4.3 输出带 `schema_version=2` 的 rule_dimensions，包含 cases 与 suite 两个部分、命中/未命中检查点及重复证据。
- [x] 4.4 增加有限且可解释的内部一致性冲突规则；只有输出明确冲突证据时才扣分，复杂语义保持由 Judge 判断。
- [x] 4.5 更新规则总判定与现有 API 序列化测试，保证旧记分卡 JSON 仍可读取。

## 5. 记分卡幂等与版本单一来源

- [x] 5.1 先新增失败测试，覆盖 completed 相同指纹直接返回、规则已完成仅续跑 Judge、不同指纹拒绝覆盖三条路径。
- [x] 5.2 在首次写入前计算包含 Run Envelope、Ruleset 和 Prompt 版本的完整输入指纹，并实现单向记分卡状态机。
- [x] 5.3 删除重试入口对既有规则字段和完成 Judge 字段的清空/覆盖，保证 completed 记分卡不可变。
- [x] 5.4 将 Judge Prompt 版本收敛为 case_judge Skill 的单一来源，并校验实际返回版本与冻结版本一致。
- [x] 5.5 增加重复领取 Worker 任务的幂等回归测试，验证不会再次调用 Judge 或改变历史时间戳/证据。

## 6. Runtime Harness、取消与安全审计

- [x] 6.1 先新增失败测试，覆盖生成中取消、Judge 中取消、敏感异常脱敏以及一次 Skill 尝试只产生一组生命周期事件。
- [x] 6.2 将同一个 run_context 从 Evaluation Worker 传递到生成工作流、LangGraph、Specialist/RAG 和 Judge，并在阶段边界检查取消。
- [x] 6.3 规定 Skill Executor 为 skill_started/completed/failed/cancelled 的唯一事件生产者，移除 Evaluation Service 中重复的 Skill 生命周期记录。
- [x] 6.4 为评测编排保留独立的 evaluation、rule 和 judge_retry 事件，并确保每个事件包含可追溯阶段、尝试次数和受限错误类型。
- [x] 6.5 对记分卡错误摘要、API 错误和运行事件统一应用脱敏及长度限制，增加 Basic/Bearer、API Key、URL 凭据和通用 token 测试。

## 7. API、前端与兼容性

- [x] 7.1 更新评测 API Schema 和前端 presentation 映射，正确展示 rule warning、Judge unavailable、套件级覆盖证据和 Judge 重试原因。
- [x] 7.2 保持双轨独立输出，不增加综合总分；新增前端测试确保 warning 不显示为“双轨通过”。
- [x] 7.3 优化评测运行详情查询，预加载结果记分卡，避免列表和详情序列化产生逐结果查询。
- [x] 7.4 使用旧格式与新格式记分卡夹具验证 API/UI 向后兼容。

## 8. 验证与交付

- [x] 8.1 运行全部后端测试以及 evaluation、case_judge、Runtime Harness 定向测试，记录通过数量和任何跳过项。
- [x] 8.2 运行前端测试与生产构建，验证评测列表、详情和双轨展示无回归。
- [x] 8.3 使用 Mock 模式完成一次端到端评测，验证配置冻结、完整 Judge 批次、套件覆盖、取消和时间线事件。
- [x] 8.4 在旧 pending/running 运行处理完毕后执行 Worker 灰度验证，并记录 Judge unavailable 率、重试率、取消延迟和重复事件数量。
- [x] 8.5 运行 `openspec validate harden-evaluation-integrity --strict`，修复所有规范错误后提交代码审核。
