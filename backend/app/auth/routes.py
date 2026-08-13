from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import AuthTokenOut, LoginRequest, UserOut
from app.auth.security import (
    create_access_token,
    get_current_user,
    permissions_for,
    verify_password,
)
from app.core.config import Settings, get_settings
from app.db.base import User
from app.db.session import get_session

router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        phone=user.phone,
        display_name=user.display_name,
        role=user.role,
        permissions=permissions_for(user),
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.post("/auth/login", response_model=AuthTokenOut)
async def login(payload: LoginRequest, session: SessionDep, settings: SettingsDep) -> AuthTokenOut:
    user = await session.scalar(select(User).where(User.phone == payload.phone))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "手机号或密码错误")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已停用，请联系管理员")
    return AuthTokenOut(
        access_token=create_access_token(user, settings),
        expires_in=settings.auth_token_ttl_minutes * 60,
        user=_user_out(user),
    )


@router.get("/auth/me", response_model=UserOut)
async def me(user: CurrentUserDep) -> UserOut:
    return _user_out(user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(_: CurrentUserDep) -> None:
    # Access tokens are short-lived and stateless; the client discards its token.
    return None
