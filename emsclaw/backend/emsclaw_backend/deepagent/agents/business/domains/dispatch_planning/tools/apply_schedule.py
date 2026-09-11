"""apply_schedule - 下发充放电计划到 PCS 实际调度(HITL 审批)。

工具被 get_interrupt_on 声明,框架在执行 body 前拦截审批;approve 后 body 运行:
校验 24 条 intervals → supersede 旧 active → insert 新 active(status=active)。
此后 PcsService.decide_mode_and_power 读该 active 计划驱动每 tick 充放电。
"""
from __future__ import annotations

import shortuuid
import time

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _date_str, _now, _schedule_mapper, _today

_VALID_MODES = {"charge", "discharge", "standby"}


class IntervalSpec(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    mode: str = Field(..., description="charge | discharge | standby")
    power_kw: float = Field(..., ge=0)
    power_ratio: float = Field(..., ge=0, le=1)
    soc_target_pct: float = Field(..., ge=0, le=1)
    period: str = Field(default="")
    tariff_price: float = Field(default=0.0)


class ApplyScheduleSchema(BaseModel):
    schedule: list[IntervalSpec] = Field(..., description="24 条 DispatchInterval(调度优化输出)")
    strategies: list[str] = Field(default_factory=list, description="策略组合(如 [\"省钱\",\"保电池\"];空=省钱)")
    target_date: str | None = Field(default=None, description="YYYY-MM-DD,缺省=今天")
    objective: dict = Field(default_factory=dict, description="计划 summary 快照(供解释/对比)")


@tool(args_schema=ApplyScheduleSchema)
@timeout_fallback(timeout_seconds=15)
def apply_schedule(
    schedule: list,
    strategies: list | None = None,
    target_date: str | None = None,
    objective: dict | None = None,
    config: RunnableConfig | None = None,
) -> dict:
    """下发 24h 充放电计划到储能 PCS 实际调度。下发后立即生效,当日每 tick 的 PCS
    充放电按本计划 power_ratio 执行;旧计划自动失效。

    参数取自 optimize_dispatch 的输出(schedule + summary)。返回 {schedule_id, status, ...}。
    """
    from emsclaw_backend.db.models import ChargeSchedule
    try:
        if len(schedule) != 24:
            return {"status": "rejected", "reason": f"计划必须为 24 条,收到 {len(schedule)} 条"}
        intervals = []
        for seg in schedule:
            seg = seg if isinstance(seg, dict) else seg.model_dump()
            mode = seg.get("mode")
            if mode not in _VALID_MODES:
                return {"status": "rejected", "reason": f"非法 mode:{mode}"}
            intervals.append({
                "hour": int(seg["hour"]),
                "mode": mode,
                "power_kw": float(seg.get("power_kw", 0.0)),
                "power_ratio": float(seg.get("power_ratio", 0.0)),
                "soc_target_pct": float(seg.get("soc_target_pct", 0.0)),
                "period": seg.get("period", ""),
                "tariff_price": float(seg.get("tariff_price", 0.0)),
            })
        intervals.sort(key=lambda s: s["hour"])

        td = target_date or _today().isoformat()
        now = _now()
        # 从 LangGraph 运行时配置中提取 thread_id(=session_id),用于追溯创建来源
        thread_id = "unknown"
        if config and "configurable" in config and config["configurable"].get("thread_id"):
            thread_id = config["configurable"]["thread_id"]
        mapper = _schedule_mapper()
        # 先 supersede 旧 active(若有),再 insert 新 active
        mapper.supersede_active(td, now)
        rec = ChargeSchedule(
            id=f"SCH-{shortuuid.uuid()[:8].upper()}",
            target_date=td, status="active", strategies=list(strategies or []),
            intervals=intervals, objective=objective or {},
            created_by=thread_id, created_at=now, updated_at=now,
        )
        rec = mapper.insert(rec)
        return {
            "status": "active",
            "schedule_id": rec.id,
            "target_date": td,
            "strategies": list(strategies or []),
            "summary": objective or {},
            "note": "计划已下发并立即生效,储能将按计划充放电。",
        }
    except Exception as e:  # pragma: no cover
        return {"status": "error", "reason": f"下发失败:{e}"}
