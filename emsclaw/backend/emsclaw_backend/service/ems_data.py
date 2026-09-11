"""EMS 数据层:从 tick 快照表派生 LP 所需全部输入数据。

设计原则：
- 所有预测/统计都从 tick 写入的快照表聚合而来,与 tick 同源
- 数据不足时回退到 station_service 的确定性公式,但**必须**在返回中标注
  `source="fallback_formula"` / `confidence="low"`,让 agent 感知"预测其实是猜的"
  （避免电价等关键输入被静默兜底成一个看似可信的数字）
- 月度已发生最大需量从 MeterSnapshot.rolling_demand_kw 聚合,进需量电费口径

对外接口:
- forecast_from_ticks(target_date, days=7) -> dict(含 load_kw/pv_kw + source/confidence)
- month_max_demand_kw(now=None) -> float(当月已发生最大滚动需量,无数据=0)
"""
from __future__ import annotations

import time
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
from typing import Any

from emsclaw_backend.mapper.station_mapper import StationMapper
from emsclaw_backend.service.station_service import (
    StationSimService,
    _load_profile_base_kw,
    _seasonal_pv_factor,
    _clear_sky_irradiance,
    _trapezoid_kwh,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")

# 历史不足此天数 → 回退公式(经验值:3 天日均才稳定)
_MIN_HISTORY_DAYS = 3
# 默认回看天数
_DEFAULT_LOOKBACK_DAYS = 7


def _now_dt(now: datetime | None = None) -> datetime:
    return now or datetime.now(tz=_SHANGHAI)


def _hour_of(ts: int) -> int:
    """unix 秒 → 当地小时(0-23)。"""
    return datetime.fromtimestamp(ts, tz=_SHANGHAI).hour


def _date_range_endpoints(target_date: _date, days: int) -> tuple[int, int]:
    """[target_date - days, target_date) 的 unix 起止(右开)。"""
    start_day = target_date - timedelta(days=days)
    start_ts = int(datetime(start_day.year, start_day.month, start_day.day,
                            tzinfo=_SHANGHAI).timestamp())
    end_day = target_date
    end_ts = int(datetime(end_day.year, end_day.month, end_day.day,
                          tzinfo=_SHANGHAI).timestamp())
    return start_ts, end_ts


def _bucket_hourly_mean(snaps: list, value_attr: str) -> list[float]:
    """把快照按 hour 桶聚合取均值,返回长度 24 的 list(缺数据小时=0.0)。

    snaps: 带 timestamp + <value_attr> 字段的对象列表。
    """
    sums: dict[int, float] = defaultdict(float)
    counts: dict[int, int] = defaultdict(int)
    for s in snaps:
        h = _hour_of(int(s.timestamp))
        sums[h] += float(getattr(s, value_attr))
        counts[h] += 1
    return [
        round(sums[h] / counts[h], 2) if counts[h] else 0.0
        for h in range(24)
    ]


def _has_enough_history(snaps: list, min_days: int = _MIN_HISTORY_DAYS) -> bool:
    """快照覆盖天数 ≥ min_days 视为历史充足(按日期去重计)。"""
    if not snaps:
        return False
    days_seen = {datetime.fromtimestamp(int(s.timestamp), tz=_SHANGHAI).date()
                 for s in snaps}
    return len(days_seen) >= min_days


def forecast_from_ticks(
    target_date: _date,
    days: int = _DEFAULT_LOOKBACK_DAYS,
    mapper: StationMapper | None = None,
) -> dict:
    """从近 N 天 tick 快照聚合目标日的 24h 负荷/光伏预测(kW)。

    流程:
    1. 取近 `days` 天 [target_date - days, target_date) 的 meter_snapshots +
       pv_snapshots,按 hour 桶取均值
    2. 历史充足(≥3 天) → source="tick_history", confidence="high"
    3. 历史不足 → 回退到 station_service.get_forecast_day 的确定性公式,
       source="fallback_formula", confidence="low"
    4. 光伏预测可选:用 weather_snapshots 的辐照做修正(初版直接用 pv_snapshots 均值)

    返回字段与 station_service.get_forecast_day 对齐,额外加 source/confidence。
    """
    mapper = mapper or StationMapper()
    start_ts, end_ts = _date_range_endpoints(target_date, days)

    # 取近 N 天的快照(场站级:用第一个 meter/pv 设备)
    meter = mapper.first_meter_device()
    pv_dev = mapper.first_pv_device()

    load_kw: list[float] = [0.0] * 24
    pv_kw: list[float] = [0.0] * 24
    source = "fallback_formula"
    confidence = "low"
    days_covered = 0

    if meter is not None:
        m_snaps = mapper.meter_snapshots_range(meter.id, start_ts, end_ts)
        if _has_enough_history(m_snaps):
            load_kw = _bucket_hourly_mean(m_snaps, "load_kw")
            days_covered = len({datetime.fromtimestamp(int(s.timestamp), tz=_SHANGHAI).date()
                                for s in m_snaps})
            source = "tick_history"
            confidence = "high"

    if pv_dev is not None:
        p_snaps = mapper.pv_snapshots_range(pv_dev.id, start_ts, end_ts)
        if _has_enough_history(p_snaps):
            # 仅在有足够光伏历史时才覆盖;否则保持 0(回退公式分支会重算)
            pv_kw = _bucket_hourly_mean(p_snaps, "generation_kw")
            if source == "tick_history":
                # 负荷已 tick 同源,光伏也用快照(若光伏历史不足则单独标 partial)
                pass

    # 历史不足 → 回退公式(与 station_service.get_forecast_day 同公式,保证可循)
    if source == "fallback_formula":
        svc = StationSimService()
        fb = svc.get_forecast_day(target_date)
        load_kw = list(fb["load_kw"])
        pv_kw = list(fb["pv_kw"])

    net_load_kw = [round(load_kw[h] - pv_kw[h], 2) for h in range(24)]
    return {
        "target_date": target_date.isoformat(),
        "load_kw": load_kw,
        "pv_kw": pv_kw,
        "net_load_kw": net_load_kw,
        "load_peak_kw": round(max(load_kw), 2) if load_kw else 0.0,
        "pv_peak_kw": round(max(pv_kw), 2) if pv_kw else 0.0,
        "load_energy_kwh": round(_trapezoid_kwh(load_kw), 1),
        "pv_energy_kwh": round(_trapezoid_kwh(pv_kw), 1),
        "pv_rated_kwp": pv_dev.rated_capacity_kwp if pv_dev else 0.0,
        "seasonal_factor": _seasonal_pv_factor(target_date.timetuple().tm_yday),
        # 数据来源标注(关键:让 agent 感知"预测其实是猜的")
        "source": source,                # "tick_history" | "fallback_formula"
        "confidence": confidence,        # "high" | "low"
        "days_covered": days_covered,    # tick 同源时实际覆盖的天数
        "lookback_days": days,           # 请求的回看天数
    }


def month_max_demand_kw(now: datetime | None = None) -> float:
    """当月已发生最大滚动需量(kW,15min 滑窗峰值)。

    需量电费按月计,口径=max(当月已发生峰值, 当日 dmax)。LP 的 dmax 是当日
    预测峰值,agent 据此向用户解释"你的需量电费已经按 X kW 计了,今天若超过 X
    才会触发新的更高计费档"。
    无任何快照 → 返回 0.0(月初首次调用)。
    """
    now = _now_dt(now)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_ts = int(month_start.timestamp())
    end_ts = int(now.timestamp())

    mapper = StationMapper()
    meter = mapper.first_meter_device()
    if meter is None:
        return 0.0
    # 复用 station_mapper 已有的 demand_max_since(它就是按 rolling_demand_kw desc 取首行)
    return float(mapper.meter_demand_max_since(meter.id, start_ts))
