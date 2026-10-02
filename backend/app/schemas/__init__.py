from datetime import datetime
from typing import Literal

import json

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    slug: str = ""
    base_url: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    slug: str | None = None
    base_url: str | None = None
    agent_runtime_v2_enabled: bool | None = None
    agent_specialist_allowlist: list[str] | None = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    slug: str = ""
    base_url: str = ""
    agent_runtime_v2_enabled: bool = False
    agent_specialist_allowlist: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("agent_specialist_allowlist", mode="before")
    @classmethod
    def decode_specialist_allowlist(cls, value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = []
        return value if isinstance(value, list) else []


class ProjectStatsOut(BaseModel):
    id: int
    name: str
    description: str
    slug: str = ""
    base_url: str = ""
    created_at: datetime
    updated_at: datetime
    testcase_count: int = 0
    generation_count: int = 0
    wiki_count: int = 0
    has_skeleton: bool = False
    last_generation_at: datetime | None = None
    last_generation_status: str | None = None


class ProjectStageOut(BaseModel):
    """项目当前所处的真实工作阶段，用于工作台与「继续工作」入口。

    stage: import（导入需求）→ confirm（确认功能点）→ generate（AI 生成）
           → review（人工评审）→ done（用例入库）
    """

    stage: Literal["import", "confirm", "generate", "review", "done"]
    document_id: int | None = None
    document_title: str = ""
    task_id: int | None = None
    generating: bool = False
    failed: bool = False
    pending_drafts: int = 0
    item_count: int = 0
    testcase_count: int = 0


class ProjectSkillPolicyOverrideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_name: str = Field(min_length=1, max_length=100)
    enabled: bool
    timeout_seconds: float | None = Field(default=None, ge=30)
    max_cases: int | None = Field(default=None, ge=1)
    execution_order: int | None = Field(default=None, ge=0, le=10000)
    prompt_version: str | None = Field(default=None, min_length=1, max_length=100)


class ProjectSkillPolicyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: int = Field(ge=0)
    overrides: list[ProjectSkillPolicyOverrideIn] = Field(default_factory=list)


class ProjectSkillPolicyOverrideOut(ProjectSkillPolicyOverrideIn):
    pass


class ProjectSkillPolicyDefaultsOut(BaseModel):
    timeout_seconds: float
    max_cases: int
    execution_order: int
    prompt_version: str
    prompt_versions: list[str]


class ProjectSkillPolicyResolvedOut(BaseModel):
    enabled: bool
    timeout_seconds: float
    max_cases: int
    execution_order: int
    prompt_version: str


class ProjectSkillPolicySpecialistOut(BaseModel):
    skill_name: str
    overrides: ProjectSkillPolicyOverrideOut | None = None
    defaults: ProjectSkillPolicyDefaultsOut
    resolved: ProjectSkillPolicyResolvedOut


class ProjectSkillPolicyStateOut(BaseModel):
    revision_no: int
    catalog_fingerprint: str
    specialists: list[ProjectSkillPolicySpecialistOut]


class HomeOverviewOut(BaseModel):
    total_projects: int
    total_testcases: int
    total_generations: int
    projects: list[ProjectStatsOut]
    latest_active_project_id: int | None = None
    latest_active_stage: ProjectStageOut | None = None


class StrategyOut(BaseModel):
    key: str
    title: str
    description: str = ""
    min_cases_per_feature: int = 2
    max_cases_per_feature: int = 4
    recommended: bool = False


class SkillOut(BaseModel):
    name: str
    version: str
    title: str
    description: str
    category: str
    stage: str
    tags: list[str] = []
    selectable: bool = False
    group: str | None = None
    icon: str | None = None
    execution_order: int = 100


class SkillCatalogOut(BaseModel):
    core: list[SkillOut] = []
    specialist: list[SkillOut] = []
    strategies: list[StrategyOut] = []


class RequirementDocumentCreate(BaseModel):
    title: str
    content: str


class RequirementItemOut(BaseModel):
    id: int
    module: str
    feature: str
    description: str
    acceptance_criteria: str
    constraints: str
    priority: str
    sort_order: int
    confirmed: bool

    model_config = {"from_attributes": True}


class RequirementItemUpdate(BaseModel):
    module: str | None = None
    feature: str | None = None
    description: str | None = None
    acceptance_criteria: str | None = None
    constraints: str | None = None
    priority: str | None = None
    confirmed: bool | None = None


class RequirementItemCreate(BaseModel):
    module: str = ""
    feature: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    acceptance_criteria: str = ""
    constraints: str = ""
    priority: str = "P1"


class RequirementDocumentOut(BaseModel):
    id: int
    project_id: int
    title: str
    source_type: str
    status: str
    test_scope: str = ""
    created_at: datetime
    items: list[RequirementItemOut] = []

    model_config = {"from_attributes": True}


class TestScopeUpdate(BaseModel):
    test_scope: str = ""


class GenerationTaskCreate(BaseModel):
    document_id: int
    strategy: str = "full"  # full | quick
    specialist_skills: list[str] = Field(
        default_factory=list,
        description="从 /skills Catalog 选择的专项 Skill",
    )
    use_knowledge: bool = False  # 生成前检索项目知识库并注入 prompt（RAG）


class AgentRunEventOut(BaseModel):
    id: int
    sequence: int
    stage: str = ""
    event_type: str
    payload_summary: str = "{}"
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentRunOut(BaseModel):
    id: int
    generation_task_id: int | None = None
    evaluation_run_id: int | None = None
    parent_run_id: int | None = None
    resume_from_run_id: int | None = None
    thread_id: int | None = None
    message_id: int | None = None
    run_kind: str = "generation"
    execution_mode: str = "worker"
    status: str
    cancel_requested: bool = False
    attempt_count: int = 0
    max_attempts: int = 1
    deadline_at: datetime | None = None
    waiting_since: datetime | None = None
    stop_reason: str = ""
    llm_calls_used: int = 0
    tool_calls_used: int = 0
    tokens_reserved: int = 0
    tokens_used: int = 0
    transport_retries_used: int = 0
    quality_repairs_used: int = 0
    budget_warning_emitted: bool = False
    usage_accounting_version: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeDocumentCreate(BaseModel):
    title: str
    content: str
    source_type: str = "doc"  # doc | case | defect


class KnowledgeDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    source_type: str
    status: str
    error_message: str = ""
    chunk_count: int = 0
    created_at: datetime


class KnowledgeChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: str
    heading: str = ""


class KnowledgeSearchRequest(BaseModel):
    query: str
    top_k: int = 5


class KnowledgeSearchHit(BaseModel):
    content: str
    title: str = ""
    heading: str = ""
    source_type: str = "doc"
    score: float = 0.0
    match: str = "vector"  # vector 语义 / keyword 关键词 / both 双路命中


class GeneratedCaseDraftOut(BaseModel):
    id: int
    requirement_item_id: int | None
    title: str
    priority: str
    case_type: str
    is_smoke: bool = False
    precondition: str
    steps: str
    expected_result: str
    quality_status: str
    quality_issues: str
    review_status: str
    reject_reason: str = ""
    was_edited: bool = False
    skill_name: str
    judge_score: float | None = None
    judge_issues: str = ""
    module: str = ""
    feature: str = ""

    model_config = {"from_attributes": True}


class QualityReportOut(BaseModel):
    id: int
    total_cases: int
    pass_count: int
    warning_count: int
    fail_count: int
    coverage_rate: float
    uncovered_features: str
    suggestions: str
    avg_judge_score: float | None = None
    hallucination_count: int = 0
    duplicate_count: int = 0

    model_config = {"from_attributes": True}


class AttemptSummaryOut(BaseModel):
    id: int
    requirement_item_id: int | None = None
    skill_name: str
    attempt_no: int
    status: str
    failure_code: str = ""
    failure_detail: str = "{}"
    retry_directive: str = "{}"
    latency_ms: int = 0
    tokens_used: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class FailureCandidateOut(BaseModel):
    id: int
    task_id: int
    requirement_item_id: int | None = None
    final_attempt_id: int | None = None
    title: str = ""
    input_snapshot: str = "{}"
    failure_code: str = ""
    status: str
    promoted_sample_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReviewStatsOut(BaseModel):
    total: int = 0
    adopted: int = 0
    rejected: int = 0
    edited_adopted: int = 0
    pending: int = 0
    reviewed: bool = False
    adoption_rate: float = 0.0
    edit_rate: float = 0.0
    rejection_rate: float = 0.0


class GenerationTaskOut(BaseModel):
    id: int
    project_id: int
    document_id: int
    strategy: str
    strategy_config: str = ""
    status: str
    progress: int
    stage: str = ""
    error_message: str
    tokens_used: int = 0
    knowledge_refs: str = ""  # JSON: {item_id: [{title, heading, score}]}，RAG 溯源
    created_at: datetime
    updated_at: datetime
    drafts: list[GeneratedCaseDraftOut] = []
    attempts: list[AttemptSummaryOut] = []
    failure_candidates: list[FailureCandidateOut] = []
    quality_report: QualityReportOut | None = None
    review_stats: ReviewStatsOut | None = None

    model_config = {"from_attributes": True}


class GenerationTaskSummaryOut(BaseModel):
    """生成记录列表项：不含草稿明细的轻量视图。"""

    id: int
    document_id: int
    document_title: str = ""
    strategy: str
    specialist_skills: list[str] = []
    status: str
    progress: int
    error_message: str = ""
    tokens_used: int = 0
    created_at: datetime
    draft_count: int = 0
    smoke_count: int = 0
    coverage_rate: float | None = None
    review_stats: ReviewStatsOut | None = None


class ConfirmRequest(BaseModel):
    item_ids: list[int] | None = None


class ReviewAction(BaseModel):
    draft_ids: list[int]
    action: Literal["adopt", "reject", "to_confirm"]
    reject_reason: str = ""  # 驳回原因（badcase 归因用）


class DraftEdit(BaseModel):
    title: str | None = None
    priority: str | None = None
    case_type: str | None = None
    precondition: str | None = None
    steps: str | None = None
    expected_result: str | None = None


class TestCaseUpdate(BaseModel):
    title: str | None = None
    priority: str | None = None
    case_type: str | None = None
    precondition: str | None = None
    steps: str | None = None
    expected_result: str | None = None
    module: str | None = None
    feature: str | None = None


class CatalogRename(BaseModel):
    type: Literal["module", "feature"]
    old_module: str = Field(..., min_length=1)
    old_feature: str | None = None
    new_name: str = Field(..., min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_feature_rename(self):
        if self.type == "feature" and not self.old_feature:
            raise ValueError("重命名功能点需提供 old_feature")
        return self


class CatalogRenameOut(BaseModel):
    updated_items: int


class TestCaseOut(BaseModel):
    id: int
    project_id: int
    requirement_item_id: int | None = None
    project_name: str = ""
    title: str
    priority: str
    case_type: str
    is_smoke: bool = False
    precondition: str
    steps: str
    expected_result: str
    status: str
    source: str
    created_at: datetime
    module: str = ""
    feature: str = ""

    model_config = {"from_attributes": True}


class ExecutionStats(BaseModel):
    total: int
    passed: int
    failed: int
    blocked: int
    pending: int
    executed: int
    pass_rate: float


class TestTaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    batch_name: str = Field("线下测试", min_length=1, max_length=100)  # 首个批次名称
    case_ids: list[int] = []
    source_task_id: int | None = None  # 传入生成任务 ID 时，自动导入该任务已采纳入库的用例

    @model_validator(mode="after")
    def validate_case_source(self):
        if not self.case_ids and self.source_task_id is None:
            raise ValueError("请选择用例或指定生成任务")
        return self


class TestTaskUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    status: Literal["in_progress", "completed"] | None = None


class TestBatchCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    case_ids: list[int] = []
    copy_from_batch_id: int | None = None  # 复用某个已有批次的用例集（结果重置）

    @model_validator(mode="after")
    def validate_case_source(self):
        if not self.case_ids and self.copy_from_batch_id is None:
            raise ValueError("请选择用例或指定要复用的批次")
        return self


class TestBatchUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    status: Literal["in_progress", "completed"] | None = None


class TestBatchOut(BaseModel):
    id: int
    task_id: int
    name: str
    status: str
    created_at: datetime
    updated_at: datetime
    stats: ExecutionStats

    model_config = {"from_attributes": True}


class TestTaskOut(BaseModel):
    id: int
    project_id: int
    name: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime
    stats: ExecutionStats
    batches: list[TestBatchOut] = []

    model_config = {"from_attributes": True}


class BatchCaseOut(BaseModel):
    id: int  # 执行记录 ID
    case_id: int
    title: str = ""
    priority: str = ""
    case_type: str = ""
    is_smoke: bool = False
    precondition: str = ""
    steps: str = ""
    expected_result: str = ""
    module: str = ""
    feature: str = ""
    result: str
    note: str
    defect_ref: str
    executed_at: datetime | None = None


class TestBatchDetailOut(TestBatchOut):
    cases: list[BatchCaseOut] = []


class BatchCaseMark(BaseModel):
    result: Literal["pending", "passed", "failed", "blocked"]
    note: str = ""
    defect_ref: str = ""


class BatchCaseBatchMark(BaseModel):
    batch_case_ids: list[int] = Field(..., min_length=1)
    result: Literal["pending", "passed", "failed", "blocked"]


class BatchCasesAdd(BaseModel):
    case_ids: list[int] = Field(..., min_length=1)


class DefectItemOut(BaseModel):
    batch_case_id: int
    batch_id: int
    batch_name: str
    case_id: int
    title: str = ""
    priority: str = ""
    module: str = ""
    feature: str = ""
    result: str
    note: str
    defect_ref: str
    executed_at: datetime | None = None


class SystemSettingsOut(BaseModel):
    llm_api_key_set: bool
    llm_api_key_masked: str
    llm_base_url: str
    llm_model: str
    llm_mock_mode: bool
    use_mock_llm: bool
    eval_llm_api_key_set: bool = False
    eval_llm_api_key_masked: str = ""
    eval_llm_base_url: str = ""
    eval_llm_model: str = ""
    embedding_api_key_set: bool = False
    embedding_api_key_masked: str = ""
    embedding_base_url: str = ""
    embedding_model: str = ""
    rerank_api_key_set: bool = False
    rerank_api_key_masked: str = ""
    rerank_base_url: str = ""
    rerank_model: str = ""


class SettingsTestRequest(BaseModel):
    target: Literal["generation", "eval", "embedding", "rerank"] = "generation"


class SettingsTestOut(BaseModel):
    ok: bool
    message: str = ""
    model: str = ""
    base_url: str = ""


class SystemSettingsUpdate(BaseModel):
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_mock_mode: bool | None = None
    eval_llm_api_key: str | None = None
    eval_llm_base_url: str | None = None
    eval_llm_model: str | None = None
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    rerank_api_key: str | None = None
    rerank_base_url: str | None = None
    rerank_model: str | None = None


# ---------- 测试助手 Agent ----------

class AgentChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    document_id: int | None = None  # 本轮上传的需求文档 ID，触发流水线上下文
    after_sequence: int = Field(0, ge=0)


class AgentResumeRequest(BaseModel):
    approved: bool
    checkpoint_thread_id: str = Field(..., min_length=1, max_length=200)
    after_sequence: int = Field(0, ge=0)


class AgentToolCallOut(BaseModel):
    name: str
    task_id: int | None = None  # start_generation 产生的生成任务 ID，前端渲染进度卡片


class AgentMessageOut(BaseModel):
    id: int
    role: str
    content: str
    tool_calls: list[AgentToolCallOut] = []
    attachment: dict | None = None  # {document_id, title, source_type}
    created_at: datetime


class AgentThreadStateOut(BaseModel):
    thread_id: int
    workflow_state: dict = {}
    pending_approval: dict | None = None


# ---------- 评测 ----------

class EvalCheckpoint(BaseModel):
    text: str
    keywords: list[str] = []


class PromoteFailureCandidateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    checkpoints: list[EvalCheckpoint] = Field(..., min_length=1)


class EvalSampleCreate(BaseModel):
    title: str
    content: str
    checkpoints: list[EvalCheckpoint] = []


class EvalSampleUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    checkpoints: list[EvalCheckpoint] | None = None


class EvalSampleOut(BaseModel):
    id: int
    project_id: int
    title: str
    content: str
    checkpoints: list[EvalCheckpoint] = []
    created_at: datetime


class EvalRunCreate(BaseModel):
    label: str
    sample_ids: list[int]
    strategy: str = "full"
    experiment: dict = {}


class EvaluationDimensionOut(BaseModel):
    score: int | None = None
    verdict: str = ""
    evidence: list[str] = Field(default_factory=list)


class EvaluationScorecardOut(BaseModel):
    ruleset_version: str = ""
    judge_prompt_version: str = ""
    input_fingerprint: str = ""
    rule_score: int | None = None
    rule_verdict: str = ""
    rule_dimensions: dict = Field(default_factory=dict)
    judge_status: str = "not_evaluated"
    judge_verdict: str = ""
    judge_dimensions: dict = Field(default_factory=dict)
    judge_reason: str = ""
    golden_alignment: dict = Field(default_factory=dict)
    assessment_status: str = "not_evaluated"


class EvaluationRunDualTrackSummaryOut(BaseModel):
    rule_pass_rate: float | None = None
    judge_pass_rate: float | None = None
    judge_unavailable_count: int = 0
    assessment_status_counts: dict[str, int] = Field(default_factory=dict)
    evaluated_case_count: int = 0


class EvalResultOut(BaseModel):
    id: int
    sample_id: int
    sample_title: str = ""
    task_id: int | None = None
    status: str
    metrics: dict = {}
    error_summary: str = ""
    scorecard: EvaluationScorecardOut | None = None


class EvalRunOut(BaseModel):
    id: int
    project_id: int
    label: str
    config: dict = {}
    config_snapshot: dict = {}
    sample_set_fingerprint: str = ""
    is_baseline: bool = False
    agent_run_id: int | None = None
    status: str
    progress: int
    stage: str = ""
    error_message: str = ""
    metrics: dict = {}
    dual_track_summary: EvaluationRunDualTrackSummaryOut | None = None
    created_at: datetime
    results: list[EvalResultOut] = []


# ---------- Wiki ----------

class WikiPageCreate(BaseModel):
    project_id: int | None = None  # None = 工作台总 Wiki
    parent_id: int | None = None
    title: str = Field(..., min_length=1, max_length=200)
    content: str = ""
    is_template: bool = False


class WikiPageUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    content: str | None = None
    parent_id: int | None = None
    order: int | None = None
    is_template: bool | None = None


class WikiPageOut(BaseModel):
    id: int
    project_id: int | None = None
    parent_id: int | None = None
    title: str
    content: str = ""
    is_template: bool = False
    order: int = 0
    updated_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class WikiCopyRequest(BaseModel):
    target_project_id: int


class WikiCopyResult(BaseModel):
    copied_pages: int


# ---------- 测试骨架 ----------

class SkeletonOptionOut(BaseModel):
    language: str
    framework: str
    blurb: str


class SkeletonGenerateRequest(BaseModel):
    language: str = Field(..., min_length=1)
    framework: str = ""
    mode: Literal["template", "ai"] = "template"
    base_url: str = ""  # 覆盖项目 base_url


class SkeletonFileOut(BaseModel):
    path: str
    content: str


class SkeletonOut(BaseModel):
    id: int
    project_id: int
    language: str
    framework: str
    mode: str = "template"
    files: list[SkeletonFileOut] = Field(default_factory=list)
    generated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("files", mode="before")
    @classmethod
    def decode_files(cls, value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = []
        return value if isinstance(value, list) else []


class SkeletonFilesUpdate(BaseModel):
    files: list[SkeletonFileOut] = Field(..., min_length=1)

