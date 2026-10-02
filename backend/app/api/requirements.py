from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

import json
from io import BytesIO
from urllib.parse import quote

from app.database import get_db
from app.api.deps import require_project_access
from app.models.project import Project
from app.models.requirement import RequirementDocument, RequirementItem
from app.schemas import (
    ConfirmRequest,
    RequirementDocumentCreate,
    RequirementDocumentOut,
    RequirementItemCreate,
    RequirementItemOut,
    RequirementItemUpdate,
    TestScopeUpdate,
)
from app.services.document_parser import DocumentParseError, parse_upload, title_from_filename
from app.services.featurelist_service import export_featurelist, parse_featurelist
from app.services.generation_service import confirm_requirements, structure_requirements
from app.services.settings_service import get_project_runtime_config
from app.skills import propose_test_scope

router = APIRouter(
    prefix="/projects/{project_id}/requirements",
    tags=["requirements"],
    dependencies=[Depends(require_project_access)],
)


def _get_document(db: Session, project_id: int, document_id: int) -> RequirementDocument | None:
    return (
        db.query(RequirementDocument)
        .options(joinedload(RequirementDocument.items))
        .filter(RequirementDocument.id == document_id, RequirementDocument.project_id == project_id)
        .first()
    )


def _invalidate_confirmation(db: Session, doc: RequirementDocument) -> None:
    if doc.status != "confirmed":
        return
    doc.status = "structured"
    db.query(RequirementItem).filter(RequirementItem.document_id == doc.id).update(
        {"confirmed": False}, synchronize_session=False
    )


@router.get("", response_model=list[RequirementDocumentOut])
def list_documents(project_id: int, db: Session = Depends(get_db)):
    docs = (
        db.query(RequirementDocument)
        .options(joinedload(RequirementDocument.items))
        .filter(RequirementDocument.project_id == project_id, RequirementDocument.is_eval == False)
        .order_by(RequirementDocument.created_at.desc())
        .all()
    )
    return docs


