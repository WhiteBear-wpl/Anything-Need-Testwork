from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import current_user_id
from app.models.project import Project
from app.models.wiki import WikiPage
from app.schemas import (
    WikiCopyRequest,
    WikiCopyResult,
    WikiPageCreate,
    WikiPageOut,
    WikiPageUpdate,
)
from app.services import wiki_service

router = APIRouter(prefix="/wiki", tags=["wiki"])


def _owned_project_or_404(db: Session, project_id: int) -> Project:
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user_id(db))
        .first()
    )
    if not project:
        raise HTTPException(404, "项目不存在")
    return project


def _owned_page_or_404(db: Session, page_id: int) -> WikiPage:
    page = wiki_service.get_page(db, current_user_id(db), page_id)
    if not page:
        raise HTTPException(404, "Wiki 页面不存在")
    return page


@router.get("", response_model=list[WikiPageOut])
def list_wiki(
    project_id: int | None = None,
    db: Session = Depends(get_db),
):
    """列出 Wiki 页面。project_id 缺省时返回工作台总 Wiki，否则返回项目内 Wiki。"""
    if project_id is not None:
        _owned_project_or_404(db, project_id)
    return wiki_service.list_pages(db, current_user_id(db), project_id)


@router.post("", response_model=WikiPageOut, status_code=201)
def create_wiki(data: WikiPageCreate, db: Session = Depends(get_db)):
    if data.project_id is not None:
        _owned_project_or_404(db, data.project_id)
    page = wiki_service.create_page(
        db,
        current_user_id(db),
        title=data.title,
        content=data.content,
        project_id=data.project_id,
        parent_id=data.parent_id,
        is_template=data.is_template,
    )
    return page


@router.get("/{page_id}", response_model=WikiPageOut)
def get_wiki(page_id: int, db: Session = Depends(get_db)):
    return _owned_page_or_404(db, page_id)


@router.patch("/{page_id}", response_model=WikiPageOut)
def update_wiki(page_id: int, data: WikiPageUpdate, db: Session = Depends(get_db)):
    page = _owned_page_or_404(db, page_id)
    fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    return wiki_service.update_page(db, page, **fields)


@router.delete("/{page_id}", status_code=204)
def delete_wiki(page_id: int, db: Session = Depends(get_db)):
    page = _owned_page_or_404(db, page_id)
    wiki_service.delete_page(db, page)


@router.post("/{page_id}/copy", response_model=WikiCopyResult)
def copy_wiki(page_id: int, data: WikiCopyRequest, db: Session = Depends(get_db)):
    """把总 Wiki 页面（含全部后代）复制到目标项目，实现跨项目复用。"""
    page = _owned_page_or_404(db, page_id)
    if page.project_id is not None:
        raise HTTPException(400, "只有总 Wiki 页面可复制到项目")
    _owned_project_or_404(db, data.target_project_id)
    count = wiki_service.copy_page_to_project(db, page, data.target_project_id)
    return WikiCopyResult(copied_pages=count)
