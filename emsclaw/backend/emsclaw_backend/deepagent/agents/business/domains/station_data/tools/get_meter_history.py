"""get_meter_history - 关口表历史趋势。"""
from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _stn, _now, _downsample, _hhmm


class GetMeterHistorySchema(BaseModel):
    hours: int = Field(default=24, description="回溯小时数", ge=1, le=168)


@tool(args_schema=GetMeterHistorySchema)
@timeout_fallback(timeout_seconds=15)
def get_meter_history(hours: int = 24) -> str:
    """获取关口表历史趋势(下网/上网/负荷/滚动需量/逆流标记)。

    数据来自 meter_snapshots(分钟级),降采样为 48 点趋势。
    用于需量控制与防逆流的历史回放与风险评估。
    """
    stn = _stn()
    to = _now()
    frm = to - hours * 3600
    try:
        rows = stn.meter_snapshots_range(frm, to)
    except Exception as exc:
        return f"【关口表历史】\n暂无数据({exc})"
    if not rows:
        return "【关口表历史】\n暂无数据"
    import_pts = _downsample([(r.timestamp, r.import_kw) for r in rows])
    export_pts = _downsample([(r.timestamp, r.export_kw) for r in rows])
    load_pts = _downsample([(r.timestamp, r.load_kw) for r in rows])
    demand_pts = _downsample([(r.timestamp, r.rolling_demand_kw) for r in rows])
    reverse_cnt = sum(1 for r in rows if r.reverse_flow)
    peak_import = max(r.import_kw for r in rows)
    peak_export = max(r.export_kw for r in rows)
    peak_demand = max(r.rolling_demand_kw for r in rows)

    def _series(pts):
        return ", ".join(f"{_hhmm(ts)}:{v:.0f}" for ts, v in pts)

    return (
        f"【关口表历史 - 近{hours}h, {len(rows)} 条原始点 -> 48 点趋势】\n"
        f"下网(进口)峰值={peak_import:.1f}kW 上网(出口)峰值={peak_export:.1f}kW "
        f"滚动需量峰值={peak_demand:.1f}kW 逆流告警次数={reverse_cnt}\n"
        f"下网趋势: {_series(import_pts)}\n"
        f"上网趋势: {_series(export_pts)}\n"
        f"负荷趋势: {_series(load_pts)}\n"
        f"滚动需量趋势: {_series(demand_pts)}"
    )
