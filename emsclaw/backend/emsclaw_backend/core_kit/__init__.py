"""core_kit — emsclaw 内置 Agent 能力包。

包内容：
  - tools   : 6 个 LLM 工具（web 搜索/爬取、元能力 propose_*/eval_*/grade_eval）
  - skills  : 10 个 builtin skill（office 文档 / 元能力 / 飞书 / K8s 诊断）

被 agents/research 装配使用，未来其他 profile 也能复用。
"""
from __future__ import annotations

import os
from typing import List

from .tools import TOOLS
from .skills import BUILTIN_SKILLS_DIR, BUILTIN_SKILL_ROUTE, RETAINED_SKILLS

__all__ = [
    "TOOLS",
    "BUILTIN_SKILLS_DIR",
    "BUILTIN_SKILL_ROUTE",
    "RETAINED_SKILLS",
    "get_tool_names",
    "get_skill_routes",
]


def get_tool_names() -> List[str]:
    """返回所有 tool 的名称列表（用于日志/UI 展示）。"""
    return [getattr(t, "name", str(t)) for t in TOOLS]


def get_skill_routes() -> List[str]:
    """返回可用 skill 的虚拟路径（按 RETAINED_SKILLS 白名单过滤）。"""
    if not os.path.isdir(BUILTIN_SKILLS_DIR):
        return []
    return [
        f"{BUILTIN_SKILL_ROUTE}{name}/"
        for name in RETAINED_SKILLS
        if os.path.isdir(os.path.join(BUILTIN_SKILLS_DIR, name))
    ]
