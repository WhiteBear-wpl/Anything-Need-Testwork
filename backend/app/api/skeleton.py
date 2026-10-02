from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import current_user_id
from app.models.project import Project
from app.schemas import (
    SkeletonFilesUpdate,
    SkeletonGenerateRequest,
    SkeletonOptionOut,
    SkeletonOut,
)
from app.services import skeleton_service

router = APIRouter(prefix="/projects", tags=["skeleton"])


def _owned_project_or_404(db: Session, project_id: int) -> Project:
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user_id(db))
        .first()
    )
    if not project:
        raise HTTPException(404, "项目不存在")
    return project


@router.get("/skeleton/options", response_model=list[SkeletonOptionOut])
def skeleton_options():
    return skeleton_service.list_skeleton_options()


@router.get("/{project_id}/skeleton", response_model=SkeletonOut | None)
def get_skeleton(project_id: int, db: Session = Depends(get_db)):
    _owned_project_or_404(db, project_id)
    skeleton = skeleton_service.get_skeleton(db, project_id)
    return skeleton


@router.post("/{project_id}/skeleton/generate", response_model=SkeletonOut)
async def generate_skeleton(
    project_id: int,
    data: SkeletonGenerateRequest,
    db: Session = Depends(get_db),
):
    project = _owned_project_or_404(db, project_id)
    # 允许生成时覆盖 base_url（不改项目本身）
    if data.base_url:
        ctx_base = data.base_url
        if not project.slug:
            project.slug = project.name
        project.base_url = ctx_base
        db.commit()
    skeleton = await skeleton_service.save_skeleton(
        db,
        current_user_id(db),
        project,
        language=data.language,
        framework=data.framework,
        mode=data.mode,
    )
    return skeleton


@router.patch("/{project_id}/skeleton/files", response_model=SkeletonOut)
def update_skeleton_files(
    project_id: int,
    data: SkeletonFilesUpdate,
    db: Session = Depends(get_db),
):
    _owned_project_or_404(db, project_id)
    skeleton = skeleton_service.get_skeleton(db, project_id)
    if skeleton is None:
        raise HTTPException(404, "项目尚未初始化测试骨架")
    import json

    skeleton.files = json.dumps(
        [{"path": f["path"], "content": f["content"]} for f in data.files],
        ensure_ascii=False,
    )
    db.commit()
    db.refresh(skeleton)
    return skeleton
