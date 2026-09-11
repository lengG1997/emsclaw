from __future__ import annotations

import time
import shortuuid
import secrets
from typing import Any, Optional
from datetime import datetime

from fastapi import APIRouter, Response, Request, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
import bcrypt

from emsclaw_backend.db.models import User, UserSession
from emsclaw_backend.db.session import AsyncSessionLocal
from emsclaw_backend.config import settings
from emsclaw_backend.user.dependencies import get_current_user, require_user

router = APIRouter(prefix="/auth", tags=["auth"])

class ApiResponse(BaseModel):
    code: int = Field(default=0, description="业务状态码，0 表示成功")
    msg: str = Field(default="ok", description="业务消息")
    data: Any = Field(default=None, description="返回数据")

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    fullname: str
    email: str
    password: str
    username: Optional[str] = None

class AuthUser(BaseModel):
    id: str
    fullname: str
    email: str
    role: str = "user"
    is_active: bool = True
    created_at: str = ""
    updated_at: str = ""
    last_login_at: Optional[str] = None

class AuthStatusData(BaseModel):
    authenticated: bool
    auth_provider: str = "local"
    user: Optional[AuthUser] = None


class TokenResponse(BaseModel):
    user: AuthUser
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ChangeFullnameRequest(BaseModel):
    fullname: str


