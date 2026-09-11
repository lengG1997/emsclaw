"""纯函数 LP 求解器:DispatchInputs → DispatchResult。

无 IO、无全局状态、可单测。从 optimize_dispatch.py 拆出(scipy HiGHS 已验证正确,
此模块只负责数学,不涉及站配置/电价读取等 IO)。

新增能力:
- apply_scenario:what-if 缩放(load/pv/price),不改变 LP 结构
- sanity_check:能量守恒自检(ΔSOC ≈ ΣPc·η − ΣPd/η),避免"模型自己 rationalize 异常"
- active_constraints:用户约束在解里是否 binding(松弛推断)
- summary.carbon_cost:绿电优先的电费代价(w_carbon>0 时重解一次 w_carbon=0 对照)
- run_sweep/SweepSpec:敏感性批量扫描(显式采样点 + 内部二分临界值),
  替代 agent 逐值循环试探
"""
from __future__ import annotations

import copy
import math
from typing import Any, Literal

from pydantic import BaseModel, Field

try:
    from scipy.optimize import linprog
    _SCIPY_AVAILABLE = True
except Exception:  # pragma: no cover
    _SCIPY_AVAILABLE = False

_N = 24  # 小时数(15min 分辨率属"明确不做",用保守系数过渡)

# 需量考核口径系数:LP 按小时均值建模,国内需量电费按 15 分钟滑窗最大值计,
# 小时内负荷波动会被平均掉——dmax 约束与需量电费按 k×小时峰值保守估计。
_DEMAND_15MIN_FACTOR = 1.15

# demand_ok 判定容差(kW):peak_demand_kw 是**四舍五入到 0.1 的报告值**,而 cap 是精确值,
# 严格比较会在边界上误判"越限"(实测 cap=1284.55 时报告 1284.6,差 0.05 kW 就翻盘,
# 导致 find_limit 把可行边界找错)。1.0 kW 相对 1000+ kW 的需量上限是 0.1% 量级。
_DEMAND_OK_TOL_KW = 1.0

# ── reserve 档位─────────────────────────────────────────
# 背景:裸传 `{"type":"reserve"}` 若按 `0.30×峰荷` 取关键负荷、保障 2 小时,
# 会强制**每小时 SOC ≥ 2×0.3×峰荷 / cap**。对「电池容量小、申报需量紧」的站
# (实测:峰荷 1510kW / cap 2000kWh / 申报 1250kW),该硬下限把物理需量下限从
# 1046.5 抬到 1258.3 kW,直接超过申报值 → **必然 infeasible**;
# 模型据此以为"参数写错了",逐轮试探 hours_val / critical_load_kw 组合,
# 单卡浪费 41% 墙钟。
# 故改为三档显式档位,关键负荷功率按峰荷比例取,保障时长统一 2 小时:
#   低 = 0.10×峰荷(只保最基本关键负荷) / 中 = 0.20×峰荷(**缺省**) / 高 = 0.30×峰荷(接近全部重要负荷)
# 「高」档等价于裸传语义,保留以便需要最强保障时显式选用(可能因需量上限不可行)。
_RESERVE_LEVEL_FRACTION = {"低": 0.10, "中": 0.20, "高": 0.30}
_RESERVE_DEFAULT_FRACTION = _RESERVE_LEVEL_FRACTION["中"]
_RESERVE_DEFAULT_HOURS = 2.0

# 变量布局(共 193 维):Pc,Pd,Pim,Pex,Pcurt 各 N;soc N;dmax 1;rup,rdn 各 N
_OFF = {
    "Pc": 0, "Pd": _N, "Pim": 2 * _N, "Pex": 3 * _N, "Pcurt": 4 * _N,
    "soc": 5 * _N, "dmax": 6 * _N, "rup": 6 * _N + 1, "rdn": 6 * _N + 1 + _N,
}
_NVARS = 6 * _N + 1 + 2 * _N

# 碳排放因子(kgCO2/kWh,华东电网平均)——solver 自留一份,与 _shared 同步
_CARBON_FACTOR = 0.581
# 上网电价(元/kWh);当前无余电上网收益
_SELL_PRICE = 0.0

# 能量守恒校验容差:|ΔSOC×cap − (ΣPc·η − ΣPd/η)| < 此值视为自洽
# LP 数值精度 + 功率四舍五入(0.1kW)累计误差远小于此,真 bug(如旧 SOC 量纲错误)
# 偏差会到 600+ kWh,容差留足避免误报。
_ENERGY_SANITY_TOL_KWH = 5.0


def _row() -> list[float]:
    return [0.0] * _NVARS


# ── 输入模型(从 optimize_dispatch.py 提到此处供 solver 单测直接构造)───
class ConstraintSpec(BaseModel):
    """自然语言约束的结构化形式(agent 翻译 NL → 此结构)。"""
    type: Literal[
        "mode_lock", "demand_cap", "soc_target", "throughput_cap",
        "no_export", "cost_cap", "reserve", "respect_declared_demand",
    ] = Field(..., description="约束类型")
    hours: list[int] | None = Field(default=None, description="mode_lock:锁定的小时列表(0-23)")
    mode: Literal["charge", "discharge", "standby"] | None = Field(
        default=None,
        description="mode_lock:锁定的模式(discharge=禁充+放电≥min_power,charge=禁放+充电≥min_power;"
                    "min_power 缺省 0 时待机也合法)")
    min_power_kw: float | None = Field(default=None, description="mode_lock:该时段最小绝对功率")
    value_kw: float | None = Field(default=None, description="demand_cap:需量上限(kW)")
    hour: int | None = Field(default=None, description="soc_target:目标小时(0-23)")
    soc_pct: float | None = Field(default=None, description="soc_target/reserve:目标 SOC(0-1)")
    kwh: float | None = Field(default=None, description="throughput_cap:日吞吐上限(kWh)")
    yuan: float | None = Field(default=None, description="cost_cap:日电费上限(元)")
    level: Literal["低", "中", "高"] | None = Field(
        default=None,
        description="reserve:备用档位(**推荐用法**)。低/中/高分别按峰荷的 10%/20%/30% "
                    "作为关键负荷功率,保障时长固定 2 小时。裸传 reserve(不给 level 与 "
                    "critical_load_kw)等价于**中档**。")
    hours_val: float | None = Field(
        default=None, description="reserve:保障小时数(缺省 2)")
    critical_load_kw: float | None = Field(
        default=None,
        description="reserve:关键负荷功率(kW)。**显式给值时优先于 level**;"
                    "与 level 同时缺省时按中档(0.20×峰荷)估算")


class ScenarioSpec(BaseModel):
    """what-if 场景假设(对输入做缩放,不改变 LP 结构)。"""
    load_scale: float = Field(default=1.0, description="负荷缩放倍数(+20% → 1.2)")
    pv_scale: float = Field(default=1.0, description="光伏出力缩放倍数(阴天 → 0.3)")
    price_delta: float = Field(default=0.0, description="电价整体平移(元/kWh,可为负)")


# ── 场景缩放 ───────────────────────────────────────────────────
def apply_scenario(inputs: dict, scenario: "ScenarioSpec | dict | None") -> dict:
    """对 inputs 做 what-if 缩放(load/pv/price),返回新 dict(不改原对象)。

    缩放只改输入数据,不改变 LP 结构、约束、站配置。空 scenario 或全 1.0/0.0 → 原样返回。
    标记 scenario_applied 字段透传到最终结果,让 agent 感知"这是假设值"。
    """
    if scenario is None:
        return inputs
    if isinstance(scenario, BaseModel):
        scenario = scenario.model_dump()
    load_scale = float(scenario.get("load_scale", 1.0) or 1.0)
    pv_scale = float(scenario.get("pv_scale", 1.0) or 1.0)
    price_delta = float(scenario.get("price_delta", 0.0) or 0.0)
    if load_scale == 1.0 and pv_scale == 1.0 and price_delta == 0.0:
        return inputs
    out = copy.deepcopy(inputs)
    out["load_kw"] = [v * load_scale for v in out["load_kw"]]
    out["pv_kw"] = [v * pv_scale for v in out["pv_kw"]]
    if price_delta != 0.0:
        out["price"] = [v + price_delta for v in out["price"]]
    out["scenario_applied"] = {
        "load_scale": load_scale,
        "pv_scale": pv_scale,
        "price_delta": price_delta,
    }
    return out


