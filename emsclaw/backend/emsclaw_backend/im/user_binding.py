from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import shortuuid
from sqlalchemy import select, update

from emsclaw_backend.db.models import IMUserBinding as IMUserBindingRow
from emsclaw_backend.db.session import AsyncSessionLocal
from emsclaw_backend.im.base import IMPlatform


@dataclass
class IMUserBinding:
    id: str
    platform: IMPlatform
    platform_user_id: str
    platform_union_id: Optional[str]
    agent_user_id: str
    created_at: int
    updated_at: int
    status: str = "active"


class IMUserBindingManager:
    def __init__(self):
        self.model = IMUserBindingRow

    async def get_binding(self, platform: IMPlatform, platform_user_id: str) -> Optional[IMUserBinding]:
        async with AsyncSessionLocal() as s:
            row = (
                await s.execute(
                    select(self.model).where(
                        self.model.platform == platform.value,
                        self.model.platform_user_id == platform_user_id,
                        self.model.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if not row:
                return None
            return self._row_to_model(row)

    async def get_binding_by_agent_user(self, platform: IMPlatform, agent_user_id: str) -> Optional[IMUserBinding]:
        async with AsyncSessionLocal() as s:
            row = (
                await s.execute(
                    select(self.model)
                    .where(
                        self.model.platform == platform.value,
                        self.model.agent_user_id == agent_user_id,
                        self.model.status == "active",
                    )
                    .order_by(self.model.updated_at.desc())
                )
            ).scalar_one_or_none()
            if not row:
                return None
            return self._row_to_model(row)

    async def create_binding(
        self,
        platform: IMPlatform,
        platform_user_id: str,
        agent_user_id: str,
        platform_union_id: Optional[str] = None,
    ) -> IMUserBinding:
        now = int(time.time())
        async with AsyncSessionLocal() as s:
            existing = (
                await s.execute(
                    select(self.model).where(
                        self.model.platform == platform.value,
                        self.model.platform_user_id == platform_user_id,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                existing.agent_user_id = agent_user_id
                existing.platform_union_id = platform_union_id or ""
                existing.updated_at = now
                existing.status = "active"
                await s.commit()
                return self._row_to_model(existing)

            binding = IMUserBinding(
                id=shortuuid.uuid(),
                platform=platform,
                platform_user_id=platform_user_id,
                platform_union_id=platform_union_id,
                agent_user_id=agent_user_id,
                created_at=now,
                updated_at=now,
                status="active",
            )
            s.add(
                self.model(
                    id=binding.id,
                    platform=binding.platform.value,
                    platform_user_id=binding.platform_user_id,
                    platform_union_id=binding.platform_union_id or "",
                    agent_user_id=binding.agent_user_id,
                    created_at=binding.created_at,
                    updated_at=binding.updated_at,
                    status=binding.status,
                )
            )
            await s.commit()
            return binding

    async def remove_binding(self, platform: IMPlatform, platform_user_id: str) -> bool:
        now = int(time.time())
        async with AsyncSessionLocal() as s:
            result = await s.execute(
                update(self.model)
                .where(
                    self.model.platform == platform.value,
                    self.model.platform_user_id == platform_user_id,
                )
                .values(status="inactive", updated_at=now)
            )
            await s.commit()
            return (result.rowcount or 0) > 0

    async def remove_binding_by_agent_user(self, platform: IMPlatform, agent_user_id: str) -> bool:
        now = int(time.time())
        async with AsyncSessionLocal() as s:
            result = await s.execute(
                update(self.model)
                .where(
                    self.model.platform == platform.value,
                    self.model.agent_user_id == agent_user_id,
                    self.model.status == "active",
                )
                .values(status="inactive", updated_at=now)
            )
            await s.commit()
            return (result.rowcount or 0) > 0

    def _row_to_model(self, row: IMUserBindingRow) -> IMUserBinding:
        return IMUserBinding(
            id=row.id,
            platform=IMPlatform(row.platform),
            platform_user_id=row.platform_user_id,
            platform_union_id=row.platform_union_id or None,
            agent_user_id=row.agent_user_id,
            created_at=int(row.created_at or 0),
            updated_at=int(row.updated_at or 0),
            status=row.status or "active",
        )
