"""profile 装配层入口 -- 按 mode 分发到对应 builder。

build_agent(mode, ...) 是 deep_agent() 之后的统一装配入口。
未知 mode 兜底走 business。
"""
from __future__ import annotations
from typing import Any, Optional, Tuple

from loguru import logger

from emsclaw_backend.task_settings import TaskSettings

VALID_MODES = {"business"}


def normalize_mode(mode: Optional[str]) -> str:
    if mode in VALID_MODES:
        return mode  # type: ignore[return-value]
    return "business"


async def build_agent(
    mode: Optional[str],
    session_id: str,
    user_id: Optional[str] = None,
    model_config: Optional[dict] = None,
    task_settings: Optional[TaskSettings] = None,
    diagnostic_enabled: bool = False,
    language: Optional[str] = None,
    checkpointer: Optional[Any] = None,
) -> Tuple[Any, Any, int, Any]:
    """按 mode 装配 agent。

    Args:
        checkpointer: langgraph checkpointer(business mode 用)。
            None 时,business 内部自动从 get_checkpointer() 取;非 None 覆盖(测试可传 MemorySaver)。
    """
    m = normalize_mode(mode)
    logger.info(f"[profiles] build_agent mode={mode!r} -> {m}")

    if task_settings is None:
        from emsclaw_backend.task_settings import TaskSettings as _TS
        task_settings = _TS()

    # business（默认）
    from .business import build_business_agent
    return await build_business_agent(
        session_id, user_id, model_config, task_settings, checkpointer=checkpointer,
        language=language)