@router.post("", response_model=RequirementDocumentOut, status_code=201)
async def create_document(project_id: int, data: RequirementDocumentCreate, db: Session = Depends(get_db)):
    if not db.query(Project).get(project_id):
        raise HTTPException(404, "项目不存在")

    doc = RequirementDocument(
        project_id=project_id,
        title=data.title,
        raw_content=data.content,
        source_type="text",
        status="uploaded",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.post("/upload", response_model=RequirementDocumentOut, status_code=201)
async def upload_document(
    project_id: int,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    db: Session = Depends(get_db),
):
    if not db.query(Project).get(project_id):
        raise HTTPException(404, "项目不存在")

    filename = file.filename or ""
    data = await file.read()
    try:
        content, source_type = parse_upload(filename, data)
    except DocumentParseError as exc:
        raise HTTPException(400, str(exc)) from exc

    doc = RequirementDocument(
        project_id=project_id,
        title=(title or title_from_filename(filename) or "未命名需求")[:200],
        raw_content=content,
        source_type=source_type,
        status="uploaded",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.post("/{document_id}/structure", response_model=RequirementDocumentOut)
async def structure_document(project_id: int, document_id: int, db: Session = Depends(get_db)):
    doc = (
        db.query(RequirementDocument)
        .options(joinedload(RequirementDocument.items))
        .filter(RequirementDocument.id == document_id, RequirementDocument.project_id == project_id)
        .first()
    )
    if not doc:
        raise HTTPException(404, "需求文档不存在")

    await structure_requirements(db, doc)
    db.refresh(doc)
    return doc


@router.patch("/{document_id}/scope", response_model=RequirementDocumentOut)
def update_scope(
    project_id: int,
    document_id: int,
    data: TestScopeUpdate,
    db: Session = Depends(get_db),
):
    doc = _get_document(db, project_id, document_id)
    if not doc:
        raise HTTPException(404, "需求文档不存在")
    doc.test_scope = data.test_scope or ""
    db.commit()
    db.refresh(doc)
    return doc


@router.post("/{document_id}/scope/generate", response_model=RequirementDocumentOut)
async def generate_scope(project_id: int, document_id: int, db: Session = Depends(get_db)):
    doc = _get_document(db, project_id, document_id)
    if not doc:
        raise HTTPException(404, "需求文档不存在")
    scope = await propose_test_scope(doc.raw_content, get_project_runtime_config(db, project_id))
    doc.test_scope = json.dumps(scope, ensure_ascii=False)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{document_id}/featurelist/export")
def export_document_featurelist(
    project_id: int,
    document_id: int,
    format: str = "xlsx",
    db: Session = Depends(get_db),
):
    doc = _get_document(db, project_id, document_id)
    if not doc:
        raise HTTPException(404, "需求文档不存在")
    items = [
        {
            "module": it.module,
            "feature": it.feature,
            "priority": it.priority,
            "description": it.description,
            "acceptance_criteria": it.acceptance_criteria,
            "constraints": it.constraints,
        }
        for it in sorted(doc.items, key=lambda x: x.sort_order)
    ]
    fmt = "md" if format == "md" else "xlsx"
    content, media_type, ext = export_featurelist(doc.title, items, fmt)
    filename = f"{doc.title or 'featurelist'}-功能清单.{ext}"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(BytesIO(content), media_type=media_type, headers=headers)


@router.post("/featurelist/import", response_model=RequirementDocumentOut, status_code=201)
async def import_featurelist(
    project_id: int,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    db: Session = Depends(get_db),
):
    if not db.query(Project).get(project_id):
        raise HTTPException(404, "项目不存在")

    filename = file.filename or ""
    data = await file.read()
    try:
        items_data = parse_featurelist(filename, data)
    except DocumentParseError as exc:
        raise HTTPException(400, str(exc)) from exc

    doc = RequirementDocument(
        project_id=project_id,
        title=(title or title_from_filename(filename) or "导入的功能清单")[:200],
        raw_content="",
        source_type="featurelist",
        status="structured",
    )
    db.add(doc)
    db.flush()

    for idx, item in enumerate(items_data):
        db.add(RequirementItem(
            document_id=doc.id,
            module=item.get("module", ""),
            feature=item.get("feature", ""),
            description=item.get("description", ""),
            acceptance_criteria=item.get("acceptance_criteria", ""),
            constraints=item.get("constraints", ""),
            priority=item.get("priority", "P1"),
            sort_order=idx,
            confirmed=False,
        ))

    db.commit()
    db.refresh(doc)
    return doc



@router.post("/{document_id}/confirm", response_model=RequirementDocumentOut)
def confirm_document(
    project_id: int,
    document_id: int,
    data: ConfirmRequest = ConfirmRequest(),
    db: Session = Depends(get_db),
):
    doc = (
        db.query(RequirementDocument)
        .options(joinedload(RequirementDocument.items))
        .filter(RequirementDocument.id == document_id, RequirementDocument.project_id == project_id)
        .first()
    )
    if not doc:
        raise HTTPException(404, "需求文档不存在")

    confirm_requirements(db, document_id, data.item_ids)
    db.refresh(doc)
    return doc


@router.post("/{document_id}/items", response_model=RequirementItemOut, status_code=201)
def create_item(
    project_id: int,
    document_id: int,
    data: RequirementItemCreate,
    db: Session = Depends(get_db),
):
    doc = _get_document(db, project_id, document_id)
    if not doc:
        raise HTTPException(404, "需求文档不存在")

    max_order = max((item.sort_order for item in doc.items), default=-1)
    item = RequirementItem(
        document_id=document_id,
        module=data.module,
        feature=data.feature,
        description=data.description,
        acceptance_criteria=data.acceptance_criteria,
        constraints=data.constraints,
        priority=data.priority,
        sort_order=max_order + 1,
        confirmed=False,
    )
    _invalidate_confirmation(db, doc)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{document_id}/items/{item_id}", response_model=RequirementItemOut)
def update_item(
    project_id: int,
    document_id: int,
    item_id: int,
    data: RequirementItemUpdate,
    db: Session = Depends(get_db),
):
    item = (
        db.query(RequirementItem)
        .join(RequirementDocument)
        .filter(
            RequirementItem.id == item_id,
            RequirementDocument.id == document_id,
            RequirementDocument.project_id == project_id,
        )
        .first()
    )
    if not item:
        raise HTTPException(404, "功能点不存在")

    doc = db.get(RequirementDocument, document_id)
    _invalidate_confirmation(db, doc)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{document_id}/items/{item_id}", status_code=204)
def delete_item(project_id: int, document_id: int, item_id: int, db: Session = Depends(get_db)):
    item = (
        db.query(RequirementItem)
        .join(RequirementDocument)
        .filter(
            RequirementItem.id == item_id,
            RequirementDocument.id == document_id,
            RequirementDocument.project_id == project_id,
        )
        .first()
    )
    if not item:
        raise HTTPException(404, "功能点不存在")

    doc = db.get(RequirementDocument, document_id)
    _invalidate_confirmation(db, doc)
    db.delete(item)
    db.commit()
