from __future__ import annotations

import time
import shortuuid

import bcrypt
from loguru import logger
from sqlalchemy import select

from emsclaw_backend.config import settings
from emsclaw_backend.db.models import User
from emsclaw_backend.db.session import AsyncSessionLocal


async def ensure_admin_user() -> None:
    if not getattr(settings, "bootstrap_admin_enabled", True):
        return

    username = str(getattr(settings, "bootstrap_admin_username", "admin") or "admin").strip()
    password = str(getattr(settings, "bootstrap_admin_password", "admin123") or "admin123")
    fullname = str(getattr(settings, "bootstrap_admin_fullname", "Admin") or "Admin")
    email = str(getattr(settings, "bootstrap_admin_email", "admin@localhost") or "admin@localhost")

    if not username:
        return

    now = int(time.time())
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    async with AsyncSessionLocal() as s:
        existing = (
            await s.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()

        if not existing:
            user_id = str(shortuuid.uuid())
            s.add(User(
                id=user_id,
                username=username,
                password_hash=hashed,
                fullname=fullname,
                email=email,
                role="admin",
                is_active=True,
                created_at=now,
                updated_at=now,
                last_login=0,
            ))
            await s.commit()
            logger.info("Bootstrapped admin user: {}", username)
            return

        if getattr(settings, "bootstrap_update_admin_password", False):
            existing.password_hash = hashed
            existing.fullname = fullname
            existing.email = email
            existing.role = existing.role or "admin"
            existing.is_active = getattr(existing, "is_active", True)
            existing.updated_at = now
            await s.commit()
            logger.info("Updated bootstrapped admin user password: {}", username)
