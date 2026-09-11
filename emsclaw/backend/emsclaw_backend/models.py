from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
import uuid
import time
from loguru import logger
from sqlalchemy import select, or_

from emsclaw_backend.db.models import Model
from emsclaw_backend.db.session import AsyncSessionLocal
from emsclaw_backend.config import settings

class ModelConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., description="Display Name")
    provider: str = Field(..., description="openai, anthropic, etc.")
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_name: str = Field(..., description="Actual model name e.g. gpt-4o")
    context_window: Optional[int] = Field(
        default=None,
        description="Model context window in tokens. Auto-detected from model_name if not set.",
    )
    is_system: bool = False
    user_id: Optional[str] = None
    is_active: bool = True
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))

class CreateModelRequest(BaseModel):
    name: str
    provider: str = "openai"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_name: str
    context_window: Optional[int] = Field(
        default=None,
        ge=1024, le=10_000_000,
        description="Model context window in tokens. Leave empty for auto-detection.",
    )

class UpdateModelRequest(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    context_window: Optional[int] = Field(
        default=None,
        ge=1024, le=10_000_000,
        description="Model context window in tokens. Leave empty for auto-detection.",
    )
    is_active: Optional[bool] = None

async def init_system_models():
    """
    Initialize system models from environment variables or settings.
    Only creates system model when DS_API_KEY is configured;
    otherwise cleans up any existing system model with empty key.
    """
    now = int(time.time())

    async with AsyncSessionLocal() as s:
        # Cleanup legacy system-qwen model
        qwen_row = (await s.execute(
            select(Model).where(Model.id == "system-qwen", Model.is_system == True)
        )).scalar_one_or_none()
        if qwen_row:
            await s.delete(qwen_row)

        if not settings.model_ds_api_key:
            default_row = (await s.execute(
                select(Model).where(Model.id == "system-default", Model.is_system == True)
            )).scalar_one_or_none()
            if default_row:
                await s.delete(default_row)
            await s.commit()
            logger.info("DS_API_KEY not set, skipping system model creation")
            return

        system_definitions = [
            {
                "id": "system-default",
                "name": settings.model_ds_name,
                "provider": "openai",
                "base_url": settings.model_ds_base_url,
                "api_key": settings.model_ds_api_key,
                "model_name": settings.model_ds_name,
                "context_window": settings.context_window or 0,
                "is_system": True,
                "is_active": True,
            }
        ]

        for doc in system_definitions:
            existing = await s.get(Model, doc["id"])
            if not existing:
                row = Model(**doc, created_at=now, updated_at=now)
                s.add(row)
            else:
                for k, v in doc.items():
                    setattr(existing, k, v)
                existing.updated_at = now
        await s.commit()

async def get_model_config(model_id: str) -> Optional[ModelConfig]:
    async with AsyncSessionLocal() as s:
        row = await s.get(Model, model_id)
        if not row:
            return None
        return ModelConfig(
            id=row.id,
            name=row.name,
            provider=row.provider,
            base_url=row.base_url or None,
            api_key=row.api_key or None,
            model_name=row.model_name,
            context_window=row.context_window or None,
            is_system=row.is_system,
            user_id=row.user_id or None,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

async def list_user_models(user_id: str) -> List[ModelConfig]:
    # Return System models + User models
    async with AsyncSessionLocal() as s:
        q = select(Model).where(
            or_(Model.is_system == True, Model.user_id == user_id)
        ).order_by(Model.created_at.desc())
        rows = (await s.execute(q)).scalars().all()

        models = []
        for row in rows:
            models.append(ModelConfig(
                id=row.id,
                name=row.name,
                provider=row.provider,
                base_url=row.base_url or None,
                api_key=row.api_key or None,
                model_name=row.model_name,
                context_window=row.context_window or None,
                is_system=row.is_system,
                user_id=row.user_id or None,
                is_active=row.is_active,
                created_at=row.created_at,
                updated_at=row.updated_at,
            ))
        return models
