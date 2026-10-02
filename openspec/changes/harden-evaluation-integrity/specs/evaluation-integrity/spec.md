## Purpose

确保 AITC 的双轨测试用例评测结果完整、可复现、可审计，使规则轨和 LLM Judge 轨能够作为可信的版本比较与发布门禁依据。

## ADDED Requirements

### Requirement: Judge 输出必须满足严格契约
系统 MUST 要求每条 Judge 结果包含固定的业务相关性、可执行性、可验证性、场景完整性、边界意识和覆盖合理性六个维度；每个维度 MUST 是 1 至 5 的整数，且 Judge 结果 MUST 拒绝未知字段、缺失字段和非法分值。

#### Scenario: 六维结果完整有效
- **WHEN** Judge 为每条候选用例返回全部六个合法整数维度且没有未知字段
- **THEN** 系统接受该批 Judge 输出并继续计算语义判定

#### Scenario: Judge 缺少评分维度
- **WHEN** Judge 返回的任意用例结果缺少一个或多个固定维度
- **THEN** 系统将该响应判定为契约失败，不得为缺失维度填充默认分数

#### Scenario: Judge 返回非法字段或分值
- **WHEN** Judge 返回未知字段、非整数分值或超出 1 至 5 范围的分值
- **THEN** 系统将该响应判定为契约失败

### Requirement: Judge 批次必须完整且索引一致
系统 MUST 将一次评测结果中的全部候选用例视为不可拆分的 Judge 批次。返回索引 MUST 与候选用例索引集合完全一致，并且每个索引只能出现一次。

#### Scenario: Judge 返回完整批次
- **WHEN** 候选用例索引为 0 至 N-1 且 Judge 恰好返回每个索引一次
- **THEN** 系统允许该批次进入 `completed` 状态

#### Scenario: Judge 漏评部分用例
- **WHEN** Judge 响应没有覆盖全部候选用例索引
- **THEN** 系统将整个批次判定为失败，不得把已返回的部分结果写成 `completed` 或 `pass`

#### Scenario: Judge 返回重复或越界索引
- **WHEN** Judge 响应包含重复索引、负数索引或超出候选数量的索引
- **THEN** 系统将整个批次判定为契约失败

### Requirement: Judge 失败必须定向重试并安全降级
系统 SHALL 只对可恢复的传输失败、解析失败和契约失败执行受限次数的定向重试。重试耗尽后，系统 MUST 将 Judge 轨标记为 `unavailable`，同时保留已经完成的规则轨结果。

#### Scenario: 首次响应为可恢复的契约失败
- **WHEN** Judge 首次返回缺失维度或不完整索引，并且重试预算尚未耗尽
- **THEN** 系统发起一次包含具体契约错误的定向重试

#### Scenario: 非可恢复错误
- **WHEN** Judge 调用因无效配置、认证失败或其他确定性错误失败
- **THEN** 系统不进行无意义重试，并将 Judge 轨标记为 `unavailable`

#### Scenario: 重试最终失败
- **WHEN** 所有允许的 Judge 尝试均未返回完整合法批次
- **THEN** 系统保留规则轨结果、记录受限且脱敏的错误摘要，并禁止产生 Judge 通过结论

### Requirement: 评测运行必须消费冻结配置
系统 MUST 在评测运行创建时冻结影响生成和评分结果的非敏感配置，并在整次运行中仅使用该快照决定模型、生成策略、RAG、Skill、Ruleset 和 Judge Prompt 版本。实时项目配置的后续变化不得改变已经创建的评测运行。

#### Scenario: 运行期间修改项目配置
- **WHEN** 评测运行创建后，用户修改项目的模型、RAG 或 Skill 配置
- **THEN** 已创建运行继续使用创建时冻结的配置，新配置只影响之后创建的运行

#### Scenario: 冻结配置缺少必需字段
- **WHEN** Worker 发现运行快照缺少完成评测所需的配置字段
- **THEN** 系统以可诊断错误停止该运行，不得静默回退到实时项目配置

