"""agents 共享件 —— 从现有 agent.py 抽出的装配零件。

profile 装配件共用（business）：模型、沙箱、SSE 中间件、
工具落盘中间件、两层记忆。这里只做装配，不含业务策略。
"""
from __future__ import annotations

import os
from typing import Any, List, Optional

from loguru import logger

from emsclaw_backend.deepagent.engine import get_llm_model
from emsclaw_backend.deepagent.full_sandbox_backend import FullSandboxBackend
from emsclaw_backend.observability.sse_middleware import SSEMonitoringMiddleware
from emsclaw_backend.deepagent.offload_middleware import ToolResultOffloadMiddleware
from emsclaw_backend.task_settings import TaskSettings

_WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", "/home/emsclaw")
_MAX_MEMORY_CHARS = 4000


def get_model(model_config: Optional[dict], task_settings: TaskSettings) -> Any:
    """构造 LLM model（复用 engine.get_llm_model）。"""
    return get_llm_model(model_config, max_tokens_override=task_settings.max_tokens)


def build_sandbox(
    session_id: str,
    user_id: str,
    task_settings: TaskSettings,
    workspace_dir: str = _WORKSPACE_DIR,
) -> FullSandboxBackend:
    """会话级隔离沙箱。"""
    return FullSandboxBackend(
        session_id=session_id,
        user_id=user_id or "default_user",
        base_dir=workspace_dir,
        execute_timeout=task_settings.sandbox_exec_timeout,
        max_output_chars=task_settings.max_output_chars,
    )


def build_sse(agent_name: str = "DeepAgent") -> SSEMonitoringMiddleware:
    return SSEMonitoringMiddleware(agent_name=agent_name, parent_agent=None, verbose=False)


def build_offload(workspace_dir: str, sandbox: FullSandboxBackend) -> ToolResultOffloadMiddleware:
    return ToolResultOffloadMiddleware(workspace_dir=workspace_dir, backend=sandbox)


def ensure_memory(user_id: str, workspace_dir: str) -> List[str]:
    """两层记忆：全局 AGENTS.md（跨会话）+ 会话 CONTEXT.md。

    返回实际注入用的文件路径列表（含截断处理）。
    逻辑平移自原 agent.py:416-460。
    """
    mem_user = user_id or "default_user"
    mem_dir = os.path.join(_WORKSPACE_DIR, "_memory", mem_user)
    os.makedirs(mem_dir, exist_ok=True)
    os.chmod(mem_dir, 0o777)

    global_mem = os.path.join(mem_dir, "AGENTS.md")
    if not os.path.isfile(global_mem):
        with open(global_mem, "w") as f:
            f.write("# Global Memory (persists across all sessions)\n\n"
                    "## User Preferences\n\n## General Patterns\n\n## Notes\n")
        logger.info(f"[Memory] 初始化全局 Memory: {global_mem}")

    session_mem = os.path.join(workspace_dir, "CONTEXT.md")
    if not os.path.isfile(session_mem):
        with open(session_mem, "w") as f:
            f.write("# Session Context (this session only)\n\n"
                    "## Project Context\n\n## Task Notes\n")
        logger.info(f"[Memory] 初始化会话 Context: {session_mem}")

    use_files: List[str] = []
    for mf in [global_mem, session_mem]:
        try:
            size = os.path.getsize(mf)
            if size > _MAX_MEMORY_CHARS:
                with open(mf, "r", encoding="utf-8") as f:
                    full = f.read()
                truncated = full[:_MAX_MEMORY_CHARS].rsplit("\n", 1)[0]
                tmp = mf + ".truncated"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(truncated + "\n\n(Memory truncated — keep entries concise to stay under limit)\n")
                use_files.append(tmp)
            else:
                use_files.append(mf)
        except Exception:
            use_files.append(mf)
    return use_files
