"""emergency_stop - 紧急停止所有在线储能 PCS(置待机 + 0 功率)。"""
import time

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _pcs


class EmergencyStopSchema(BaseModel):
    reason: str = Field(default="", description="紧急停止原因(记录用)")
    device_id: str = Field(
        default="",
        description="指定 PCS 编号则只停该台;留空则停全部在线 PCS"
    )


@tool(args_schema=EmergencyStopSchema)
@timeout_fallback(timeout_seconds=15)
def emergency_stop(reason: str = "", device_id: str = "") -> str:
    """紧急停止储能设备:把指定(或全部在线)PCS 置为待机、功率归零。

    高风险熔断操作,下发后 override 4 小时不回落(防止自动恢复继续运行)。
    """
    svc = _pcs()
    expires = int(time.time()) + 4 * 3600  # 4h 不回落
    stopped: list[str] = []

    if device_id:
        pcs = svc._mapper.find_pcs_by_id(device_id) or svc._mapper.find_pcs_by_device_id(device_id)
        if pcs is None:
            return f"❌ 设备不存在: {device_id}"
        svc.set_mode(pcs.id, mode="standby", power_kw=0.0, expires_at=expires)
        stopped.append(device_id)
    else:
        pairs = svc._mapper.find_online_pcs_with_battery() or []
        for pcs, _ in pairs:
            svc.set_mode(pcs.id, mode="standby", power_kw=0.0, expires_at=expires)
            stopped.append(getattr(pcs, "device_id", pcs.id))

    if not stopped:
        return f"🚨 紧急停止:无在线 PCS 可停(原因: {reason or '未提供'})"
    return (
        f"🚨 紧急停止已执行(原因: {reason or '未提供'})\n"
        f"• 已停止 PCS: {', '.join(stopped)}\n"
        f"• 模式: 待机(功率 0kW)\n"
        f"• override 4 小时内不自动回落(需人工恢复)"
    )
