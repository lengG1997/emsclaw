"""get_schedule_status - 当前调度执行状态(只读,被动偏差监测)。

读当日 active ChargeSchedule + 最新电池快照,对比【计划 SOC】与【实际 SOC】,
返回结构化数字 JSON。仅在用户询问"执行得怎么样/偏差/是否跟得上计划"时被动调用。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _now, _pcs, _schedule_mapper

_SH = ZoneInfo("Asia/Shanghai")


@tool
@timeout_fallback(timeout_seconds=15)
def get_schedule_status() -> dict:
    """查询当日充放电计划执行状态:当前小时计划、计划 SOC vs 实际 SOC、偏差、是否跟得上。

    被动监测--用户主动询问执行偏差时调用。返回结构化数字 JSON。
    """
    try:
        now = _now()
        dt = datetime.fromtimestamp(now, tz=_SH)
        date_str = dt.strftime("%Y-%m-%d")
        hour = dt.hour
        sched = _schedule_mapper().get_active_schedule(date_str)
        if sched is None or not sched.intervals:
            return {"status": "no_active_schedule", "date": date_str,
                    "reason": "当日无已下发的 active 充放电计划,储能处于待机。"}

        # 当前小时计划
        cur = next((s for s in sched.intervals if s.get("hour") == hour), None)
        # 实际 SOC(在线电池 SOC 容量加权均值)
        rows = _pcs().list_status()
        cap_total = 0.0
        soc_weighted = 0.0
        for r in rows:
            bat = r.get("battery")
            snap = r.get("latest_battery_snapshot")
            if bat is None:
                continue
            cap = float(bat.rated_capacity_kwh)
            cap_total += cap
            soc = float(snap.soc) if snap is not None else float(bat.soc)
            soc_weighted += soc * cap
        actual_soc = (soc_weighted / cap_total) if cap_total > 0 else 0.0

        planned_soc = float(cur.get("soc_target_pct", actual_soc)) if cur else actual_soc
        deviation = actual_soc - planned_soc
        # 偏差 <5% 视为跟得上
        on_track = abs(deviation) <= 0.05

        return {
            "status": "ok",
            "date": date_str,
            "current_hour": hour,
            "active_schedule": {
                "schedule_id": sched.id,
                "strategies": sched.strategies or [],
                "target_date": sched.target_date,
            },
            "current_hour_plan": cur,
            "actual_soc_pct": round(actual_soc, 4),
            "planned_soc_pct": round(planned_soc, 4),
            "deviation_pct": round(deviation, 4),
            "on_track": on_track,
        }
    except Exception as e:  # pragma: no cover
        return {"status": "error", "reason": f"查询执行状态失败:{e}"}
