"""全局评测 API：评测衡量的是生成能力（Prompt / 模型 / RAG 策略），与具体业务项目无关。

所有样本与运行挂在一个自动创建的隐藏评测项目下（Project.is_eval=True），
生成链路无需改动，业务列表通过 is_eval 过滤不受影响。
"""

import json
from datetime import datetime

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database import SessionLocal, get_db
from app.api.deps import current_user_id
from app.models.evaluation import EvalResult, EvalRun, EvalRunSample, EvalSample
from app.models.agent_run import AgentRun, AgentRunEvent
from app.agent_runtime.repository import AgentRunRepository
from app.agent_runtime.service import create_evaluation_runner_run
from app.models.generation import GenerationFailureCandidate, GenerationTask
from app.models.project import Project
from app.schemas import (
    EvalRunCreate,
    EvalRunOut,
    EvalResultOut,
    EvalSampleCreate,
    EvalSampleOut,
    EvalSampleUpdate,
    FailureCandidateOut,
    GenerationTaskOut,
    PromoteFailureCandidateRequest,
)
from app.services.evaluation_experiment_service import (
    build_experiment_snapshot, compare_runs, freeze_run_samples, set_run_baseline,
)
from app.services.generation_service import build_strategy_config
from app.services.settings_service import get_project_runtime_config
from app.skills.registry import get_registry

router = APIRouter(prefix="/evaluations", tags=["evaluations"])

EVAL_PROJECT_NAME = "__evaluation__"


def _eval_project(db: Session) -> Project:
    user_id = current_user_id(db)
    project = db.query(Project).filter(Project.user_id == user_id, Project.is_eval == True).first()
    if not project:
        project = Project(
            user_id=user_id,
            name=EVAL_PROJECT_NAME,
            description="评测专用隐藏项目",
            is_eval=True,
        )
        db.add(project)
        try:
            db.commit()
        except IntegrityError:
            # 同一用户首次并发进入评测页时，由唯一索引保证只保留一个隐藏项目。
            db.rollback()
            project = db.query(Project).filter(
                Project.user_id == user_id,
                Project.is_eval == True,
            ).first()
            if not project:
                raise
        db.refresh(project)
    return project


def _sample_to_out(sample: EvalSample) -> EvalSampleOut:
    try:
        checkpoints = json.loads(sample.checkpoints or "[]")
    except json.JSONDecodeError:
        checkpoints = []
    return EvalSampleOut(
        id=sample.id,
        project_id=sample.project_id,
        title=sample.title,
        content=sample.content,
        checkpoints=checkpoints,
        created_at=sample.created_at,
    )


def _parse_json(raw: str, fallback):
    try:
        data = json.loads(raw or "")
        return data if isinstance(data, type(fallback)) else fallback
    except json.JSONDecodeError:
        return fallback


def _scorecard_to_out(scorecard):
    if scorecard is None:
        return None
    return {
        "ruleset_version": scorecard.ruleset_version or "",
        "judge_prompt_version": scorecard.judge_prompt_version or "",
        "input_fingerprint": scorecard.input_fingerprint or "",
        "rule_score": scorecard.rule_score,
        "rule_verdict": scorecard.rule_verdict or "",
        "rule_dimensions": _parse_json(scorecard.rule_dimensions, {}),
        "judge_status": scorecard.judge_status or "not_evaluated",
        "judge_verdict": scorecard.judge_verdict or "",
        "judge_dimensions": _parse_json(scorecard.judge_dimensions, {}),
        "judge_reason": scorecard.judge_reason or "",
        "golden_alignment": _parse_json(scorecard.golden_alignment, {}),
        "assessment_status": scorecard.assessment_status or "not_evaluated",
    }


