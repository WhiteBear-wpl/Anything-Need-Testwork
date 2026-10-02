from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.project import Project
from app.models.system_config import SystemConfig
from app.services.model_endpoint_security import validate_model_base_url


@dataclass(frozen=True)
class RuntimeModelConfig:
    """一次模型调用链使用的不可变配置，避免并发请求互相覆盖 API Key。"""

    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_mock_mode: bool = False
    eval_llm_api_key: str = ""
    eval_llm_base_url: str = ""
    eval_llm_model: str = ""
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = ""
    rerank_api_key: str = ""
    rerank_base_url: str = ""
    rerank_model: str = ""

    @property
    def use_mock_llm(self) -> bool:
        return self.llm_mock_mode or not self.llm_api_key

    @property
    def rerank_configured(self) -> bool:
        return bool(self.rerank_base_url and self.rerank_api_key and self.rerank_model)


def runtime_config(row: SystemConfig) -> RuntimeModelConfig:
    return RuntimeModelConfig(
        llm_api_key=row.llm_api_key or "",
        llm_base_url=row.llm_base_url or "",
        llm_model=row.llm_model or "",
        llm_mock_mode=bool(row.llm_mock_mode),
        eval_llm_api_key=row.eval_llm_api_key or "",
        eval_llm_base_url=row.eval_llm_base_url or "",
        eval_llm_model=row.eval_llm_model or "",
        embedding_api_key=row.embedding_api_key or "",
        embedding_base_url=row.embedding_base_url or "",
        embedding_model=row.embedding_model or "",
        rerank_api_key=row.rerank_api_key or "",
        rerank_base_url=row.rerank_base_url or "",
        rerank_model=row.rerank_model or "",
    )


def new_user_config(user_id: int) -> SystemConfig:
    """创建不含任何密钥的用户配置，可继承部署环境中的非敏感模型元数据。"""
    return SystemConfig(
        user_id=user_id,
        llm_api_key="",
        llm_base_url=settings.llm_base_url,
        llm_model=settings.llm_model,
        llm_mock_mode=False,
        eval_llm_api_key="",
        eval_llm_base_url="",
        eval_llm_model="",
        embedding_api_key="",
        embedding_base_url=settings.embedding_base_url,
        embedding_model=settings.embedding_model,
        rerank_api_key="",
        rerank_base_url=settings.rerank_base_url,
        rerank_model=settings.rerank_model,
    )


