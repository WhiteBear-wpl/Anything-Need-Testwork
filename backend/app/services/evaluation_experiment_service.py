"""Pure-ish persistence helpers for immutable evaluation experiments."""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit

from app.models.evaluation import EvalRun, EvalRunSample
from app.services.evaluation_scorecard_service import RULESET_VERSION
from app.services.generation_service import build_strategy_config
from app.services.settings_service import RuntimeModelConfig
from app.skills.case_judge.handler import EVALUATION_PROMPT_VERSION
from app.skills.policy import PolicyResolver, ProjectSkillOverride


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_checkpoints(raw: str) -> str:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        value = []
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _reject_url_credentials(url: object, *, model_role: str) -> None:
    value = str(url or "").strip()
    if not value:
        return
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ValueError(f"invalid {model_role} model base URL") from exc
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(
            f"URL credentials are not allowed in the {model_role} model base URL"
        )


def build_experiment_snapshot(registry, runtime_config, experiment: dict) -> dict:
    """Validate a request-time experiment configuration without persisting secrets."""
    raw_specialists = experiment.get("specialists") or []
    overrides = [
        ProjectSkillOverride(
            skill_name=str(item["skill_name"]),
            enabled=bool(item.get("enabled", False)),
            timeout_seconds=item.get("timeout_seconds"),
            max_cases=item.get("max_cases"),
            execution_order=item.get("execution_order"),
            prompt_version=item.get("prompt_version"),
        )
        for item in raw_specialists
    ]
    requested = [item.skill_name for item in overrides if item.enabled]
    resolved = PolicyResolver(registry).resolve_requested(overrides, requested, revision_no=0)
    snapshot = build_strategy_config(
        strategy=str(experiment.get("strategy") or "full"),
        specialist_skills=requested,
        use_knowledge=bool(experiment.get("use_knowledge", False)),
        model_config=runtime_config,
        strict_specialists=True,
        policy_state=resolved,
    )
    models = snapshot.get("models", {})
    for role in ("generation", "evaluation", "embedding", "rerank"):
        _reject_url_credentials(
            (models.get(role) or {}).get("base_url"),
            model_role=role,
        )
    generation_override = experiment.get("generation_model")
    evaluation_override = experiment.get("evaluation_model")
    if generation_override:
        models.setdefault("generation", {})["model"] = str(generation_override)
    if evaluation_override:
        models.setdefault("evaluation", {})["model"] = str(evaluation_override)
    models.setdefault("evaluation", {})["credential_source"] = (
        "evaluation"
        if runtime_config.eval_llm_base_url
        and runtime_config.eval_llm_api_key
        and runtime_config.eval_llm_model
        else "generation"
    )
    snapshot["evaluation_integrity_version"] = 1
    snapshot["ruleset_version"] = RULESET_VERSION
    snapshot["judge_prompt_version"] = EVALUATION_PROMPT_VERSION
    return snapshot


