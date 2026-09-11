"""get_forecast - 站级负荷/光伏/净负荷预测。"""
from __future__ import annotations

from datetime import date as _date

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _stn


class GetForecastSchema(BaseModel):
    days: int = Field(default=1, description="预测天数(1=仅今日)", ge=1, le=7)


@tool(args_schema=GetForecastSchema)
@timeout_fallback(timeout_seconds=15)
def get_forecast(days: int = 1) -> str:
    """获取站级负荷/光伏/净负荷预测(kW,24h 逐时),与场站 tick 同源。

    返回每日 24h 负荷/光伏/净负荷曲线峰值、谷值、日电量,以及逆流风险时段
    (净负荷为负=光伏过剩可能逆流)。供削峰填谷/防逆流策略制定与优化建模。
    """
    stn = _stn()
    today = _date.today()
    lines: list[str] = ["【站级负荷·光伏预测】"]
    for i in range(max(1, days)):
        d = today
        if i > 0:
            from datetime import timedelta
            d = today + timedelta(days=i)
        try:
            fc = stn.get_forecast_day(d)
        except Exception as exc:
            lines.append(f"\n## {d.isoformat()}\n暂无数据({exc})")
            continue
        load = fc["load_kw"]
        pv = fc["pv_kw"]
        net = fc["net_load_kw"]
        reverse_hours = [h for h, v in enumerate(net) if v < 0]
        lines.append(
            f"\n## {fc['target_date']}\n"
            f"负荷: 峰{max(load):.0f}kW 谷{min(load):.0f}kW 日电量{fc['load_energy_kwh']:.0f}kWh\n"
            f"光伏: 峰{max(pv):.0f}kW 日发电{fc['pv_energy_kwh']:.0f}kWh 额定{fc['pv_rated_kwp']:.0f}kWp 季节因子{fc['seasonal_factor']}\n"
            f"净负荷(负荷-光伏): 峰{max(net):.0f}kW 谷{min(net):.0f}kW"
        )
        if reverse_hours:
            lines.append(
                f"光伏过剩(净负荷<0)时段: {', '.join(f'{h:02d}:00' for h in reverse_hours)} "
                f"(可能逆流,峰值过剩{-min(net):.0f}kW)"
            )
        else:
            lines.append("光伏过剩(净负荷<0)时段: 无")
    return "\n".join(lines)