def get_or_create_config(db: Session, user_id: int) -> SystemConfig:
    row = db.query(SystemConfig).filter(SystemConfig.user_id == user_id).first()
    if row:
        return row

    row = new_user_config(user_id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # 同一用户首次并发进入设置/生成页时，唯一索引只允许一个配置行。
        db.rollback()
        row = db.query(SystemConfig).filter(SystemConfig.user_id == user_id).first()
        if not row:
            raise
    db.refresh(row)
    return row


def ensure_bootstrap_admin_config(db: Session, admin_user_id: int) -> SystemConfig:
    """仅在管理员没有历史配置时，用部署环境配置初始化管理员。"""
    row = db.query(SystemConfig).filter(SystemConfig.user_id == admin_user_id).first()
    if row:
        return row

    eval_config = (settings.eval_llm_base_url, settings.eval_llm_api_key, settings.eval_llm_model)
    if not all(eval_config):
        eval_config = ("", "", "")

    row = SystemConfig(
        user_id=admin_user_id,
        llm_api_key=settings.llm_api_key,
        llm_base_url=settings.llm_base_url,
        llm_model=settings.llm_model,
        llm_mock_mode=settings.llm_mock_mode,
        eval_llm_api_key=eval_config[1],
        eval_llm_base_url=eval_config[0],
        eval_llm_model=eval_config[2],
        embedding_api_key=settings.embedding_api_key,
        embedding_base_url=settings.embedding_base_url,
        embedding_model=settings.embedding_model,
        rerank_api_key=settings.rerank_api_key,
        rerank_base_url=settings.rerank_base_url,
        rerank_model=settings.rerank_model,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_user_runtime_config(db: Session, user_id: int) -> RuntimeModelConfig:
    return runtime_config(get_or_create_config(db, user_id))


def get_project_runtime_config(db: Session, project_id: int) -> RuntimeModelConfig:
    user_id = db.query(Project.user_id).filter(Project.id == project_id).scalar()
    if not user_id:
        raise RuntimeError("项目不存在或未关联用户")
    return get_user_runtime_config(db, int(user_id))


def mask_api_key(key: str) -> tuple[bool, str]:
    if not key:
        return False, ""
    if len(key) <= 4:
        return True, "****"
    return True, f"{'*' * 8}{key[-4:]}"


def serialize_settings(row: SystemConfig) -> dict:
    key_set, key_masked = mask_api_key(row.llm_api_key)
    eval_key_set, eval_key_masked = mask_api_key(row.eval_llm_api_key)
    emb_key_set, emb_key_masked = mask_api_key(row.embedding_api_key)
    rerank_key_set, rerank_key_masked = mask_api_key(row.rerank_api_key)
    config = runtime_config(row)
    return {
        "llm_api_key_set": key_set,
        "llm_api_key_masked": key_masked,
        "llm_base_url": row.llm_base_url,
        "llm_model": row.llm_model,
        "llm_mock_mode": row.llm_mock_mode,
        "use_mock_llm": config.use_mock_llm,
        "eval_llm_api_key_set": eval_key_set,
        "eval_llm_api_key_masked": eval_key_masked,
        "eval_llm_base_url": row.eval_llm_base_url,
        "eval_llm_model": row.eval_llm_model,
        "embedding_api_key_set": emb_key_set,
        "embedding_api_key_masked": emb_key_masked,
        "embedding_base_url": row.embedding_base_url,
        "embedding_model": row.embedding_model,
        "rerank_api_key_set": rerank_key_set,
        "rerank_api_key_masked": rerank_key_masked,
        "rerank_base_url": row.rerank_base_url,
        "rerank_model": row.rerank_model,
    }


def update_config(db: Session, user_id: int, data: dict) -> SystemConfig:
    row = get_or_create_config(db, user_id)

    for field in ("llm_base_url", "eval_llm_base_url", "embedding_base_url", "rerank_base_url"):
        if field in data and data[field] is not None:
            data[field] = validate_model_base_url(data[field])

    final_eval = (
        data.get("eval_llm_base_url", row.eval_llm_base_url),
        data.get("eval_llm_api_key", row.eval_llm_api_key),
        data.get("eval_llm_model", row.eval_llm_model),
    )
    if any(final_eval) and not all(final_eval):
        raise ValueError("评测专用模型需同时填写 API 地址、模型和 Key；三项全部留空则复用生成模型")

    final_rerank = (
        data.get("rerank_base_url", row.rerank_base_url),
        data.get("rerank_api_key", row.rerank_api_key),
        data.get("rerank_model", row.rerank_model),
    )
    if any(final_rerank) and not all(final_rerank):
        raise ValueError("Rerank 模型需同时填写 API 地址、模型和 Key；三项全部留空则不启用精排")

    if "llm_api_key" in data and data["llm_api_key"] is not None:
        row.llm_api_key = data["llm_api_key"]
    if data.get("llm_base_url") is not None:
        row.llm_base_url = data["llm_base_url"]
    if data.get("llm_model") is not None:
        row.llm_model = data["llm_model"]
    if data.get("llm_mock_mode") is not None:
        row.llm_mock_mode = data["llm_mock_mode"]
    if "eval_llm_api_key" in data and data["eval_llm_api_key"] is not None:
        row.eval_llm_api_key = data["eval_llm_api_key"]
    if data.get("eval_llm_base_url") is not None:
        row.eval_llm_base_url = data["eval_llm_base_url"]
    if data.get("eval_llm_model") is not None:
        row.eval_llm_model = data["eval_llm_model"]
    if "embedding_api_key" in data and data["embedding_api_key"] is not None:
        row.embedding_api_key = data["embedding_api_key"]
    if data.get("embedding_base_url") is not None:
        row.embedding_base_url = data["embedding_base_url"]
    if data.get("embedding_model") is not None:
        row.embedding_model = data["embedding_model"]
    if "rerank_api_key" in data and data["rerank_api_key"] is not None:
        row.rerank_api_key = data["rerank_api_key"]
    if data.get("rerank_base_url") is not None:
        row.rerank_base_url = data["rerank_base_url"]
    if data.get("rerank_model") is not None:
        row.rerank_model = data["rerank_model"]

    db.commit()
    db.refresh(row)
    return row
