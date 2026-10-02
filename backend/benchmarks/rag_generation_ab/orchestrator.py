"""Configuration contract and real paired execution for the generation experiment."""

import json

from app.models.evaluation import EvalResult, EvalRun, EvalSample
from app.models.knowledge import KnowledgeDocument
from app.models.project import Project
from app.models.system_config import SystemConfig
from app.services.evaluation_experiment_service import build_experiment_snapshot, freeze_run_samples
from app.services.evaluation_service import run_evaluation_workflow
from app.services.knowledge_service import ingest_document
from app.services.settings_service import get_project_runtime_config
from app.skills.registry import get_registry
from benchmarks.rag_generation_ab.dataset import load_samples


def build_experiments() -> tuple[dict, dict]:
    shared = {"strategy": "full", "specialists": [], "generation_model": None, "evaluation_model": None}
    return ({**shared, "use_knowledge": False}, {**shared, "use_knowledge": True})


def resolve_eval_project(db, *, user_id: int) -> Project:
    """Return the user's singleton hidden evaluation project."""
    project = (
        db.query(Project)
        .filter(Project.user_id == user_id, Project.is_eval.is_(True))
        .one_or_none()
    )
    if project is not None:
        return project
    project = Project(
        user_id=user_id,
        name="__evaluation__",
        description="评测专用隐藏项目",
        is_eval=True,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _create_run(db, project: Project, eval_samples: list[EvalSample], experiment: dict) -> EvalRun:
    model_config = get_project_runtime_config(db, project.id)
    snapshot = build_experiment_snapshot(get_registry(), model_config, experiment)
    run = EvalRun(
        project_id=project.id,
        label="treatment-rag" if experiment["use_knowledge"] else "baseline-no-rag",
        config=json.dumps(snapshot, ensure_ascii=False),
        config_snapshot=json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
        status="pending",
    )
    db.add(run)
    db.flush()
    frozen, fingerprint = freeze_run_samples(run, eval_samples)
    run.sample_set_fingerprint = fingerprint
    db.add_all(frozen)
    db.flush()
    frozen_by_source = {row.source_sample_id: row.id for row in frozen}
    for sample in eval_samples:
        db.add(
            EvalResult(
                run_id=run.id,
                sample_id=sample.id,
                run_sample_id=frozen_by_source[sample.id],
            )
        )
    db.commit()
    return run


async def _ingest_ab_knowledge(db, project: Project, samples) -> None:
    existing = db.query(KnowledgeDocument).filter(KnowledgeDocument.project_id == project.id).all()
    if existing:
        raise RuntimeError("隐藏评测项目已有知识文档，无法保证本次 A/B 的知识变量纯净")
    for item in samples:
        doc = KnowledgeDocument(
            project_id=project.id,
            title=f"A/B 补充知识：{item.title}",
            source_type="defect",
            raw_content=item.knowledge_path.read_text(encoding="utf-8"),
            status="processing",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        await ingest_document(db, doc)


async def execute_pair(db) -> tuple[EvalRun, EvalRun]:
    config_row = db.query(SystemConfig).first()
    if config_row is None:
        raise RuntimeError("没有可用的模型配置")
    if not (config_row.llm_api_key and config_row.embedding_api_key):
        raise RuntimeError("需要真实生成模型和 Embedding 模型配置")
    project = resolve_eval_project(db, user_id=config_row.user_id)
    samples = load_samples()
    eval_samples: list[EvalSample] = []
    for item in samples:
        sample = EvalSample(
            project_id=project.id,
            title=item.title,
            content=item.requirement,
            checkpoints=json.dumps(item.checkpoints, ensure_ascii=False),
        )
        db.add(sample)
        eval_samples.append(sample)
    db.commit()

    baseline_experiment, treatment_experiment = build_experiments()
    baseline = _create_run(db, project, eval_samples, baseline_experiment)
    await run_evaluation_workflow(baseline.id)

    await _ingest_ab_knowledge(db, project, samples)
    treatment = _create_run(db, project, eval_samples, treatment_experiment)
    await run_evaluation_workflow(treatment.id)
    return baseline, treatment
