from typing import Any


class SkillError(Exception):
    """Base class for Skill definition and execution failures."""


class SkillDefinitionError(SkillError):
    """A deployed Skill package does not satisfy its manifest contract."""


class SkillContractError(SkillError):
    def __init__(self, skill_name: str, validation_errors: list[dict[str, Any]] | None = None):
        self.skill_name = skill_name
        self.validation_errors = validation_errors or []
        super().__init__(f"Skill `{skill_name}` contract validation failed")


class SkillInputError(SkillContractError):
    """The caller supplied inputs outside the declared Skill contract."""


class SkillOutputError(SkillContractError):
    """A Skill handler returned output outside its declared contract."""


class SkillTimeoutError(TimeoutError, SkillError):
    def __init__(self, skill_name: str):
        self.skill_name = skill_name
        super().__init__(f"Skill `{skill_name}` timed out")


class SkillSnapshotDependencyError(SkillError):
    """A frozen task depends on a Prompt version missing from this deployment."""

    def __init__(self, skill_name: str, prompt_version: str):
        self.skill_name = skill_name
        self.prompt_version = prompt_version
        super().__init__(
            f"Skill `{skill_name}` snapshot dependency is unavailable: prompt version `{prompt_version}`"
        )
