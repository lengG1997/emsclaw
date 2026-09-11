"""PcsController — PCS 模拟 HTTP 入口。

端点:
- POST /pcs/sim/tick            beat 调用,推进一帧(X-API-Key 鉴权,同 chat.py)
- GET  /pcs/{pcs_id}/status     最新快照(user 鉴权)
- GET  /pcs/{pcs_id}/snapshots  时序曲线(user 鉴权)
- POST /pcs/{pcs_id}/mode       手动设模式(user 鉴权)

调用 PcsService 完成业务逻辑。
"""
from __future__ import annotations
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field

from emsclaw_backend.config import settings
from emsclaw_backend.service.pcs_service import PcsService
from emsclaw_backend.service.station_service import StationSimService
from emsclaw_backend.user.dependencies import require_user, User

router = APIRouter(prefix="/pcs", tags=["pcs"])


class ApiResponse(BaseModel):
    code: int = Field(default=0)
    msg: str = Field(default="ok")
    data: Any = Field(default=None)


class SetModeBody(BaseModel):
    mode: str = Field(..., description="charge / discharge / standby / auto")
    power_kw: float = Field(default=0.0, ge=0, description="目标绝对功率(kW)")
    expires_at: int = Field(default=0, description="override 到期墙钟秒;0=立即过期")


def _ok(data: Any, msg: str = "ok") -> ApiResponse:
    return ApiResponse(code=0, msg=msg, data=data)


async def _verify_task_api_key(x_api_key: Optional[str] = None) -> None:
    """If TASK_SERVICE_API_KEY is set, require it in X-API-Key header."""
    if not settings.task_service_api_key:
        return
    if (x_api_key or "").strip() != settings.task_service_api_key.strip():
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


@router.post("/sim/tick", response_model=ApiResponse, summary="推进模拟一帧")
async def tick(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> ApiResponse:
    """task-service beat 每分钟调用;推进所有 online PCS 一帧 + 场站级数据(光伏/关口表/天气/日电量)。

    StationSimService.tick 内部先调 PcsService.tick_all(返回 ticked),再生成场站数据。
    响应仍含 ``ticked`` 字段(保端点契约)。
    """
    await _verify_task_api_key(x_api_key)
    try:
        result = StationSimService().tick()
        return _ok(result, msg=f"推进 {result['ticked']} 台 PCS")
    except Exception as e:
        logger.exception("station tick failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=ApiResponse, summary="列出全部 PCS 及状态")
async def list_pcs(_user: User = Depends(require_user)) -> ApiResponse:
    """返回所有 PCS 的配置 + 关联电池 + 各自最新快照(供仪表盘 KPI 与主 PCS 选择)。"""
    rows = PcsService().list_status()
    return _ok([_snap_dict_full(r) for r in rows], msg=f"共 {len(rows)} 台 PCS")


@router.get("/schedule", response_model=ApiResponse, summary="充放电调度计划")
async def get_charge_schedule(
    date: str | None = Query(default=None, description="查询日期 YYYY-MM-DD,缺省=今天"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    """充放电调度计划:读指定日期已下发(active)的 ChargeSchedule,供场站总览页展示。"""
    return _ok(PcsService().get_charge_schedule(target_date=date), msg="充放电调度计划")


@router.get("/{pcs_id}/status", response_model=ApiResponse, summary="最新快照")
async def get_status(
    pcs_id: str,
    _user: User = Depends(require_user),
) -> ApiResponse:
    st = PcsService().get_status(pcs_id)
    if st is None:
        raise HTTPException(status_code=404, detail=f"PCS '{pcs_id}' 不存在")
    return _ok({
        "pcs": _snap_dict(st.get("pcs")),
        "battery": _snap_dict(st.get("battery")),
    })


@router.get("/{pcs_id}/snapshots", response_model=ApiResponse, summary="时序曲线")
async def get_snapshots(
    pcs_id: str,
    frm: int = Query(default=0, alias="from", description="起始墙钟秒"),
    to: int = Query(default=0, description="结束墙钟秒(0=现在)"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    to = to or int(__import__("time").time())
    rows = PcsService().list_snapshots(pcs_id, frm, to)
    return _ok([_snap_dict(r) for r in rows], msg=f"共 {len(rows)} 条快照")


@router.get("/{pcs_id}/battery-snapshots", response_model=ApiResponse, summary="电池时序曲线")
async def get_battery_snapshots(
    pcs_id: str,
    frm: int = Query(default=0, alias="from", description="起始墙钟秒"),
    to: int = Query(default=0, description="结束墙钟秒(0=现在)"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    """电池历史快照(SOC/电压/电流/温度),供场站总览页绘制 SOC 曲线。"""
    to = to or int(__import__("time").time())
    rows = PcsService().list_battery_snapshots(pcs_id, frm, to)
    return _ok([_snap_dict(r) for r in rows], msg=f"共 {len(rows)} 条电池快照")


@router.post("/{pcs_id}/mode", response_model=ApiResponse, summary="手动设模式")
async def set_mode(
    pcs_id: str,
    body: SetModeBody,
    _user: User = Depends(require_user),
) -> ApiResponse:
    try:
        updated = PcsService().set_mode(
            pcs_id, mode=body.mode, power_kw=body.power_kw,
            expires_at=body.expires_at,
        )
        return _ok({"pcs_id": updated.id, "override_mode": updated.override_mode},
                    msg=f"PCS '{pcs_id}' 模式已设为 {body.mode}")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


def _snap_dict(snap) -> Optional[dict]:
    if snap is None:
        return None
    cols = {c.name for c in snap.__table__.columns}
    return {c: getattr(snap, c) for c in cols}


def _snap_dict_full(item: dict) -> dict:
    return {
        "pcs": _snap_dict(item.get("pcs")),
        "battery": _snap_dict(item.get("battery")),
        "latest_pcs_snapshot": _snap_dict(item.get("latest_pcs_snapshot")),
        "latest_battery_snapshot": _snap_dict(item.get("latest_battery_snapshot")),
    }