# ── 模型构建 ───────────────────────────────────────────────────
def _demand_ub(inputs: dict, constraints: list[dict]) -> float | None:
    """合并后的需量上限 = 所有需量类约束的 min。

    - demand_cap:「需量压到 X kW」,X 由调用方(LLM)给定;
    - respect_declared_demand:「不超申报值」,以站配置申报需量为硬上限,
      真实值由工具从系统读取,不依赖调用方传数(避免 LLM 猜数)。
    两类约束统一合并取 min(后传的不得放宽先传的)。
    """
    cfg = inputs["config"]
    ub: float | None = None
    for con in constraints:
        ctype = con.get("type")
        if ctype not in ("demand_cap", "respect_declared_demand"):
            continue
        val = con.get("value_kw")
        if ctype == "respect_declared_demand":
            val = cfg["contract_demand_kw"]
        if val is None:
            continue
        v = float(val)
        ub = v if ub is None else min(ub, v)
    return ub


def _build_model(
    inputs: dict,
    weights: dict,
    constraints: list[dict],
    *,
    demand_ub: float | None,
    objective: str = "normal",
) -> tuple:
    """构建调度优化 LP,返回 (c, bounds, A_ub, b_ub, A_eq, b_eq)。

    demand_ub: 需量上限(已合并 min);None = 不加需量上限(诊断用)。
    objective: 'normal' = 加权多目标;'min_demand' = 仅最小化 dmax;
              'min_throughput' = 仅最小化 Σ(Pc+Pd)。
    """
    st = inputs["storage"]
    rated = st["total_rated_kw"]
    cap = st["total_cap_kwh"]
    eff = max(st["eff"], 0.01)
    eta = eff ** 0.5
    min_soc = st["min_soc"]
    max_soc = st["max_soc"]
    soc_init = st["initial_soc"]
    load = inputs["load_kw"]
    pv = inputs["pv_kw"]
    price = inputs["price"]
    cfg = inputs["config"]
    demand_price = cfg["demand_price_yuan_per_kw_month"]
    # 防逆流设定:策略组合 None -> 沿用站配置;否则用组合值(防逆流=0 严禁上网)
    ar = weights.get("anti_reverse")
    export_cap = cfg["anti_reverse_setpoint_kw"] if ar is None else float(ar)

    # ── 目标向量 c ──
    c = _row()
    if objective == "min_demand":
        c[_OFF["dmax"]] = 1.0
    elif objective == "min_throughput":
        for t in range(_N):
            c[_OFF["Pc"] + t] = 1.0
            c[_OFF["Pd"] + t] = 1.0
    else:
        w_degrade = weights["w_degrade"]
        w_carbon = weights["w_carbon"]
        w_ramp = weights["w_ramp"]
        for t in range(_N):
            c[_OFF["Pc"] + t] = w_degrade
            c[_OFF["Pd"] + t] = w_degrade
            c[_OFF["Pim"] + t] = price[t] + w_carbon * _CARBON_FACTOR
            c[_OFF["Pex"] + t] = -_SELL_PRICE
            c[_OFF["rup"] + t] = w_ramp
            c[_OFF["rdn"] + t] = w_ramp
        c[_OFF["dmax"]] = demand_price / 30.0

    # ── 变量界 ──
    bounds = [(0.0, None)] * _NVARS
    for t in range(_N):
        bounds[_OFF["Pc"] + t] = (0.0, rated)
        bounds[_OFF["Pd"] + t] = (0.0, rated)
        bounds[_OFF["Pcurt"] + t] = (0.0, float(pv[t]))
        bounds[_OFF["Pex"] + t] = (0.0, export_cap)
        bounds[_OFF["soc"] + t] = (min_soc * cap, max_soc * cap)
    bounds[_OFF["dmax"]] = (0.0, None)

    A_eq: list[list[float]] = []
    b_eq: list[float] = []
    A_ub: list[list[float]] = []
    b_ub: list[float] = []

    # 1. 功率平衡(等式):Pd - Pc + Pim - Pex + (pv - Pcurt) = load
    for t in range(_N):
        r = _row()
        r[_OFF["Pd"] + t] = 1.0
        r[_OFF["Pc"] + t] = -1.0
        r[_OFF["Pim"] + t] = 1.0
        r[_OFF["Pex"] + t] = -1.0
        r[_OFF["Pcurt"] + t] = -1.0
        A_eq.append(r)
        b_eq.append(float(load[t]) - float(pv[t]))

    # 2. SOC 动态(等式):soc[t] = soc_prev + Pc[t]·η - Pd[t]/η
    #    soc 变量单位为 kWh(界/初值/末态均为 *cap,提取 /cap 成百分比),
    #    故充/放系数为 η、1/η,不带 /cap(多除一次 cap 会让轨迹几乎冻结)。
    for t in range(_N):
        r = _row()
        r[_OFF["soc"] + t] = 1.0
        r[_OFF["Pc"] + t] = -eta
        r[_OFF["Pd"] + t] = (1.0 / eta)
        if t == 0:
            b_eq.append(soc_init * cap)
        else:
            r[_OFF["soc"] + t - 1] = -1.0
            b_eq.append(0.0)
        A_eq.append(r)

    # 3. 末态 SOC ≥ 初始(日内闭环,不透支次日)
    r = _row()
    r[_OFF["soc"] + _N - 1] = -1.0
    A_ub.append(r)
    b_ub.append(-soc_init * cap)

    # 4. 需量 epigraph:dmax ≥ k·Pim[t]。dmax 代表计费口径的需量(15min 滑窗),
    #    小时均值需乘保守系数 k;目标里按需量电价罚 dmax。
    for t in range(_N):
        r = _row()
        r[_OFF["Pim"] + t] = _DEMAND_15MIN_FACTOR
        r[_OFF["dmax"]] = -1.0
        A_ub.append(r)
        b_ub.append(0.0)

    # 5. 波动平滑(等式):(Pd[t]-Pc[t]) - (Pd[t-1]-Pc[t-1]) = rup[t] - rdn[t]
    for t in range(1, _N):
        r = _row()
        r[_OFF["Pd"] + t] = 1.0
        r[_OFF["Pc"] + t] = -1.0
        r[_OFF["Pd"] + t - 1] = -1.0
        r[_OFF["Pc"] + t - 1] = 1.0
        r[_OFF["rup"] + t] = -1.0
        r[_OFF["rdn"] + t] = 1.0
        A_eq.append(r)
        b_eq.append(0.0)

    # 6. 注入约束(需量上限已合并到 demand_ub,循环后统一应用)
    # reserve 关键负荷功率的解析优先级:
    #   critical_load_kw(显式数值) > level(档位) > 中档缺省(0.20×峰荷)
    # 两者都缺省时若取 0.30×峰荷,对大装机小申报需量的站必然 infeasible。
    critical_kw = None
    reserve_level = None
    for con in constraints:
        if con.get("type") != "reserve":
            continue
        if con.get("critical_load_kw") is not None:
            critical_kw = float(con["critical_load_kw"])
            break
        if reserve_level is None and con.get("level"):
            reserve_level = con["level"]
    if critical_kw is None:
        frac = _RESERVE_LEVEL_FRACTION.get(reserve_level, _RESERVE_DEFAULT_FRACTION)
        critical_kw = frac * max(load) if load else 0.0
    essential_kw = critical_kw

    for con in constraints:
        ctype = con.get("type")
        if ctype == "mode_lock":
            hours = con.get("hours") or []
            mode = con.get("mode")
            mp = con.get("min_power_kw") or 0.0
            for h in hours:
                if not (0 <= h < _N):
                    continue
                if mode == "charge":
                    # Pc[h] ≥ mp, Pd[h] = 0
                    r = _row(); r[_OFF["Pc"] + h] = -1.0
                    A_ub.append(r); b_ub.append(-mp)
                    r2 = _row(); r2[_OFF["Pd"] + h] = 1.0
                    A_eq.append(r2); b_eq.append(0.0)
                elif mode == "discharge":
                    r = _row(); r[_OFF["Pd"] + h] = -1.0
                    A_ub.append(r); b_ub.append(-mp)
                    r2 = _row(); r2[_OFF["Pc"] + h] = 1.0
                    A_eq.append(r2); b_eq.append(0.0)
                elif mode == "standby":
                    r = _row(); r[_OFF["Pc"] + h] = 1.0
                    A_eq.append(r); b_eq.append(0.0)
                    r2 = _row(); r2[_OFF["Pd"] + h] = 1.0
                    A_eq.append(r2); b_eq.append(0.0)
        elif ctype in ("demand_cap", "respect_declared_demand"):
            # 需量上限统一由 demand_ub 应用(循环外),两类约束合并取 min
            continue
        elif ctype == "soc_target":
            h = con.get("hour")
            sp = con.get("soc_pct")
            if h is not None and sp is not None and 0 <= h < _N:
                r = _row(); r[_OFF["soc"] + h] = -1.0
                A_ub.append(r); b_ub.append(-float(sp) * cap)
        elif ctype == "throughput_cap":
            kwh = con.get("kwh")
            if kwh is not None:
                r = _row()
                for t in range(_N):
                    r[_OFF["Pc"] + t] = 1.0
                    r[_OFF["Pd"] + t] = 1.0
                A_ub.append(r); b_ub.append(float(kwh))
        elif ctype == "no_export":
            for t in range(_N):
                bounds[_OFF["Pex"] + t] = (0.0, 0.0)
        elif ctype == "cost_cap":
            yuan = con.get("yuan")
            if yuan is not None:
                r = _row()
                for t in range(_N):
                    r[_OFF["Pim"] + t] = price[t]
                A_ub.append(r); b_ub.append(float(yuan))
        elif ctype == "reserve":
            # 保备用:SOC 下限 ≥ 支撑 hrs 小时关键负荷所需能量(kWh,与 soc 变量同单位)。
            # 注意单位:此处必须是 kWh,与 soc 变量同单位(算成分数会与 lo 比较而永不生效)。
            hrs = con.get("hours_val") or _RESERVE_DEFAULT_HOURS
            reserve_kwh = hrs * essential_kw
            reserve_kwh = max(reserve_kwh, min_soc * cap)
            for t in range(_N):
                lo, hi = bounds[_OFF["soc"] + t]
                bounds[_OFF["soc"] + t] = (max(lo, reserve_kwh), hi)

    # 需量上限(合并 min)应用到 dmax 上界
    if demand_ub is not None:
        lo, hi = bounds[_OFF["dmax"]]
        hi = float(demand_ub) if hi is None else min(float(hi), float(demand_ub))
        bounds[_OFF["dmax"]] = (lo, hi)

    return c, bounds, A_ub, b_ub, A_eq, b_eq


