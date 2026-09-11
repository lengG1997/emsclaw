"""
agent.py — 组装 DeepAgent：系统提示词 + 模型 + 工具（内置 + 外部扩展）+ Skills + 监控中间件。

架构：
  - HybridSandboxBackend 作为默认后端：
    - 文件操作（read_file/write_file/edit_file/ls/glob/grep）→ 本地 /home/emsclaw/
    - 命令执行（execute）→ 远程 sandbox 容器
    - 通过 Docker 共享卷同步文件
  - CompositeBackend 路由：
    - /builtin-skills/ → FilesystemBackend（内置 skills，只读，始终加载）
    - /skills/         → FilteredFilesystemBackend（外置 skills，可屏蔽/删除）
  - deepagents 内置工具层统一管理所有工具（不再使用 MCP sandbox 工具）

Skills 架构：
  - 内置 skills（/app/builtin-skills/）：Office 文档等核心能力，
    COPY 进 Docker 镜像，不依赖宿主机挂载（避免 macOS 大小写不敏感文件系统的冲突）
  - 外置 skills（/app/Skills/）：用户自行安装的 skills，
    支持屏蔽和删除管理

监控中间件：
  - SSEMonitoringMiddleware 通过 wrap_tool_call 拦截工具执行前后
  - 事件存储在 middleware.sse_events，由 runner.py 轮询消费
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend
from emsclaw_backend.deepagent.engine import get_llm_model
from emsclaw_backend.deepagent.tools import propose_skill_save, eval_skill, grade_eval
from emsclaw_backend.deepagent.full_sandbox_backend import FullSandboxBackend
from emsclaw_backend.deepagent.filtered_backend import FilteredFilesystemBackend
from emsclaw_backend.observability.sse_middleware import SSEMonitoringMiddleware
from emsclaw_backend.deepagent.offload_middleware import ToolResultOffloadMiddleware
from emsclaw_backend.deepagent.diagnostic import DIAGNOSTIC_ENABLED, DiagnosticLogger
from emsclaw_backend.config import settings

# ───────────────────────────────────────────────────────────────────
# 路径配置
# ───────────────────────────────────────────────────────────────────

_BUILTIN_SKILLS_DIR = os.environ.get("BUILTIN_SKILLS_DIR", "/app/builtin-skills")
_EXTERNAL_SKILLS_DIR = os.environ.get("EXTERNAL_SKILLS_DIR", "/app/Skills")
_BUILTIN_SKILLS_ROUTE = "/builtin-skills/"
_EXTERNAL_SKILLS_ROUTE = "/skills/"
_WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", "/home/emsclaw")

# ───────────────────────────────────────────────────────────────────
# Backend 构建
# ───────────────────────────────────────────────────────────────────


def _build_backend(session_id: str, sandbox: FullSandboxBackend, blocked_skills: Set[str] | None = None):
    """
    构建 CompositeBackend 工厂函数（会话级隔离）：
      - 默认: 传入的 FullSandboxBackend 实例
      - /builtin-skills/ 路由: FilesystemBackend（内置 skills，始终加载）
      - /skills/          路由: FilteredFilesystemBackend（外置 skills，过滤屏蔽项）
    """
    routes = {}

    if os.path.isdir(_BUILTIN_SKILLS_DIR):
        logger.info(f"[Skills] 内置 skills: {_BUILTIN_SKILLS_DIR} → {_BUILTIN_SKILLS_ROUTE}")
        routes[_BUILTIN_SKILLS_ROUTE] = FilesystemBackend(
            root_dir=_BUILTIN_SKILLS_DIR,
            virtual_mode=True,
        )

    if os.path.isdir(_EXTERNAL_SKILLS_DIR):
        logger.info(f"[Skills] 外置 skills: {_EXTERNAL_SKILLS_DIR} → {_EXTERNAL_SKILLS_ROUTE}"
                     f" (blocked: {blocked_skills or set()})")
        routes[_EXTERNAL_SKILLS_ROUTE] = FilteredFilesystemBackend(
            root_dir=_EXTERNAL_SKILLS_DIR,
            virtual_mode=True,
            blocked_skills=blocked_skills or set(),
        )

    if routes:
        # 返回工厂函数以确保路由生效
        return lambda rt: CompositeBackend(default=sandbox, routes=routes)
    else:
        return sandbox


# ───────────────────────────────────────────────────────────────────
# 系统提示词
# ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT_TEMPLATE = """You are emsclaw, a proactive personal AI assistant designed to help users solve problems, conduct research, and complete tasks efficiently.

Current date and time: {current_datetime}.

## Language
Always respond in {language_instruction}.

## Core Principles
- Adapt to the conversation. Chat naturally for casual topics, but take concrete actions when the user asks for tasks or problem-solving.
- Prefer execution over explanation. If a task can be solved through code or tools, implement and execute the solution instead of only describing it.
- **Write files, not chat**: When the user asks to write, create, or generate code/scripts/files, ALWAYS use `write_file` to create real files — never just paste code in chat.
- **Write → Execute → Fix loop**: After writing ANY executable script, you MUST immediately run it via `execute` to verify correctness. If it fails, fix and re-run.
- **Skill-first approach**: ALWAYS check available skills (`/builtin-skills/` and `/skills/`) before starting any task. If a skill matches, `read_file` its SKILL.md and follow the workflow. Do NOT reinvent what a skill already provides.
- **SKILL.md files are instruction documents** — use `read_file` to read them, NEVER `execute` them as scripts.
- Solve problems proactively. Only ask questions when the intent or requirements are truly unclear.

