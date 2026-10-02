from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel

from app.services.settings_service import RuntimeModelConfig


SkillCategory = Literal["core", "specialist", "utility", "quality"]
SkillStage = Literal["requirement", "generation", "quality", "review"]


@dataclass
class SkillUIConfig:
    selectable: bool = False
    group: str | None = None
    icon: str | None = None


@dataclass(frozen=True)
class SkillPolicyDefaults:
    """Deployment-owned limits and published prompt versions for a Specialist."""

    max_cases: int
    default_prompt_version: str
    prompt_versions: dict[str, str]


@dataclass
class SkillMeta:
    name: str
    version: str
    title: str
    description: str
    category: SkillCategory
    stage: SkillStage
    tags: list[str] = field(default_factory=list)
    ui: SkillUIConfig = field(default_factory=SkillUIConfig)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    directory: Path | None = None
    strategies: dict[str, Any] = field(default_factory=dict)
    entrypoint: str = "handler:run"
    input_model_ref: str = ""
    output_model_ref: str = ""
    execution_order: int = 100
    timeout_seconds: float = 420
    policy: SkillPolicyDefaults | None = None


@dataclass
class SkillContext:
    model_config: RuntimeModelConfig
    project_id: int | None = None
    task_id: int | None = None
    strategy: str = "full"
    use_mock: bool = False
    runtime: Any | None = None
    timeout_seconds: float | None = None
    max_cases: int | None = None
    prompt_version: str | None = None


SkillRunFn = Callable[[dict[str, Any], SkillContext], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class SkillDefinition:
    meta: SkillMeta
    handler: SkillRunFn
    input_model: type[BaseModel]
    output_model: type[BaseModel]
