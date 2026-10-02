"""当前用户与资源所有权依赖。"""

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project


def current_user_id(db: Session) -> int:
    user_id = db.info.get("user_id")
    if not user_id:
        raise HTTPException(401, "登录已失效，请重新登录")
    return int(user_id)


def require_project_access(project_id: int, db: Session = Depends(get_db)) -> Project:
    project = (
        db.query(Project)
        .filter(
            Project.id == project_id,
            Project.user_id == current_user_id(db),
            Project.is_eval == False,
        )
        .first()
    )
    if not project:
        raise HTTPException(404, "项目不存在")
    return project


def require_admin(db: Session = Depends(get_db)) -> None:
    if not db.info.get("is_admin"):
        raise HTTPException(403, "仅管理员可以访问模型设置")
