"""get_pv_status - 光伏阵列实时发电状态。"""
from langchain_core.tools import tool

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _stn


@tool
@timeout_fallback(timeout_seconds=15)
def get_pv_status() -> str:
    """获取光伏阵列实时发电状态(当前出力、辐照、额定容量、利用率)。"""
    ov = _stn().get_overview()
    pv = ov.get("pv")
    rated = ov.get("pv_rated_kwp", 0) or 0
    if pv is None:
        return "【光伏状态】\n• 暂无光伏设备或数据"
    util = (pv["generation_kw"] / rated * 100) if rated else 0.0
    return (
        f"【光伏状态】\n"
        f"• 当前出力: {pv['generation_kw']:.1f}kW\n"
        f"• 额定容量: {rated:.1f}kWp\n"
        f"• 辐照强度: {pv['irradiance']:.0f}W/m²\n"
        f"• 组件温度: {pv['temperature']:.1f}°C\n"
        f"• 状态: {pv['status']}\n"
        f"• 利用率: {util:.1f}%"
    )
