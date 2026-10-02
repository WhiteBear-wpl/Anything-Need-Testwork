from fastapi import APIRouter, Depends, HTTPException

from app.schemas import SkillCatalogOut, SkillOut, StrategyOut
from app.skills.registry import get_registry

router = APIRouter(prefix="/skills", tags=["skills"])


def _skill_to_out(meta) -> SkillOut:
    return SkillOut(
        name=meta.name,
        version=meta.version,
        title=meta.title,
        description=meta.description,
        category=meta.category,
        stage=meta.stage,
        tags=meta.tags,
        selectable=meta.ui.selectable,
        group=meta.ui.group,
        icon=meta.ui.icon,
        execution_order=meta.execution_order,
    )


@router.get("", response_model=SkillCatalogOut)
def list_skills():
    registry = get_registry()
    all_skills = registry.list_skills()
    core = [_skill_to_out(s) for s in all_skills if s.category == "core"]
    specialist = [_skill_to_out(s) for s in registry.list_selectable_specialists()]
    strategies = [
        StrategyOut(
            key=s["key"],
            title=s.get("title", s["key"]),
            description=s.get("description", ""),
            min_cases_per_feature=s.get("min_cases_per_feature", 2),
            max_cases_per_feature=s.get("max_cases_per_feature", 4),
            recommended=bool(s.get("recommended", False)),
        )
        for s in registry.list_strategies()
    ]
    return SkillCatalogOut(core=core, specialist=specialist, strategies=strategies)


@router.get("/{skill_name}", response_model=SkillOut)
def get_skill(skill_name: str):
    registry = get_registry()
    try:
        meta = registry.get_skill(skill_name)
    except KeyError as exc:
        raise HTTPException(404, "Skill 不存在") from exc
    return _skill_to_out(meta)