def _solve_linprog(c, bounds, A_ub, b_ub, A_eq, b_eq):
    import numpy as np  # 局部 import,scipy 在则 numpy 必在
    return linprog(
        c=np.array(c, dtype=float),
        A_ub=np.array(A_ub, dtype=float) if A_ub else None,
        b_ub=np.array(b_ub, dtype=float) if b_ub else None,
        A_eq=np.array(A_eq, dtype=float) if A_eq else None,
        b_eq=np.array(b_eq, dtype=float) if b_eq else None,
        bounds=bounds,
        method="highs",
    )


def _demand_diagnostic(inputs: dict, weights: dict, constraints: list[dict],
                       demand_ub: float | None) -> dict | None:
    """需量上限不可行时,放开需量上限(其余约束不变)求物理可行最小关口峰值。

    返回诊断字段(agent 直接据此调整申报需量,无需二分试算):
    diagnosis / min_feasible_demand_cap_kw / requested_demand_cap_kw / recommendation。
    无需量类约束 → None(冲突来自其它约束)。
    """
    if demand_ub is None:
        return None
    c2, bounds2, A_ub2, b_ub2, A_eq2, b_eq2 = _build_model(
        inputs, weights, constraints, demand_ub=None, objective="min_demand")
    res2 = _solve_linprog(c2, bounds2, A_ub2, b_ub2, A_eq2, b_eq2)
    base = {"requested_demand_cap_kw": round(float(demand_ub), 1)}
    if not res2.success:
        return {
            **base,
            "diagnosis": "other_constraints_infeasible",
            "min_feasible_demand_cap_kw": None,
            "recommendation": (
                "即便放开需量上限仍无可行解——冲突来自其它约束"
                "(保底 SOC/电费上限/SOC 目标等)。建议逐一放宽这些约束后重试。"
            ),
        }
    min_cap = float(res2.x[_OFF["dmax"]])
    ceil_cap = int(math.ceil(min_cap - 1e-6))
    return {
        **base,
        "diagnosis": "demand_cap_below_feasible",
        "min_feasible_demand_cap_kw": round(min_cap, 1),
        "recommendation": (
            f"需量上限 {float(demand_ub):.0f} kW 低于物理可行下限 {min_cap:.0f} kW"
            f"(其余约束不变时电池最大削峰仅能压到 {min_cap:.0f} kW)。"
            f"建议把申报需量/需量上限上调到 ≥ {ceil_cap} kW 后重试。"
        ),
    }


def _reserve_floor_info(inputs: dict, constraints: list[dict]) -> dict | None:
    """reserve 约束折算出的 SOC 下限(kWh / %cap),把「保供 vs 不超申报」的冲突显性化。

    原返回只说"约束冲突",模型看不到冲突来自 reserve 的哪一项(档位?时长?),
    于是转头去试参数。这里把折算过程直接写进返回,让冲突原因对模型可见。
    """
    cap = inputs["storage"]["total_cap_kwh"]
    if cap <= 0:
        return None
    for con in constraints:
        if con.get("type") != "reserve":
            continue
        hrs = float(con.get("hours_val") or _RESERVE_DEFAULT_HOURS)
        ck = con.get("critical_load_kw")
        if ck is not None:
            level = None
            source = "显式 critical_load_kw"
            essential = float(ck)
        else:
            lv = con.get("level")
            level = lv or "中(缺省)"
            frac = _RESERVE_LEVEL_FRACTION.get(lv, _RESERVE_DEFAULT_FRACTION)
            source = f"档位「{level}」= 峰荷×{frac:.2f}"
            essential = frac * max(inputs["load_kw"]) if inputs["load_kw"] else 0.0
        floor_kwh = max(hrs * essential, inputs["storage"]["min_soc"] * cap)
        return {
            "level": level,
            "source": source,
            "hours": hrs,
            "critical_load_kw": round(essential, 1),
            "reserve_soc_floor_kwh": round(floor_kwh, 1),
            "reserve_soc_floor_pct": round(floor_kwh / cap * 100, 1),
        }
    return None