#### Scenario: 获取运行所需密钥
- **WHEN** 冻结配置引用一个需要认证的模型供应商
- **THEN** 系统可以在执行时安全解析密钥，但模型、供应商和生成行为 MUST 继续受冻结快照约束，且密钥不得写入快照或审计输出

### Requirement: 规则评分必须区分单用例质量与套件质量
系统 SHALL 在单用例层评价字段完整性、步骤可执行性、预期可验证性和内部一致性，并在同一评测样本的候选套件层计算检查点联合覆盖和重复情况。

#### Scenario: 多条互补用例联合覆盖全部检查点
- **WHEN** 不同候选用例分别覆盖正常、异常和边界检查点，且套件联合覆盖全部检查点
- **THEN** 系统将套件检查点覆盖判定为完整，不要求每条用例单独覆盖全部检查点

#### Scenario: 套件存在重复用例
- **WHEN** 同一候选套件中存在语义上高度重复且没有新增覆盖价值的用例
- **THEN** 系统在套件层记录重复证据并产生相应规则告警或失败判定

#### Scenario: 字段齐全但内容互相矛盾
- **WHEN** 用例标题、前置条件、步骤或预期结果之间存在可确定的矛盾
- **THEN** 系统不得仅因为字段非空而给予内部一致性满分，并 MUST 输出矛盾证据

### Requirement: 双轨状态必须准确表达两条轨道
系统 MUST 仅在规则轨判定为 `pass` 且 Judge 轨判定为 `pass` 时输出 `dual_pass`。规则告警、规则失败、Judge concern 和 Judge unavailable MUST 保持可区分。

#### Scenario: 规则和 Judge 均通过
- **WHEN** 规则轨为 `pass` 且 Judge 轨完成并为 `pass`
- **THEN** 系统输出 `dual_pass`

#### Scenario: 规则告警但 Judge 通过
- **WHEN** 规则轨为 `warning` 且 Judge 轨为 `pass`
- **THEN** 系统输出非 `dual_pass` 的规则问题状态，并保留具体告警证据

#### Scenario: Judge 不可用
- **WHEN** 规则轨已完成但 Judge 轨最终不可用
- **THEN** 系统输出 `judge_unavailable`，且不得推导或伪造综合通过状态

### Requirement: 记分卡必须幂等且保留历史证据
系统 MUST 使用输入指纹和版本信息识别相同评测。相同输入的重复执行不得覆盖已完成记分卡；影响结果的输入或版本发生变化时，系统 MUST 创建新的可追溯评测结果。

#### Scenario: 重复处理已完成结果
- **WHEN** Worker 再次领取一个已经拥有相同输入指纹且状态为 `completed` 的评测结果
- **THEN** 系统返回既有结果，不重新评分、不覆盖证据

#### Scenario: 从规则完成状态恢复 Judge
- **WHEN** 记分卡已持久化规则轨但 Judge 轨尚未完成，并且输入指纹保持一致
- **THEN** 系统只继续未完成的 Judge 阶段，不清空或重写规则证据

#### Scenario: 影响评测的版本发生变化
- **WHEN** 输入内容、模型、Ruleset 或 Judge Prompt 版本发生变化
- **THEN** 系统不得覆盖原记分卡，而是通过新的评测结果保留前后版本证据

### Requirement: Runtime Harness 必须贯穿评测链路
系统 MUST 让取消、超时、错误脱敏和事件审计覆盖需求处理、生成、Skill、规则评分和 Judge 阶段。每个 Skill 尝试只能产生一组权威生命周期事件。

#### Scenario: 生成阶段收到取消请求
- **WHEN** 用户在 LangGraph 生成或 Specialist/RAG 执行期间取消评测
- **THEN** 系统停止后续工作，不再进入规则或 Judge 阶段，并保留取消前已经产生的审计事件

#### Scenario: 异常包含敏感信息
- **WHEN** Provider 或 Skill 异常正文包含认证头、密钥、令牌或其他敏感值
- **THEN** 数据库、API 和运行事件中只保存脱敏后的错误摘要

#### Scenario: Skill 正常完成
- **WHEN** 一个 Skill 尝试成功执行一次
- **THEN** 时间线中恰好存在一条开始事件和一条完成事件，不因 Service 与 Executor 同时记录而重复
