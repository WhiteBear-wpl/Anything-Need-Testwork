from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import current_user_id
from app.schemas import SettingsTestOut, SettingsTestRequest, SystemSettingsOut, SystemSettingsUpdate
from app.services.llm import test_model_connection
from app.services.settings_service import (
    get_or_create_config,
    runtime_config,
    serialize_settings,
    update_config,
)
from app.services.model_endpoint_security import ModelEndpointError

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SystemSettingsOut)
def get_settings(db: Session = Depends(get_db)):
    row = get_or_create_config(db, current_user_id(db))
    return serialize_settings(row)


@router.patch("", response_model=SystemSettingsOut)
def patch_settings(data: SystemSettingsUpdate, db: Session = Depends(get_db)):
    try:
        row = update_config(db, current_user_id(db), data.model_dump(exclude_unset=True))
    except (ModelEndpointError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return serialize_settings(row)


@router.post("/test", response_model=SettingsTestOut)
async def test_settings(data: SettingsTestRequest, db: Session = Depends(get_db)):
    row = get_or_create_config(db, current_user_id(db))
    return await test_model_connection(runtime_config(row), data.target)