def _infeasible_result(inputs: dict, weights: dict, constraints: list[dict],
                       demand_ub: float | None, res) -> dict:
    """不可行 → 通用 reason + (若由需量上限引起)可行下限诊断 + reserve 折算明细。"""
    reason = f"约束冲突,求解不可行:{res.message}。"
    diag = _demand_diagnostic(inputs, weights, constraints, demand_ub)
    out: dict = {"status": "infeasible", "reason": reason}
    rf = _reserve_floor_info(inputs, constraints)
    if rf is not None:
        out["reserve_floor"] = rf
    if diag is None:
        out["reason"] = reason + "建议放宽约束(需量上限/电费上限/SOC 目标)后重试。"
        return out
    out.update(diag)
    if rf is not None and diag.get("diagnosis") == "demand_cap_below_feasible":
        out["reason"] = (
            reason
            + f"其中 reserve 约束(来源:{rf['source']},折算 SOC 下限 "
              f"{rf['reserve_soc_floor_pct']}% = {rf['reserve_soc_floor_kwh']:.0f} kWh)"
              f"已把物理需量下限抬到 {diag['min_feasible_demand_cap_kw']:.0f} kW,"
              f"高于申报的 {diag['requested_demand_cap_kw']:.0f} kW。"
              f"这是**约束之间的冲突**,不是参数写错 —— 请上报用户决策,"
              f"不要靠调 reserve 参数重试。"
        )
    return out


# ── 自检与对偶推断 ────────────────────────────────────
def _energy_sanity_check(x, inputs: dict) -> dict:
    """能量守恒自检:|ΔSOC − (ΣPc·η − ΣPd/η)| < tol。

    不能让 LLM 自己去发现数据不对(实测不可靠——75s 侦探戏里子 agent
    发现 SOC 轨迹异常却 rationalize 掉);solver 自检 + warnings 透传给 agent,
    避免"模型自己 rationalize 异常"的侦探戏。
    """
    st = inputs["storage"]
    cap = st["total_cap_kwh"]
    eta = max(st["eff"], 0.01) ** 0.5
    init_soc_kwh = st["initial_soc"] * cap
    final_soc_kwh = float(x[_OFF["soc"] + _N - 1])
    delta_soc = final_soc_kwh - init_soc_kwh
    net_charge = sum(
        float(x[_OFF["Pc"] + t]) * eta - float(x[_OFF["Pd"] + t]) / eta
        for t in range(_N)
    )
    diff = abs(delta_soc - net_charge)
    conserved = diff < _ENERGY_SANITY_TOL_KWH
    warnings: list[str] = []
    if not conserved:
        warnings.append(
            f"能量守恒校验失败:ΔSOC={delta_soc:.1f}kWh,净充入={net_charge:.1f}kWh,"
            f"差值={diff:.1f}kWh(超过容差 {_ENERGY_SANITY_TOL_KWH}kWh)"
        )
    if final_soc_kwh < init_soc_kwh - 0.1:
        warnings.append(
            f"末态 SOC {final_soc_kwh:.1f}kWh 低于初始 {init_soc_kwh:.1f}kWh"
            "(日内闭环约束应已强制 ≥ 初始,若出现说明约束失效)"
        )
    return {
        "energy_conserved": conserved,
        "delta_soc_kwh": round(delta_soc, 2),
        "net_charge_kwh": round(net_charge, 2),
        "diff_kwh": round(diff, 2),
        "warnings": warnings,
    }


def _active_constraints(x, inputs: dict, constraints: list[dict]) -> list[dict]:
    """检查用户注入的约束在解里是否 binding(松弛推断)。

    每条约束返回 {type, binding: bool}。binding=True 表示该约束在最优解处
    起作用(松弛=0);False 表示松弛>0 未起作用。agent 据此直接告知用户
    "哪些约束实际锁住了",无需自己从结果反推(消灭"锁了却 standby"的侦探戏)。
    """
    cap = inputs["storage"]["total_cap_kwh"]
    min_soc_kwh = min(float(x[_OFF["soc"] + t]) for t in range(_N))
    peak_import = max(float(x[_OFF["Pim"] + t]) for t in range(_N))
    # 需量类约束的 value_kw / contract_demand_kw 是计费口径,binding 判定必须同口径,
    # 否则"顶到上限"会被误判为未生效
    peak_demand_billing = _DEMAND_15MIN_FACTOR * peak_import
    total_throughput = sum(
        float(x[_OFF["Pc"] + t]) + float(x[_OFF["Pd"] + t]) for t in range(_N)
    )
    grid_cost = sum(
        float(inputs["price"][t]) * float(x[_OFF["Pim"] + t]) for t in range(_N)
    )
    export_sum = sum(float(x[_OFF["Pex"] + t]) for t in range(_N))
    TOL_KW = 1.0
    TOL_KWH = 1.0
    TOL_YUAN = 5.0

    out: list[dict] = []
    for con in constraints:
        ctype = con.get("type")
        binding: bool | None = None
        if ctype == "demand_cap":
            v = float(con.get("value_kw") or 0)
            binding = abs(peak_demand_billing - v) < TOL_KW
        elif ctype == "respect_declared_demand":
            v = float(inputs["config"]["contract_demand_kw"])
            binding = abs(peak_demand_billing - v) < TOL_KW
        elif ctype == "soc_target":
            h = con.get("hour")
            sp = con.get("soc_pct")
            if h is not None and sp is not None and 0 <= h < _N:
                binding = abs(float(x[_OFF["soc"] + h]) - float(sp) * cap) < TOL_KWH
        elif ctype == "throughput_cap":
            v = float(con.get("kwh") or 0)
            binding = abs(total_throughput - v) < TOL_KWH
        elif ctype == "cost_cap":
            v = float(con.get("yuan") or 0)
            binding = abs(grid_cost - v) < TOL_YUAN
        elif ctype == "reserve":
            hrs = float(con.get("hours_val") or _RESERVE_DEFAULT_HOURS)
            _ck = con.get("critical_load_kw")
            if _ck is not None:
                essential = float(_ck)
            else:
                # 与 _build_model 同一套解析:level 档位 > 中档缺省
                _frac = _RESERVE_LEVEL_FRACTION.get(con.get("level"),
                                                    _RESERVE_DEFAULT_FRACTION)
                essential = (_frac * max(inputs["load_kw"])
                             if inputs["load_kw"] else 0.0)
            floor = max(hrs * essential, inputs["storage"]["min_soc"] * cap)
            binding = abs(min_soc_kwh - floor) < TOL_KWH * 5
        elif ctype == "no_export":
            binding = export_sum < TOL_KW
        elif ctype == "mode_lock":
            # mode_lock 总会改解;min_power>0 时若该时段功率=min_power 视为 binding,
            # min_power=0 时(允许待机)只标记 applied
            mp = float(con.get("min_power_kw") or 0.0)
            binding = mp > 0  # 简化上报,具体 binding 检查需逐小时
        if binding is not None:
            out.append({"type": ctype, "binding": bool(binding)})
    return out


