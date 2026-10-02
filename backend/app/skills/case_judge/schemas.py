from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CaseJudgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_item: dict[str, Any] = Field(default_factory=dict)
    cases: list[dict[str, Any]] = Field(default_factory=list)
    evaluation_mode: bool = False
    requirement: str = ""
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)
    golden_case: dict[str, Any] | None = None
    contract_retry_feedback: str = ""


class CaseJudgement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    relevance: int = 3
    executability: int = 3
    verifiability: int = 3
    overall: float = 3.0
    hallucination: bool = False
    hallucination_reason: str = ""
    comment: str = ""
    dimensions: dict[str, int] = Field(default_factory=dict)
    reason: str = ""
    issue_tags: list[str] = Field(default_factory=list)
    golden_alignment: str = ""


class CaseJudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    judgements: list[CaseJudgement] = Field(default_factory=list)
    prompt_version: str = ""
