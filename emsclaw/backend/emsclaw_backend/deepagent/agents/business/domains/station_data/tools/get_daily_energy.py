"""get_daily_energy - 今日充放电电量与收益。"""
from langchain_core.tools import tool

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _stn


@tool
@timeout_fallback(timeout_seconds=15)
def get_daily_energy() -> str:
    """获取今日充放电电量与收益(累计充电/放电 kWh + 净收益)。"""
    e = _stn().get_overview().get("energy_today")
    if e is None:
        return "【今日电量】\n• 暂无数据"
    return (
        f"【今日电量与收益 - {e['date']}】\n"
        f"• 充电电量: {e['charge_kwh']:.2f}kWh\n"
        f"• 放电电量: {e['discharge_kwh']:.2f}kWh\n"
        f"• 净收益: {e['revenue']:.2f}元"
    )
