from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import AdminUserCreate, AdminUserPatch, AuthTokenOut, LoginRequest, UserOut
from app.auth.security import (
    create_access_token,
    get_current_user,
    hash_password,
    permissions_for,
    require_permission,
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


@router.get("/admin/users", response_model=list[UserOut])
async def admin_users(
    session: SessionDep,
    _: Annotated[User, Depends(require_permission("users:read"))],
    q: str | None = None,
) -> list[UserOut]:
    query = select(User).order_by(User.created_at.desc())
    if q:
        term = f"%{q.strip()}%"
        query = query.where(User.phone.ilike(term) | User.display_name.ilike(term))
    return [_user_out(user) for user in (await session.scalars(query)).all()]


@router.post("/admin/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def admin_create_user(
    payload: AdminUserCreate,
    session: SessionDep,
    _: Annotated[User, Depends(require_permission("users:manage"))],
) -> UserOut:
    if await session.scalar(select(User).where(User.phone == payload.phone)):
        raise HTTPException(status.HTTP_409_CONFLICT, "手机号已存在")
    user = User(
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        role=payload.role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return _user_out(user)


@router.patch("/admin/users/{user_id}", response_model=UserOut)
async def admin_patch_user(
    user_id: UUID,
    payload: AdminUserPatch,
    session: SessionDep,
    actor: Annotated[User, Depends(require_permission("users:manage"))],
) -> UserOut:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if target.id == actor.id and payload.is_active is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能停用当前账号")
    if target.id == actor.id and payload.role == "member":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能降级当前管理员账号")
    if payload.display_name is not None:
        target.display_name = payload.display_name
    if payload.role is not None:
        target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active
    if payload.password:
        target.password_hash = hash_password(payload.password)
    await session.commit()
    await session.refresh(target)
    return _user_out(target)
