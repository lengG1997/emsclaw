# -*- coding: utf-8 -*-
"""场站"需量物理下限"独立核算器（模型选型评测的正确性 oracle）。

为什么需要它
------------
`scripts/model_matrix_report.py` 的交叉校验只能证明"模型之间是否收敛"，
不能证明"收敛到的数字对不对"。本脚本从**冻结的关口表历史负荷曲线**出发，
按储能硬约束独立解出可达到的最小需量峰值，作为对照真值。

模型给出的"物理下限"是对**次日负荷预测**求解的结果，而本脚本用的是**历史实测**
曲线，两者不是同一个量；因此本脚本的作用是**量级与机理校验**（例如能证伪
"下限 = 836 kW 这种纯功率受限的答案"），而非逐位比对。

约束（全部取自 DB，非假设）
--------------------------
- 并网侧放电能力 = Σ PCS.rated_power_kw × rated_efficiency
- 可用电量 = Σ battery.rated_capacity_kwh × (soc − min_soc)
- 申报需量 = station_config.contract_demand_kw

用法：
    python scripts/station_floor_oracle.py
    python scripts/station_floor_oracle.py --window-hours 24 --json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys

def _detect_pg_container() -> str:
    """定位 compose 起的 postgres 容器。可用 EMSCLAW_PG 显式覆盖。"""
    override = os.environ.get("EMSCLAW_PG")
    if override:
        return override
    try:
        out = subprocess.run(
            ["docker", "ps", "--filter", "label=com.docker.compose.service=postgres",
             "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=15,
        ).stdout.split()
        if out:
            return out[0]
    except Exception:
        pass
    return "postgres"


PG_CONTAINER = _detect_pg_container()
DB = os.environ.get("EMSCLAW_DB", "ai_agent")
PGUSER = os.environ.get("EMSCLAW_PGUSER", "agentone")


def psql(sql: str) -> list[list[str]]:
    r = subprocess.run(
        ["docker", "exec", "-i", PG_CONTAINER, "psql", "-U", PGUSER, "-d", DB,
         "-t", "-A", "-F", "|", "-c", sql],
        capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        sys.stderr.write(f"[psql] rc={r.returncode} {r.stderr[:300]}\n")
    out = (r.stdout or "").strip()
    return [ln.split("|") for ln in out.splitlines() if ln.strip()]


def hardware() -> dict:
    """从 DB 读储能硬约束。"""
    pcs = psql("SELECT rated_power_kw, rated_efficiency FROM pcs_devices;")
    bat = psql("SELECT rated_capacity_kwh, soc, soh FROM battery_devices;")
    cfg = psql("SELECT contract_demand_kw, anti_reverse_export_setpoint_kw "
               "FROM station_config LIMIT 1;")
    minsoc = psql("SELECT min(min_soc) FROM pcs_devices;")

    grid_kw = sum(float(p[0]) * float(p[1]) for p in pcs if len(p) >= 2)
    usable_kwh = 0.0
    for b in bat:
        if len(b) < 3:
            continue
        cap, soc, soh = float(b[0]), float(b[1]), float(b[2])
        usable_kwh += cap * max(0.0, soc - float(minsoc[0][0])) * soh
    return {
        "contract_demand_kw": float(cfg[0][0]),
        "anti_reverse_export_kw": float(cfg[0][1]),
        "n_pcs": len(pcs),
        "grid_discharge_kw": round(grid_kw, 1),
        "usable_energy_kwh": round(usable_kwh, 1),
        "min_soc": float(minsoc[0][0]),
    }


def truth_constants() -> dict:
    """可直接对账的实测真值 —— 模型答复里出现这些数字才算"有据"。

    这些不是"模型之间的共识"，而是 DB 里能独立读到的量：
      contract_demand_kw   申报需量（station_config）
      max_rolling_demand   本月已发生最大需量（rolling_demand 的极值）
      max_load_kw          累计最大负荷（load_kw 的极值）
    """
    r = psql("SELECT round(max(rolling_demand_kw)::numeric,1), "
             "round(max(load_kw)::numeric,1), "
             "round(max(import_kw)::numeric,1) FROM meter_snapshots;")
    out = {}
    if r and len(r[0]) >= 3:
        out = {
            "max_rolling_demand_kw": float(r[0][0]),
            "max_load_kw": float(r[0][1]),
            "max_import_kw": float(r[0][2]),
        }
    day = psql("SELECT to_char(to_timestamp(timestamp),'YYYY-MM-DD'), "
               "round(max(load_kw)::numeric,1) FROM meter_snapshots "
               "GROUP BY 1 ORDER BY 1;")
    out["daily_max_load_kw"] = {d[0]: float(d[1]) for d in day if len(d) >= 2}
    return out


def load_series(limit: int) -> list[tuple[int, float]]:
    rows = psql("SELECT timestamp, load_kw FROM meter_snapshots "
                f"ORDER BY timestamp DESC LIMIT {limit};")
    series = [(int(r[0]), float(r[1])) for r in rows if len(r) >= 2]
    series.sort()
    return series


def min_achievable_peak(series: list[tuple[int, float]], grid_kw: float,
                        usable_kwh: float, eff: float = 0.9,
                        step_h: float = 1.0 / 60.0) -> dict:
    """给定负荷序列，解"削峰所需电量 = 可用电量"的临界阈值。

    E(T) = Σ max(0, load_i − T) · dt  为把峰值压到 T 所需的放电量（并网侧）。
    电池并网可供电量 = usable_kwh · eff。E 关于 T 单调递减，二分求 E(T*) = 可供电量。
    同时峰值还受功率约束：T ≥ max_load − grid_kw。
    """
    loads = [v for _t, v in series]
    if not loads:
        return {}
    peak = max(loads)
    power_floor = peak - grid_kw
    supply = usable_kwh * eff

    def energy_above(t: float) -> float:
        return sum(max(0.0, v - t) for v in loads) * step_h

    lo, hi = 0.0, peak
    if energy_above(peak) >= supply:          # 储能富余，峰值可忽略
        t_star = peak
    else:
        for _ in range(200):
            mid = (lo + hi) / 2.0
            if energy_above(mid) > supply:
                lo = mid
            else:
                hi = mid
        t_star = hi
    return {
        "n_samples": len(loads),
        "span_hours": round(len(loads) * step_h, 2),
        "raw_peak_kw": round(peak, 1),
        "power_limited_floor_kw": round(power_floor, 1),
        "energy_supply_at_grid_kwh": round(supply, 1),
        "energy_limited_floor_kw": round(t_star, 1),
        "binding_constraint": "power" if power_floor > t_star else "energy",
        "floor_kw": round(max(power_floor, t_star), 1),
        "energy_above_1250_kwh": round(energy_above(1250.0), 1),
        "energy_above_1303_kwh": round(energy_above(1303.0), 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100000, help="取样条数上限")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    hw = hardware()
    series = load_series(args.limit)
    res = min_achievable_peak(series, hw["grid_discharge_kw"], hw["usable_energy_kwh"])
    tr = truth_constants()
    # 申报需量取 station_config 的权威值（oracle 的 hardware 段已含）
    tr["contract_demand_kw"] = hw["contract_demand_kw"]
    out = {"hardware": hw, "truth": tr, "oracle": res}

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    print("== 储能硬约束（取自 DB） ==")
    for k, v in hw.items():
        print(f"  {k:<26} {v}")
    print("== 可对账实测真值 ==")
    for k, v in tr.items():
        print(f"  {k:<26} {v}")
    print("== 独立核算的物理下限（基于冻结的历史负荷曲线） ==")
    for k, v in res.items():
        print(f"  {k:<28} {v}")
    if res:
        print("\n[读法] floor_kw 为可达到的最小需量峰值；")
        print(f"       申报需量 {hw['contract_demand_kw']:g} kW "
              f"{'低于' if hw['contract_demand_kw'] < res['floor_kw'] else '不低于'}该下限"
              f" → 目标{'不可达' if hw['contract_demand_kw'] < res['floor_kw'] else '可达'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
