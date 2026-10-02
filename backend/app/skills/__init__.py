"""AI Skill 插件体系 — 通过 SkillRegistry 发现与调度。"""

from app.services.settings_service import RuntimeModelConfig
from app.skills.base import SkillContext
from app.skills.registry import get_registry

__all__ = [
    "SkillContext",
    "get_registry",
    "parse_requirements",
    "propose_test_scope",
    "generate_cases_for_feature",
    "generate_specialist_cases",
]


def _build_context(model_config: RuntimeModelConfig, **kwargs) -> SkillContext:
    from app.agent_runtime.harness import get_active_runtime_harness

    kwargs.setdefault("runtime", get_active_runtime_harness())
    return SkillContext(model_config=model_config, use_mock=model_config.use_mock_llm, **kwargs)


async def parse_requirements(raw_content: str, model_config: RuntimeModelConfig) -> list[dict]:
    registry = get_registry()
    result = await registry.run(
        "requirement_parser",
        {"raw_content": raw_content},
        _build_context(model_config),
    )
    return result.get("items", [])


async def propose_test_scope(raw_content: str, model_config: RuntimeModelConfig) -> dict:
    registry = get_registry()
    result = await registry.run(
        "test_proposal",
        {"raw_content": raw_content},
        _build_context(model_config),
    )
    return result.get("scope", {})


async def generate_cases_for_feature(
    feature_item: dict,
    model_config: RuntimeModelConfig,
    strategy: str = "detailed",
) -> list[dict]:
    registry = get_registry()
    strategy = registry.normalize_strategy(strategy)
    result = await registry.run(
        "case_writer",
        {"feature_item": feature_item, "strategy": strategy},
        _build_context(model_config, strategy=strategy),
    )
    return result.get("cases", [])


async def generate_specialist_cases(
    feature_item: dict,
    skill_name: str,
    model_config: RuntimeModelConfig,
) -> list[dict]:
    registry = get_registry()
    resolved = registry.resolve_skill_name(skill_name)
    result = await registry.run(
        resolved,
        {"feature_item": feature_item},
        _build_context(model_config),
    )
    return result.get("cases", [])


def list_selectable_specialist_names() -> list[str]:
    return [s.name for s in get_registry().list_selectable_specialists()]