# ── 主求解 ─────────────────────────────────────────────────────
def _solve(inputs: dict, weights: dict,
           constraints: list[dict]) -> tuple[list[dict], dict, dict, list[dict]] | dict:
    """构建并求解调度优化模型。

    成功返回 (schedule[24], summary, sanity_check, active_constraints);
    不可行返回 {status, reason, ...诊断}。
    """
    st = inputs["storage"]
    rated = st["total_rated_kw"]
    cap = st["total_cap_kwh"]
    if rated <= 0 or cap <= 0:
        return {"status": "no_storage",
                "reason": "无在线储能设备,无法生成充放电策略。请先录入 PCS 与电池。"}

    demand_ub = _demand_ub(inputs, constraints)
    c, bounds, A_ub, b_ub, A_eq, b_eq = _build_model(
        inputs, weights, constraints, demand_ub=demand_ub)
    res = _solve_linprog(c, bounds, A_ub, b_ub, A_eq, b_eq)
    if not res.success:
        return _infeasible_result(inputs, weights, constraints, demand_ub, res)
    x = res.x

    load = inputs["load_kw"]
    pv = inputs["pv_kw"]
    price = inputs["price"]
    cfg = inputs["config"]
    demand_price = cfg["demand_price_yuan_per_kw_month"]
    w_degrade = weights["w_degrade"]
    w_carbon = weights["w_carbon"]

    # ── 提取 schedule + summary ──
    schedule: list[dict] = []
    charge_kwh = discharge_kwh = 0.0
    pv_self_use = pv_curtail = import_kwh = export_kwh = 0.0
    grid_cost = 0.0
    peak_import = 0.0
    for t in range(_N):
        pc = float(x[_OFF["Pc"] + t])
        pd = float(x[_OFF["Pd"] + t])
        pim = float(x[_OFF["Pim"] + t])
        pex = float(x[_OFF["Pex"] + t])
        pcurt = float(x[_OFF["Pcurt"] + t])
        soc = float(x[_OFF["soc"] + t])
        if pc > 1e-6:
            mode = "charge"
            power = pc
        elif pd > 1e-6:
            mode = "discharge"
            power = pd
        else:
            mode = "standby"
            power = 0.0
        charge_kwh += pc
        discharge_kwh += pd
        pv_self_use += float(pv[t]) - pcurt
        pv_curtail += pcurt
        import_kwh += pim
        export_kwh += pex
        grid_cost += price[t] * pim
        peak_import = max(peak_import, pim)
        schedule.append({
            "hour": t,
            "mode": mode,
            "power_kw": round(power, 1),
            "power_ratio": round(power / rated, 4) if rated > 0 else 0.0,
            "soc_target_pct": round(soc / cap, 4) if cap > 0 else 0.0,
            "period": inputs["period"][t],
            "tariff_price": round(price[t], 3),
        })

    # ── 需量口径统一──
    # LP 以小时为分辨率,小时内负荷波动被平均掉;国内需量电费按 15min 滑窗最大值计,
    # 故乘 _DEMAND_15MIN_FACTOR 保守折算。**只有这个"计费需量"才与** demand_cap /
    # respect_declared_demand / contract_demand_kw / dmax 同量纲。
    # 对外报告的 peak_demand_kw 与需量电费都必须用它,否则余量会被高估约 9 倍。
    peak_demand_billing = _DEMAND_15MIN_FACTOR * peak_import
    demand_charge = (demand_price / 30.0) * peak_demand_billing
    carbon_kg = _CARBON_FACTOR * import_kwh
    supply = pv_self_use + import_kwh
    green_rate = (pv_self_use / supply) if supply > 0 else 0.0

    # 无电池基线(光伏直供、余电不上网):用于估算节省
    baseline_import = [max(0.0, load[t] - pv[t]) for t in range(_N)]
    baseline_grid_cost = sum(price[t] * baseline_import[t] for t in range(_N))
    baseline_peak = max(baseline_import) if baseline_import else 0.0
    baseline_peak_billing = _DEMAND_15MIN_FACTOR * baseline_peak
    baseline_demand = (demand_price / 30.0) * baseline_peak_billing
    est_savings = (baseline_grid_cost + baseline_demand) - (grid_cost + demand_charge)

    # 绿电优先代价:w_carbon>0 时重解一次 w_carbon=0,差值=多付的电费
    # (约束不变,只换目标 → 可行性不变,只有目标值变)
    carbon_cost = 0.0
    if w_carbon > 0:
        w2 = dict(weights)
        w2["w_carbon"] = 0.0
        c2, b2, au2, bu2, ae2, be2 = _build_model(
            inputs, w2, constraints, demand_ub=demand_ub)
        res2 = _solve_linprog(c2, b2, au2, bu2, ae2, be2)
        if res2.success:
            grid_cost_no_carbon = sum(
                price[t] * float(res2.x[_OFF["Pim"] + t]) for t in range(_N)
            )
            peak_no_carbon = max(float(res2.x[_OFF["Pim"] + t]) for t in range(_N))
            # 与主解同口径,否则 carbon_cost 会掺进一个假的"需量差"
            demand_no_carbon = (demand_price / 30.0) * (
                _DEMAND_15MIN_FACTOR * peak_no_carbon)
            carbon_cost = round(
                (grid_cost + demand_charge) - (grid_cost_no_carbon + demand_no_carbon), 2)
            carbon_cost = max(0.0, carbon_cost)  # 守住:理论上 ≥0,数值噪声兜底

    summary = {
        "grid_cost": round(grid_cost, 2),
        "demand_charge": round(demand_charge, 2),
        "degradation_cost": round(w_degrade * (charge_kwh + discharge_kwh), 2),
        "carbon_kg": round(carbon_kg, 1),
        "carbon_cost": round(carbon_cost, 2),
        "pv_self_use_kwh": round(pv_self_use, 1),
        "pv_curtail_kwh": round(pv_curtail, 1),
        "pv_total_kwh": round(sum(float(p) for p in pv), 1),
        "peak_load_kw": round(max(load) if load else 0.0, 1),
        "load_total_kwh": round(sum(float(x_) for x_ in load), 1),
        "charge_kwh": round(charge_kwh, 1),
        "discharge_kwh": round(discharge_kwh, 1),
        "green_rate": round(green_rate, 4),
        # peak_demand_kw 是**计费需量**(15min 滑窗口径),与 contract_demand_kw /
        # demand_cap 同量纲,可直接相减得余量。原始小时均值另存 *_raw_kw 仅供追溯。
        "peak_demand_kw": round(peak_demand_billing, 1),
        "peak_demand_raw_kw": round(peak_import, 1),
        "contract_demand_kw": round(cfg["contract_demand_kw"], 1),
        "demand_margin_kw": round(float(cfg["contract_demand_kw"]) - peak_demand_billing, 1),
        "est_savings_yuan": round(est_savings, 2),
        "baseline_grid_cost": round(baseline_grid_cost, 2),
        "baseline_demand_charge": round(baseline_demand, 2),
        "baseline_peak_kw": round(baseline_peak_billing, 1),
        "baseline_peak_raw_kw": round(baseline_peak, 1),
    }
    sanity = _energy_sanity_check(x, inputs)
    active = _active_constraints(x, inputs, constraints)
    return schedule, summary, sanity, active


def _min_feasible_demand(inputs: dict, weights: dict,
                         constraints: list[dict] | None = None) -> float | None:
    """放开需量上限时,电池可削到的物理最小**计费需量**(kW)。

    objective='min_demand' 只最小化 dmax(不计成本),得到当前负荷/光伏/储能下的
    计费需量物理下限,与需量上限本身无关。求解不可行返回 None。

    constraints: 需求方必须传**与自己一致的约束集**。需量类约束本就被 demand_ub=None
    屏蔽,但非需量类(reserve / SOC 目标 / 电费上限)会抬高这个下限 ——
    典型:漏传 reserve 会把下限算低约 10%,导致后续二分的区间上界不可行。
    """
    c, bounds, A_ub, b_ub, A_eq, b_eq = _build_model(
        inputs, weights, list(constraints or []), demand_ub=None, objective="min_demand")
    res = _solve_linprog(c, bounds, A_ub, b_ub, A_eq, b_eq)
    if not res.success:
        return None
    return float(res.x[_OFF["dmax"]])


def _min_feasible_throughput(inputs: dict, weights: dict) -> float | None:
    """保持关口功率 ≤ 申报需量时,电池所需的最小日吞吐(充+放, kWh)。

    objective='min_throughput' 最小化 Σ(Pc+Pd),同时把需量上限压在申报需量上,
    得到「要守住申报需量,至少得循环多少」的物理下限。日吞吐上限低于它 → 与需量约束
    冲突不可行。申报需量低于物理下限时求解不可行返回 None。
    """
    demand_ub = _demand_ub(inputs, [{"type": "respect_declared_demand"}])
    c, bounds, A_ub, b_ub, A_eq, b_eq = _build_model(
        inputs, weights, [], demand_ub=demand_ub, objective="min_throughput")
    res = _solve_linprog(c, bounds, A_ub, b_ub, A_eq, b_eq)
    if not res.success:
        return None
    return sum(
        float(res.x[_OFF["Pc"] + t]) + float(res.x[_OFF["Pd"] + t])
        for t in range(_N)
    )


