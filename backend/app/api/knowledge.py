from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import require_project_access
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.project import Project
from app.schemas import (
    KnowledgeChunkOut,
    KnowledgeDocumentCreate,
    KnowledgeDocumentOut,
    KnowledgeSearchHit,
    KnowledgeSearchRequest,
)
from app.services.document_parser import DocumentParseError, parse_upload, title_from_filename
from app.services.knowledge_service import delete_document_vectors, ingest_document, retrieve

router = APIRouter(
    prefix="/projects/{project_id}/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(require_project_access)],
)


def _get_doc(db: Session, project_id: int, doc_id: int) -> KnowledgeDocument:
    doc = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == doc_id, KnowledgeDocument.project_id == project_id)
        .first()
    )
    if not doc:
        raise HTTPException(404, "知识文档不存在")
    return doc


@router.get("", response_model=list[KnowledgeDocumentOut])
def list_documents(project_id: int, db: Session = Depends(get_db)):
    return (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.project_id == project_id)
        .order_by(KnowledgeDocument.created_at.desc())
        .all()
    )


@router.post("", response_model=KnowledgeDocumentOut, status_code=201)
async def create_document(project_id: int, data: KnowledgeDocumentCreate, db: Session = Depends(get_db)):
    if not db.get(Project, project_id):
        raise HTTPException(404, "项目不存在")

    doc = KnowledgeDocument(
        project_id=project_id,
        title=data.title[:200],
        source_type=data.source_type,
        raw_content=data.content,
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    try:
        await ingest_document(db, doc)
    except Exception as exc:
        raise HTTPException(400, f"知识入库失败：{exc}") from exc
    db.refresh(doc)
    return doc


@router.post("/upload", response_model=KnowledgeDocumentOut, status_code=201)
async def upload_document(
    project_id: int,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    source_type: str = Form("doc"),
    db: Session = Depends(get_db),
):
    if not db.get(Project, project_id):
        raise HTTPException(404, "项目不存在")

    filename = file.filename or ""
    data = await file.read()
    try:
        content, _ = parse_upload(filename, data)
    except DocumentParseError as exc:
        raise HTTPException(400, str(exc)) from exc

    doc = KnowledgeDocument(
        project_id=project_id,
        title=(title or title_from_filename(filename) or "未命名知识")[:200],
        source_type=source_type,
        raw_content=content,
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    try:
        await ingest_document(db, doc)
    except Exception as exc:
        raise HTTPException(400, f"知识入库失败：{exc}") from exc
    db.refresh(doc)
    return doc


@router.get("/{doc_id}/chunks", response_model=list[KnowledgeChunkOut])
def list_chunks(project_id: int, doc_id: int, db: Session = Depends(get_db)):
    _get_doc(db, project_id, doc_id)
    return (
        db.query(KnowledgeChunk)
        .filter(KnowledgeChunk.document_id == doc_id)
        .order_by(KnowledgeChunk.id)
        .all()
    )


@router.delete("/{doc_id}", status_code=204)
def delete_document(project_id: int, doc_id: int, db: Session = Depends(get_db)):
    doc = _get_doc(db, project_id, doc_id)
    delete_document_vectors(doc)
    db.delete(doc)
    db.commit()


@router.post("/search", response_model=list[KnowledgeSearchHit])
async def search_knowledge(project_id: int, data: KnowledgeSearchRequest, db: Session = Depends(get_db)):
    try:
        return await retrieve(db, project_id, data.query, top_k=data.top_k)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
