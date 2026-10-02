from typing import Any

from pathlib import Path

from app.skills.base import SkillContext, SkillDefinition, SkillMeta
from app.skills.loader import discover_skills
from app.skills.executor import SkillExecutor
from app.skills.errors import SkillSnapshotDependencyError

STRATEGY_DEFAULTS = {
    "full": {
        "title": "完整用例",
        "description": "覆盖功能、边界与异常，并自动标记其中的冒烟用例",
        "min_cases_per_feature": 5,
        "max_cases_per_feature": 12,
        "recommended": True,
    },
    "quick": {
        "title": "快速冒烟",
        "description": "只生成核心主路径冒烟用例，每个功能点 2～4 条",
        "min_cases_per_feature": 2,
        "max_cases_per_feature": 4,
        "recommended": False,
    },
}

LEGACY_SKILL_ALIASES = {
    "api": "api_test",
}

LEGACY_STRATEGY_MAP = {
    "detailed": "full",
    "standard": "full",
    "smoke": "quick",
    "functional_only": "quick",
}


class SkillRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root
        self._definitions = discover_skills(root)
        self._executor = SkillExecutor()

    def reload(self) -> None:
        self._definitions = discover_skills(self._root)

    def list_skills(
        self,
        *,
        category: str | None = None,
        stage: str | None = None,
        selectable_only: bool = False,
    ) -> list[SkillMeta]:
        items = [definition.meta for definition in self._definitions.values()]
        if category:
            items = [s for s in items if s.category == category]
        if stage:
            items = [s for s in items if s.stage == stage]
        if selectable_only:
            items = [s for s in items if s.ui.selectable]
        return sorted(items, key=lambda s: (s.execution_order, s.name))

    def get_skill(self, name: str) -> SkillMeta:
        resolved = self.resolve_skill_name(name)
        if resolved not in self._definitions:
            raise KeyError(f"Skill 不存在: {name}")
        return self._definitions[resolved].meta

    def get_definition(self, name: str) -> SkillDefinition:
        resolved = self.resolve_skill_name(name)
        if resolved not in self._definitions:
            raise KeyError(f"Skill 不存在: {name}")
        return self._definitions[resolved]

    def resolve_skill_name(self, name: str) -> str:
        return LEGACY_SKILL_ALIASES.get(name, name)

    def prompt_path(self, skill_name: str, prompt_version: str) -> Path:
        meta = self.get_skill(skill_name)
        if meta.policy is None or prompt_version not in meta.policy.prompt_versions:
            raise SkillSnapshotDependencyError(meta.name, prompt_version)
        if meta.directory is None:
            raise SkillSnapshotDependencyError(meta.name, prompt_version)
        path = (meta.directory / meta.policy.prompt_versions[prompt_version]).resolve()
        root = meta.directory.resolve()
        if (path.parent != root and root not in path.parents) or not path.is_file():
            raise SkillSnapshotDependencyError(meta.name, prompt_version)
        return path

    def list_selectable_specialists(self) -> list[SkillMeta]:
        return self.list_skills(category="specialist", selectable_only=True)

    def validate_specialist_selection(
        self,
        names: list[str],
        *,
        strict: bool,
    ) -> list[str]:
        catalog = self.list_selectable_specialists()
        allowed = {skill.name for skill in catalog}
        selected: set[str] = set()
        invalid: list[str] = []
        for raw_name in names:
            name = self.resolve_skill_name(str(raw_name))
            if name in allowed:
                selected.add(name)
            elif name not in invalid:
                invalid.append(name)
        if strict and invalid:
            raise ValueError(f"不可用的 Specialist: {', '.join(invalid)}")
        return [skill.name for skill in catalog if skill.name in selected]

    def resolve_specialists(
        self,
        allowlist: list[str],
        requested: list[str],
    ) -> list[str]:
        allowed = set(self.validate_specialist_selection(allowlist, strict=False))
        wanted = set(self.validate_specialist_selection(requested, strict=False))
        return [
            skill.name
            for skill in self.list_selectable_specialists()
            if skill.name in allowed and skill.name in wanted
        ]

    def list_strategies(self) -> list[dict[str, Any]]:
        case_writer = self._definitions.get("case_writer")
        case_writer_meta = case_writer.meta if case_writer else None
        strategies = []
        source = case_writer_meta.strategies if case_writer_meta else STRATEGY_DEFAULTS
        for key, spec in source.items():
            defaults = STRATEGY_DEFAULTS.get(key, {})
            merged = {**defaults, **spec, "key": key}
            strategies.append(merged)
        if not strategies:
            for key, spec in STRATEGY_DEFAULTS.items():
                strategies.append({**spec, "key": key})
        return strategies

    def normalize_strategy(self, strategy: str) -> str:
        valid = set(STRATEGY_DEFAULTS)
        case_writer = self._definitions.get("case_writer")
        if case_writer:
            valid |= set(case_writer.meta.strategies)
        if strategy in valid:
            return strategy
        return LEGACY_STRATEGY_MAP.get(strategy, "full")

    def validate_specialist_skills(self, names: list[str]) -> list[str]:
        """Compatibility alias for historical, non-strict configuration reads."""
        return self.validate_specialist_selection(names, strict=False)

    async def run(self, name: str, inputs: dict[str, Any], context: SkillContext) -> dict[str, Any]:
        resolved = self.resolve_skill_name(name)
        if resolved not in self._definitions:
            raise KeyError(f"Skill 不存在: {name}")
        definition = self._definitions[resolved]
        return await self._executor.execute(definition, inputs, context)


_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry
