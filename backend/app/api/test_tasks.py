from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_project_access
from app.database import get_db
from app.models.execution import TestBatch, TestBatchCase, TestTask
from app.models.generation import GeneratedCaseDraft
from app.models.requirement import RequirementItem
from app.models.testcase import TestCase
from app.schemas import (
    BatchCaseBatchMark,
    BatchCaseMark,
    BatchCaseOut,
    BatchCasesAdd,
    DefectItemOut,
    TestBatchCreate,
    TestBatchDetailOut,
    TestBatchOut,
    TestBatchUpdate,
    TestTaskCreate,
    TestTaskOut,
    TestTaskUpdate,
)

router = APIRouter(
    prefix="/projects/{project_id}/tasks",
    tags=["test-tasks"],
    dependencies=[Depends(require_project_access)],
)


def _serialize_task(task: TestTask) -> TestTaskOut:
    return TestTaskOut.model_validate(task)


def _get_task(db: Session, project_id: int, task_id: int) -> TestTask:
    task = (
        db.query(TestTask)
        .filter(TestTask.id == task_id, TestTask.project_id == project_id)
        .first()
    )
    if not task:
        raise HTTPException(404, "测试任务不存在")
    return task


def _get_batch(db: Session, project_id: int, task_id: int, batch_id: int) -> TestBatch:
    task = _get_task(db, project_id, task_id)
    batch = next((b for b in task.batches if b.id == batch_id), None)
    if not batch:
        raise HTTPException(404, "批次不存在")
    return batch


def _resolve_case_ids_by_selection(db: Session, project_id: int, case_ids: list[int]) -> list[int]:
    rows = (
        db.query(TestCase.id)
        .filter(TestCase.project_id == project_id, TestCase.id.in_(case_ids))
        .all()
    )
    ids = [r[0] for r in rows]
    if len(ids) != len(set(case_ids)):
        raise HTTPException(400, "部分用例不存在或不属于该项目")
    return ids


def _resolve_case_ids(db: Session, project_id: int, data: TestTaskCreate) -> list[int]:
    """确定任务包含的用例：手动圈选或从生成任务导入已入库用例。"""
    if data.case_ids:
        return _resolve_case_ids_by_selection(db, project_id, data.case_ids)

    rows = (
        db.query(TestCase.id)
        .join(GeneratedCaseDraft, TestCase.draft_id == GeneratedCaseDraft.id)
        .filter(
            TestCase.project_id == project_id,
            GeneratedCaseDraft.task_id == data.source_task_id,
        )
        .all()
    )
    ids = [r[0] for r in rows]
    if not ids:
        raise HTTPException(400, "该生成任务没有已入库的用例，请先在评审中采纳用例")
    return ids


@router.post("", response_model=TestTaskOut)
def create_task(project_id: int, data: TestTaskCreate, db: Session = Depends(get_db)):
    case_ids = _resolve_case_ids(db, project_id, data)
    task = TestTask(project_id=project_id, name=data.name, description=data.description)
    batch = TestBatch(name=data.batch_name)
    batch.batch_cases = [TestBatchCase(case_id=cid) for cid in case_ids]
    task.batches = [batch]
    db.add(task)
    db.commit()
    db.refresh(task)
    return _serialize_task(task)


@router.get("", response_model=list[TestTaskOut])
def list_tasks(project_id: int, db: Session = Depends(get_db)):
    tasks = (
        db.query(TestTask)
        .options(selectinload(TestTask.batches).selectinload(TestBatch.batch_cases))
        .filter(TestTask.project_id == project_id)
        .order_by(TestTask.created_at.desc())
        .all()
    )
    return [_serialize_task(task) for task in tasks]


@router.get("/{task_id}", response_model=TestTaskOut)
def get_task(project_id: int, task_id: int, db: Session = Depends(get_db)):
    return _serialize_task(_get_task(db, project_id, task_id))


