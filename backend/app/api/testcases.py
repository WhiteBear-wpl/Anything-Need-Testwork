from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import current_user_id, require_project_access
from app.models.project import Project
from app.models.requirement import RequirementDocument, RequirementItem
from app.models.testcase import TestCase
from app.schemas import CatalogRename, CatalogRenameOut, TestCaseOut, TestCaseUpdate

router = APIRouter(prefix="/testcases", tags=["testcases"])
project_router = APIRouter(
    prefix="/projects/{project_id}/testcases",
    tags=["testcases"],
    dependencies=[Depends(require_project_access)],
)


def _serialize_testcase(
    tc: TestCase,
    module: str | None = None,
    feature: str | None = None,
    project_name: str | None = None,
) -> TestCaseOut:
    data = TestCaseOut.model_validate(tc)
    data.module = module or ""
    data.feature = feature or ""
    data.project_name = project_name or ""
    return data


def _query_testcases(db: Session, project_id: int | None = None):
    q = (
        db.query(TestCase, RequirementItem.module, RequirementItem.feature, Project.name)
        .join(Project, TestCase.project_id == Project.id)
        .outerjoin(RequirementItem, TestCase.requirement_item_id == RequirementItem.id)
        .filter(Project.user_id == current_user_id(db), Project.is_eval == False)
    )
    if project_id is not None:
        q = q.filter(TestCase.project_id == project_id)
    return q.order_by(Project.name, RequirementItem.module, RequirementItem.feature, TestCase.created_at.desc())


@router.get("", response_model=list[TestCaseOut])
def list_all_testcases(
    project_id: int | None = Query(None, description="按项目筛选"),
    db: Session = Depends(get_db),
):
    rows = _query_testcases(db, project_id).all()
    return [_serialize_testcase(tc, module, feature, project_name) for tc, module, feature, project_name in rows]


@project_router.get("", response_model=list[TestCaseOut])
def list_testcases(project_id: int, db: Session = Depends(get_db)):
    rows = _query_testcases(db, project_id).all()
    return [_serialize_testcase(tc, module, feature, project_name) for tc, module, feature, project_name in rows]


@project_router.get("/{case_id}", response_model=TestCaseOut)
def get_testcase(project_id: int, case_id: int, db: Session = Depends(get_db)):
    row = (
        _query_testcases(db, project_id)
        .filter(TestCase.id == case_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "用例不存在")
    tc, module, feature, project_name = row
    return _serialize_testcase(tc, module, feature, project_name)


@project_router.patch("/{case_id}", response_model=TestCaseOut)
def update_testcase(
    project_id: int,
    case_id: int,
    data: TestCaseUpdate,
    db: Session = Depends(get_db),
):
    row = (
        _query_testcases(db, project_id)
        .filter(TestCase.id == case_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "用例不存在")

    tc, module, feature, project_name = row
    update_data = data.model_dump(exclude_unset=True)
    module_value = update_data.pop("module", None)
    feature_value = update_data.pop("feature", None)

    for field, value in update_data.items():
        setattr(tc, field, value)

    if module_value is not None or feature_value is not None:
        if not tc.requirement_item_id:
            raise HTTPException(400, "用例未关联需求项，无法修改目录")
        item = db.query(RequirementItem).filter(RequirementItem.id == tc.requirement_item_id).first()
        if not item:
            raise HTTPException(400, "用例未关联需求项，无法修改目录")
        if module_value is not None:
            item.module = module_value
        if feature_value is not None:
            item.feature = feature_value

    db.commit()
    db.refresh(tc)

    row = (
        _query_testcases(db, project_id)
        .filter(TestCase.id == case_id)
        .first()
    )
    tc, module, feature, project_name = row
    return _serialize_testcase(tc, module, feature, project_name)


@project_router.patch("/catalog/rename", response_model=CatalogRenameOut)
def rename_catalog(
    project_id: int,
    data: CatalogRename,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")

    q = (
        db.query(RequirementItem)
        .join(RequirementDocument, RequirementItem.document_id == RequirementDocument.id)
        .filter(RequirementDocument.project_id == project_id, RequirementItem.module == data.old_module)
    )
    if data.type == "feature":
        q = q.filter(RequirementItem.feature == data.old_feature)
        items = q.all()
        for item in items:
            item.feature = data.new_name
    else:
        items = q.all()
        for item in items:
            item.module = data.new_name

    if not items:
        raise HTTPException(404, "未找到可重命名的目录项")

    db.commit()
    return CatalogRenameOut(updated_items=len(items))


@project_router.delete("/{case_id}", status_code=204)
def delete_testcase(project_id: int, case_id: int, db: Session = Depends(get_db)):
    tc = db.query(TestCase).filter(TestCase.id == case_id, TestCase.project_id == project_id).first()
    if not tc:
        raise HTTPException(404, "用例不存在")
    db.delete(tc)
    db.commit()
