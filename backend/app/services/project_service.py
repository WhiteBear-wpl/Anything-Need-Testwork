from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.generation import GenerationTask
from app.models.project import Project
from app.models.requirement import RequirementDocument
from app.models.skeleton import ProjectSkeleton
from app.models.testcase import TestCase
from app.models.wiki import WikiPage


def compute_project_stage(db: Session, project_id: int) -> dict:
    """从需求文档、生成任务、用例库的真实状态推导项目所处阶段。

    阶段状态机：import → confirm → generate → review → done。
    需求文档比最新生成任务更新时（开始新一轮），以文档状态为准。
    """
    latest_doc = (
        db.query(RequirementDocument)
        .filter(
            RequirementDocument.project_id == project_id,
            RequirementDocument.is_eval == False,
        )
        .order_by(RequirementDocument.id.desc())
        .first()
    )
    latest_task = (
        db.query(GenerationTask)
        .filter(
            GenerationTask.project_id == project_id,
            GenerationTask.is_eval == False,
        )
        .order_by(GenerationTask.id.desc())
        .first()
    )
    testcase_count = (
        db.query(func.count(TestCase.id))
        .filter(TestCase.project_id == project_id)
        .scalar()
        or 0
    )

    result = {
        "stage": "import",
        "document_id": None,
        "document_title": "",
        "task_id": None,
        "generating": False,
        "failed": False,
        "pending_drafts": 0,
        "item_count": 0,
        "testcase_count": testcase_count,
    }

    if latest_doc is None:
        return result

    doc_newer_than_task = (
        latest_task is None or latest_doc.created_at > latest_task.created_at
    )

    if doc_newer_than_task:
        result["document_id"] = latest_doc.id
        result["document_title"] = latest_doc.title
        result["item_count"] = len(latest_doc.items)
        result["stage"] = "generate" if latest_doc.status == "confirmed" else "confirm"
        return result

    result["task_id"] = latest_task.id
    result["document_id"] = latest_task.document_id
    if latest_task.status in ("pending", "generating"):
        result["stage"] = "review"
        result["generating"] = True
        return result
    if latest_task.status == "failed":
        result["stage"] = "generate"
        result["failed"] = True
        return result

    stats = latest_task.review_stats
    result["pending_drafts"] = stats["pending"]
    result["stage"] = "review" if stats["pending"] > 0 else "done"
    return result


def get_home_overview(db: Session, user_id: int) -> dict:
    projects = (
        db.query(Project)
        .filter(Project.user_id == user_id, Project.is_eval == False)
        .order_by(Project.updated_at.desc())
        .all()
    )

    testcase_counts = dict(
        db.query(TestCase.project_id, func.count(TestCase.id))
        .join(Project, TestCase.project_id == Project.id)
        .filter(Project.user_id == user_id, Project.is_eval == False)
        .group_by(TestCase.project_id)
        .all()
    )
    generation_counts = dict(
        db.query(GenerationTask.project_id, func.count(GenerationTask.id))
        .join(Project, GenerationTask.project_id == Project.id)
        .filter(Project.user_id == user_id, Project.is_eval == False)
        .filter(GenerationTask.is_eval == False)
        .group_by(GenerationTask.project_id)
        .all()
    )
    wiki_counts = dict(
        db.query(WikiPage.project_id, func.count(WikiPage.id))
        .filter(WikiPage.user_id == user_id, WikiPage.project_id.isnot(None))
        .group_by(WikiPage.project_id)
        .all()
    )
    skeleton_project_ids = {
        s.project_id
        for s in db.query(ProjectSkeleton.project_id)
        .filter(ProjectSkeleton.user_id == user_id)
        .all()
    }

    latest_subq = (
        db.query(
            GenerationTask.project_id,
            func.max(GenerationTask.id).label("latest_id"),
        )
        .join(Project, GenerationTask.project_id == Project.id)
        .filter(Project.user_id == user_id, Project.is_eval == False)
        .filter(GenerationTask.is_eval == False)
        .group_by(GenerationTask.project_id)
        .subquery()
    )
    latest_tasks = {
        task.project_id: task
        for task in db.query(GenerationTask)
        .join(latest_subq, GenerationTask.id == latest_subq.c.latest_id)
        .all()
    }

    project_items = []
    latest_active_project_id = None
    latest_active_at: datetime | None = None

    for project in projects:
        last_task = latest_tasks.get(project.id)
        last_at = last_task.created_at if last_task else None
        if last_at and (latest_active_at is None or last_at > latest_active_at):
            latest_active_at = last_at
            latest_active_project_id = project.id

        project_items.append(
            {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "slug": project.slug,
                "base_url": project.base_url,
                "created_at": project.created_at,
                "updated_at": project.updated_at,
                "testcase_count": testcase_counts.get(project.id, 0),
                "generation_count": generation_counts.get(project.id, 0),
                "wiki_count": wiki_counts.get(project.id, 0),
                "has_skeleton": project.id in skeleton_project_ids,
                "last_generation_at": last_at,
                "last_generation_status": last_task.status if last_task else None,
            }
        )

    if latest_active_project_id is None and projects:
        latest_active_project_id = projects[0].id

    latest_active_stage = (
        compute_project_stage(db, latest_active_project_id)
        if latest_active_project_id
        else None
    )

    return {
        "total_projects": len(projects),
        "total_testcases": sum(testcase_counts.values()),
        "total_generations": sum(generation_counts.values()),
        "projects": project_items,
        "latest_active_project_id": latest_active_project_id,
        "latest_active_stage": latest_active_stage,
    }
