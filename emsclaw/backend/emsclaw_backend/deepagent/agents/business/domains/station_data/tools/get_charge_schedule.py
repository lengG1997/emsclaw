"""get_charge_schedule - 今日 24h 充放电调度计划(调 PcsService 单一真相源)。"""
from langchain_core.tools import tool

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _pcs


@tool
@timeout_fallback(timeout_seconds=15)
def get_charge_schedule() -> str:
    """获取今日 24h 充放电调度计划(读当日已下发的 active ChargeSchedule)。

    返回各小时的充放电模式与目标功率(站级聚合)。无已下发计划则告知当日储能待机。
    """
    sched = _pcs().get_charge_schedule()
    if sched.get("status") == "none" or not sched.get("segments"):
        return (f"【今日充放电调度计划 - {sched['date']}】\n"
                f"当日无已下发的充放电计划,储能处于待机。")
    lines = [f"【今日充放电调度计划 - {sched['date']}】"
             f"（策略组合:{'、'.join(sched.get('strategies') or []) or '-'} / 状态:{sched.get('status')}）",
             f"在线 PCS 总额定功率: {sched['total_rated_power_kw']:.0f}kW"]
    for seg in sched["segments"]:
        if seg["power_kw"]:
            lines.append(f"• {seg['start']}-{seg['end']}  {seg['label']}  "
                         f"{seg['power_kw']:.0f}kW  (计划SOC末:{seg['soc_target_pct']*100:.0f}%)")
        else:
            lines.append(f"• {seg['start']}-{seg['end']}  {seg['label']}")
    return "\n".join(lines)
