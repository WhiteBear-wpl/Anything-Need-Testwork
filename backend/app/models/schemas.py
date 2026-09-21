from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StepType(str, Enum):
    UI = 'UI'
    API = 'API'
    DATA = 'DATA'
    RULE = 'RULE'


class CaseStatus(str, Enum):
    PENDING = '待执行'
    RUNNING = '执行中'
    PASSED = '已通过'
    FAILED = '已失败'


class Priority(str, Enum):
    P0 = 'P0'
    P1 = 'P1'
    P2 = 'P2'


class TestCase(BaseModel):
    id: int | None = None
    title: str
    type: StepType = StepType.UI
    owner: str = 'system'
    status: CaseStatus = CaseStatus.PENDING
    priority: Priority = Priority.P1
    duration: str = '0.0 min'
    summary: str = ''
    pass_rate: int = 0


class ExecutionLog(BaseModel):
    id: int
    step: str
    status: str
    message: str
    timestamp: str


class DiagnosisItem(BaseModel):
    id: int
    title: str
    level: Priority = Priority.P1
    evidence: list[str] = Field(default_factory=list)
    reason: str = ''
    suggestion: str = ''
    confirmed: bool = False


class ExecutionRequest(BaseModel):
    case_ids: list[int] = Field(default_factory=list)
    environment: str = 'staging'
    browser: str = 'chromium'
    retry_count: int = 1
    description: str = ''


class ExecutionResponse(BaseModel):
    run_id: str
    status: str = 'queued'
    message: str = '已进入执行队列'


class CaseListResponse(BaseModel):
    items: list[TestCase]
    total: int


class HealthResponse(BaseModel):
    status: str
    version: str


class RunSummary(BaseModel):
    total_steps: int = 12
    completed_steps: int = 8
    failed_steps: int = 1
    status: str = 'running'
    current_task: str = 'API创建用户 → UI登录验证'
    logs: list[ExecutionLog] = Field(default_factory=list)


class ReportSummary(BaseModel):
    pass_rate: float = 96.8
    fail_rate: float = 3.2
    coverage: float = 87.0
    avg_time: str = '2.4 min'
    trend: list[int] = Field(default_factory=lambda: [58, 70, 66, 82, 88, 93, 96])
