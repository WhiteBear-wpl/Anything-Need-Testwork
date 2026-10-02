"""用户密码与初始化管理员服务。"""

import hashlib
import hmac
import secrets

from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64


def normalize_username(username: str) -> str:
    return username.strip().casefold()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def ensure_bootstrap_admin(db: Session) -> User:
    """首次启动创建环境变量指定的管理员；后续启动不重置其密码。"""
    username = normalize_username(settings.auth_username)
    user = db.query(User).filter(User.username == username).first()
    if user:
        if not user.is_admin or not user.is_active:
            user.is_admin = True
            user.is_active = True
            db.commit()
            db.refresh(user)
        return user

    user = User(
        username=username,
        password_hash=hash_password(settings.auth_password),
        is_admin=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
