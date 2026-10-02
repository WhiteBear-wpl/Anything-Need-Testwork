import importlib.util
import inspect
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml
from pydantic import BaseModel

from app.skills.base import (
    SkillDefinition,
    SkillMeta,
    SkillPolicyDefaults,
    SkillRunFn,
    SkillUIConfig,
)
from app.skills.errors import SkillDefinitionError

SKILLS_ROOT = Path(__file__).resolve().parent
LOCAL_REF = re.compile(r"^[a-z_][a-z0-9_]*:[A-Za-z_][A-Za-z0-9_]*$")
VALID_CATEGORIES = {"core", "specialist", "utility", "quality"}
VALID_STAGES = {"requirement", "generation", "quality", "review"}


def _parse_ui(raw: dict | None) -> SkillUIConfig:
    raw = raw or {}
    return SkillUIConfig(
        selectable=bool(raw.get("selectable", False)),
        group=raw.get("group"),
        icon=raw.get("icon"),
    )


def _require_local_ref(value: Any, field: str, manifest_path: Path) -> str:
    if not isinstance(value, str) or not LOCAL_REF.fullmatch(value):
        raise SkillDefinitionError(
            f"{manifest_path}: {field} must use a local relative module reference like handler:run"
        )
    return value


def _parse_specialist_policy(
    raw: Any,
    *,
    skill_dir: Path,
    manifest_path: Path,
    required: bool,
) -> SkillPolicyDefaults | None:
    if raw is None:
        if required:
            raise SkillDefinitionError(f"{manifest_path}: policy is required for a selectable Specialist")
        return None
    if not isinstance(raw, dict):
        raise SkillDefinitionError(f"{manifest_path}: policy must be an object")

    try:
        max_cases = int(raw["max_cases"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SkillDefinitionError(f"{manifest_path}: policy.max_cases must be a positive integer") from exc
    if max_cases < 1:
        raise SkillDefinitionError(f"{manifest_path}: policy.max_cases must be a positive integer")

    default_prompt_version = raw.get("default_prompt_version")
    prompt_versions = raw.get("prompt_versions")
    if not isinstance(default_prompt_version, str) or not default_prompt_version.strip():
        raise SkillDefinitionError(f"{manifest_path}: policy.default_prompt_version is required")
    if not isinstance(prompt_versions, dict) or not prompt_versions:
        raise SkillDefinitionError(f"{manifest_path}: policy.prompt_versions must be a non-empty mapping")
    if default_prompt_version not in prompt_versions:
        raise SkillDefinitionError(
            f"{manifest_path}: policy.default_prompt_version must be declared in policy.prompt_versions"
        )

    validated_versions: dict[str, str] = {}
    root = skill_dir.resolve()
    for version, relative_path in prompt_versions.items():
        if not isinstance(version, str) or not version.strip():
            raise SkillDefinitionError(f"{manifest_path}: policy.prompt_versions keys must be non-empty strings")
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise SkillDefinitionError(f"{manifest_path}: policy.prompt_versions values must be local prompt paths")
        prompt_path = (skill_dir / relative_path).resolve()
        if prompt_path.parent != root and root not in prompt_path.parents:
            raise SkillDefinitionError(f"{manifest_path}: policy prompt path must remain inside the Skill package")
        if not prompt_path.is_file():
            raise SkillDefinitionError(f"{manifest_path}: policy prompt file does not exist: {relative_path}")
        validated_versions[version] = relative_path

    return SkillPolicyDefaults(
        max_cases=max_cases,
        default_prompt_version=default_prompt_version,
        prompt_versions=validated_versions,
    )


def _load_manifest(skill_dir: Path) -> SkillMeta:
    manifest_path = skill_dir / "skill.yaml"
    if not manifest_path.exists():
        raise SkillDefinitionError(f"Missing skill.yaml: {skill_dir}")

    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SkillDefinitionError(f"Invalid skill.yaml: {manifest_path}") from exc
    if not isinstance(data, dict) or not data.get("name"):
        raise SkillDefinitionError(f"Invalid skill.yaml: {manifest_path}")
    if not data.get("version"):
        raise SkillDefinitionError(f"{manifest_path}: version is required")

    category = data.get("category", "utility")
    stage = data.get("stage", "generation")
    if category not in VALID_CATEGORIES:
        raise SkillDefinitionError(f"{manifest_path}: invalid category `{category}`")
    if stage not in VALID_STAGES:
        raise SkillDefinitionError(f"{manifest_path}: invalid stage `{stage}`")

    ui = _parse_ui(data.get("ui"))
    if category == "specialist" and ui.selectable and "execution_order" not in data:
        raise SkillDefinitionError(
            f"{manifest_path}: execution_order is required for a selectable Specialist"
        )

    entrypoint = _require_local_ref(data.get("entrypoint"), "entrypoint", manifest_path)
    input_model_ref = _require_local_ref(data.get("input_model"), "input_model", manifest_path)
    output_model_ref = _require_local_ref(data.get("output_model"), "output_model", manifest_path)
    try:
        execution_order = int(data.get("execution_order", 100))
        timeout_seconds = float(data.get("timeout_seconds", 420))
    except (TypeError, ValueError) as exc:
        raise SkillDefinitionError(
            f"{manifest_path}: execution_order and timeout_seconds must be numeric"
        ) from exc
    if not 30 <= timeout_seconds <= 600:
        raise SkillDefinitionError(f"{manifest_path}: timeout_seconds must be between 30 and 600")
    policy = _parse_specialist_policy(
        data.get("policy"),
        skill_dir=skill_dir,
        manifest_path=manifest_path,
        required=category == "specialist" and ui.selectable,
    )

    return SkillMeta(
        name=str(data["name"]),
        version=str(data["version"]),
        title=data.get("title", data["name"]),
        description=data.get("description", ""),
        category=category,
        stage=stage,
        tags=list(data.get("tags") or []),
        ui=ui,
        inputs=dict(data.get("inputs") or {}),
        outputs=dict(data.get("outputs") or {}),
        directory=skill_dir,
        strategies=dict(data.get("strategies") or {}),
        entrypoint=entrypoint,
        input_model_ref=input_model_ref,
        output_model_ref=output_model_ref,
        execution_order=execution_order,
        timeout_seconds=timeout_seconds,
        policy=policy,
    )


def _load_local_symbol(skill_dir: Path, reference: str, skill_name: str) -> Any:
    module_name, symbol_name = reference.split(":", 1)
    module_path = (skill_dir / f"{module_name}.py").resolve()
    if module_path.parent != skill_dir.resolve():
        raise SkillDefinitionError(f"Skill `{skill_name}` reference must remain inside its package")
    if not module_path.is_file():
        raise SkillDefinitionError(f"Skill `{skill_name}` missing local module: {module_name}.py")

    unique_module_name = f"aitc_skill_{skill_name}_{module_name}_{abs(hash(module_path))}"
    spec = importlib.util.spec_from_file_location(unique_module_name, module_path)
    if spec is None or spec.loader is None:
        raise SkillDefinitionError(f"Unable to load Skill `{skill_name}` module: {module_name}.py")
    module: ModuleType = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise SkillDefinitionError(f"Unable to import Skill `{skill_name}` module: {module_name}.py") from exc
    if not hasattr(module, symbol_name):
        raise SkillDefinitionError(f"Skill `{skill_name}` module `{module_name}` has no `{symbol_name}`")
    return getattr(module, symbol_name)


def _load_definition(skill_dir: Path) -> SkillDefinition:
    meta = _load_manifest(skill_dir)
    handler = _load_local_symbol(skill_dir, meta.entrypoint, meta.name)
    if not callable(handler) or not inspect.iscoroutinefunction(handler):
        raise SkillDefinitionError(f"Skill `{meta.name}` entrypoint must be an async function")

    input_model = _load_local_symbol(skill_dir, meta.input_model_ref, meta.name)
    output_model = _load_local_symbol(skill_dir, meta.output_model_ref, meta.name)
    for field, model in (("input_model", input_model), ("output_model", output_model)):
        if not inspect.isclass(model) or not issubclass(model, BaseModel):
            raise SkillDefinitionError(f"Skill `{meta.name}` {field} must reference a Pydantic BaseModel")

    return SkillDefinition(
        meta=meta,
        handler=handler,
        input_model=input_model,
        output_model=output_model,
    )


def discover_skills(root: Path | None = None) -> dict[str, SkillDefinition]:
    root = (root or SKILLS_ROOT).resolve()
    definitions: dict[str, SkillDefinition] = {}

    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("_") or child.name == "shared":
            continue
        if not (child / "skill.yaml").exists():
            continue

        definition = _load_definition(child)
        if definition.meta.name in definitions:
            raise SkillDefinitionError(f"Duplicate Skill name: {definition.meta.name}")
        definitions[definition.meta.name] = definition

    if not definitions:
        raise SkillDefinitionError("No Skills discovered; check the skills directory")
    return definitions


def normalize_inputs(meta: SkillMeta, inputs: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(inputs)
    for key, spec in meta.inputs.items():
        if spec.get("required") and key not in normalized:
            raise ValueError(f"Skill `{meta.name}` missing required input: {key}")
        if key not in normalized and "default" in spec:
            normalized[key] = spec["default"]
    return normalized
