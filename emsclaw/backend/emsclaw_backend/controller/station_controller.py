"""StationController - 场站级(光伏/关口表/天气/电价/日电量/需量)HTTP 入口。

端点(user 鉴权):
- GET /station/overview          场站总览聚合(一次拿全)
- GET /station/pv/snapshots      光伏时序曲线
- GET /station/meter/snapshots   关口表时序曲线(进/出口功率/逆流/需量)
- GET /station/weather/snapshots 气象时序曲线
- GET /station/tariff            电价时段表(尖/峰/平/谷)
- GET /station/energy/daily      日充放电电量与收益
- GET /station/demand            需量控制状态

调用 StationSimService 完成查询。
"""
from __future__ import annotations
import time
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from emsclaw_backend.service.station_service import StationSimService
from emsclaw_backend.user.dependencies import require_user, User
from emsclaw_backend.entity.station import StationConfigUpdateDTO

router = APIRouter(prefix="/station", tags=["station"])


class ApiResponse(BaseModel):
    code: int = Field(default=0)
    msg: str = Field(default="ok")
    data: Any = Field(default=None)


def _ok(data: Any, msg: str = "ok") -> ApiResponse:
    return ApiResponse(code=0, msg=msg, data=data)


def _snap_dict(snap) -> Optional[dict]:
    if snap is None:
        return None
    cols = {c.name for c in snap.__table__.columns}
    return {c: getattr(snap, c) for c in cols}


def _svc() -> StationSimService:
    from emsclaw_backend.service.station_service import get_default_service
    return get_default_service()


@router.get("/overview", response_model=ApiResponse, summary="场站总览聚合")
async def overview(_user: User = Depends(require_user)) -> ApiResponse:
    return _ok(_svc().get_overview(), msg="场站总览")


@router.get("/pv/snapshots", response_model=ApiResponse, summary="光伏时序曲线")
async def pv_snapshots(
    frm: int = Query(default=0, alias="from", description="起始墙钟秒"),
    to: int = Query(default=0, description="结束墙钟秒(0=现在)"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    to = to or int(time.time())
    rows = _svc().pv_snapshots_range(frm, to)
    return _ok([_snap_dict(r) for r in rows], msg=f"共 {len(rows)} 条光伏快照")


@router.get("/meter/snapshots", response_model=ApiResponse, summary="关口表时序曲线")
async def meter_snapshots(
    frm: int = Query(default=0, alias="from", description="起始墙钟秒"),
    to: int = Query(default=0, description="结束墙钟秒(0=现在)"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    to = to or int(time.time())
    rows = _svc().meter_snapshots_range(frm, to)
    return _ok([_snap_dict(r) for r in rows], msg=f"共 {len(rows)} 条关口表快照")


@router.get("/weather/snapshots", response_model=ApiResponse, summary="气象时序曲线")
async def weather_snapshots(
    frm: int = Query(default=0, alias="from", description="起始墙钟秒"),
    to: int = Query(default=0, description="结束墙钟秒(0=现在)"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    to = to or int(time.time())
    rows = _svc().weather_snapshots_range(frm, to)
    return _ok([_snap_dict(r) for r in rows], msg=f"共 {len(rows)} 条气象快照")


@router.get("/tariff", response_model=ApiResponse, summary="电价时段表")
async def tariff(_user: User = Depends(require_user)) -> ApiResponse:
    rows = _svc().list_tariffs()
    return _ok([_snap_dict(r) for r in rows], msg=f"共 {len(rows)} 条电价时段")


@router.get("/energy/daily", response_model=ApiResponse, summary="日充放电电量与收益")
async def energy_daily(
    days: int = Query(default=7, ge=1, le=30, description="最近天数"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    rows = _svc().list_daily_energy(days)
    return _ok([_snap_dict(r) for r in rows], msg=f"共 {len(rows)} 天电量记录")


@router.get("/demand", response_model=ApiResponse, summary="需量控制状态")
async def demand(_user: User = Depends(require_user)) -> ApiResponse:
    return _ok(_svc().get_demand(), msg="需量状态")


@router.put("/config", response_model=ApiResponse, summary="更新站配置(申报需量/防逆流/电价)")
async def update_config(
    body: StationConfigUpdateDTO,
    _user: User = Depends(require_user),
) -> ApiResponse:
    """更新站配置:申报需量、防逆流上网阈值、容量/需量电价。全可选项,至少传一项,值 ≥ 0。"""
    try:
        cfg = _svc().update_station_config(body.model_dump(exclude_none=True))
        return _ok(cfg, msg="站配置已更新")
    except ValueError as e:
        return ApiResponse(code=1, msg=str(e))


@router.get("/forecast", response_model=ApiResponse, summary="站级负荷/光伏预测(未来 N 天)")
async def forecast(
    days: int = Query(default=7, ge=1, le=30, description="预测天数"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    """站级 24h 负荷/光伏预测(kW),与 tick 同源(确定性双峰负荷 + 晴空辐照 × 季节因子)。"""
    return _ok(_svc().get_forecast(days=days), msg=f"未来 {days} 天站级预测")


@router.get("/forecast/day/{target_date}", response_model=ApiResponse, summary="单日站级预测")
async def forecast_day(
    target_date: date,
    _user: User = Depends(require_user),
) -> ApiResponse:
    """某日 24h 负荷/光伏/净负荷预测(kW)+ 聚合(峰/日电量)。"""
    return _ok(_svc().get_forecast_day(target_date), msg=f"{target_date} 站级预测")


@router.post("/seed-history", response_model=ApiResponse, summary="回灌历史快照(按 tick 逻辑回放)")
async def seed_history(
    hours: int = Query(default=168, ge=1, le=720, description="回灌小时数(默认 168=7 天)"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    """按 1 分钟一帧回放 tick 逻辑,灌满历史快照(光伏/关口表/天气/日电量)。

    默认 168h=10080 帧,每帧自带 commit,耗时较长(几分钟)。用于总览页图表冷启动。
    """
    return _ok(_svc().seed_history(hours=hours), msg=f"回灌 {hours}h 历史")