def runtime_config_from_snapshot(
    snapshot: dict,
    secret_config: RuntimeModelConfig,
) -> RuntimeModelConfig:
    """Resolve rotated secrets without allowing live settings to change experiment behavior."""
    if not isinstance(snapshot, dict) or snapshot.get("evaluation_integrity_version") != 1:
        raise ValueError("incomplete immutable config snapshot: missing integrity version")
    if not snapshot.get("ruleset_version"):
        raise ValueError("incomplete immutable config snapshot: missing Ruleset version")
    if not snapshot.get("judge_prompt_version"):
        raise ValueError("incomplete immutable config snapshot: missing Judge Prompt version")
    if snapshot["ruleset_version"] != RULESET_VERSION:
        raise ValueError(
            f"frozen Ruleset version is unavailable: {snapshot['ruleset_version']}"
        )
    if snapshot["judge_prompt_version"] != EVALUATION_PROMPT_VERSION:
        raise ValueError(
            "frozen Judge Prompt version is unavailable: "
            f"{snapshot['judge_prompt_version']}"
        )

    frozen_versions = snapshot.get("skill_versions")
    frozen_prompts = snapshot.get("prompt_fingerprints")
    if not isinstance(frozen_versions, dict) or not isinstance(frozen_prompts, dict):
        raise ValueError("incomplete immutable config snapshot: missing Skill contracts")
    current_contract = build_strategy_config(
        strategy=str(snapshot.get("strategy") or "full")
    )
    if snapshot.get("workflow_version") != current_contract.get("workflow_version"):
        raise ValueError(
            f"frozen evaluation workflow is unavailable: {snapshot.get('workflow_version')}"
        )
    if snapshot.get("generation_parameters") != current_contract.get("generation_parameters"):
        raise ValueError("frozen generation parameters are unavailable")
    current_versions = current_contract.get("skill_versions") or {}
    current_prompts = current_contract.get("prompt_fingerprints") or {}
    for skill_name, frozen_version in frozen_versions.items():
        if current_versions.get(skill_name) != frozen_version:
            raise ValueError(
                f"frozen Skill version is unavailable: {skill_name}@{frozen_version}"
            )
        if current_prompts.get(skill_name, "") != frozen_prompts.get(skill_name, ""):
            raise ValueError(
                f"frozen Skill prompt is unavailable: {skill_name}"
            )

    retrieval = snapshot.get("retrieval")
    required_retrieval = {
        "mode",
        "embedding_adapter",
        "vector_store",
        "collection_version",
        "top_k",
        "recall_top_k",
        "similarity_threshold",
        "rrf_k",
    }
    if not isinstance(retrieval, dict) or not required_retrieval.issubset(retrieval):
        raise ValueError("incomplete immutable config snapshot: missing retrieval parameters")
    current_retrieval = current_contract.get("retrieval") or {}
    for key in ("mode", "embedding_adapter", "vector_store", "collection_version"):
        if retrieval[key] != current_retrieval.get(key):
            raise ValueError(f"frozen retrieval adapter is unavailable: {key}")
    try:
        top_k = int(retrieval["top_k"])
        recall_top_k = int(retrieval["recall_top_k"])
        threshold = float(retrieval["similarity_threshold"])
        rrf_k = int(retrieval["rrf_k"])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid immutable retrieval parameters") from exc
    if not (1 <= top_k <= recall_top_k <= 200 and 0 <= threshold <= 1 and 1 <= rrf_k <= 1000):
        raise ValueError("invalid immutable retrieval parameters")

    models = snapshot.get("models")
    if not isinstance(models, dict):
        raise ValueError("incomplete immutable config snapshot: missing models")

    required_models = ("generation", "evaluation", "embedding", "rerank")
    if any(not isinstance(models.get(name), dict) for name in required_models):
        raise ValueError("incomplete immutable config snapshot: missing model sections")
    generation = models["generation"]
    evaluation = models["evaluation"]
    embedding = models["embedding"]
    rerank = models["rerank"]
    if any(key not in generation for key in ("base_url", "model", "mock_mode")):
        raise ValueError("incomplete immutable config snapshot: missing generation model fields")
    if any(key not in evaluation for key in ("base_url", "model", "credential_source")):
        raise ValueError("incomplete immutable config snapshot: missing evaluation model fields")
    if any(key not in section for section in (embedding, rerank) for key in ("base_url", "model")):
        raise ValueError("incomplete immutable config snapshot: missing retrieval model fields")

    credential_source = evaluation["credential_source"]
    if credential_source == "evaluation":
        evaluation_key = secret_config.eval_llm_api_key
    elif credential_source == "generation":
        evaluation_key = secret_config.llm_api_key
    else:
        raise ValueError("incomplete immutable config snapshot: invalid evaluation credential source")

    return RuntimeModelConfig(
        llm_api_key=secret_config.llm_api_key,
        llm_base_url=str(generation["base_url"] or ""),
        llm_model=str(generation["model"] or ""),
        llm_mock_mode=bool(generation["mock_mode"]),
        eval_llm_api_key=evaluation_key,
        eval_llm_base_url=str(evaluation["base_url"] or ""),
        eval_llm_model=str(evaluation["model"] or ""),
        embedding_api_key=secret_config.embedding_api_key,
        embedding_base_url=str(embedding["base_url"] or ""),
        embedding_model=str(embedding["model"] or ""),
        rerank_api_key=secret_config.rerank_api_key,
        rerank_base_url=str(rerank["base_url"] or ""),
        rerank_model=str(rerank["model"] or ""),
    )


def freeze_run_samples(run: EvalRun, samples) -> tuple[list[EvalRunSample], str]:
    """Build run-owned sample snapshots and their order-independent set fingerprint."""
    frozen: list[EvalRunSample] = []
    identity: list[dict] = []
    for sample in sorted(samples, key=lambda item: item.id):
        checkpoints = _canonical_checkpoints(sample.checkpoints)
        content_hash = _digest(sample.content or "")
        checkpoints_hash = _digest(checkpoints)
        frozen.append(EvalRunSample(
            run_id=run.id,
            source_sample_id=sample.id,
            sample_version=sample.version or 1,
            title_snapshot=sample.title,
            content_snapshot=sample.content or "",
            checkpoints_snapshot=checkpoints,
            content_sha256=content_hash,
            checkpoints_sha256=checkpoints_hash,
        ))
        identity.append({
            "id": sample.id,
            "version": sample.version or 1,
            "content_sha256": content_hash,
            "checkpoints_sha256": checkpoints_hash,
        })
    fingerprint = _digest(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return frozen, fingerprint


def compare_runs(runs: list[EvalRun]) -> dict:
    if len(runs) < 2:
        raise ValueError("at least two evaluation runs are required")
    fingerprints = {run.sample_set_fingerprint for run in runs}
    if "" in fingerprints or len(fingerprints) != 1:
        return {"comparable": False, "baseline_id": None, "metric_deltas": {}}
    baseline = next((run for run in runs if run.is_baseline), min(runs, key=lambda run: run.id))
    return {"comparable": True, "baseline_id": baseline.id, "metric_deltas": {}}


def set_run_baseline(db, run: EvalRun) -> EvalRun:
    if run.status != "completed":
        raise ValueError("only completed evaluation runs can become a baseline")
    if not run.sample_set_fingerprint:
        raise ValueError("evaluation run has no sample set fingerprint")
    db.query(EvalRun).filter(
        EvalRun.project_id == run.project_id,
        EvalRun.sample_set_fingerprint == run.sample_set_fingerprint,
        EvalRun.id != run.id,
    ).update({"is_baseline": False}, synchronize_session=False)
    run.is_baseline = True
    db.commit()
    db.refresh(run)
    return run
