from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import shortuuid
from sqlalchemy import select, update

from emsclaw_backend.deepagent.sessions import async_create_agent_session, async_get_agent_session
from emsclaw_backend.db.models import IMChatSession as IMChatSessionRow
from emsclaw_backend.db.models import Session as SessionRow
from emsclaw_backend.db.session import AsyncSessionLocal
from emsclaw_backend.im.base import IMPlatform
from emsclaw_backend.notifications import publish as notify


@dataclass
class IMChatSession:
    id: str
    platform: IMPlatform
    platform_chat_id: str
    agent_user_id: str
    agent_session_id: str
    created_at: int
    updated_at: int
    status: str = "active"


class IMChatSessionRepo:
    def __init__(self):
        self.model = IMChatSessionRow

    async def get_active_session(
        self,
        platform: IMPlatform,
        platform_chat_id: str,
        user_id: str,
    ) -> Optional[IMChatSession]:
        async with AsyncSessionLocal() as s:
            row = (
                await s.execute(
                    select(self.model)
                    .where(
                        self.model.platform == platform.value,
                        self.model.platform_chat_id == platform_chat_id,
                        self.model.agent_user_id == user_id,
                        self.model.status == "active",
                    )
                    .order_by(self.model.updated_at.desc())
                )
            ).scalar_one_or_none()
            if not row:
                return None
            return self._row_to_model(row)

    async def add_session(self, session: IMChatSession) -> None:
        async with AsyncSessionLocal() as s:
            s.add(
                self.model(
                    id=session.id,
                    platform=session.platform.value,
                    platform_chat_id=session.platform_chat_id,
                    agent_user_id=session.agent_user_id,
                    agent_session_id=session.agent_session_id,
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                    status=session.status,
                )
            )
            await s.commit()

    async def touch_session(self, session_id: str, updated_at: int) -> None:
        async with AsyncSessionLocal() as s:
            await s.execute(
                update(self.model).where(self.model.id == session_id).values(updated_at=updated_at)
            )
            await s.commit()

    async def get_latest_by_user(self, platform: IMPlatform, user_id: str) -> Optional[IMChatSession]:
        async with AsyncSessionLocal() as s:
            row = (
                await s.execute(
                    select(self.model)
                    .where(
                        self.model.platform == platform.value,
                        self.model.agent_user_id == user_id,
                        self.model.status == "active",
                    )
                    .order_by(self.model.updated_at.desc())
                )
            ).scalar_one_or_none()
            if not row:
                return None
            return self._row_to_model(row)

    async def list_recent_sessions(
        self,
        platform: IMPlatform,
        user_id: str,
        limit: int = 5,
    ) -> List[IMChatSession]:
        async with AsyncSessionLocal() as s:
            rows = (
                await s.execute(
                    select(self.model)
                    .where(
                        self.model.platform == platform.value,
                        self.model.agent_user_id == user_id,
                        self.model.status == "active",
                    )
                    .order_by(self.model.updated_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
            return [self._row_to_model(r) for r in rows]

    async def close_session(self, session_id: str) -> None:
        async with AsyncSessionLocal() as s:
            await s.execute(
                update(self.model)
                .where(self.model.id == session_id)
                .values(status="closed", updated_at=int(time.time()))
            )
            await s.commit()

    def _row_to_model(self, row: IMChatSessionRow) -> IMChatSession:
        return IMChatSession(
            id=row.id,
            platform=IMPlatform(row.platform),
            platform_chat_id=row.platform_chat_id,
            agent_user_id=row.agent_user_id,
            agent_session_id=row.agent_session_id,
            created_at=int(row.created_at or 0),
            updated_at=int(row.updated_at or 0),
            status=row.status or "active",
        )


class IMUserCurrentModelConfigRepo:
    def __init__(self):
        self.model = SessionRow

    async def get_latest_model_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as s:
            row = (
                await s.execute(
                    select(self.model.model_config_)
                    .where(
                        self.model.user_id == user_id,
                        self.model.model_config_.isnot(None),
                    )
                    .order_by(self.model.updated_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if not isinstance(row, dict):
                return None
            return deepcopy(row)


class IMUserCurrentModelConfigService:
    def __init__(self, model_config_repo: Optional[IMUserCurrentModelConfigRepo] = None):
        self.model_config_repo = model_config_repo or IMUserCurrentModelConfigRepo()

    async def get_current_model_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        if not user_id:
            return None
        return await self.model_config_repo.get_latest_model_config(user_id)


class IMSessionManager:
    def __init__(
        self,
        session_repo: Optional[IMChatSessionRepo] = None,
        model_config_service: Optional[IMUserCurrentModelConfigService] = None,
    ):
        self.session_repo = session_repo or IMChatSessionRepo()
        self.model_config_service = model_config_service or IMUserCurrentModelConfigService()

    async def get_or_create_session(
        self,
        platform: IMPlatform,
        platform_chat_id: str,
        user_id: str,
    ) -> IMChatSession:
        existing = await self.session_repo.get_active_session(
            platform=platform,
            platform_chat_id=platform_chat_id,
            user_id=user_id,
        )
        if existing:
            try:
                await async_get_agent_session(existing.agent_session_id)
            except Exception:
                await self.session_repo.close_session(existing.id)
                return await self.create_new_session(
                    platform=platform, platform_chat_id=platform_chat_id, user_id=user_id,
                )
            existing.updated_at = int(time.time())
            await self.session_repo.touch_session(existing.id, updated_at=existing.updated_at)
            await self._backfill_source(existing.agent_session_id, platform)
            return existing
        return await self.create_new_session(platform=platform, platform_chat_id=platform_chat_id, user_id=user_id)

    async def _backfill_source(self, agent_session_id: str, platform: IMPlatform) -> None:
        """Ensure the linked AgentSession has `source` and pinned state set."""
        try:
            agent = await async_get_agent_session(agent_session_id)
            changed = False
            if not agent.source:
                agent.source = platform.value
                changed = True
            if platform == IMPlatform.WECHAT and not agent.pinned:
                agent.pinned = True
                changed = True
            if changed:
                await agent.save()
        except Exception:
            pass

    async def create_new_session(
        self,
        platform: IMPlatform,
        platform_chat_id: str,
        user_id: str,
    ) -> IMChatSession:
        model_config = await self.model_config_service.get_current_model_config(user_id)
        agent_session = await async_create_agent_session(
            mode="business",
            user_id=user_id,
            model_config=model_config,
            source=platform.value,
        )
        if platform == IMPlatform.WECHAT:
            agent_session.pinned = True
            await agent_session.save()
        now = int(time.time())
        im_session = IMChatSession(
            id=shortuuid.uuid(),
            platform=platform,
            platform_chat_id=platform_chat_id,
            agent_user_id=user_id,
            agent_session_id=agent_session.session_id,
            created_at=now,
            updated_at=now,
        )
        await self.session_repo.add_session(im_session)
        notify("session_created", {
            "session_id": agent_session.session_id,
            "user_id": user_id,
            "source": platform.value,
        })
        return im_session

    async def get_latest_by_user(self, platform: IMPlatform, user_id: str) -> Optional[IMChatSession]:
        return await self.session_repo.get_latest_by_user(platform=platform, user_id=user_id)

    async def list_recent_sessions(
        self,
        platform: IMPlatform,
        user_id: str,
        limit: int = 5,
    ) -> List[IMChatSession]:
        return await self.session_repo.list_recent_sessions(
            platform=platform,
            user_id=user_id,
            limit=limit,
        )

    async def close_session(self, session_id: str) -> None:
        await self.session_repo.close_session(session_id)
