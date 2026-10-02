import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent.checkpoint import delete_checkpoint
from app.database import get_db
from app.api.deps import current_user_id
from app.models.project import Project
from app.schemas import (
    HomeOverviewOut,
    ProjectCreate,
    ProjectOut,
    ProjectSkillPolicyStateOut,
    ProjectSkillPolicyWrite,
    ProjectStageOut,
    ProjectUpdate,
)
from app.services.knowledge_service import delete_document_vectors
from app.services.project_service import compute_project_stage, get_home_overview
from app.services.skill_policy_service import (
    StaleSkillPolicyRevision,
    get_project_policy_state,
    initialize_project_skill_policies,
    replace_project_policy,
)
from app.skills.policy import ProjectSkillOverride
from app.skills.registry import get_registry

router = APIRouter(prefix="/projects", tags=["projects"])


def _owned_project_or_404(db: Session, project_id: int) -> Project:
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user_id(db),
        Project.is_eval == False,
    ).first()
    if not project:
        raise HTTPException(404, "项目不存在")
    return project


@router.get("/overview", response_model=HomeOverviewOut)
def get_overview(db: Session = Depends(get_db)):
    return get_home_overview(db, current_user_id(db))


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return (
        db.query(Project)
        .filter(Project.user_id == current_user_id(db), Project.is_eval == False)
        .order_by(Project.updated_at.desc())
        .all()
    )


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(
        user_id=current_user_id(db),
        name=data.name,
        description=data.description,
        slug=data.slug,
        base_url=data.base_url,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    initialize_project_skill_policies(
        db,
        project.id,
        actor_id=current_user_id(db),
    )
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user_id(db),
        Project.is_eval == False,
    ).first()
    if not project:
        raise HTTPException(404, "项目不存在")
    return project


@router.get("/{project_id}/stage", response_model=ProjectStageOut)
def get_project_stage(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user_id(db),
        Project.is_eval == False,
    ).first()
    if not project:
        raise HTTPException(404, "项目不存在")
    return compute_project_stage(db, project_id)


@router.get("/{project_id}/skill-policies", response_model=ProjectSkillPolicyStateOut)
def get_skill_policies(project_id: int, db: Session = Depends(get_db)):
    _owned_project_or_404(db, project_id)
    return ProjectSkillPolicyStateOut.model_validate(
        get_project_policy_state(db, project_id).to_api_out()
    )


@router.put("/{project_id}/skill-policies", response_model=ProjectSkillPolicyStateOut)
def put_skill_policies(
    project_id: int,
    data: ProjectSkillPolicyWrite,
    db: Session = Depends(get_db),
):
    _owned_project_or_404(db, project_id)
    overrides = [
        ProjectSkillOverride(
            skill_name=item.skill_name,
            enabled=item.enabled,
            timeout_seconds=item.timeout_seconds,
            max_cases=item.max_cases,
            execution_order=item.execution_order,
            prompt_version=item.prompt_version,
        )
        for item in data.overrides
    ]
    try:
        state = replace_project_policy(
            db,
            project_id,
            overrides,
            base_revision=data.base_revision,
            actor_id=current_user_id(db),
        )
    except StaleSkillPolicyRevision as exc:
        raise HTTPException(409, "Skill 策略已被更新，请刷新后重试") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return ProjectSkillPolicyStateOut.model_validate(state.to_api_out())


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, data: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user_id(db),
        Project.is_eval == False,
    ).first()
    if not project:
        raise HTTPException(404, "项目不存在")
    validated_allowlist = None
    if data.agent_specialist_allowlist is not None:
        try:
            validated_allowlist = get_registry().validate_specialist_selection(
                data.agent_specialist_allowlist,
                strict=True,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if data.name is not None:
        project.name = data.name
    if data.description is not None:
        project.description = data.description
    if data.slug is not None:
        project.slug = data.slug
    if data.base_url is not None:
        project.base_url = data.base_url
    if data.agent_runtime_v2_enabled is not None:
        project.agent_runtime_v2_enabled = data.agent_runtime_v2_enabled
    if validated_allowlist is not None:
        project.agent_specialist_allowlist = json.dumps(validated_allowlist)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user_id(db),
        Project.is_eval == False,
    ).first()
    if not project:
        raise HTTPException(404, "项目不存在")
    # 先清理知识库向量，SQLite 复用主键时残留向量会污染新项目的检索
    for doc in project.knowledge_documents:
        delete_document_vectors(doc)
    checkpoint_thread_id = (
        project.agent_thread.checkpoint_thread_id if project.agent_thread else ""
    )
    db.delete(project)
    db.commit()
    await delete_checkpoint(checkpoint_thread_id)
