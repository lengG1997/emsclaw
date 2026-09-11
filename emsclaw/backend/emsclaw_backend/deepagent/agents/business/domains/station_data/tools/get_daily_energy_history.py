"""get_daily_energy_history - 近 N 天日充放电量与收益历史。"""
from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _stn


class GetDailyEnergyHistorySchema(BaseModel):
    days: int = Field(default=7, description="回溯天数", ge=1, le=30)


@tool(args_schema=GetDailyEnergyHistorySchema)
@timeout_fallback(timeout_seconds=15)
def get_daily_energy_history(days: int = 7) -> str:
    """获取近 N 天日充放电量与收益历史,评估经济性趋势。"""
    stn = _stn()
    try:
        rows = stn.list_daily_energy(days) or []
    except Exception as exc:
        return f"【日电量历史】\n暂无数据({exc})"
    if not rows:
        return "【日电量历史】\n暂无数据"
    lines = [f"【日电量与收益 - 近{days}天】"]
    total_rev = 0.0
    for r in sorted(rows, key=lambda x: x.date):
        total_rev += r.revenue or 0
        lines.append(
            f"• {r.date}: 充电{r.charge_kwh:.1f}kWh 放电{r.discharge_kwh:.1f}kWh 收益{r.revenue:.1f}元"
        )
    lines.append(f"• 累计收益: {total_rev:.1f}元 日均{total_rev/len(rows):.1f}元")
    return "\n".join(lines)
