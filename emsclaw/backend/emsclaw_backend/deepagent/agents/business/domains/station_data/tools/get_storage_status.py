"""get_storage_status - 储能本体实时状态(合并 PCS + 电池)。"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _pcs


class GetStorageStatusSchema(BaseModel):
    device_id: str = Field(
        default="PCS-001",
        description="储能单元编号(PCS-xxx 或 BAT-xxx 均可)"
    )


@tool(args_schema=GetStorageStatusSchema)
@timeout_fallback(timeout_seconds=15)
def get_storage_status(device_id: str = "PCS-001") -> str:
    """获取储能本体的实时运行状态:PCS 变流器参数 + 配对电池 BMS 状态。

    传入 PCS 编号或电池编号均可,自动定位 PCS 与其配对电池,返回合并视图。
    """
    svc = _pcs()
    m = svc._mapper
    # 先按 PCS 查;查不到再按电池查其配对 PCS
    pcs = m.find_pcs_by_id(device_id) or m.find_pcs_by_device_id(device_id)
    bat = None
    if pcs is not None and pcs.battery_id:
        bat = m.find_battery_by_id(pcs.battery_id) or m.find_battery_by_device_id(pcs.battery_id)
    if pcs is None:
        # 按 battery 查,再反查配对 PCS
        bat = bat or m.find_battery_by_id(device_id) or m.find_battery_by_device_id(device_id)
        if bat is not None:
            for p in (m.find_all_pcs_with_latest() or []):
                po = p.get("pcs")
                if po is not None and getattr(po, "battery_id", None) == bat.id:
                    pcs = po
                    p_row = p
                    break
    if pcs is None and bat is None:
        return f"【储能状态 - {device_id}】\n• 设备不存在"

    lines = [f"【储能状态 - {device_id}】"]
    # PCS 部分
    if pcs is not None:
        snap = m.latest_pcs_snapshot(pcs.id)
        if snap is not None:
            power = snap.active_power_kw
            direction = "放电" if power < 0 else ("充电" if power > 0 else "待机")
            lines.append(
                f"\n## PCS\n"
                f"• 有功功率: {power:.1f}kW ({direction})\n"
                f"• 无功功率: {snap.reactive_power_kvar:.1f}kVar\n"
                f"• 运行模式: {snap.mode}\n"
                f"• 交流侧电压: {snap.ac_voltage_v:.1f}V\n"
                f"• 直流侧电压: {snap.dc_voltage_v:.1f}V\n"
                f"• 效率: {snap.efficiency*100:.1f}%\n"
                f"• 状态: {snap.status}\n"
                f"• SOC 限值: {pcs.min_soc*100:.0f}%-{pcs.max_soc*100:.0f}%"
            )
        else:
            lines.append("\n## PCS\n• 暂无运行数据")
    # 电池部分
    if bat is not None:
        snap = m.latest_battery_snapshot(bat.id)
        soc = (snap.soc if snap else bat.soc) * 100
        voltage = (snap.voltage if snap else bat.rated_voltage_v)
        current = (snap.current_a if snap else 0.0)
        temp = (snap.temperature if snap else 28.0)
        cycles = (snap.cycle_count if snap else bat.cycle_count)
        sign = "放电中" if current < 0 else ("充电中" if current > 0 else "静置")
        lines.append(
            f"\n## 电池\n"
            f"• SOC (荷电状态): {soc:.1f}%\n"
            f"• SOH (健康状态): {bat.soh*100:.1f}%\n"
            f"• 电压: {voltage:.1f}V\n"
            f"• 电流: {current:.1f}A ({sign})\n"
            f"• 温度: {temp:.1f}°C\n"
            f"• 循环次数: {cycles} 次\n"
            f"• 额定容量: {bat.rated_capacity_kwh}kWh"
        )
    return "\n".join(lines)
