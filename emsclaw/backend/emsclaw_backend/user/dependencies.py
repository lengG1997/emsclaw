import time
from typing import Optional
from fastapi import Request, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import delete

from emsclaw_backend.db.models import UserSession
from emsclaw_backend.db.session import AsyncSessionLocal
from emsclaw_backend.config import settings

class User(BaseModel):
    id: str
    username: str
    role: str = "user"

async def get_current_user(request: Request) -> Optional[User]:
    """
    Dependency to get current authenticated user from session cookie.
    """
    if getattr(settings, "auth_provider", "local") == "none":
        return User(id="anonymous", username="Anonymous", role="user")

    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        session_id = auth.split(" ", 1)[1].strip()
    else:
        session_id = request.cookies.get(settings.session_cookie)
    if not session_id:
        return None

    # Look up session in PostgreSQL (UserSession.id is the token string)
    async with AsyncSessionLocal() as s:
        session_obj = await s.get(UserSession, session_id)

        if not session_obj:
            return None

        # Optionally check expiration
        if session_obj.expires_at < time.time():
            # Clean up expired session
            await s.execute(delete(UserSession).where(UserSession.id == session_id))
            await s.commit()
            return None

        return User(
            id=str(session_obj.user_id),
            username=session_obj.username,
            role=session_obj.role or "user"
        )

async def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    """
    Dependency to enforce authentication.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