def _run_to_out(run: EvalRun, sample_titles: dict[int, str]) -> EvalRunOut:
    metrics = _parse_json(run.metrics, {})
    return EvalRunOut(
        id=run.id,
        project_id=run.project_id,
        label=run.label,
        config=_parse_json(run.config, {}),
        config_snapshot=_parse_json(run.config_snapshot, {}),
        sample_set_fingerprint=run.sample_set_fingerprint or "",
        is_baseline=bool(run.is_baseline),
        agent_run_id=run.agent_run_id,
        status=run.status,
        progress=run.progress,
        stage=run.stage or "",
        error_message=run.error_message,
        metrics=metrics,
        dual_track_summary=metrics.get("dual_track") or None,
        created_at=run.created_at,
        results=[
            EvalResultOut(
                id=r.id,
                sample_id=r.sample_id,
                sample_title=sample_titles.get(r.sample_id, ""),
                task_id=r.task_id,
                status=r.status,
                metrics=_parse_json(r.metrics, {}),
                error_summary=r.error_summary or "",
                scorecard=_scorecard_to_out(r.scorecard),
            )
            for r in run.results
        ],
    )


def _sample_titles(db: Session, project_id: int) -> dict[int, str]:
    return dict(
        db.query(EvalSample.id, EvalSample.title)
        .filter(EvalSample.project_id == project_id)
        .all()
    )


def _candidate_to_out(candidate: GenerationFailureCandidate) -> FailureCandidateOut:
    return FailureCandidateOut.model_validate(candidate)


def _owned_candidate(db: Session, candidate_id: int) -> GenerationFailureCandidate:
    candidate = (
        db.query(GenerationFailureCandidate)
        .join(GenerationTask, GenerationFailureCandidate.task_id == GenerationTask.id)
        .join(Project, GenerationTask.project_id == Project.id)
        .filter(
            GenerationFailureCandidate.id == candidate_id,
            Project.user_id == current_user_id(db),
            Project.is_eval == False,
        )
        .first()
    )
    if not candidate:
        raise HTTPException(404, "失败候选不存在")
    return candidate


# ---------- 样本管理 ----------

@router.get("/failure-candidates", response_model=list[FailureCandidateOut])
def list_failure_candidates(db: Session = Depends(get_db)):
    candidates = (
        db.query(GenerationFailureCandidate)
        .join(GenerationTask, GenerationFailureCandidate.task_id == GenerationTask.id)
        .join(Project, GenerationTask.project_id == Project.id)
        .filter(Project.user_id == current_user_id(db), Project.is_eval == False)
        .order_by(GenerationFailureCandidate.created_at.desc())
        .all()
    )
    return [_candidate_to_out(candidate) for candidate in candidates]


@router.get("/failure-candidates/{candidate_id}", response_model=FailureCandidateOut)
def get_failure_candidate(candidate_id: int, db: Session = Depends(get_db)):
    return _candidate_to_out(_owned_candidate(db, candidate_id))


@router.post("/failure-candidates/{candidate_id}/promote", response_model=EvalSampleOut, status_code=201)
def promote_failure_candidate(
    candidate_id: int,
    data: PromoteFailureCandidateRequest,
    db: Session = Depends(get_db),
):
    candidate = _owned_candidate(db, candidate_id)
    if candidate.status != "pending":
        raise HTTPException(400, "该失败候选已处理")

    sample = EvalSample(
        project_id=_eval_project(db).id,
        title=data.title.strip(),
        content=candidate.input_snapshot,
        checkpoints=json.dumps([item.model_dump() for item in data.checkpoints], ensure_ascii=False),
    )
    db.add(sample)
    db.flush()
    candidate.status = "promoted"
    candidate.promoted_sample_id = sample.id
    candidate.promoted_at = datetime.utcnow()
    db.commit()
    db.refresh(sample)
    return _sample_to_out(sample)


@router.post("/failure-candidates/{candidate_id}/dismiss", response_model=FailureCandidateOut)
def dismiss_failure_candidate(candidate_id: int, db: Session = Depends(get_db)):
    candidate = _owned_candidate(db, candidate_id)
    if candidate.status != "pending":
        raise HTTPException(400, "该失败候选已处理")
    candidate.status = "dismissed"
    candidate.dismissed_at = datetime.utcnow()
    db.commit()
    db.refresh(candidate)
    return _candidate_to_out(candidate)

