"""Persistence boundary for project Specialist Policy and Revision audit."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.skill_policy import ProjectSkillPolicy, ProjectSkillPolicyRevision
from app.skills.policy import PolicyResolver, ProjectSkillOverride, ResolvedProjectSkillPolicy
from app.skills.registry import get_registry


class StaleSkillPolicyRevision(Exception):
    def __init__(self, expected: int, actual: int):
        self.expected = expected
        self.actual = actual
        super().__init__(f"Skill Policy revision is stale: expected {expected}, current {actual}")


@dataclass(frozen=True)
class ProjectSkillPolicyState:
    project_id: int
    revision_no: int
    overrides: tuple[ProjectSkillOverride, ...]
    resolved: ResolvedProjectSkillPolicy

    def to_api_out(self) -> dict[str, Any]:
        registry = get_registry()
        overrides_by_name = {item.skill_name: item for item in self.overrides}
        specialists = []
        for item in self.resolved.specialists:
            meta = registry.get_skill(item.skill_name)
            defaults = meta.policy
            specialists.append(
                {
                    "skill_name": item.skill_name,
                    "overrides": (
                        overrides_by_name[item.skill_name].to_dict()
                        if item.skill_name in overrides_by_name
                        else None
                    ),
                    "defaults": {
                        "timeout_seconds": meta.timeout_seconds,
                        "max_cases": defaults.max_cases,
                        "execution_order": meta.execution_order,
                        "prompt_version": defaults.default_prompt_version,
                        "prompt_versions": sorted(defaults.prompt_versions),
                    },
                    "resolved": item.to_dict(),
                }
            )
        return {
            "revision_no": self.revision_no,
            "catalog_fingerprint": self.resolved.catalog_fingerprint,
            "specialists": specialists,
        }


def _resolver() -> PolicyResolver:
    return PolicyResolver(get_registry())


def _row_to_override(row: ProjectSkillPolicy) -> ProjectSkillOverride:
    return ProjectSkillOverride(
        skill_name=row.skill_name,
        enabled=row.enabled,
        timeout_seconds=row.timeout_seconds,
        max_cases=row.max_cases,
        execution_order=row.execution_order,
        prompt_version=row.prompt_version,
    )


def _latest_revision_no(db: Session, project_id: int) -> int:
    return int(
        db.query(func.max(ProjectSkillPolicyRevision.revision_no))
        .filter(ProjectSkillPolicyRevision.project_id == project_id)
        .scalar()
        or 0
    )


def _resolved_revision_snapshot(resolved: ResolvedProjectSkillPolicy) -> dict[str, Any]:
    return {
        "policy_revision": resolved.revision_no,
        "catalog_fingerprint": resolved.catalog_fingerprint,
        "specialists": {
            item.skill_name: item.to_dict()
            for item in resolved.specialists
        },
    }


def get_project_policy_state(db: Session, project_id: int) -> ProjectSkillPolicyState:
    revision_no = _latest_revision_no(db, project_id)
    rows = (
        db.query(ProjectSkillPolicy)
        .filter(ProjectSkillPolicy.project_id == project_id)
        .order_by(ProjectSkillPolicy.skill_name)
        .all()
    )
    overrides = tuple(_row_to_override(row) for row in rows)
    resolved = _resolver().resolve(list(overrides), revision_no=revision_no)
    return ProjectSkillPolicyState(
        project_id=project_id,
        revision_no=revision_no,
        overrides=overrides,
        resolved=resolved,
    )


def initialize_project_skill_policies(
    db: Session,
    project_id: int,
    *,
    actor_id: int | None,
) -> ProjectSkillPolicyState:
    """Create the initial enabled policy revision for a newly created project."""
    if _latest_revision_no(db, project_id) > 0:
        return get_project_policy_state(db, project_id)

    overrides = [
        ProjectSkillOverride(skill_name=meta.name, enabled=True)
        for meta in get_registry().list_selectable_specialists()
    ]
    return replace_project_policy(
        db,
        project_id,
        overrides,
        base_revision=0,
        actor_id=actor_id,
    )


def replace_project_policy(
    db: Session,
    project_id: int,
    overrides: list[ProjectSkillOverride],
    *,
    base_revision: int,
    actor_id: int | None,
) -> ProjectSkillPolicyState:
    actual_revision = _latest_revision_no(db, project_id)
    if base_revision != actual_revision:
        raise StaleSkillPolicyRevision(base_revision, actual_revision)

    next_revision = actual_revision + 1
    ordered_overrides = sorted(overrides, key=lambda item: item.skill_name)
    resolved = _resolver().resolve(ordered_overrides, revision_no=next_revision)

    try:
        db.query(ProjectSkillPolicy).filter(
            ProjectSkillPolicy.project_id == project_id
        ).delete(synchronize_session=False)
        db.add_all(
            [
                ProjectSkillPolicy(
                    project_id=project_id,
                    skill_name=override.skill_name,
                    enabled=override.enabled,
                    timeout_seconds=override.timeout_seconds,
                    max_cases=override.max_cases,
                    execution_order=override.execution_order,
                    prompt_version=override.prompt_version,
                    updated_by=actor_id,
                )
                for override in ordered_overrides
            ]
        )
        db.add(
            ProjectSkillPolicyRevision(
                project_id=project_id,
                revision_no=next_revision,
                source="user_save",
                overrides_snapshot=json.dumps(
                    [item.to_dict() for item in ordered_overrides],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                resolved_snapshot=json.dumps(
                    _resolved_revision_snapshot(resolved),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                catalog_fingerprint=resolved.catalog_fingerprint,
                created_by=actor_id,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_project_policy_state(db, project_id)
