"""持久化用户注册、登录与进程内会话。"""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.services.auth_service import hash_password, normalize_username, verify_password
from app.services.settings_service import new_user_config

router = APIRouter(prefix="/auth", tags=["auth"])


@dataclass(frozen=True)
class AuthSession:
    user_id: int
    username: str
    is_admin: bool
    expires_at: datetime


_active_tokens: dict[str, AuthSession] = {}
_token_lock = Lock()
_failed_logins: dict[str, tuple[int, datetime | None]] = {}
_login_lock = Lock()
_registration_attempts: dict[str, list[datetime]] = {}
_registration_lock = Lock()
_dummy_password_hash = hash_password("wb-dummy-password")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        username = normalize_username(value)
        if not 3 <= len(username) <= 32:
            raise ValueError("用户名需为 3-32 个字符")
        if any(not (char.isalnum() or char in "_-") for char in username):
            raise ValueError("用户名只能包含文字、字母、数字、下划线或短横线")
        return username


class LoginResponse(BaseModel):
    token: str
    user_id: int
    username: str
    is_admin: bool


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _issue_session(user: User) -> LoginResponse:
    token = secrets.token_hex(32)
    session = AuthSession(
        user_id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.auth_token_ttl_hours),
    )
    with _token_lock:
        _active_tokens[token] = session
    return LoginResponse(
        token=token,
        user_id=user.id,
        username=user.username,
        is_admin=user.is_admin,
    )


@router.post("/register", response_model=LoginResponse, status_code=201)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    if not settings.allow_registration:
        raise HTTPException(403, "当前未开放注册")

    now = datetime.now(timezone.utc)
    client_key = _client_key(request)
    cutoff = now - timedelta(hours=1)
    with _registration_lock:
        recent = [t for t in _registration_attempts.get(client_key, []) if t > cutoff]
        if len(recent) >= settings.registration_max_per_hour:
            raise HTTPException(429, "注册过于频繁，请稍后再试")
        recent.append(now)
        _registration_attempts[client_key] = recent

    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(409, "用户名已存在")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        is_admin=False,
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()
        # 与用户同一事务创建空 Key 配置，避免首次访问时的并发初始化竞争。
        db.add(new_user_config(user.id))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "用户名已存在") from exc
    db.refresh(user)
    return _issue_session(user)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    client_key = _client_key(request)
    now = datetime.now(timezone.utc)
    with _login_lock:
        attempts, locked_until = _failed_logins.get(client_key, (0, None))
        if locked_until and locked_until > now:
            retry_after = max(1, int((locked_until - now).total_seconds()))
            raise HTTPException(
                429,
                "登录失败次数过多，请稍后再试",
                headers={"Retry-After": str(retry_after)},
            )
        if locked_until:
            attempts = 0
            _failed_logins.pop(client_key, None)

    username = normalize_username(payload.username)
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    password_ok = verify_password(payload.password, user.password_hash if user else _dummy_password_hash)
    if not user or not password_ok:
        with _login_lock:
            attempts += 1
            locked_until = None
            if attempts >= settings.auth_max_attempts:
                locked_until = now + timedelta(minutes=settings.auth_lockout_minutes)
            _failed_logins[client_key] = (attempts, locked_until)
        raise HTTPException(401, "用户名或密码错误")

    with _login_lock:
        _failed_logins.pop(client_key, None)
    return _issue_session(user)


@router.post("/logout", status_code=204)
def logout(request: Request, payload: dict | None = None):
    token = getattr(request.state, "auth_token", "") or (payload or {}).get("token", "")
    revoke_token(token)


def get_session(token: str) -> AuthSession | None:
    now = datetime.now(timezone.utc)
    with _token_lock:
        session = _active_tokens.get(token)
        if session is None:
            return None
        if session.expires_at <= now:
            _active_tokens.pop(token, None)
            return None
        return session


def is_valid_token(token: str) -> bool:
    return get_session(token) is not None


def revoke_token(token: str) -> None:
    if not token:
        return
    with _token_lock:
        _active_tokens.pop(token, None)
