from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas import GeneratedTestCase


class SkillGeneratedTestCase(GeneratedTestCase):
    model_config = ConfigDict(extra="forbid")

    skill_name: str = ""


class CaseSkillOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[SkillGeneratedTestCase] = Field(default_factory=list)


class SpecialistInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_item: dict[str, Any]
    scope: dict[str, Any] | None = None
    knowledge: list[dict[str, Any]] = Field(default_factory=list)
    core_cases: list[dict[str, Any]] = Field(default_factory=list)