def _preview(inputs: dict, weights: dict, used: list[str]) -> dict:
    """preview 模式:只看现状/基线/可行域,不求解带约束的策略。

    一次调用返回四件事,让 agent 在定约束前就有数据锚点,消灭「先求解→从结果学数据→
    再猜约束」的 solve-to-learn 试错:
    - station_context:站级现状(申报需量/需量电价/防逆流/负荷·光伏/储能含可用容量/电价时段)
    - baseline_no_storage:无储能基线(关口峰值/电费/需量电费)
    - default:无约束(给定策略组合,空=省钱)下的默认效果(峰值需量/吞吐/费用)
    - envelope.demand_kw:需量可行域 [min_feasible, unconstrained] + 申报需量
    - envelope.throughput_kwh:日吞吐可行域 [min_feasible, unconstrained]
    """
    st = inputs["storage"]
    cfg = inputs["config"]
    if st["total_rated_kw"] <= 0 or st["total_cap_kwh"] <= 0:
        return {"status": "no_storage",
                "reason": "无在线储能设备,无法生成充放电策略。请先录入 PCS 与电池。"}

    # 无约束(给定策略组合)默认效果
    solved = _solve(inputs, weights, [])
    if isinstance(solved, dict):  # pragma: no cover
        return solved
    _schedule, default_summary, _sanity, _active = solved

    load = inputs["load_kw"]
    pv = inputs["pv_kw"]
    price = inputs["price"]
    min_cap = _min_feasible_demand(inputs, weights)

    # 吞吐可行域:下限=守住申报需量所需最小循环量;上限=同约束下策略自然吞吐
    tp_floor = _min_feasible_throughput(inputs, weights)
    # 边界精度:cap 取 floor 精确值在 HiGHS 边界上不可行(实测 floor+1 才可行)。
    # 上报带 1% 余量的安全下界,agent 直接取 cap ≥ min_feasible_kwh 即不再撞边界。
    if tp_floor is not None:
        tp_floor = round(math.ceil(tp_floor * 1.01), 1)
    ceil = _solve(inputs, weights, [{"type": "respect_declared_demand"}])
    if isinstance(ceil, dict):  # 申报需量低于物理下限 → 无可行的需量+吞吐组合
        tp_ceil = None
    else:
        tp_ceil = float(ceil[1]["charge_kwh"]) + float(ceil[1]["discharge_kwh"])

    # 电价时段:按 24h 聚合成 {period, price, hours}
    period_price: dict[str, float] = {}
    period_hours: dict[str, list[int]] = {}
    for t in range(_N):
        p = inputs["period"][t]
        period_price[p] = price[t]
        period_hours.setdefault(p, []).append(t)
    tariff = [
        {"period": p, "price": round(period_price[p], 3), "hours": hs}
        for p, hs in period_hours.items()
    ]

    return {
        "status": "preview",
        "strategies": used or ["省钱"],
        "target_date": inputs["target_date"],
        "scenario_applied": inputs.get("scenario_applied"),
        # v2:数据来源标注 + 需量计费口径(让 agent 在 preview 阶段就感知数据可信度)
        "forecast_source": inputs.get("forecast_source"),
        "forecast_confidence": inputs.get("forecast_confidence"),
        "demand_charge_basis": inputs.get("demand_charge_basis"),
        "station_context": {
            "target_date": inputs["target_date"],
            "contract_demand_kw": round(cfg["contract_demand_kw"], 1),
            "demand_price_yuan_per_kw_month": round(cfg["demand_price_yuan_per_kw_month"], 1),
            "anti_reverse_setpoint_kw": round(cfg["anti_reverse_setpoint_kw"], 1),
            "load_peak_kw": round(max(load) if load else 0.0, 1),
            "load_total_kwh": round(sum(load), 1),
            "pv_peak_kw": round(max(pv) if pv else 0.0, 1),
            "pv_total_kwh": round(sum(pv), 1),
            "storage": {
                "total_rated_kw": round(st["total_rated_kw"], 1),
                "total_cap_kwh": round(st["total_cap_kwh"], 1),
                "initial_soc": round(st["initial_soc"], 4),
                "min_soc": round(st["min_soc"], 4),
                "max_soc": round(st["max_soc"], 4),
                "eff": round(st["eff"], 4),
                "n_pcs": st["n_pcs"],
                "usable_capacity_kwh": round(st["total_cap_kwh"] * (st["max_soc"] - st["min_soc"]), 1),
            },
            "tariff": tariff,
        },
        "baseline_no_storage": {
            # peak_import_kw 保持**原始小时均值**口径(与字段名一致);
            # 计费口径另给 peak_demand_kw,避免两个"峰值"混用
            "peak_import_kw": default_summary.get("baseline_peak_raw_kw",
                                                  default_summary["baseline_peak_kw"]),
            "peak_demand_kw": default_summary["baseline_peak_kw"],
            "grid_cost_yuan": default_summary["baseline_grid_cost"],
            "demand_charge_yuan": default_summary["baseline_demand_charge"],
        },
        "default": default_summary,
        "envelope": {
            "demand_kw": {
                "contract_demand_kw": round(cfg["contract_demand_kw"], 1),
                "unconstrained_peak_kw": round(default_summary["peak_demand_kw"], 1),
                "min_feasible_kw": round(min_cap, 1) if min_cap is not None else None,
                "units": ("kW,计费需量口径(15min 滑窗保守折算 ×1.15);"
                          "与 demand_cap / 申报需量同量纲"),
                "note": (
                    "需量上限建议取 [min_feasible, unconstrained] 之间;"
                    "「不超申报值」直接用 respect_declared_demand(上限=申报需量),无需传数。"
                ),
            },
            "throughput_kwh": {
                "min_feasible_kwh": round(tp_floor, 1) if tp_floor is not None else None,
                "unconstrained_kwh": round(tp_ceil, 1) if tp_ceil is not None else None,
                "note": (
                    "日吞吐上限(充+放合计)建议取 [min_feasible, unconstrained] 之间;"
                    "min_feasible=守住申报需量所需最小循环量的安全下界(已含余量,低于它不可行);"
                    "unconstrained=同约束(不超申报需量)下策略最优的自然吞吐。"
                    "仅当你会叠加需量约束(不超申报需量)时 min_feasible 才是硬下限;"
                    "完全不设需量约束时少循环没有此下限(电池可基本不工作)。"
                ),
            },
        },
        "note": (
            "preview 不求解带约束的策略。先读 station_context / envelope 定数据锚点,"
            "再带 constraints 正式调用一次:数值类约束(需量上限/日吞吐上限)取 envelope 真实区间,"
            "「不超申报值」用 respect_declared_demand。"
        ),
    }


# ── 敏感性扫描(把「逐值循环」从 LLM 下沉到 solver)──────────
# 背景(实测):子代理用 8 轮 LLM、
# 49.09s、约 15.3 万 input token 手工二分试探 load_scale=1.2/1.05/1.1/1.03/1.02/1.01,
# 而 13 次 LP 求解在服务端合计只跑 0.71s —— 确定性计算被 agentic 循环放大了约 69 倍。
# 这里把循环下沉:一次调用返回整条曲线 + 内部二分的临界值,LLM 只负责决定
# 「要不要做敏感性分析」,不再负责「逐个取值」。
_MAX_SWEEP_POINTS = 32
_LIMIT_TOL = 1e-3
_LIMIT_MAX_ITER = 16
_LIMIT_DIRECTION = {"load_scale": "max", "pv_scale": "min", "demand_cap_kw": "min"}


