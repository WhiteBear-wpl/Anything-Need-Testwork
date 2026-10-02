from dataclasses import asdict
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.config import settings
from app.agent_runtime.repository import AgentRunRepository
from app.agent_runtime.contracts import RunStatus
from app.agent_runtime.service import create_case_writer_run, is_runtime_v2_enabled
from app.api.deps import require_project_access
from app.models.generation import (
    GeneratedCaseDraft,
    GenerationAttempt,
    GenerationFailureCandidate,
    GenerationTask,
)
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.project import Project
from app.models.requirement import RequirementDocument, RequirementItem
from app.models.testcase import TestCase
from app.schemas import (
    AgentRunEventOut,
    AgentRunOut,
    DraftEdit,
    GeneratedCaseDraftOut,
    GenerationTaskCreate,
    GenerationTaskOut,
    GenerationTaskSummaryOut,
    ReviewAction,
    TestCaseOut,
)
from app.services.generation_service import (
    adopt_drafts,
    build_strategy_config_payload,
    parse_strategy_config,
    reject_drafts,
    run_judge_for_task,
)
from app.services.skill_policy_service import get_project_policy_state
from app.skills.policy import PolicyResolver
from app.skills.registry import get_registry
from app.services.collaboration_metrics import (
    build_project_rollout_report,
    build_task_collaboration_summary,
)
from app.services.quality_checker import judge_summary
from app.services.settings_service import get_project_runtime_config
from app.services.testcase_export_service import export_testcases
from app.workflows.generation.runner import resume_generation_workflow, run_generation_workflow

router = APIRouter(
    prefix="/projects/{project_id}/generations",
    tags=["generations"],
    dependencies=[Depends(require_project_access)],
)


def _latest_task_run(db: Session, project_id: int, task_id: int) -> AgentRun:
    run = (
        db.query(AgentRun)
        .filter(AgentRun.project_id == project_id, AgentRun.generation_task_id == task_id)
        .order_by(AgentRun.id.desc())
        .first()
    )
    if not run:
        raise HTTPException(404, "该生成任务没有 Runtime V2 运行记录")
    return run


def _task_run(db: Session, project_id: int, task_id: int, run_id: int | None) -> AgentRun:
    if run_id is None:
        return _latest_task_run(db, project_id, task_id)
    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.id == run_id,
            AgentRun.project_id == project_id,
            AgentRun.generation_task_id == task_id,
        )
        .first()
    )
    if run is None:
        raise HTTPException(404, "Runtime V2 运行记录不存在")
    return run


async def _run_generation_task(task_id: int):
    await run_generation_workflow(task_id)


async def _resume_generation_task(task_id: int):
    await resume_generation_workflow(task_id)


@router.get("", response_model=list[GenerationTaskOut])
def list_tasks(project_id: int, db: Session = Depends(get_db)):
    return (
        db.query(GenerationTask)
        .options(
            joinedload(GenerationTask.drafts).joinedload(GeneratedCaseDraft.requirement_item),
            joinedload(GenerationTask.quality_report),
            joinedload(GenerationTask.attempts),
            joinedload(GenerationTask.failure_candidates),
        )
        .filter(GenerationTask.project_id == project_id, GenerationTask.is_eval == False)
        .order_by(GenerationTask.created_at.desc())
        .all()
    )