@router.patch("/{task_id}", response_model=TestTaskOut)
def update_task(project_id: int, task_id: int, data: TestTaskUpdate, db: Session = Depends(get_db)):
    task = _get_task(db, project_id, task_id)
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return _serialize_task(task)


@router.delete("/{task_id}", status_code=204)
def delete_task(project_id: int, task_id: int, db: Session = Depends(get_db)):
    task = _get_task(db, project_id, task_id)
    db.delete(task)
    db.commit()


@router.get("/{task_id}/defects", response_model=list[DefectItemOut])
def list_defects(
    project_id: int,
    task_id: int,
    include_blocked: bool = Query(False),
    db: Session = Depends(get_db),
):
    """任务级缺陷列表：聚合所有批次中失败（可选含阻塞）的执行记录。"""
    _get_task(db, project_id, task_id)
    results = ["failed", "blocked"] if include_blocked else ["failed"]
    rows = (
        db.query(TestBatchCase, TestBatch, TestCase, RequirementItem.module, RequirementItem.feature)
        .join(TestBatch, TestBatchCase.batch_id == TestBatch.id)
        .join(TestCase, TestBatchCase.case_id == TestCase.id)
        .outerjoin(RequirementItem, TestCase.requirement_item_id == RequirementItem.id)
        .filter(TestBatch.task_id == task_id, TestBatchCase.result.in_(results))
        .order_by(TestBatchCase.executed_at.desc())
        .all()
    )
    return [
        DefectItemOut(
            batch_case_id=bc.id,
            batch_id=batch.id,
            batch_name=batch.name,
            case_id=tc.id,
            title=tc.title,
            priority=tc.priority,
            module=module or "",
            feature=feature or "",
            result=bc.result,
            note=bc.note,
            defect_ref=bc.defect_ref,
            executed_at=bc.executed_at,
        )
        for bc, batch, tc, module, feature in rows
    ]


@router.post("/{task_id}/batches", response_model=TestTaskOut)
def create_batch(project_id: int, task_id: int, data: TestBatchCreate, db: Session = Depends(get_db)):
    task = _get_task(db, project_id, task_id)
    if data.copy_from_batch_id is not None:
        source = next((b for b in task.batches if b.id == data.copy_from_batch_id), None)
        if not source:
            raise HTTPException(400, "要复用的批次不存在")
        case_ids = [bc.case_id for bc in source.batch_cases]
        if not case_ids:
            raise HTTPException(400, "要复用的批次没有用例")
    else:
        case_ids = _resolve_case_ids_by_selection(db, project_id, data.case_ids)

    batch = TestBatch(name=data.name)
    batch.batch_cases = [TestBatchCase(case_id=cid) for cid in case_ids]
    task.batches.append(batch)
    db.commit()
    db.refresh(task)
    return _serialize_task(task)


@router.get("/{task_id}/batches/{batch_id}", response_model=TestBatchDetailOut)
def get_batch(project_id: int, task_id: int, batch_id: int, db: Session = Depends(get_db)):
    batch = _get_batch(db, project_id, task_id, batch_id)
    rows = (
        db.query(TestBatchCase, TestCase, RequirementItem.module, RequirementItem.feature)
        .join(TestCase, TestBatchCase.case_id == TestCase.id)
        .outerjoin(RequirementItem, TestCase.requirement_item_id == RequirementItem.id)
        .filter(TestBatchCase.batch_id == batch_id)
        .order_by(RequirementItem.module, RequirementItem.feature, TestCase.created_at.desc())
        .all()
    )
    detail = TestBatchDetailOut.model_validate(batch)
    detail.cases = [
        BatchCaseOut(
            id=bc.id,
            case_id=tc.id,
            title=tc.title,
            priority=tc.priority,
            case_type=tc.case_type,
            is_smoke=tc.is_smoke,
            precondition=tc.precondition,
            steps=tc.steps,
            expected_result=tc.expected_result,
            module=module or "",
            feature=feature or "",
            result=bc.result,
            note=bc.note,
            defect_ref=bc.defect_ref,
            executed_at=bc.executed_at,
        )
        for bc, tc, module, feature in rows
    ]
    return detail


