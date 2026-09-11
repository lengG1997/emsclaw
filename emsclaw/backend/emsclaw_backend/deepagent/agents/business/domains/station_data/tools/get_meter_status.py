"""get_meter_status - 关口表实时状态。"""
from langchain_core.tools import tool

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _stn


@tool
@timeout_fallback(timeout_seconds=15)
def get_meter_status() -> str:
    """获取关口表实时状态:下网功率、上网功率、逆流标记、实测负荷、当前需量。"""
    ov = _stn().get_overview()
    m = ov.get("meter")
    if m is None:
        return "【关口表状态】\n• 暂无关口表数据"
    rf = "⚠️ 逆流告警" if m["reverse_flow"] else "正常"
    return (
        f"【关口表状态】\n"
        f"• 下网(进口)功率: {m['import_kw']:.1f}kW\n"
        f"• 上网(出口)功率: {m['export_kw']:.1f}kW\n"
        f"• 实测负荷: {m['load_kw']:.1f}kW\n"
        f"• 滚动需量(15min): {m['rolling_demand_kw']:.1f}kW\n"
        f"• 频率: {m['frequency']:.2f}Hz\n"
        f"• 功率因数: {m['power_factor']:.3f}\n"
        f"• 防逆流: {rf}"
    )