@router.post("", response_model=GenerationTaskOut, status_code=201)
async def create_task(
    project_id: int,
    data: GenerationTaskCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "项目不存在")

    doc = (
        db.query(RequirementDocument)
        .filter(RequirementDocument.id == data.document_id, RequirementDocument.project_id == project_id)
        .first()
    )
    if not doc:
        raise HTTPException(404, "需求文档不存在")
    if doc.status != "confirmed":
        raise HTTPException(400, "请先确认功能点后再生成")

    try:
        policy_state = get_project_policy_state(db, project_id)
        resolved_policy = PolicyResolver(get_registry()).resolve_requested(
            list(policy_state.overrides),
            data.specialist_skills or [],
            revision_no=policy_state.revision_no,
        )
        strategy_config = build_strategy_config_payload(
            data,
            get_project_runtime_config(db, project_id),
            strict_specialists=True,
            policy_state=resolved_policy,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    task = GenerationTask(
        project_id=project_id,
        document_id=data.document_id,
        strategy=data.strategy,
        strategy_config=strategy_config,
        status="pending",
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    if is_runtime_v2_enabled(settings.agent_runtime_v2_enabled, project):
        create_case_writer_run(
            db,
            task,
            model_snapshot=asdict(get_project_runtime_config(db, project_id)),
        )
    else:
        background_tasks.add_task(_run_generation_task, task.id)
    return task


@router.get("/summary", response_model=list[GenerationTaskSummaryOut])
def list_task_summaries(project_id: int, db: Session = Depends(get_db)):
    """生成记录列表：只返回统计信息，不返回草稿明细。"""
    tasks = (
        db.query(GenerationTask)
        .options(joinedload(GenerationTask.drafts), joinedload(GenerationTask.quality_report))
        .filter(GenerationTask.project_id == project_id, GenerationTask.is_eval == False)
        .order_by(GenerationTask.created_at.desc())
        .all()
    )

    doc_ids = {t.document_id for t in tasks}
    doc_titles = {}
    if doc_ids:
        for doc_id, title in (
            db.query(RequirementDocument.id, RequirementDocument.title)
            .filter(RequirementDocument.id.in_(doc_ids))
            .all()
        ):
            doc_titles[doc_id] = title

    result = []
    for t in tasks:
        config = parse_strategy_config(t)
        drafts = t.drafts or []
        result.append(
            GenerationTaskSummaryOut(
                id=t.id,
                document_id=t.document_id,
                document_title=doc_titles.get(t.document_id, ""),
                strategy=config["strategy"],
                specialist_skills=config["specialist_skills"],
                status=t.status,
                progress=t.progress,
                error_message=t.error_message,
                tokens_used=t.tokens_used or 0,
                created_at=t.created_at,
                draft_count=len(drafts),
                smoke_count=sum(1 for d in drafts if d.is_smoke),
                coverage_rate=t.quality_report.coverage_rate if t.quality_report else None,
                review_stats=t.review_stats,
            )
        )
    return result


@router.get("/collaboration/report")
def get_project_collaboration_report(
    project_id: int,
    limit: int = 30,
    db: Session = Depends(get_db),
):
    return build_project_rollout_report(db, project_id, limit=limit)


@router.get("/{task_id}", response_model=GenerationTaskOut)
def get_task(project_id: int, task_id: int, db: Session = Depends(get_db)):
    task = (
        db.query(GenerationTask)
        .options(
            joinedload(GenerationTask.drafts).joinedload(GeneratedCaseDraft.requirement_item),
            joinedload(GenerationTask.quality_report),
            joinedload(GenerationTask.attempts),
            joinedload(GenerationTask.failure_candidates),
        )
        .filter(GenerationTask.id == task_id, GenerationTask.project_id == project_id)
        .first()
    )
    if not task:
        raise HTTPException(404, "生成任务不存在")
    return task


@router.get("/{task_id}/run", response_model=AgentRunOut)
def get_task_run(project_id: int, task_id: int, db: Session = Depends(get_db)):
    return _latest_task_run(db, project_id, task_id)


@router.get("/{task_id}/collaboration")
def get_collaboration_summary(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    run_id: int | None = None,
):
    run = _task_run(db, project_id, task_id, run_id)
    return build_task_collaboration_summary(db, project_id, task_id, run.id)


@router.get("/{task_id}/run/events", response_model=list[AgentRunEventOut])
def list_task_run_events(
    project_id: int,
    task_id: int,
    after_sequence: int = 0,
    run_id: int | None = None,
    db: Session = Depends(get_db),
):
    run = _task_run(db, project_id, task_id, run_id)
    return (
        db.query(AgentRunEvent)
        .filter(
            AgentRunEvent.agent_run_id == run.id,
            AgentRunEvent.sequence > max(0, after_sequence),
        )
        .order_by(AgentRunEvent.sequence.asc())
        .all()
    )


@router.post("/{task_id}/run/cancel", response_model=AgentRunOut)
def cancel_task_run(project_id: int, task_id: int, db: Session = Depends(get_db)):
    run = _latest_task_run(db, project_id, task_id)
    if not AgentRunRepository(db).request_cancel(run.id):
        raise HTTPException(400, "该运行已结束，无法取消")
    return db.get(AgentRun, run.id)


@router.post("/{task_id}/run/retry", response_model=AgentRunOut, status_code=201)
def retry_task_run(project_id: int, task_id: int, db: Session = Depends(get_db)):
    run = _latest_task_run(db, project_id, task_id)
    if run.status not in ("failed", "cancelled", RunStatus.BUDGET_EXHAUSTED.value):
        raise HTTPException(400, "只有失败、已取消或预算耗尽的运行可以重试")
    project = db.get(Project, project_id)
    if not project or not is_runtime_v2_enabled(settings.agent_runtime_v2_enabled, project):
        raise HTTPException(409, "Runtime V2 灰度开关未开启，无法创建重试运行")
    task = db.get(GenerationTask, task_id)
    if not task:
        raise HTTPException(404, "生成任务不存在")
    task.status = "pending"
    task.stage = "等待恢复"
    task.error_message = ""
    db.commit()
    return create_case_writer_run(
        db,
        task,
        model_snapshot=asdict(get_project_runtime_config(db, project_id)),
        resume=True,
        parent_run_id=run.parent_run_id,
        resume_from_run_id=run.id,
    )


@router.post("/{task_id}/resume", response_model=GenerationTaskOut)
def resume_task(
    project_id: int,
    task_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """从 LangGraph 最近一次成功检查点恢复失败任务。"""
    task = (
        db.query(GenerationTask)
        .options(
            joinedload(GenerationTask.drafts).joinedload(GeneratedCaseDraft.requirement_item),
            joinedload(GenerationTask.quality_report),
        )
        .filter(GenerationTask.id == task_id, GenerationTask.project_id == project_id)
        .first()
    )
    if not task:
        raise HTTPException(404, "生成任务不存在")
    if task.status != "failed":
        raise HTTPException(400, "只有失败的生成任务可以恢复")

    task.status = "pending"
    task.stage = "等待恢复"
    task.error_message = ""
    db.commit()
    db.refresh(task)
    background_tasks.add_task(_resume_generation_task, task.id)
    return task


@router.get("/{task_id}/export")
def export_drafts(
    project_id: int,
    task_id: int,
    format: str = "xlsx",
    smoke_only: bool = False,
    db: Session = Depends(get_db),
):
    task = (
        db.query(GenerationTask)
        .options(joinedload(GenerationTask.drafts))
        .filter(GenerationTask.id == task_id, GenerationTask.project_id == project_id)
        .first()
    )
    if not task:
        raise HTTPException(404, "生成任务不存在")

    drafts = list(task.drafts or [])
    if smoke_only:
        drafts = [d for d in drafts if d.is_smoke]
    if not drafts:
        raise HTTPException(400, "没有可导出的用例")

    item_ids = {d.requirement_item_id for d in drafts if d.requirement_item_id}
    items_map = {}
    if item_ids:
        for item in db.query(RequirementItem).filter(RequirementItem.id.in_(item_ids)).all():
            items_map[item.id] = item

    doc = db.get(RequirementDocument, task.document_id)
    doc_title = (doc.title if doc else "") or f"任务{task_id}"

    cases = []
    for d in drafts:
        item = items_map.get(d.requirement_item_id)
        cases.append({
            "id": d.id,
            "module": item.module if item else "",
            "feature": item.feature if item else "",
            "title": d.title,
            "priority": d.priority,
            "case_type": d.case_type,
            "is_smoke": d.is_smoke,
            "precondition": d.precondition,
            "steps": d.steps,
            "expected_result": d.expected_result,
            "review_status": d.review_status,
            "source": "ai_generated",
        })

    fmt = "md" if format == "md" else "xlsx"
    export_title = f"{doc_title}-生成任务{task_id}"
    content, media_type, ext = export_testcases(export_title, cases, fmt=fmt, include_review=True)
    suffix = "冒烟" if smoke_only else "用例"
    filename = f"{doc_title}-任务{task_id}-{suffix}.{ext}"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(BytesIO(content), media_type=media_type, headers=headers)


@router.post("/{task_id}/review", response_model=list[TestCaseOut])
def review_drafts(project_id: int, task_id: int, data: ReviewAction, db: Session = Depends(get_db)):
    task = db.query(GenerationTask).filter(
        GenerationTask.id == task_id,
        GenerationTask.project_id == project_id,
    ).first()
    if not task:
        raise HTTPException(404, "生成任务不存在")
    if data.action == "adopt":
        return adopt_drafts(db, task_id, data.draft_ids)
    if data.action == "reject":
        reject_drafts(db, task_id, data.draft_ids, data.reject_reason)
        return []
    if data.action == "to_confirm":
        drafts = (
            db.query(GeneratedCaseDraft)
            .filter(GeneratedCaseDraft.task_id == task_id, GeneratedCaseDraft.id.in_(data.draft_ids))
            .all()
        )
        for d in drafts:
            # 已采纳 / 已驳回的用例是终态，不允许回到待确认
            if d.review_status not in ("adopted", "rejected"):
                d.review_status = "to_confirm"
        db.commit()
        return []
    raise HTTPException(400, "无效操作")


@router.post("/{task_id}/judge", response_model=GenerationTaskOut)
async def rejudge_task(project_id: int, task_id: int, db: Session = Depends(get_db)):
    """手动（重新）运行 AI Judge 评分，并刷新质检报告中的评分汇总。"""
    task = (
        db.query(GenerationTask)
        .options(joinedload(GenerationTask.drafts), joinedload(GenerationTask.quality_report))
        .filter(GenerationTask.id == task_id, GenerationTask.project_id == project_id)
        .first()
    )
    if not task:
        raise HTTPException(404, "生成任务不存在")
    if not task.drafts:
        raise HTTPException(400, "该任务没有可评分的用例")

    await run_judge_for_task(db, task)

    if task.quality_report:
        avg_score, hallucination = judge_summary(list(task.drafts))
        task.quality_report.avg_judge_score = avg_score
        task.quality_report.hallucination_count = hallucination
        db.commit()

    db.refresh(task)
    return task


@router.patch("/{task_id}/drafts/{draft_id}", response_model=GeneratedCaseDraftOut)
def edit_draft(
    project_id: int,
    task_id: int,
    draft_id: int,
    data: DraftEdit,
    db: Session = Depends(get_db),
):
    draft = (
        db.query(GeneratedCaseDraft)
        .join(GenerationTask, GeneratedCaseDraft.task_id == GenerationTask.id)
        .filter(
            GeneratedCaseDraft.id == draft_id,
            GeneratedCaseDraft.task_id == task_id,
            GenerationTask.project_id == project_id,
        )
        .first()
    )
    if not draft:
        raise HTTPException(404, "候选用例不存在")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(draft, field, value)
    draft.review_status = "edited"
    draft.was_edited = True
    db.commit()
    db.refresh(draft)
    return draft
