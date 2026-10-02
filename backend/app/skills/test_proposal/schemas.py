from pydantic import BaseModel, ConfigDict

from app.ai.schemas import TestProposal


class TestProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_content: str


class TestProposalOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: TestProposal
