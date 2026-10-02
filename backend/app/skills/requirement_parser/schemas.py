from pydantic import BaseModel, ConfigDict

from app.ai.schemas import RequirementFeature


class RequirementParserInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_content: str


class RequirementParserOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RequirementFeature]