@router.patch("/{task_id}/batches/{batch_id}", response_model=TestBatchOut)
def update_batch(
    project_id: int, task_id: int, batch_id: int, data: TestBatchUpdate, db: Session = Depends(get_db)
):
    batch = _get_batch(db, project_id, task_id, batch_id)
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(batch, field, value)
    db.commit()
    db.refresh(batch)
    return TestBatchOut.model_validate(batch)


@router.delete("/{task_id}/batches/{batch_id}", status_code=204)
def delete_batch(project_id: int, task_id: int, batch_id: int, db: Session = Depends(get_db)):
    batch = _get_batch(db, project_id, task_id, batch_id)
    if len(batch.task.batches) <= 1:
        raise HTTPException(400, "任务至少保留一个批次，如需删除请直接删除任务")
    db.delete(batch)
    db.commit()


def _apply_mark(bc: TestBatchCase, result: str, note: str = "", defect_ref: str = "") -> None:
    bc.result = result
    bc.note = note
    bc.defect_ref = defect_ref
    bc.executed_at = datetime.now() if result != "pending" else None


@router.patch("/{task_id}/batches/{batch_id}/cases/batch", response_model=TestBatchOut)
def batch_mark_cases(
    project_id: int, task_id: int, batch_id: int, data: BatchCaseBatchMark, db: Session = Depends(get_db)
):
    batch = _get_batch(db, project_id, task_id, batch_id)
    batch_cases = {bc.id: bc for bc in batch.batch_cases}
    missing = [bid for bid in data.batch_case_ids if bid not in batch_cases]
    if missing:
        raise HTTPException(400, "部分执行记录不属于该批次")
    for bid in data.batch_case_ids:
        bc = batch_cases[bid]
        # 批量标记不覆盖已有备注与缺陷号
        _apply_mark(bc, data.result, bc.note, bc.defect_ref)
    db.commit()
    db.refresh(batch)
    return TestBatchOut.model_validate(batch)


@router.patch("/{task_id}/batches/{batch_id}/cases/{batch_case_id}", response_model=TestBatchOut)
def mark_case(
    project_id: int,
    task_id: int,
    batch_id: int,
    batch_case_id: int,
    data: BatchCaseMark,
    db: Session = Depends(get_db),
):
    batch = _get_batch(db, project_id, task_id, batch_id)
    bc = next((c for c in batch.batch_cases if c.id == batch_case_id), None)
    if not bc:
        raise HTTPException(404, "执行记录不存在")
    _apply_mark(bc, data.result, data.note, data.defect_ref)
    db.commit()
    db.refresh(batch)
    return TestBatchOut.model_validate(batch)


@router.post("/{task_id}/batches/{batch_id}/cases", response_model=TestBatchOut)
def add_cases(
    project_id: int, task_id: int, batch_id: int, data: BatchCasesAdd, db: Session = Depends(get_db)
):
    batch = _get_batch(db, project_id, task_id, batch_id)
    valid_ids = set(_resolve_case_ids_by_selection(db, project_id, data.case_ids))
    existing = {bc.case_id for bc in batch.batch_cases}
    for cid in valid_ids - existing:
        batch.batch_cases.append(TestBatchCase(case_id=cid))
    db.commit()
    db.refresh(batch)
    return TestBatchOut.model_validate(batch)


@router.delete("/{task_id}/batches/{batch_id}/cases/{batch_case_id}", response_model=TestBatchOut)
def remove_case(
    project_id: int, task_id: int, batch_id: int, batch_case_id: int, db: Session = Depends(get_db)
):
    batch = _get_batch(db, project_id, task_id, batch_id)
    bc = next((c for c in batch.batch_cases if c.id == batch_case_id), None)
    if not bc:
        raise HTTPException(404, "执行记录不存在")
    db.delete(bc)
    db.commit()
    db.refresh(batch)
    return TestBatchOut.model_validate(batch)
