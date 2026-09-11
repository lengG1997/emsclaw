"""set_station_config 工具 - 更新场站配置(申报需量/防逆流/容量与需量电价)。

写 StationConfig 单行(upsert),影响调度优化/收益核算/需量状态/总览等所有读配置的路径。
写操作,经 device_operation 域 HITL 审批后执行。与 reset_station_defaults(整体重建)不同,
本工具只精准更新传入字段,其余保持不变。
"""
import json

from langchain_core.tools import tool

from emsclaw_backend.entity.station import StationConfigUpdateDTO
from emsclaw_backend.service.station_service import StationSimService


@tool(args_schema=StationConfigUpdateDTO)
def set_station_config(
    contract_demand_kw: float | None = None,
    anti_reverse_export_setpoint_kw: float | None = None,
    capacity_price_yuan_per_kw_month: float | None = None,
    demand_price_yuan_per_kw_month: float | None = None,
) -> str:
    """更新场站配置:申报需量(kW)、防逆流上网阈值(kW)、容量电价/需量电价(元/kW·月)。

    至少传一项;未传的字段保持不变。更新后立即生效——调度策略生成、收益核算、
    需量状态读取到的都是新值。返回更新后的完整站配置。
    """
    data = {
        "contract_demand_kw": contract_demand_kw,
        "anti_reverse_export_setpoint_kw": anti_reverse_export_setpoint_kw,
        "capacity_price_yuan_per_kw_month": capacity_price_yuan_per_kw_month,
        "demand_price_yuan_per_kw_month": demand_price_yuan_per_kw_month,
    }
    try:
        cfg = StationSimService().update_station_config(data)
        return json.dumps({"success": True, "message": "站配置已更新",
                           "data": cfg}, ensure_ascii=False, indent=2)
    except ValueError as e:
        return json.dumps({"success": False, "message": str(e), "data": None},
                          ensure_ascii=False, indent=2)
