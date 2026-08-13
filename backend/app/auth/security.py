from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.base import User
from app.db.session import get_session

PASSWORD_ITERATIONS = 600_000
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"users:read", "users:manage"}),
    "member": frozenset({"workspace:use"}),
}

_bearer = HTTPBearer(auto_error=False)
_current_user_id: ContextVar[UUID | None] = ContextVar("current_user_id", default=None)


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    actual_salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), actual_salt, PASSWORD_ITERATIONS
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(actual_salt).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, _ = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hash_password(
            password, salt=base64.urlsafe_b64decode(salt + "=" * (-len(salt) % 4))
        )
        # Preserve the iteration count stored with the credential.
        if int(iterations) != PASSWORD_ITERATIONS:
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                base64.urlsafe_b64decode(salt + "=" * (-len(salt) % 4)),
                int(iterations),
            )
            expected = encoded.rsplit("$", 1)[1]
            actual = base64.urlsafe_b64encode(digest).decode().rstrip("=")
            return hmac.compare_digest(actual, expected)
        return hmac.compare_digest(candidate, encoded)
    except (ValueError, TypeError):
        return False


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_access_token(user: User, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.auth_token_ttl_minutes)).timestamp()),
    }
    encoded = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(
        settings.auth_secret_key.encode(), encoded.encode(), hashlib.sha256
    ).digest()
    return f"{encoded}.{_b64encode(signature)}"


def decode_access_token(token: str, settings: Settings) -> UUID:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(
            settings.auth_secret_key.encode(), encoded.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_b64decode(signature), expected):
            raise ValueError("invalid signature")
        payload = json.loads(_b64decode(encoded))
        if int(payload["exp"]) <= int(datetime.now(UTC).timestamp()):
            raise ValueError("expired")
        return UUID(payload["sub"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "登录已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = decode_access_token(credentials.credentials, settings)
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在或已停用")
    context_token = _current_user_id.set(user.id)
    try:
        yield user
    finally:
        _current_user_id.reset(context_token)


def current_user_id() -> UUID:
    user_id = _current_user_id.get()
    if user_id is None:
        raise RuntimeError("当前操作缺少用户身份")
    return user_id


def permissions_for(user: User) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(user.role, frozenset()))


def require_permission(permission: str):
    async def dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if permission not in ROLE_PERMISSIONS.get(user.role, frozenset()):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "没有执行此操作的权限")
        return user

    return dependency