## Workspace
Your workspace directory is {workspace_dir}/.
- All files should be created under this directory using absolute paths.
- The workspace is shared between the file system and the execution sandbox.

## Sandbox Boundary
The sandbox is an isolated execution environment. Scripts running in the sandbox CANNOT import or call your tools directly (`from functions import ...` will FAIL with `ModuleNotFoundError`).

**Data flow**: Use YOUR tools to gather data → save results to workspace files via `write_file` → write sandbox scripts that READ those files. NEVER call your tools from within sandbox scripts.

**Large tool results** are automatically saved to `research_data/` files (raw format). To use them in sandbox scripts: `read_file` the data → write a clean JSON file via a Python script with `json.dump()` → sandbox scripts read that clean file.

## Task Completion Strategy

### Step 1: Understand & Plan
- Identify ALL deliverables, requirements, and output format.
- For any task involving 2+ steps, call `write_todos` BEFORE starting.
- Check Memory: **AGENTS.md** and **CONTEXT.md**.
- **Check Available Skills (MANDATORY)** — review the skills catalog. If ANY skill matches the task, `read_file` that SKILL.md and follow its workflow. Do NOT skip this step.

### Step 2: Execute
- If a skill matched → follow the skill's workflow completely.
- Otherwise, use tools directly. Priority: existing skills > built-in tools.
- **Before `propose_skill_save`**: confirm the artifact is complete and tested before proposing to save.
- Build incrementally — one component per tool call. Test via `execute` after writing.

### Step 3: Verify & Deliver
- Re-read the user's original request. Check all deliverables are produced.
- If a script fails, fix the specific error — do NOT rewrite from scratch. If it fails 2+ times, simplify.

### Step 4: Reflect & Capture
After completing a non-trivial task:
- **Reusable workflow** → Suggest saving as a **skill** via `propose_skill_save`.
- **User preference learned** → Update **AGENTS.md** via `edit_file`.
- **Project context learned** → Update **CONTEXT.md** via `edit_file`.
"""


_EVAL_SYSTEM_PROMPT_TEMPLATE = """You are emsclaw, a proactive personal AI assistant designed to help users solve problems, conduct research, and complete tasks efficiently.

Current date and time: {current_datetime}

## Core Principles
- Prefer execution over explanation. If a task can be solved through code or tools, implement and execute the solution instead of only describing it.
- Always respond in the same language the user uses.
- When the user asks to write, create, or generate code/scripts/files, ALWAYS use write_file to create real files.
- Use sandbox execution whenever it can produce verifiable results.

