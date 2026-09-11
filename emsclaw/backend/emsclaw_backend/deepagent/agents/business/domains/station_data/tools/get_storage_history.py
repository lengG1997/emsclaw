"""get_storage_history - 储能功率/SOC 历史趋势。"""
from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _pcs, _now, _downsample, _hhmm


class GetStorageHistorySchema(BaseModel):
    hours: int = Field(default=24, description="回溯小时数", ge=1, le=168)


@tool(args_schema=GetStorageHistorySchema)
@timeout_fallback(timeout_seconds=20)
def get_storage_history(hours: int = 24) -> str:
    """获取储能历史趋势(总有功功率 + 容量加权 SOC)。

    数据来自 pcs_snapshots/battery_snapshots(分钟级),按 60s 桶聚合后降采样 48 点。
    功率正值=充电,负值=放电。用于评估实际充放电与调度计划的吻合度、SOC 是否越限。
    """
    pcs = _pcs()
    to = _now()
    frm = to - hours * 3600
    try:
        rows = pcs.list_status() or []
    except Exception:
        rows = []
    if not rows:
        return "【储能历史】\n暂无 PCS 设备"

    p_bucket: dict[int, float] = {}
    s_bucket: dict[int, float] = {}
    cap_bucket: dict[int, float] = {}
    total_cap = 0.0
    for r in rows:
        p = r.get("pcs")
        bat = r.get("battery")
        pid = getattr(p, "id", None)
        cap = getattr(bat, "rated_capacity_kwh", 0) or 0
        total_cap += cap
        if not pid:
            continue
        try:
            psnaps = pcs.list_snapshots(pid, frm, to) or []
            bsnaps = pcs.list_battery_snapshots(pid, frm, to) or []
        except Exception:
            psnaps, bsnaps = [], []
        for s in psnaps:
            k = round(s.timestamp / 60) * 60
            p_bucket[k] = p_bucket.get(k, 0.0) + s.active_power_kw
        for s in bsnaps:
            k = round(s.timestamp / 60) * 60
            s_bucket[k] = s_bucket.get(k, 0.0) + s.soc * cap
            cap_bucket[k] = cap_bucket.get(k, 0.0) + cap

    if not p_bucket and not s_bucket:
        return "【储能历史】\n近时段无运行快照"
    keys = sorted(set(p_bucket) | set(s_bucket))
    power_pts = _downsample([(k, p_bucket.get(k, 0.0)) for k in keys])
    soc_pts = _downsample([
        (k, (s_bucket.get(k, 0.0) / cap_bucket[k] * 100) if cap_bucket.get(k) else 0.0)
        for k in keys
    ])
    powers = [p_bucket.get(k, 0.0) for k in keys]
    socs = [(s_bucket.get(k, 0.0) / cap_bucket[k] * 100) if cap_bucket.get(k) else 0.0 for k in keys]

    def _series(pts):
        return ", ".join(f"{_hhmm(ts)}:{v:.0f}" for ts, v in pts)

    return (
        f"【储能历史 - 近{hours}h, 总容量{total_cap:.0f}kWh】\n"
        f"有功峰值(充电+)={max(powers):.1f}kW 谷值(放电-)={min(powers):.1f}kW "
        f"SOC 区间={min(socs):.1f}%-{max(socs):.1f}%\n"
        f"有功趋势(kW): {_series(power_pts)}\n"
        f"SOC趋势(%): {_series(soc_pts)}"
    )
