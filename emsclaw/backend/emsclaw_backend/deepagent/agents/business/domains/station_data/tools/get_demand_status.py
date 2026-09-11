"""get_demand_status - 需量控制状态。"""
from langchain_core.tools import tool

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _stn


@tool
@timeout_fallback(timeout_seconds=15)
def get_demand_status() -> str:
    """获取需量控制状态:当前需量、今日最大需量、申报需量、超需量风险。"""
    d = _stn().get_demand()
    risk = "⚠️ 超申报需量" if d["current_demand_kw"] > d["contract_demand_kw"] else "正常"
    return (
        f"【需量控制】\n"
        f"• 当前需量: {d['current_demand_kw']:.1f}kW\n"
        f"• 今日最大需量: {d['max_demand_today_kw']:.1f}kW\n"
        f"• 申报需量: {d['contract_demand_kw']:.1f}kW\n"
        f"• 需量电价: {d['demand_price_yuan_per_kw_month']:.2f}元/kW·月\n"
        f"• 需量占比: {d['demand_ratio']*100:.1f}%\n"
        f"• 状态: {risk}"
    )
