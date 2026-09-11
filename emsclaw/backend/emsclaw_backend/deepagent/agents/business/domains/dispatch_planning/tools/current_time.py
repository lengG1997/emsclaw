"""current_time - 本地时间戳工具(替代沙箱 execute date)。

报告落盘命名需要时间戳,旧做法是沙箱里跑 `date`——一次 REST 往返冷启动可高达 ~20s
(trace 6d1e34c8...)。本工具在 backend 进程内直接返回 Asia/Shanghai 当前时间,
零沙箱往返,供 agent 拼报告文件名/时间上下文。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback

_SH = ZoneInfo("Asia/Shanghai")


@tool
@timeout_fallback(timeout_seconds=5)
def current_time() -> dict:
    """获取当前本地时间(Asia/Shanghai),用于报告文件名时间戳与时间上下文。返回结构化 JSON。

    零网络往返——在应用进程内直接取系统时钟,不要用沙箱命令行 date。
    """
    now = datetime.now(tz=_SH)
    return {
        "status": "ok",
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "hour": now.hour,
        "weekday": now.strftime("%A"),
        "iso": now.isoformat(timespec="seconds"),
        "filename_ts": now.strftime("%Y%m%d_%H%M%S"),
    }
