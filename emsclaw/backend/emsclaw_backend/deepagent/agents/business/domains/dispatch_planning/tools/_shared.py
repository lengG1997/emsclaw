"""dispatch_planning 工具共享辅助。

统一提供 PcsService / StationService / ScheduleMapper 句柄,以及调度优化输入聚合:
负荷·光伏预测(tick 同源,见 ems_data.forecast_from_ticks)、分时电价(24h 价格+时段名)、
储能聚合参数、站配置。所有工具按需 from ._shared import ... 使用。工具自取数据(不经 Lead),
避免 MW/kW 口径坑。
"""
from __future__ import annotations

import time
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from emsclaw_backend.mapper.schedule_mapper import ScheduleMapper
from emsclaw_backend.mapper.station_mapper import StationMapper
from emsclaw_backend.service.ems_data import forecast_from_ticks, month_max_demand_kw
from emsclaw_backend.service.pcs_service import PcsService, get_default_service as _get_pcs_svc
from emsclaw_backend.service.station_service import get_default_service as _get_station_svc

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_PERIOD_NAMES = {"sharp": "尖", "peak": "峰", "flat": "平", "valley": "谷"}
_CARBON_FACTOR = 0.581  # kgCO2/kWh(华东电网平均水平)
_SELL_PRICE = 0.0       # 上网电价(元/kWh);当前无余电上网收益


def _pcs() -> PcsService:
    return _get_pcs_svc()


def _stn():
    return _get_station_svc()


def _station_mapper() -> StationMapper:
    return StationMapper()


def _schedule_mapper() -> ScheduleMapper:
    return ScheduleMapper()


def _now() -> int:
    return int(time.time())


def _today() -> _date:
    return datetime.now(tz=_SHANGHAI).date()


def _date_str(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=_SHANGHAI).strftime("%Y-%m-%d")


def _tariff_24h(region: str = "default") -> tuple[list[float], list[str]]:
    """返回 (price[24], period_name[24])。无电价记录 → 全 0.7 元/平段。"""
    rows = _station_mapper().list_tariffs(region)
    price = [0.7] * 24
    period = ["平"] * 24
    for t in rows:
        ptype = t.period_type
        name = _PERIOD_NAMES.get(ptype, "平")
        for h in range(t.start_hour, min(t.end_hour, 24)):
            price[h] = float(t.energy_price)
            period[h] = name
    return price, period


def _storage_aggregate() -> dict:
    """聚合在线 PCS + 电池:总额定功率/总容量/SOC 上下限/效率/当前 SOC。

    返回 {total_rated_kw, total_cap_kwh, min_soc, max_soc, eff, initial_soc, n_pcs}。
    无设备 → total_rated=0(上游据此判定不可优化)。
    """
    rows = _pcs().list_status()
    if not rows:
        return {"total_rated_kw": 0.0, "total_cap_kwh": 0.0,
                "min_soc": 0.1, "max_soc": 0.9, "eff": 0.9,
                "initial_soc": 0.5, "n_pcs": 0}
    total_rated = 0.0
    total_cap = 0.0
    min_soc = 1.0
    max_soc = 0.0
    eff = 0.0
    soc_weighted = 0.0
    n = 0
    for r in rows:
        pcs = r.get("pcs")
        bat = r.get("battery")
        snap = r.get("latest_battery_snapshot")
        if pcs is None or bat is None:
            continue
        total_rated += float(pcs.rated_power_kw)
        total_cap += float(bat.rated_capacity_kwh)
        min_soc = min(min_soc, float(pcs.min_soc))
        max_soc = max(max_soc, float(pcs.max_soc))
        eff += float(pcs.rated_efficiency)
        soc = float(snap.soc) if snap is not None else float(bat.soc)
        soc_weighted += soc * float(bat.rated_capacity_kwh)
        n += 1
    if n == 0 or total_cap == 0:
        return {"total_rated_kw": 0.0, "total_cap_kwh": 0.0,
                "min_soc": 0.1, "max_soc": 0.9, "eff": 0.9,
                "initial_soc": 0.5, "n_pcs": 0}
    return {
        "total_rated_kw": total_rated,
        "total_cap_kwh": total_cap,
        "min_soc": min_soc,
        "max_soc": max_soc,
        "eff": eff / n,
        "initial_soc": soc_weighted / total_cap,
        "n_pcs": n,
    }


def _station_cfg() -> dict:
    """站配置:申报需量/防逆流设定/需量电价。无配置 → 默认值。"""
    cfg = _station_mapper().get_station_config()
    if cfg is None:
        return {"contract_demand_kw": 1000.0,
                "anti_reverse_setpoint_kw": 50.0,
                "demand_price_yuan_per_kw_month": 40.0}
    return {
        "contract_demand_kw": float(cfg.contract_demand_kw),
        "anti_reverse_setpoint_kw": float(cfg.anti_reverse_export_setpoint_kw),
        "demand_price_yuan_per_kw_month": float(cfg.demand_price_yuan_per_kw_month),
    }


def gather_inputs(target_date: _date) -> dict:
    """聚合调度优化所需全部输入(预测/电价/储能/站配置/需量口径)。

    v2:负荷/光伏预测从 tick 快照派生(ems_data.forecast_from_ticks),
    历史不足回退公式并标 source/confidence——agent 据此感知"预测其实是猜的"。
    需量口径加 demand_charge_basis.month_max_so_far_kw(当月已发生最大滚动需量)。
    """
    fc = forecast_from_ticks(target_date)
    price, period = _tariff_24h()
    cfg = _station_cfg()
    month_max = month_max_demand_kw()
    return {
        "target_date": target_date.isoformat(),
        "load_kw": list(fc["load_kw"]),
        "pv_kw": list(fc["pv_kw"]),
        "price": price,
        "period": period,
        "storage": _storage_aggregate(),
        "config": cfg,
        # 预测数据来源标注(让 agent 感知 fallback)
        "forecast_source": fc["source"],          # "tick_history" | "fallback_formula"
        "forecast_confidence": fc["confidence"],  # "high" | "low"
        "forecast_days_covered": fc["days_covered"],
        # 需量计费口径:max(当月已发生峰值, 当日 dmax)
        "demand_charge_basis": {
            "month_max_so_far_kw": round(month_max, 1),
            "note": "需量电费按月计,口径=max(当月已发生峰值, 当日 dmax)",
        },
    }
