"""生成失败诊断记录的显式保留期维护。"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.generation import GenerationAttempt, GenerationFailureCandidate


RETENTION_DAYS = 90


def purge_expired_generation_attempts(db: Session, now: datetime | None = None) -> int:
    """清除未被任何失败候选引用的过期尝试记录，并返回删除数。"""
    cutoff = (now or datetime.utcnow()) - timedelta(days=RETENTION_DAYS)
    referenced_attempts = select(GenerationFailureCandidate.final_attempt_id).where(
        GenerationFailureCandidate.final_attempt_id.is_not(None)
    )
    deleted = (
        db.query(GenerationAttempt)
        .filter(
            GenerationAttempt.created_at < cutoff,
            ~GenerationAttempt.id.in_(referenced_attempts),
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted
