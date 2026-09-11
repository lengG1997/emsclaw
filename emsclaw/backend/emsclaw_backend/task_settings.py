from typing import Optional
import time
from pydantic import BaseModel, Field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from emsclaw_backend.db.session import AsyncSessionLocal
from emsclaw_backend.db.models import TaskSettings as TaskSettingsRow

# Defaults tuned for 128K context window models (e.g. DeepSeek v3.2):
#   max_tokens      = 8K    — output ceiling, sufficient for most single-step replies
#   output_reserve  = 16K   — reserved in history budget calc (actual per-step output)
#   history_budget  = 128000 × 0.85 - (16384 + 4000 + 6000 + 1000) ≈ 81K tokens
#   max_history_rounds = 10 — safe under 81K budget
DEFAULT_AGENT_STREAM_TIMEOUT = 10800
DEFAULT_SANDBOX_EXEC_TIMEOUT = 1200
DEFAULT_MAX_TOKENS = 8192
DEFAULT_OUTPUT_RESERVE = 16384
DEFAULT_MAX_HISTORY_ROUNDS = 10
DEFAULT_MAX_OUTPUT_CHARS = 50000


class TaskSettings(BaseModel):
    agent_stream_timeout: int = Field(
        default=DEFAULT_AGENT_STREAM_TIMEOUT,
        ge=60, le=21600,
        description="Agent task max execution time in seconds",
    )
    sandbox_exec_timeout: int = Field(
        default=DEFAULT_SANDBOX_EXEC_TIMEOUT,
        ge=30, le=1800,
        description="Single sandbox command timeout in seconds",
    )
    max_tokens: int = Field(
        default=DEFAULT_MAX_TOKENS,
        ge=1024, le=200000,
        description="LLM max output tokens (ceiling for model reply length)",
    )
    output_reserve: int = Field(
        default=DEFAULT_OUTPUT_RESERVE,
        ge=2048, le=65536,
        description="Tokens reserved for output in history budget calculation",
    )
    max_history_rounds: int = Field(
        default=DEFAULT_MAX_HISTORY_ROUNDS,
        ge=1, le=30,
        description="Number of history conversation rounds in context",
    )
    max_output_chars: int = Field(
        default=DEFAULT_MAX_OUTPUT_CHARS,
        ge=5000, le=100000,
        description="Max chars of sandbox output before truncation",
    )


class UpdateTaskSettingsRequest(BaseModel):
    agent_stream_timeout: Optional[int] = Field(default=None, ge=60, le=21600)
    sandbox_exec_timeout: Optional[int] = Field(default=None, ge=30, le=1800)
    max_tokens: Optional[int] = Field(default=None, ge=1024, le=200000)
    output_reserve: Optional[int] = Field(default=None, ge=2048, le=65536)
    max_history_rounds: Optional[int] = Field(default=None, ge=1, le=30)
    max_output_chars: Optional[int] = Field(default=None, ge=5000, le=100000)


async def get_task_settings(user_id: str) -> TaskSettings:
    async with AsyncSessionLocal() as s:
        row = await s.get(TaskSettingsRow, user_id)
        if not row:
            return TaskSettings()
        return TaskSettings(
            agent_stream_timeout=row.agent_stream_timeout or DEFAULT_AGENT_STREAM_TIMEOUT,
            sandbox_exec_timeout=row.sandbox_exec_timeout or DEFAULT_SANDBOX_EXEC_TIMEOUT,
            max_tokens=row.max_tokens or DEFAULT_MAX_TOKENS,
            output_reserve=row.output_reserve or DEFAULT_OUTPUT_RESERVE,
            max_history_rounds=row.max_history_rounds or DEFAULT_MAX_HISTORY_ROUNDS,
            max_output_chars=row.max_output_chars or DEFAULT_MAX_OUTPUT_CHARS,
        )


async def update_task_settings(user_id: str, updates: UpdateTaskSettingsRequest) -> TaskSettings:
    update_data = updates.model_dump(exclude_unset=True)
    if not update_data:
        return await get_task_settings(user_id)

    async with AsyncSessionLocal() as s:
        row = await s.get(TaskSettingsRow, user_id)
        if row is None:
            row = TaskSettingsRow(id=user_id)
            s.add(row)
            try:
                await s.flush()
            except IntegrityError:
                await s.rollback()
                row = await s.get(TaskSettingsRow, user_id)
                if row is None:
                    raise
        for k, v in update_data.items():
            setattr(row, k, v)
        row.updated_at = int(time.time())
        await s.commit()

    return await get_task_settings(user_id)