class SweepPoint(BaseModel):
    """扫描中的一个采样点:what-if 缩放 + 可选需量上限。"""
    label: str | None = Field(default=None, description="可读标签,如「负荷+20%」")
    load_scale: float | None = Field(default=None, description="负荷缩放倍数(缺省 1.0)")
    pv_scale: float | None = Field(default=None, description="光伏缩放倍数(缺省 1.0)")
    price_delta: float | None = Field(default=None, description="电价平移 元/kWh(缺省 0)")
    demand_cap_kw: float | None = Field(
        default=None, description="该点的需量上限 kW(缺省沿用固定约束)")


class SweepSpec(BaseModel):
    """敏感性/边界扫描:替代「一次一问」的逐值试探。

    points 与 find_limit 可同时给出(先出曲线,再给临界点)。
    """
    points: list[SweepPoint] = Field(
        default_factory=list, description=f"显式采样点列表(最多 {_MAX_SWEEP_POINTS} 个)")
    find_limit: Literal["load_scale", "pv_scale", "demand_cap_kw"] | None = Field(
        default=None,
        description=(
            "自动二分求临界值(工具内部完成,不需要多次调用):"
            "load_scale=负荷最多涨到几倍仍守住需量上限;"
            "pv_scale=光伏最低降到几成仍守住需量上限;"
            "demand_cap_kw=需量上限最紧能压到多少 kW 还可行。"))
    limit_range: list[float] | None = Field(
        default=None, description="find_limit 的搜索区间 [lo, hi];缺省按参数自动推导")
    constraints: list[ConstraintSpec] | None = Field(
        default=None, description="扫描期间固定使用的约束;缺省继承顶层 constraints")


def _sweep_num(point: dict, key: str, default: float) -> float:
    """取数值字段;None ⇒ 默认值(不能用 `or`,否则 0.0 会被吞掉)。"""
    v = point.get(key)
    return default if v is None else float(v)


def _sweep_one(inputs: dict, weights: dict, constraints: list[dict],
               point: dict) -> dict:
    """解一个采样点,返回扁平指标(不含 24h schedule,保持扫描返回体紧凑)。

    feasible=False 时不是抛错,而是把不可行当作曲线上的一个有效取值点:
    「哪个倍率开始守不住」正是扫描要回答的问题。
    """
    scenario = {
        "load_scale": _sweep_num(point, "load_scale", 1.0),
        "pv_scale": _sweep_num(point, "pv_scale", 1.0),
        "price_delta": _sweep_num(point, "price_delta", 0.0),
    }
    cons = list(constraints)
    cap = point.get("demand_cap_kw")
    if cap is not None:
        cons.append({"type": "demand_cap", "value_kw": float(cap)})
    inp = apply_scenario(inputs, scenario)
    ub = _demand_ub(inp, cons)
    if ub is None:
        # 无显式需量约束时,以站配置申报需量作为业务口径上限(与 respect_declared_demand 同源)
        ub = float(inp["config"]["contract_demand_kw"])
    row = {
        "label": point.get("label"),
        "load_scale": round(scenario["load_scale"], 4),
        "pv_scale": round(scenario["pv_scale"], 4),
        "price_delta": round(scenario["price_delta"], 4),
        "demand_cap_kw": None if cap is None else round(float(cap), 1),
        "demand_limit_kw": round(float(ub), 1),
    }
    res = _solve(inp, weights, cons)
    if isinstance(res, dict):
        row["feasible"] = False
        row["demand_ok"] = False
        row["status"] = res.get("status")
        row["reason"] = res.get("reason")
        if res.get("min_feasible_demand_cap_kw") is not None:
            row["min_feasible_demand_cap_kw"] = res["min_feasible_demand_cap_kw"]
        return row
    _schedule, summary, _sanity, _active = res
    # peak_demand_kw 是计费口径,与 ub(=cap / 申报值)同量纲 → 可直接比较
    peak = float(summary["peak_demand_kw"])
    row.update({
        "feasible": True,
        "demand_ok": peak <= float(ub) + _DEMAND_OK_TOL_KW,
        "peak_demand_kw": summary["peak_demand_kw"],
        "peak_demand_raw_kw": summary.get("peak_demand_raw_kw"),
        "demand_margin_kw": round(float(ub) - peak, 1),
        "peak_load_kw": summary["peak_load_kw"],
        "est_savings_yuan": summary["est_savings_yuan"],
        "grid_cost": summary["grid_cost"],
        "demand_charge": summary["demand_charge"],
        "charge_kwh": summary["charge_kwh"],
        "discharge_kwh": summary["discharge_kwh"],
        "green_rate": summary["green_rate"],
        "pv_curtail_kwh": summary["pv_curtail_kwh"],
    })
    return row


def _default_limit_range(inputs: dict, weights: dict, constraints: list[dict],
                         param: str) -> tuple[float, float]:
    """按参数推导二分区间,避免调用方拍数。

    - load_scale: [1.0, 3.0],负荷最多按 3 倍考虑(远超任何真实场景)
    - pv_scale:   [0.0, 1.0],光伏从「完全不出力」到「额定出力」
    - demand_cap_kw: [物理可行下限×0.95, 无约束自然峰值×1.05],由模型现算(均为计费口径)
    """
    if param == "load_scale":
        return 1.0, 3.0
    if param == "pv_scale":
        return 0.0, 1.0
    # floor 必须用**同一约束集**算:漏掉 reserve 等约束会把下限算低,导致区间上界不可行
    floor = _min_feasible_demand(inputs, weights, constraints)
    if floor is None:
        floor = 0.0
    stripped = [c for c in constraints
                if c.get("type") not in ("demand_cap", "respect_declared_demand")]
    natural = _solve(inputs, weights, stripped)
    if isinstance(natural, dict):
        # 自然峰值不可得 → 退回申报需量,并保证不低于物理下限
        natural_peak = max(float(inputs["config"]["contract_demand_kw"]), float(floor))
    else:
        # peak_demand_kw 已是计费口径,与 floor 同量纲(不再额外乘系数)
        natural_peak = float(natural[1]["peak_demand_kw"])
    lo = max(1.0, float(floor) * 0.95)
    # hi 必须是"确定可行"的一端:物理下限×1.10 保底——HiGHS 在可行域边界上会判
    # infeasible(与 _preview 里吞吐下界要留 1% 余量同因),所以不能把 hi 取在下限上。
    hi = max(float(floor) * 1.10 + 1.0, natural_peak * 1.05, lo + 1.0)
    return lo, hi


def _sweep_conflict_edge(inputs: dict, weights: dict,
                         constraints: list[dict]) -> dict | None:
    """二分区间端点即不可行时,区分「约束集冲突」与「区间选择不当」。

    返回非 None 表示**基准工况**(load_scale=1.0 / 无额外需量上限)本身就不可行 ——
    这是约束之间的冲突,调整 limit_range 无意义。原文案一律写"请调整 limit_range",
    把"约束集冲突"误报成"区间给得不对",进一步把模型推向无意义的区间试探。
    """
    base = _sweep_one(inputs, weights, constraints, {})
    if base.get("feasible"):
        return None
    d: dict = {
        "value": None,
        "feasible": False,
        "constraint_set_feasible": False,
        "reason": base.get("reason") or base.get("status"),
        "note": ("该约束集在基准工况(load_scale=1.0 / 无额外需量上限)下即不可行 —— "
                 "属**约束之间的冲突**,与搜索区间无关。请直接上报冲突并请用户决策,"
                 "**不要**调整 limit_range 或改参数重试。"),
    }
    if base.get("min_feasible_demand_cap_kw") is not None:
        d["min_feasible_demand_cap_kw"] = base["min_feasible_demand_cap_kw"]
    if base.get("diagnosis") is not None:
        d["diagnosis"] = base["diagnosis"]
    return d