@router.get("/samples", response_model=list[EvalSampleOut])
def list_samples(db: Session = Depends(get_db)):
    project_id = _eval_project(db).id
    samples = (
        db.query(EvalSample)
        .filter(EvalSample.project_id == project_id)
        .order_by(EvalSample.created_at.desc())
        .all()
    )
    return [_sample_to_out(s) for s in samples]


@router.post("/samples", response_model=EvalSampleOut, status_code=201)
def create_sample(data: EvalSampleCreate, db: Session = Depends(get_db)):
    if not data.title.strip() or not data.content.strip():
        raise HTTPException(400, "标题和需求内容不能为空")

    sample = EvalSample(
        project_id=_eval_project(db).id,
        title=data.title.strip(),
        content=data.content,
        checkpoints=json.dumps([cp.model_dump() for cp in data.checkpoints], ensure_ascii=False),
    )
    db.add(sample)
    db.commit()
    db.refresh(sample)
    return _sample_to_out(sample)


@router.put("/samples/{sample_id}", response_model=EvalSampleOut)
def update_sample(sample_id: int, data: EvalSampleUpdate, db: Session = Depends(get_db)):
    project_id = _eval_project(db).id
    sample = db.query(EvalSample).filter(
        EvalSample.id == sample_id,
        EvalSample.project_id == project_id,
    ).first()
    if not sample:
        raise HTTPException(404, "评测样本不存在")

    if data.title is not None:
        sample.title = data.title.strip()
    if data.content is not None:
        sample.content = data.content
    if data.checkpoints is not None:
        sample.checkpoints = json.dumps([cp.model_dump() for cp in data.checkpoints], ensure_ascii=False)
    db.commit()
    db.refresh(sample)
    return _sample_to_out(sample)


@router.delete("/samples/{sample_id}", status_code=204)
def delete_sample(sample_id: int, db: Session = Depends(get_db)):
    project_id = _eval_project(db).id
    sample = db.query(EvalSample).filter(
        EvalSample.id == sample_id,
        EvalSample.project_id == project_id,
    ).first()
    if not sample:
        raise HTTPException(404, "评测样本不存在")
    used = db.query(EvalResult).filter(EvalResult.sample_id == sample_id).count()
    if used:
        raise HTTPException(400, "该样本已被评测运行引用，不能删除")
    db.delete(sample)
    db.commit()


# ---------- 评测运行 ----------

@router.get("/runs", response_model=list[EvalRunOut])
def list_runs(db: Session = Depends(get_db)):
    project_id = _eval_project(db).id
    runs = (
        db.query(EvalRun)
        .options(joinedload(EvalRun.results).joinedload(EvalResult.scorecard))
        .filter(EvalRun.project_id == project_id)
        .order_by(EvalRun.created_at.desc())
        .all()
    )
    titles = _sample_titles(db, project_id)
    return [_run_to_out(r, titles) for r in runs]


@router.post("/runs", response_model=EvalRunOut, status_code=201)
def create_run(
    data: EvalRunCreate,
    db: Session = Depends(get_db),
):
    if not data.label.strip():
        raise HTTPException(400, "请填写运行标签（如 baseline）")
    project_id = _eval_project(db).id
    samples = db.query(EvalSample).filter(
        EvalSample.project_id == project_id,
        EvalSample.id.in_(data.sample_ids),
    ).all()
    if not samples:
        raise HTTPException(400, "请至少选择一个评测样本")

    running = db.query(EvalRun).filter(
        EvalRun.project_id == project_id,
        EvalRun.status.in_(["pending", "running"]),
    ).count()
    if running:
        raise HTTPException(400, "已有评测正在运行，请等待完成")

    experiment = dict(data.experiment or {})
    experiment.setdefault("strategy", data.strategy)
    try:
        runtime_config = get_project_runtime_config(db, project_id)
        snapshot = build_experiment_snapshot(get_registry(), runtime_config, experiment)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    run = EvalRun(
        project_id=project_id,
        label=data.label.strip(),
        config=json.dumps(snapshot, ensure_ascii=False),
        config_snapshot=json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
        status="pending",
    )
    db.add(run)
    db.flush()
    frozen, fingerprint = freeze_run_samples(run, samples)
    run.sample_set_fingerprint = fingerprint
    db.add_all(frozen)
    db.flush()
    for sample in samples:
        run_sample = next(item for item in frozen if item.source_sample_id == sample.id)
        db.add(EvalResult(run_id=run.id, sample_id=sample.id, run_sample_id=run_sample.id))
    db.commit()
    create_evaluation_runner_run(db, run, model_snapshot=asdict(runtime_config))
    db.refresh(run)
    return _run_to_out(run, _sample_titles(db, project_id))


