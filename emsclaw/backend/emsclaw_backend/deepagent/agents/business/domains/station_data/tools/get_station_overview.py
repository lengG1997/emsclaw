"""get_station_overview - 场站全量当前态聚合。"""
from __future__ import annotations

from datetime import date as _date

from langchain_core.tools import tool

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _pcs, _stn, _pct, _PERIOD_NAMES


@tool
@timeout_fallback(timeout_seconds=20)
def get_station_overview() -> str:
    """一次性拉取场站全量当前态,供综合诊断。

    聚合:站配置 + 储能 KPI 与各 PCS/电池明细 + 光伏 + 关口表 + 需量 +
    当前电价时段 + 今日电量收益 + 气象 + 当日负荷/光伏预测概览。
    需要场站全貌时首先调用本工具。
    """
    stn = _stn()
    pcs = _pcs()
    ov = stn.get_overview()
    lines: list[str] = ["【场站全量当前态】"]

    cfg = ov.get("station_config") or {}
    if cfg:
        lines.append(
            f"\n## 站配置\n区域={cfg.get('region','default')} "
            f"申报需量={cfg.get('contract_demand_kw',0):.0f}kW "
            f"防逆流阈值={cfg.get('anti_reverse_export_setpoint_kw',0):.0f}kW "
            f"需量电价={cfg.get('demand_price_yuan_per_kw_month',0):.1f}元/kW·月 "
            f"基本容量电价={cfg.get('capacity_price_yuan_per_kw_month',0):.1f}元/kW·月"
        )

    try:
        rows = pcs.list_status() or []
    except Exception:
        rows = []
    total_power = 0.0
    total_cap = 0.0
    soc_w = 0.0
    online = 0
    detail: list[str] = []
    for r in rows:
        psnap = r.get("latest_pcs_snapshot")
        bsnap = r.get("latest_battery_snapshot")
        bat = r.get("battery")
        p = r.get("pcs")
        pid = getattr(p, "device_id", None) or getattr(p, "id", "?")
        if psnap:
            total_power += psnap.active_power_kw
            online += 1
        if bat:
            total_cap += bat.rated_capacity_kwh
            if bat.soc is not None:
                soc_w += bat.soc * bat.rated_capacity_kwh
        soc_raw = (bsnap.soc if bsnap and bsnap.soc is not None else getattr(bat, "soc", 0)) or 0
        temp = (bsnap.temperature if bsnap else None)
        min_soc = getattr(p, "min_soc", 0.1)
        max_soc = getattr(p, "max_soc", 0.9)
        detail.append(
            f"  - {pid}: 功率={(psnap.active_power_kw if psnap else 0):.1f}kW "
            f"模式={(psnap.mode if psnap else '-')} SOC={soc_raw*100:.1f}% "
            f"SOH={getattr(bat,'soh',0)*100:.1f}% "
            f"温度={(temp if temp is not None else '-')}"
            f" SOC限值[{min_soc*100:.0f}%-{max_soc*100:.0f}%]"
        )
    wsoc = (soc_w / total_cap) if total_cap else 0.0
    direction = "放电方向" if total_power < 0 else ("充电方向" if total_power > 0 else "待机")
    lines.append(
        f"\n## 储能实时\n总有功={total_power:.1f}kW({direction}) "
        f"总容量={total_cap:.0f}kWh 加权SOC={_pct(wsoc)} 在线PCS={online}/{len(rows)}"
    )
    lines.extend(detail if detail else ["  暂无 PCS 设备"])

    pv = ov.get("pv")
    pv_rated = ov.get("pv_rated_kwp", 0) or 0
    if pv:
        util = (pv["generation_kw"] / pv_rated * 100) if pv_rated else 0.0
        lines.append(
            f"\n## 光伏\n出力={pv['generation_kw']:.1f}kW 额定={pv_rated:.0f}kWp "
            f"辐照={pv['irradiance']:.0f}W/m² 温度={pv['temperature']:.1f}℃ "
            f"状态={pv['status']} 利用率={util:.1f}%"
        )
    else:
        lines.append("\n## 光伏\n暂无光伏设备或数据")

    m = ov.get("meter")
    if m:
        rf = "⚠️逆流告警" if m.get("reverse_flow") else "正常"
        lines.append(
            f"\n## 关口表\n下网(进口)={m['import_kw']:.1f}kW 上网(出口)={m['export_kw']:.1f}kW "
            f"负荷={m['load_kw']:.1f}kW 滚动需量(15min)={m['rolling_demand_kw']:.1f}kW "
            f"频率={m['frequency']:.2f}Hz 功率因数={m['power_factor']:.3f} 防逆流={rf}"
        )
    else:
        lines.append("\n## 关口表\n暂无关口表数据")

    try:
        d = stn.get_demand()
        risk = "⚠️超申报需量" if d["current_demand_kw"] > d["contract_demand_kw"] else "正常"
        lines.append(
            f"\n## 需量控制\n当前={d['current_demand_kw']:.1f}kW 今日最大={d['max_demand_today_kw']:.1f}kW "
            f"申报={d['contract_demand_kw']:.0f}kW 占比={_pct(d['demand_ratio'])} 状态={risk}"
        )
    except Exception:
        lines.append("\n## 需量控制\n暂无数据")

    cur = ov.get("tariff_current")
    if cur:
        lines.append(
            f"\n## 当前电价\n时段={_PERIOD_NAMES.get(cur['period_type'], cur['period_type'])} "
            f"{cur['start']}-{cur['end']} @ {cur['energy_price']}元/kWh"
        )
    e = ov.get("energy_today")
    if e:
        lines.append(
            f"\n## 今日电量与收益({e['date']})\n"
            f"充电={e['charge_kwh']:.2f}kWh 放电={e['discharge_kwh']:.2f}kWh 净收益={e['revenue']:.2f}元"
        )
    w = ov.get("weather")
    if w:
        lines.append(
            f"\n## 气象\n辐照={w['irradiance']:.0f}W/m² 温度={w['temperature']:.1f}℃ "
            f"云量={w['cloud_cover']:.2f} 风速={w['wind_speed']:.1f}m/s"
        )
    try:
        fc = stn.get_forecast_day(_date.today())
        lines.append(
            f"\n## 今日预测概览\n负荷峰值={fc['load_peak_kw']:.0f}kW 光伏峰值={fc['pv_peak_kw']:.0f}kW "
            f"负荷日电量={fc['load_energy_kwh']:.0f}kWh 光伏日电量={fc['pv_energy_kwh']:.0f}kWh "
            f"季节因子={fc['seasonal_factor']}"
        )
    except Exception:
        lines.append("\n## 今日预测概览\n暂无数据")
    return "\n".join(lines)
