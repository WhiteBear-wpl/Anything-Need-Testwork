"""Pure project-level Specialist Policy resolution.

This module deliberately has no SQLAlchemy dependency: Policy rows are converted to
`ProjectSkillOverride` by the persistence layer, while task creation and runtime share
the same deterministic Manifest merge rules.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProjectSkillOverride:
    skill_name: str
    enabled: bool
    timeout_seconds: float | None = None
    max_cases: int | None = None
    execution_order: int | None = None
    prompt_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "enabled": self.enabled,
            "timeout_seconds": self.timeout_seconds,
            "max_cases": self.max_cases,
            "execution_order": self.execution_order,
            "prompt_version": self.prompt_version,
        }


@dataclass(frozen=True)
class ResolvedSpecialistPolicy:
    skill_name: str
    enabled: bool
    timeout_seconds: float
    max_cases: int
    execution_order: int
    prompt_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "timeout_seconds": self.timeout_seconds,
            "max_cases": self.max_cases,
            "execution_order": self.execution_order,
            "prompt_version": self.prompt_version,
        }


@dataclass(frozen=True)
class ResolvedProjectSkillPolicy:
    revision_no: int
    catalog_fingerprint: str
    specialists: tuple[ResolvedSpecialistPolicy, ...]

    @property
    def by_name(self) -> dict[str, ResolvedSpecialistPolicy]:
        return {item.skill_name: item for item in self.specialists}

    @property
    def enabled_specialists(self) -> tuple[ResolvedSpecialistPolicy, ...]:
        return tuple(item for item in self.specialists if item.enabled)

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "policy_revision": self.revision_no,
            "catalog_fingerprint": self.catalog_fingerprint,
            "specialists": {
                item.skill_name: item.to_dict()
                for item in self.enabled_specialists
            },
        }


class PolicyResolver:
    def __init__(self, registry) -> None:
        self.registry = registry

    def _catalog(self) -> list[Any]:
        catalog = list(self.registry.list_selectable_specialists())
        for meta in catalog:
            if meta.policy is None:
                raise ValueError(f"policy is missing for selectable specialist: {meta.name}")
        return catalog

    @staticmethod
    def _catalog_fingerprint(catalog: list[Any]) -> str:
        payload = [
            {
                "name": meta.name,
                "version": meta.version,
                "execution_order": meta.execution_order,
                "timeout_seconds": meta.timeout_seconds,
                "policy": {
                    "max_cases": meta.policy.max_cases,
                    "default_prompt_version": meta.policy.default_prompt_version,
                    "prompt_versions": meta.policy.prompt_versions,
                },
            }
            for meta in sorted(catalog, key=lambda item: item.name)
        ]
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

    def _normalize_overrides(
        self,
        overrides: list[ProjectSkillOverride],
        catalog: list[Any],
    ) -> dict[str, ProjectSkillOverride]:
        catalog_by_name = {meta.name: meta for meta in catalog}
        normalized: dict[str, ProjectSkillOverride] = {}
        for override in overrides:
            if not isinstance(override, ProjectSkillOverride):
                raise ValueError("policy overrides must use ProjectSkillOverride")
            name = self.registry.resolve_skill_name(str(override.skill_name))
            if name not in catalog_by_name:
                raise ValueError(f"unknown specialist: {name}")
            if name in normalized:
                raise ValueError(f"duplicate specialist override: {name}")
            meta = catalog_by_name[name]
            policy = meta.policy
            if override.timeout_seconds is not None:
                if not 30 <= float(override.timeout_seconds) <= meta.timeout_seconds:
                    raise ValueError(f"timeout_seconds is outside manifest bounds for {name}")
            if override.max_cases is not None:
                if not 1 <= int(override.max_cases) <= policy.max_cases:
                    raise ValueError(f"max_cases is outside manifest bounds for {name}")
            if override.execution_order is not None:
                if not 0 <= int(override.execution_order) <= 10000:
                    raise ValueError(f"execution_order is outside project bounds for {name}")
            if override.prompt_version is not None and override.prompt_version not in policy.prompt_versions:
                raise ValueError(f"prompt_version is unavailable for {name}")
            normalized[name] = ProjectSkillOverride(
                skill_name=name,
                enabled=bool(override.enabled),
                timeout_seconds=float(override.timeout_seconds) if override.timeout_seconds is not None else None,
                max_cases=int(override.max_cases) if override.max_cases is not None else None,
                execution_order=int(override.execution_order) if override.execution_order is not None else None,
                prompt_version=override.prompt_version,
            )
        return normalized

    def resolve(
        self,
        overrides: list[ProjectSkillOverride],
        *,
        revision_no: int,
    ) -> ResolvedProjectSkillPolicy:
        if revision_no < 0:
            raise ValueError("revision_no must be non-negative")
        catalog = self._catalog()
        normalized = self._normalize_overrides(overrides, catalog)
        resolved: list[ResolvedSpecialistPolicy] = []
        for meta in catalog:
            override = normalized.get(meta.name)
            defaults = meta.policy
            resolved.append(
                ResolvedSpecialistPolicy(
                    skill_name=meta.name,
                    enabled=override.enabled if override is not None else False,
                    timeout_seconds=(
                        override.timeout_seconds
                        if override is not None and override.timeout_seconds is not None
                        else meta.timeout_seconds
                    ),
                    max_cases=(
                        override.max_cases
                        if override is not None and override.max_cases is not None
                        else defaults.max_cases
                    ),
                    execution_order=(
                        override.execution_order
                        if override is not None and override.execution_order is not None
                        else meta.execution_order
                    ),
                    prompt_version=(
                        override.prompt_version
                        if override is not None and override.prompt_version is not None
                        else defaults.default_prompt_version
                    ),
                )
            )
        resolved.sort(key=lambda item: (item.execution_order, item.skill_name))
        return ResolvedProjectSkillPolicy(
            revision_no=revision_no,
            catalog_fingerprint=self._catalog_fingerprint(catalog),
            specialists=tuple(resolved),
        )

    def resolve_requested(
        self,
        overrides: list[ProjectSkillOverride],
        requested: list[str],
        *,
        revision_no: int,
    ) -> ResolvedProjectSkillPolicy:
        resolved = self.resolve(overrides, revision_no=revision_no)
        by_name = resolved.by_name
        requested_names: set[str] = set()
        for raw_name in requested:
            name = self.registry.resolve_skill_name(str(raw_name))
            if name not in by_name:
                raise ValueError(f"unknown specialist: {name}")
            if not by_name[name].enabled:
                raise ValueError(f"disabled specialist: {name}")
            requested_names.add(name)
        selected = tuple(item for item in resolved.enabled_specialists if item.skill_name in requested_names)
        return ResolvedProjectSkillPolicy(
            revision_no=resolved.revision_no,
            catalog_fingerprint=resolved.catalog_fingerprint,
            specialists=selected,
        )
