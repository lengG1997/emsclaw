"""core_kit.tools — 3 个 LLM 内置工具（精简后）。

去除了原 emsclaw 的 tooluniverse_* 生物医学工具 + 联网搜索/爬取工具。
"""
from __future__ import annotations

from emsclaw_backend.deepagent.tools import (
    propose_skill_save,
    eval_skill,
    grade_eval,
)

TOOLS = [
    propose_skill_save,
    eval_skill,
    grade_eval,
]
