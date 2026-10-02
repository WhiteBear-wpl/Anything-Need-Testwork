from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.skills.shared.contracts import CaseSkillOutput


class CaseWriterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_item: dict[str, Any]
    strategy: Literal["full", "quick"] = "full"
    scope: dict[str, Any] | None = None
    knowledge: list[dict[str, Any]] = Field(default_factory=list)
    repair_instruction: str = ""


class CaseWriterOutput(CaseSkillOutput):
    pass