@router.get("/runs/{run_id}", response_model=EvalRunOut)
def get_run(run_id: int, db: Session = Depends(get_db)):
    project_id = _eval_project(db).id
    run = (
        db.query(EvalRun)
        .options(joinedload(EvalRun.results).joinedload(EvalResult.scorecard))
        .filter(EvalRun.id == run_id, EvalRun.project_id == project_id)
        .first()
    )
    if not run:
        raise HTTPException(404, "评测运行不存在")
    return _run_to_out(run, _sample_titles(db, project_id))


def _owned_eval_run(db: Session, run_id: int) -> EvalRun:
    project_id = _eval_project(db).id
    run = db.query(EvalRun).filter(EvalRun.id == run_id, EvalRun.project_id == project_id).first()
    if not run:
        raise HTTPException(404, "评测运行不存在")
    return run


@router.post("/runs/{run_id}/baseline", response_model=EvalRunOut)
def mark_run_baseline(run_id: int, db: Session = Depends(get_db)):
    try:
        run = set_run_baseline(db, _owned_eval_run(db, run_id))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _run_to_out(run, _sample_titles(db, run.project_id))


@router.get("/compare")
def compare_eval_runs(run_ids: list[int], db: Session = Depends(get_db)):
    if len(run_ids) < 2:
        raise HTTPException(422, "至少选择两个评测运行")
    runs = [_owned_eval_run(db, run_id) for run_id in run_ids]
    if any(run.status != "completed" for run in runs):
        raise HTTPException(400, "只能比较已完成的评测运行")
    try:
        return compare_runs(runs)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/runs/{run_id}/cancel", response_model=EvalRunOut)
def cancel_eval_run(run_id: int, db: Session = Depends(get_db)):
    run = _owned_eval_run(db, run_id)
    if not run.agent_run_id or not AgentRunRepository(db).request_cancel(run.agent_run_id):
        raise HTTPException(400, "评测运行已结束，无法取消")
    if run.status == "pending":
        run.status = "cancelled"
        db.commit()
    return _run_to_out(run, _sample_titles(db, run.project_id))


@router.get("/runs/{run_id}/events")
def list_eval_run_events(run_id: int, after_sequence: int = 0, db: Session = Depends(get_db)):
    run = _owned_eval_run(db, run_id)
    if not run.agent_run_id:
        return []
    return (
        db.query(AgentRunEvent)
        .filter(AgentRunEvent.agent_run_id == run.agent_run_id, AgentRunEvent.sequence > max(0, after_sequence))
        .order_by(AgentRunEvent.sequence.asc())
        .all()
    )


@router.get("/tasks/{task_id}", response_model=GenerationTaskOut)
def get_eval_task(task_id: int, db: Session = Depends(get_db)):
    """评测样本对应生成任务的完整明细（用例 + 评分 + 质检报告）。"""
    project_id = _eval_project(db).id
    task = (
        db.query(GenerationTask)
        .options(joinedload(GenerationTask.drafts), joinedload(GenerationTask.quality_report))
        .filter(
            GenerationTask.id == task_id,
            GenerationTask.project_id == project_id,
            GenerationTask.is_eval == True,
        )
        .first()
    )
    if not task:
        raise HTTPException(404, "评测任务不存在")
    return task


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: int, db: Session = Depends(get_db)):
    project_id = _eval_project(db).id
    run = db.query(EvalRun).filter(
        EvalRun.id == run_id,
        EvalRun.project_id == project_id,
    ).first()
    if not run:
        raise HTTPException(404, "评测运行不存在")
    if run.status == "running":
        raise HTTPException(400, "评测正在运行，不能删除")
    db.delete(run)
    db.commit()
