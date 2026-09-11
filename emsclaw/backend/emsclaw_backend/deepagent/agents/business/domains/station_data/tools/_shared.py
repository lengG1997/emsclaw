"""station_data 工具共享辅助。

统一提供 PcsService / StationService 句柄与格式化/降采样助手。
所有 get_* 读工具按需 from ._shared import ... 使用。
"""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from emsclaw_backend.service.pcs_service import PcsService, get_default_service as _get_pcs_svc
from emsclaw_backend.service.station_service import get_default_service as _get_station_svc

# 电价时段名映射（尖峰平谷）
_PERIOD_NAMES = {"sharp": "尖", "peak": "峰", "flat": "平", "valley": "谷"}


def _pcs() -> PcsService:
    return _get_pcs_svc()


def _stn():
    return _get_station_svc()


def _now() -> int:
    return int(time.time())


def _pct(ratio: float) -> str:
    return f"{ratio * 100:.1f}%"


def _downsample(points: list[tuple[int, float]], n: int = 48) -> list[tuple[int, float]]:
    """把 (ts, value) 序列降采样到 n 个点(分段均值)。"""
    if not points:
        return []
    if len(points) <= n:
        return points
    step = len(points) / n
    out: list[tuple[int, float]] = []
    i = 0.0
    while i < len(points):
        lo = int(i)
        hi = min(len(points), int(i + step) + 1)
        chunk = points[lo:hi]
        if chunk:
            out.append((chunk[0][0], sum(v for _, v in chunk) / len(chunk)))
        i += step
    return out


def _hhmm(ts: int) -> str:
    d = datetime.fromtimestamp(ts, tz=ZoneInfo("Asia/Shanghai"))
    return f"{d.hour:02d}:{d.minute:02d}"
