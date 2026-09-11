"""core_kit.skills — builtin skill 路径与白名单。

白名单策略：只暴露 EMS 业务相关的 skill，过滤掉上游遗留的科研/医药类 skill。

可挂载的 skill 列表：
  - Office 文档：docx / pdf / pptx / xlsx（EMS 报告与数据导出）
  - 通讯集成：  feishu-setup
"""
from __future__ import annotations

import os

# builtin skills 物理路径（容器内 /app/builtin-skills；本地可用环境变量覆盖）
BUILTIN_SKILLS_DIR = os.environ.get("BUILTIN_SKILLS_DIR", "/app/builtin-skills")

# builtin skills 在 agent 视角下的虚拟根路径（与 deepagent 的 backend 装配保持一致）
BUILTIN_SKILL_ROUTE = "/builtin-skills/"

# 白名单：仅加载下列 skill（顺序即优先级）
RETAINED_SKILLS = [
    # ── Office 文档（EMS 报告 / 数据导出）──
    "docx",
    "pdf",
    "pptx",
    "xlsx",
    # ── 通讯集成 ──
    "feishu-setup",
]