## Workspace
Your workspace directory is {workspace_dir}/.
- All files should be created under this directory using absolute paths.
- The workspace is shared between the file system and the execution sandbox.
"""


_LANGUAGE_MAP = {
    "zh": ("Chinese (Simplified)", "你必须使用简体中文回复所有内容。所有生成的报告、文档标题和正文也必须使用简体中文。"),
    "en": ("English", "You must respond in English. All generated reports, document titles and body text must also be in English."),
}


def get_system_prompt(workspace_dir: str, sandbox_env: str | None = None, language: str | None = None) -> str:
    now = datetime.now().strftime("%Y-%m-%d %A")
    lang_code = (language or "").strip().lower()
    if lang_code in _LANGUAGE_MAP:
        lang_name, lang_detail = _LANGUAGE_MAP[lang_code]
        language_instruction = (
            f"- The user has set their preferred language to **{lang_name}** (code: `{lang_code}`).\n"
            f"- {lang_detail}\n"
            f"- This applies to ALL outputs: conversation replies, report content, section titles, chart labels, and file names."
        )
    else:
        language_instruction = "- Always respond in the same language the user uses."

    prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        current_datetime=now,
        workspace_dir=workspace_dir,
        language_instruction=language_instruction,
    )
    if sandbox_env:
        prompt += f"\n\n## Sandbox Environment Information\n{sandbox_env}"
    return prompt


def _get_eval_system_prompt(workspace_dir: str, sandbox_env: str | None = None) -> str:
    now = datetime.now().strftime("%Y-%m-%d %A")
    prompt = _EVAL_SYSTEM_PROMPT_TEMPLATE.format(
        current_datetime=now,
        workspace_dir=workspace_dir,
    )
    if sandbox_env:
        prompt += f"\n\n## Sandbox Environment Information\n{sandbox_env}"
    return prompt


# ───────────────────────────────────────────────────────────────────
# 屏蔽查询（PostgreSQL）
# ───────────────────────────────────────────────────────────────────

async def get_blocked_skills(user_id: str) -> Set[str]:
    """从 PostgreSQL 查询用户屏蔽的 skills 列表。"""
    try:
        from emsclaw_backend.db.session import AsyncSessionLocal
        from emsclaw_backend.db.models import BlockedSkill
        from sqlalchemy import select
        async with AsyncSessionLocal() as s:
            rows = (await s.execute(
                select(BlockedSkill.skill_name).where(BlockedSkill.user_id == user_id)
            )).scalars().all()
            blocked = {name for name in rows if name}
            return blocked
    except Exception as exc:
        logger.warning(f"[Skills] 查询屏蔽列表失败: {exc}")
        return set()


# ───────────────────────────────────────────────────────────────────
# 创建 Agent
# ───────────────────────────────────────────────────────────────────

async def deep_agent(
    session_id: str,
    model_config: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    task_settings: Optional["TaskSettings"] = None,
    diagnostic_enabled: bool = False,
    language: Optional[str] = None,
    mode: Optional[str] = "business",
) -> Tuple[Any, SSEMonitoringMiddleware, int, Optional[DiagnosticLogger]]:
    """创建 DeepAgent 实例（按 mode 分发到对应 profile）。

    保留旧签名兼容 + 新增 mode 参数。实际装配在 agents.build_agent。
    """
    from emsclaw_backend.deepagent.agents import build_agent
    from emsclaw_backend.task_settings import TaskSettings as _TS
    ts = task_settings or _TS()
    return await build_agent(
        mode=mode,
        session_id=session_id,
        user_id=user_id,
        model_config=model_config,
        task_settings=ts,
        diagnostic_enabled=diagnostic_enabled,
        language=language,
    )


# ───────────────────────────────────────────────────────────────────
# Eval 模式 Agent（精简版，用于 skill 测试）
# ───────────────────────────────────────────────────────────────────

async def deep_agent_eval(
    session_id: str,
    model_config: Optional[Dict[str, Any]] = None,
    skill_sources: Optional[List[str]] = None,
) -> Tuple[Any, SSEMonitoringMiddleware]:
    """
    创建用于 eval 测试的精简 Agent — 不含元工具，只加载目标 skill。

    与 deep_agent() 的关键差异：
      - 精简 system prompt（无元能力指令）
      - 不包含 propose_skill_save 等元工具
      - 可指定只加载特定 skill sources
    """
    from emsclaw_backend.task_settings import TaskSettings as _TS
    ts = _TS()
    model = get_llm_model(model_config, max_tokens_override=ts.max_tokens)

    eval_tools = []

    middleware = SSEMonitoringMiddleware(
        agent_name="EvalAgent",
        parent_agent=None,
        verbose=False,
    )

    sandbox = FullSandboxBackend(
        session_id=session_id,
        user_id="eval_runner",
        base_dir=_WORKSPACE_DIR,
        execute_timeout=ts.sandbox_exec_timeout,
        max_output_chars=ts.max_output_chars,
    )

    actual_workspace = sandbox.workspace
    sandbox_info = None
    ctx = await sandbox.get_context()
    if ctx.get("success"):
        sandbox_info = ctx.get("data")

    system_prompt = _get_eval_system_prompt(actual_workspace, sandbox_info)

    agent_kwargs: Dict[str, Any] = {
        "model": model,
        "tools": eval_tools,
        "middleware": [middleware],
        "system_prompt": system_prompt,
    }

    # 构建后端（含 skill 路由）
    routes = {}
    resolved_sources: List[str] = []

    if skill_sources:
        for src in skill_sources:
            if src == _BUILTIN_SKILLS_ROUTE and os.path.isdir(_BUILTIN_SKILLS_DIR):
                routes[_BUILTIN_SKILLS_ROUTE] = FilesystemBackend(
                    root_dir=_BUILTIN_SKILLS_DIR, virtual_mode=True,
                )
                resolved_sources.append(_BUILTIN_SKILLS_ROUTE)
            elif src == _EXTERNAL_SKILLS_ROUTE and os.path.isdir(_EXTERNAL_SKILLS_DIR):
                routes[_EXTERNAL_SKILLS_ROUTE] = FilteredFilesystemBackend(
                    root_dir=_EXTERNAL_SKILLS_DIR, virtual_mode=True,
                    blocked_skills=set(),
                )
                resolved_sources.append(_EXTERNAL_SKILLS_ROUTE)
    else:
        if os.path.isdir(_EXTERNAL_SKILLS_DIR):
            routes[_EXTERNAL_SKILLS_ROUTE] = FilteredFilesystemBackend(
                root_dir=_EXTERNAL_SKILLS_DIR, virtual_mode=True,
                blocked_skills=set(),
            )
            resolved_sources.append(_EXTERNAL_SKILLS_ROUTE)

    if routes:
        agent_kwargs["backend"] = lambda rt: CompositeBackend(default=sandbox, routes=routes)
    else:
        agent_kwargs["backend"] = sandbox

    if resolved_sources:
        agent_kwargs["skills"] = resolved_sources

    agent = create_deep_agent(**agent_kwargs)
    logger.info(f"[EvalAgent] session={session_id}, workspace={actual_workspace}, skills={resolved_sources}")
    return agent, middleware
