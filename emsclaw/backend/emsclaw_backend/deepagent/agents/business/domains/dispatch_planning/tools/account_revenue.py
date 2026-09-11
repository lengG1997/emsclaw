"""account_revenue - 多维收益核算(只读)。

读当日 PcsSnapshot/MeterSnapshot/PvSnapshot + 分时电价 + active 计划,按收益来源
(峰谷套利/需量节省/光伏自用/碳减排)拆分,返回结构化数字 JSON。agent 据此叙述并发
<revenue_breakdown> 块。不输出人读 markdown。
"""
from __future__ import annotations

from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _CARBON_FACTOR, _pcs, _station_mapper, _today

_SH = ZoneInfo("Asia/Shanghai")
_PERIOD_NAMES = {"sharp": "尖", "peak": "峰", "flat": "平", "valley": "谷"}
_TICK_HOURS = 1.0 / 60.0  # 每 tick = 1min → kWh = kW × 1/60


class AccountRevenueSchema(BaseModel):
    date: str | None = Field(default=None, description="YYYY-MM-DD,缺省=今天")


def _day_bounds(d: _date) -> tuple[int, int]:
    start = int(datetime(d.year, d.month, d.day, tzinfo=_SH).timestamp())
    return start, start + 86400


def _hour(ts: int) -> int:
    return datetime.fromtimestamp(ts, tz=_SH).hour


@tool(args_schema=AccountRevenueSchema)
@timeout_fallback(timeout_seconds=20)
def account_revenue(date: str | None = None) -> dict:
    """核算某日多维收益:按来源(峰谷套利/需量节省/光伏自用/碳减排)与时段(尖峰平谷)拆分。

    数据来自当日 1min 快照(关口表/光伏/PCS)+ 分时电价 + active 充放电计划。返回结构化
    数字 JSON,供你生成收益报告并发 <revenue_breakdown> 块。无数据时如实返回 status=no_data。
    """
    try:
        d = _today() if not date else _date.fromisoformat(date)
    except ValueError:
        return {"status": "error", "reason": f"非法日期:{date}"}
    try:
        start, end = _day_bounds(d)
        sm = _station_mapper()
        # 电价 24h
        tariffs = sm.list_tariffs("default")
        price = [0.7] * 24
        pname = ["平"] * 24
        for t in tariffs:
            for h in range(t.start_hour, min(t.end_hour, 24)):
                price[h] = float(t.energy_price)
                pname[h] = _PERIOD_NAMES.get(t.period_type, "平")
        cfg = sm.get_station_config()
        demand_price = float(cfg.demand_price_yuan_per_kw_month) if cfg else 40.0
        # 光伏
        pv_dev = sm.first_pv_device()
        pv_snaps = sm.pv_snapshots_range(pv_dev.id, start, end) if pv_dev else []
        # 关口表
        meter_dev = sm.first_meter_device()
        m_snaps = sm.meter_snapshots_range(meter_dev.id, start, end) if meter_dev else []
        # PCS(聚合所有在线 PCS 的有功)
        pcs_rows = _pcs().list_status()
        per_pcs = []
        for r in pcs_rows:
            pcs = r.get("pcs")
            if pcs is None:
                continue
            per_pcs.append(_pcs().list_snapshots(pcs.id, start, end))

        if not m_snaps and not pv_snaps:
            return {"status": "no_data", "date": d.isoformat(),
                    "reason": f"{d.isoformat()} 无关口表/光伏快照,无法核算"}

        # 按小时聚合
        imp = [0.0] * 24
        exp = [0.0] * 24
        load = [0.0] * 24
        pvg = [0.0] * 24
        bat_charge = [0.0] * 24
        bat_discharge = [0.0] * 24
        for m in m_snaps:
            h = _hour(m.timestamp)
            imp[h] += float(m.import_kw) * _TICK_HOURS
            exp[h] += float(m.export_kw) * _TICK_HOURS
            load[h] += float(m.load_kw) * _TICK_HOURS
        for p in pv_snaps:
            h = _hour(p.timestamp)
            pvg[h] += float(p.generation_kw) * _TICK_HOURS
        for snaps in per_pcs:
            for s in snaps:
                h = _hour(s.timestamp)
                ap = float(s.active_power_kw)
                if ap > 0:
                    bat_charge[h] += ap * _TICK_HOURS
                else:
                    bat_discharge[h] += (-ap) * _TICK_HOURS

        import_kwh = sum(imp)
        export_kwh = sum(exp)
        pv_total = sum(pvg)
        pv_self_use = max(0.0, pv_total - export_kwh)
        charge_kwh = sum(bat_charge)
        discharge_kwh = sum(bat_discharge)

        # 收益来源
        arbitrage = 0.0  # 峰谷套利:放电收入 - 充电成本(按时段电价)
        for h in range(24):
            arbitrage += bat_discharge[h] * price[h] * 0.9 - bat_charge[h] * price[h]
        pv_self_use_savings = pv_self_use * (sum(price) / 24.0)  # 按均价避免购电
        baseline_peak = max((max(0.0, load[h] - pvg[h]) for h in range(24)), default=0.0)
        actual_peak = max(imp) if imp else 0.0
        demand_savings = max(0.0, baseline_peak - actual_peak) * demand_price / 30.0
        # 碳:实际进口电量碳排放 vs 无电池基线(光伏直供、余电不上网)进口碳排放
        actual_carbon = import_kwh * _CARBON_FACTOR
        baseline_import_kwh = sum(max(0.0, load[h] - pvg[h]) for h in range(24))
        baseline_carbon = baseline_import_kwh * _CARBON_FACTOR
        carbon_reduction = max(0.0, baseline_carbon - actual_carbon)

        # 时段分解(尖峰平谷)
        period_breakdown = {}
        for h in range(24):
            pn = pname[h]
            b = period_breakdown.setdefault(pn, {"charge_kwh": 0.0, "discharge_kwh": 0.0,
                                                 "import_kwh": 0.0, "revenue": 0.0})
            b["charge_kwh"] += bat_charge[h]
            b["discharge_kwh"] += bat_discharge[h]
            b["import_kwh"] += imp[h]
            b["revenue"] += bat_discharge[h] * price[h] * 0.9 - bat_charge[h] * price[h]
        for pn, b in period_breakdown.items():
            for k in b:
                b[k] = round(b[k], 2)

        total = arbitrage + pv_self_use_savings + demand_savings
        return {
            "status": "ok",
            "date": d.isoformat(),
            "sources": {
                "arbitrage_yuan": round(arbitrage, 2),
                "pv_self_use_savings_yuan": round(pv_self_use_savings, 2),
                "demand_savings_yuan": round(demand_savings, 2),
                "total_yuan": round(total, 2),
            },
            "energy": {
                "import_kwh": round(import_kwh, 1),
                "export_kwh": round(export_kwh, 1),
                "pv_total_kwh": round(pv_total, 1),
                "pv_self_use_kwh": round(pv_self_use, 1),
                "charge_kwh": round(charge_kwh, 1),
                "discharge_kwh": round(discharge_kwh, 1),
            },
            "demand": {
                "baseline_peak_kw": round(baseline_peak, 1),
                "actual_peak_kw": round(actual_peak, 1),
                "demand_savings_yuan": round(demand_savings, 2),
            },
            "carbon": {
                "actual_kg": round(actual_carbon, 1),
                "reduction_kg": round(carbon_reduction, 1),
            },
            "period_breakdown": period_breakdown,
        }
    except Exception as e:  # pragma: no cover
        return {"status": "error", "reason": f"收益核算失败:{e}"}