def _to_str_ts(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        if not v:
            return ""
        return datetime.fromtimestamp(int(v)).isoformat()
    return str(v)


def _user_to_auth_user(user_obj: Optional[User]) -> AuthUser:
    """Convert a User ORM instance to AuthUser (preserves original return shape)."""
    if user_obj is None:
        return AuthUser(id="", fullname="", email="", role="user")
    last_login = getattr(user_obj, "last_login", None)
    return AuthUser(
        id=str(user_obj.id or ""),
        fullname=str(user_obj.fullname or user_obj.username or ""),
        email=str(user_obj.email or ""),
        role=str(user_obj.role or "user"),
        is_active=bool(getattr(user_obj, "is_active", True)),
        created_at=_to_str_ts(user_obj.created_at),
        updated_at=_to_str_ts(user_obj.updated_at),
        last_login_at=_to_str_ts(last_login) if last_login else None,
    )


def _auth_user_from_partial(user_id: str, **fields: Any) -> AuthUser:
    """Build an AuthUser from partial fields (mirrors original fallback dicts)."""
    return AuthUser(
        id=str(user_id or ""),
        fullname=str(fields.get("fullname") or fields.get("username") or ""),
        email=str(fields.get("email") or ""),
        role=str(fields.get("role") or "user"),
        created_at="",
        updated_at="",
        last_login_at=None,
    )


@router.get("/check-default-password", response_model=ApiResponse)
async def check_default_password() -> ApiResponse:
    """Check whether the bootstrap admin account still uses the default password."""
    username = str(getattr(settings, "bootstrap_admin_username", "admin") or "admin").strip()
    default_pwd = str(getattr(settings, "bootstrap_admin_password", "admin123") or "admin123")

    async with AsyncSessionLocal() as s:
        user_obj = (
            await s.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if not user_obj:
            return ApiResponse(data={"is_default": False})

        stored_hash = user_obj.password_hash
        if not stored_hash:
            return ApiResponse(data={"is_default": False})

        if isinstance(stored_hash, str):
            stored_hash = stored_hash.encode("utf-8")

        is_default = bcrypt.checkpw(default_pwd.encode("utf-8"), stored_hash)
    return ApiResponse(data={"is_default": is_default, "username": username, "password": default_pwd if is_default else None})


@router.post("/login", response_model=ApiResponse)
async def login(body: LoginRequest, response: Response):
    async with AsyncSessionLocal() as s:
        user_obj = (
            await s.execute(select(User).where(User.username == body.username))
        ).scalar_one_or_none()
        if not user_obj:
            return ApiResponse(code=401, msg="Invalid username or password")

        # Check password
        stored_hash = user_obj.password_hash
        if isinstance(stored_hash, str):
            stored_hash = stored_hash.encode('utf-8')

        if not bcrypt.checkpw(body.password.encode('utf-8'), stored_hash):
            return ApiResponse(code=401, msg="Invalid username or password")

        if not getattr(user_obj, "is_active", True):
            return ApiResponse(code=403, msg="User is deactivated")

        # Create session tokens (access_token is a session id)
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(48)
        expires_at = int(time.time()) + settings.session_max_age
        refresh_expires_at = int(time.time()) + settings.session_max_age * 4

        s.add(UserSession(
            id=access_token,
            user_id=str(user_obj.id),
            username=user_obj.username,
            role=str(user_obj.role or "user"),
            expires_at=expires_at,
            refresh_token=refresh_token,
            refresh_expires_at=refresh_expires_at,
        ))

        now = int(time.time())
        user_obj.last_login = now
        user_obj.updated_at = now
        await s.commit()

        auth_user = _user_to_auth_user(user_obj)

    # Set cookie
    response.set_cookie(
        key=settings.session_cookie,
        value=access_token,
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.https_only,
        samesite="lax"
    )

    return ApiResponse(
        data=TokenResponse(
            user=auth_user,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer",
        ).model_dump()
    )

@router.post("/register", response_model=ApiResponse)
async def register(body: RegisterRequest):
    username = (body.username or body.email or "").strip()
    if not username:
        return ApiResponse(code=400, msg="Username/email required")

    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(body.password.encode('utf-8'), salt).decode('utf-8')

    user_id = str(shortuuid.uuid())
    now = int(time.time())

    new_user = User(
        id=user_id,
        username=username,
        password_hash=hashed,
        fullname=body.fullname or username,
        email=body.email,
        role="user",
        is_active=True,
        created_at=now,
        updated_at=now,
        last_login=0,
    )

    async with AsyncSessionLocal() as s:
        # Pre-check to preserve existing 400 error behavior
        existing = (
            await s.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if existing:
            return ApiResponse(code=400, msg="Username already exists")

        s.add(new_user)
        try:
            await s.commit()
        except IntegrityError:
            await s.rollback()
            return ApiResponse(code=400, msg="Username already exists")

        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(48)
        expires_at = int(time.time()) + settings.session_max_age
        refresh_expires_at = int(time.time()) + settings.session_max_age * 4
        s.add(UserSession(
            id=access_token,
            user_id=user_id,
            username=username,
            role="user",
            expires_at=expires_at,
            refresh_token=refresh_token,
            refresh_expires_at=refresh_expires_at,
        ))
        await s.commit()

    return ApiResponse(
        data=TokenResponse(
            user=_user_to_auth_user(new_user),
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer",
        ).model_dump()
    )

@router.get("/status", response_model=ApiResponse)
async def get_auth_status(current_user: Optional[User] = Depends(get_current_user)) -> ApiResponse:
    auth_provider = getattr(settings, "auth_provider", "local")
    if auth_provider == "none":
        return ApiResponse(
            data=AuthStatusData(
                authenticated=True,
                auth_provider="none",
                user=AuthUser(
                    id="anonymous",
                    fullname="Anonymous User",
                    email="anonymous@localhost",
                    role="user",
                    is_active=True,
                    created_at="",
                    updated_at="",
                    last_login_at=None,
                ),
            ).model_dump()
        )

    if not current_user:
        return ApiResponse(data=AuthStatusData(authenticated=False, auth_provider=auth_provider).model_dump())

    async with AsyncSessionLocal() as s:
        user_obj = await s.get(User, str(current_user.id))
        if user_obj:
            user = _user_to_auth_user(user_obj)
        else:
            user = _auth_user_from_partial(
                current_user.id,
                username=current_user.username,
                email="",
                role=current_user.role,
            )
    return ApiResponse(data=AuthStatusData(authenticated=True, auth_provider=auth_provider, user=user).model_dump())


@router.get("/me", response_model=ApiResponse)
async def me(current_user: User = Depends(require_user)) -> ApiResponse:
    async with AsyncSessionLocal() as s:
        user_obj = await s.get(User, str(current_user.id))
        if not user_obj:
            raise HTTPException(status_code=404, detail="User not found")
        auth_user = _user_to_auth_user(user_obj)
    return ApiResponse(data=auth_user.model_dump())


@router.post("/refresh", response_model=ApiResponse)
async def refresh(body: RefreshTokenRequest) -> ApiResponse:
    async with AsyncSessionLocal() as s:
        doc = (
            await s.execute(
                select(UserSession).where(UserSession.refresh_token == body.refresh_token)
            )
        ).scalar_one_or_none()
        if not doc:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        if int(doc.refresh_expires_at or 0) < int(time.time()):
            await s.execute(delete(UserSession).where(UserSession.id == doc.id))
            await s.commit()
            raise HTTPException(status_code=401, detail="Refresh token expired")

        old_session_id = doc.id
        await s.execute(delete(UserSession).where(UserSession.id == old_session_id))

        access_token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + settings.session_max_age
        s.add(UserSession(
            id=access_token,
            user_id=str(doc.user_id),
            username=str(doc.username),
            role=str(doc.role or "user"),
            expires_at=expires_at,
            refresh_token=body.refresh_token,
            refresh_expires_at=int(doc.refresh_expires_at or 0),
        ))
        await s.commit()

    return ApiResponse(data=RefreshTokenResponse(access_token=access_token, token_type="Bearer").model_dump())


@router.post("/change-password", response_model=ApiResponse)
async def change_password(body: ChangePasswordRequest, current_user: User = Depends(require_user)) -> ApiResponse:
    async with AsyncSessionLocal() as s:
        user_obj = await s.get(User, str(current_user.id))
        if not user_obj:
            raise HTTPException(status_code=404, detail="User not found")

        stored_hash = user_obj.password_hash
        if isinstance(stored_hash, str):
            stored_hash = stored_hash.encode("utf-8")
        if not stored_hash or not bcrypt.checkpw(body.old_password.encode("utf-8"), stored_hash):
            raise HTTPException(status_code=400, detail="Invalid old password")

        user_obj.password_hash = bcrypt.hashpw(body.new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        user_obj.updated_at = int(time.time())
        await s.commit()
    return ApiResponse(data={"ok": True})


@router.post("/change-fullname", response_model=ApiResponse)
async def change_fullname(body: ChangeFullnameRequest, current_user: User = Depends(require_user)) -> ApiResponse:
    fullname = (body.fullname or "").strip()
    if not fullname:
        raise HTTPException(status_code=400, detail="fullname required")

    async with AsyncSessionLocal() as s:
        user_obj = await s.get(User, str(current_user.id))
        if user_obj:
            user_obj.fullname = fullname
            user_obj.updated_at = int(time.time())
            await s.commit()
            auth_user = _user_to_auth_user(user_obj)
        else:
            auth_user = _auth_user_from_partial(
                current_user.id,
                fullname=fullname,
                email="",
                role=current_user.role,
            )
    return ApiResponse(data=auth_user.model_dump())

@router.post("/logout", response_model=ApiResponse)
async def logout(request: Request, response: Response):
    session_id = request.cookies.get(settings.session_cookie)
    if session_id:
        async with AsyncSessionLocal() as s:
            await s.execute(delete(UserSession).where(UserSession.id == session_id))
            await s.commit()

    response.delete_cookie(settings.session_cookie)
    return ApiResponse(data={"ok": True})
