"""get_tariff - 完整电价时段表与当前时段。"""
from __future__ import annotations

from langchain_core.tools import tool

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _stn, _PERIOD_NAMES


@tool
@timeout_fallback(timeout_seconds=15)
def get_tariff() -> str:
    """获取完整电价时段表(尖/峰/平/谷 + 单价 + 时段)与当前所处时段。"""
    stn = _stn()
    rows = stn.list_tariffs()
    cur = (stn.get_overview().get("tariff_current") or {})
    lines = ["【电价时段表】"]
    if cur:
        lines.append(
            f"• 当前时段: {_PERIOD_NAMES.get(cur['period_type'], cur['period_type'])} "
            f"{cur['start']}-{cur['end']} @ {cur['energy_price']}元/kWh"
        )
    lines.append("• 全天时段(按价格降序排):")
    for r in sorted(rows, key=lambda x: -x.energy_price):
        lines.append(
            f"  {r.start_hour:02d}:00-{r.end_hour:02d}:00  "
            f"{_PERIOD_NAMES.get(r.period_type, r.period_type)}  {r.energy_price}元/kWh"
        )
    prices = [r.energy_price for r in rows]
    if prices:
        lines.append(
            f"• 价差: 最高{max(prices)}元/kWh 最低{min(prices)}元/kWh "
            f"峰谷价差{max(prices)-min(prices):.2f}元/kWh"
        )
    return "\n".join(lines)