def _sweep_find_limit(inputs: dict, weights: dict, constraints: list[dict],
                      param: str, lo: float, hi: float) -> dict:
    """二分求临界值(内部完成,调用方只拿结果)。

    判定口径:该取值下 LP 可行 **且** 关口峰值 ≤ 有效需量上限。
    单调性:load_scale 越大越难满足;pv_scale / demand_cap_kw 越大越容易满足。
    """
    direction = _LIMIT_DIRECTION[param]

    def ok(v: float) -> bool:
        row = _sweep_one(inputs, weights, constraints, {param: v})
        return bool(row.get("feasible")) and bool(row.get("demand_ok"))

    out: dict = {"param": param, "range": [round(lo, 4), round(hi, 4)],
                 "direction": direction}
    if direction == "max":
        if not ok(lo):
            conflict = _sweep_conflict_edge(inputs, weights, constraints)
            if conflict is not None:
                out.update(conflict)
                return out
            out.update({"value": None, "feasible": False,
                        "note": "搜索区间下界即已不满足约束,请下调 limit_range 后重试"})
            return out
        if ok(hi):
            out.update({"value": round(hi, 4), "feasible": True, "boundary_hit": False,
                        "note": "区间上界仍满足约束(未触界);需要精确值请扩大 limit_range"})
            return out
        a, b = lo, hi
    else:
        if ok(lo):
            out.update({"value": round(lo, 4), "feasible": True, "boundary_hit": False,
                        "note": "区间下界即已满足约束(未触界);需要精确值请扩大 limit_range"})
            return out
        if not ok(hi):
            conflict = _sweep_conflict_edge(inputs, weights, constraints)
            if conflict is not None:
                out.update(conflict)
                return out
            out.update({"value": None, "feasible": False,
                        "note": "搜索区间上界仍不满足约束,请上调 limit_range 后重试"})
            return out
        a, b = hi, lo
    for _ in range(_LIMIT_MAX_ITER):
        if abs(a - b) < _LIMIT_TOL:
            break
        m = (a + b) / 2.0
        if ok(m):
            a = m
        else:
            b = m
    # 报告值必须落在**可行一侧**:max 方向向下取整、min 方向向上取整。
    # 直接 round() 可能把值挪到边界另一侧,调用方照用会撞不可行(HiGHS 在边界上判 infeasible)。
    snapped = (math.floor(a * 100) / 100 if direction == "max"
               else math.ceil(a * 100) / 100)
    out.update({"value": snapped, "feasible": True, "boundary_hit": True})
    row = _sweep_one(inputs, weights, constraints, {param: a})
    if row.get("feasible"):
        out["at_limit"] = {
            k: row[k] for k in (
                "peak_demand_kw", "demand_limit_kw", "est_savings_yuan",
                "charge_kwh", "discharge_kwh", "green_rate")
            if k in row
        }
    if param == "load_scale":
        out["note"] = f"负荷最多可涨到 {a:.3f} 倍仍守住需量上限(超出即需放宽约束)"
    elif param == "pv_scale":
        out["note"] = f"光伏最低降到 {a:.3f} 倍仍守住需量上限(再低即需放宽约束)"
    else:
        out["note"] = f"需量上限最紧可压到 {a:.1f} kW(再紧则不可行)"
    return out


def run_sweep(inputs: dict, weights: dict, used: list[str],
              sweep: "SweepSpec | dict | None",
              base_constraints: list[dict] | None = None) -> dict:
    """执行敏感性扫描:一次返回整条曲线 + 可选临界值。

    - points:显式采样点,逐点求解(每点约 0.05~0.1s)
    - find_limit:在 limit_range 内二分定位临界值(约 16 次求解)
    约束缺省继承顶层 constraints;返回体只含扁平指标,不含 24h schedule。

    **返回键的语义区分**:
    - 扫描正常执行 → 顶层 `scan_status="ok"`。注意它**只表示扫描跑完了**,
      不代表约束可解 —— 整体可解性看 `sweep.any_feasible`,单点看 `points[i].feasible`。
      (若此处也叫 `status`,就与全解路径的 `status="ok"`(求解可行)同名不同义,
       会把模型误导成"约束集可行",进而发出注定 infeasible 的全解调用。)
    - 前置条件不满足(无在线储能) → `status="no_storage"`,与 `_solve`/`_preview` 同键同义。
    """
    spec = sweep.model_dump() if isinstance(sweep, BaseModel) else dict(sweep or {})
    cons_raw = spec.get("constraints")
    if cons_raw is None:
        cons = list(base_constraints or [])
    else:
        cons = [c.model_dump() if isinstance(c, BaseModel) else dict(c)
                for c in cons_raw]
    st = inputs["storage"]
    if st["total_rated_kw"] <= 0 or st["total_cap_kwh"] <= 0:
        return {"status": "no_storage",
                "reason": "无在线储能设备,无法生成充放电策略。请先录入 PCS 与电池。"}
    raw_points = spec.get("points") or []
    truncated = len(raw_points) > _MAX_SWEEP_POINTS
    rows = [
        _sweep_one(inputs, weights, cons,
                   p.model_dump() if isinstance(p, BaseModel) else dict(p))
        for p in raw_points[:_MAX_SWEEP_POINTS]
    ]
    out = {
        # 顶层字段名为 scan_status —— 此处的 ok 只表示「扫描执行完成」,
        # 与全解路径的 status:"ok"(求解可行)**同名不同义**,曾把模型误导成"约束集可行",
        # 进而发出注定 infeasible 的全解调用。整体是否有解请看 sweep.any_feasible。
        "scan_status": "ok",
        "strategies": used or ["省钱"],
        "target_date": inputs["target_date"],
        "sweep": {
            "constraints_used": cons,
            "points": rows,
            "points_truncated": truncated,
            "limit": None,
            "note": (
                "points=显式采样结果;limit=内部二分得到的临界值。"
                "全部为扁平指标(不含 24h schedule)。"
                "**scan_status=ok 只表示扫描完成,不代表约束可解**;"
                "单点可行性看 points[i].feasible,整体是否有解看 any_feasible。"
                "确定最终方案后再单点调用 optimize_dispatch 拿完整 schedule。"),
        },
    }
    param = spec.get("find_limit")
    if param:
        rng = spec.get("limit_range")
        if not rng or len(rng) != 2:
            lo, hi = _default_limit_range(inputs, weights, cons, param)
        else:
            lo, hi = float(rng[0]), float(rng[1])
            if hi < lo:
                lo, hi = hi, lo
        out["sweep"]["limit"] = _sweep_find_limit(
            inputs, weights, cons, param, lo, hi)

    # 聚合结论:一眼看出"这组约束到底有没有解",不必逐点扫。
    # 口径分列(避免 any_feasible=True 而 n_feasible=0 被误读为矛盾):
    #   n_points / n_points_feasible —— 只统计显式传入的采样点
    #   limit_feasible               —— 临界搜索是否找到可行边界(未做搜索时为 null)
    #   any_feasible                 —— 二者并集,即该约束集整体是否有解
    sw = out["sweep"]
    point_flags = [bool(r.get("feasible")) for r in sw["points"]]
    lim = sw.get("limit")
    lim_flag = bool(lim.get("feasible")) if isinstance(lim, dict) else None
    sw["n_points"] = len(sw["points"])
    sw["n_points_feasible"] = sum(1 for r in sw["points"] if r.get("feasible"))
    sw["n_feasible"] = sw["n_points_feasible"]  # 兼容旧键名(同一口径)
    sw["limit_feasible"] = lim_flag
    all_flags = point_flags + ([lim_flag] if lim_flag is not None else [])
    sw["any_feasible"] = (any(all_flags) if all_flags else None)
    if all_flags and not any(all_flags):
        sw["conclusion"] = (
            "该约束集在当前站**无可行解**:所有采样点与临界搜索均不可行。"
            "这是约束之间的冲突(常见于 reserve 与需量上限),"
            "请直接上报用户决策,**不要**改参数重试。")
    return out
