"""dispatch_planning 域 - LP 优化 + 下发 + tick 闭环 + 被动监测 + 收益核算 测试。

闭环验证:optimize_dispatch(调度优化) → apply_schedule(HITL 下发) → 当日每 tick 按
计划执行(decide_mode_and_power 读 active 计划) → 快照/日电量累积 → get_schedule_status
偏差监测 → account_revenue 收益核算。所有 mapper 共享同一 sqlite 引擎。
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from emsclaw_backend.db.models import (
    Device, PcsDevice, BatteryDevice, PcsSnapshot, BatterySnapshot,
    PvDevice, PvSnapshot, MeterDevice, MeterSnapshot,
    ElectricityTariff, DailyEnergyRecord, StationConfig, ChargeSchedule,
)
from emsclaw_backend.mapper.pcs_mapper import PcsMapper
from emsclaw_backend.mapper.station_mapper import StationMapper
from emsclaw_backend.mapper.schedule_mapper import ScheduleMapper
from emsclaw_backend.service.pcs_service import PcsService, reset_default_service
from emsclaw_backend.service.station_service import StationSimService

_SH = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def dispatch_env(monkeypatch):
    """单引擎共享库:建全部表,四个 mapper 模块 SyncSessionLocal 指向同一 factory。
    懒加载 default services(工具经 get_default_service 拿到,读 patch 后的 SF)。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, Session
    from sqlalchemy.pool import StaticPool
    import emsclaw_backend.mapper.pcs_mapper as pcs_m
    import emsclaw_backend.mapper.station_mapper as stn_m
    import emsclaw_backend.mapper.schedule_mapper as sched_m
    import emsclaw_backend.mapper.device_mapper as dev_m
    import emsclaw_backend.service.pcs_service as pcs_svc_mod
    import emsclaw_backend.service.station_service as stn_svc_mod

    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    tables = (Device, PcsDevice, BatteryDevice, PcsSnapshot, BatterySnapshot,
              PvDevice, PvSnapshot, MeterDevice, MeterSnapshot,
              ElectricityTariff, DailyEnergyRecord, StationConfig, ChargeSchedule)
    for tbl in tables:
        tbl.__table__.create(engine)
    sf = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    # 四个 mapper 模块全部指向同一 factory → 工具/服务读同一库
    monkeypatch.setattr(pcs_m, "SyncSessionLocal", sf)
    monkeypatch.setattr(stn_m, "SyncSessionLocal", sf)
    monkeypatch.setattr(sched_m, "SyncSessionLocal", sf)
    monkeypatch.setattr(dev_m, "SyncSessionLocal", sf)

    # 重置单例,让 get_default_service 惰性构造(读 patch 后 SF)
    reset_default_service()
    import emsclaw_backend.service.station_service as st
    st._default_service = None

    # 播种 PCS + 场站(PV/表计/电价/配置)
    pcs = PcsService()
    pcs.ensure_seeded()
    stn = StationSimService()
    stn.ensure_seeded()

    yield {
        "sf": sf,
        "pcs": PcsService,
        "stn": StationSimService,
        "tables": tables,
    }
    reset_default_service()
    st._default_service = None


def _ts(day: datetime, hour: int) -> int:
    return int(day.replace(hour=hour, minute=30, second=0, microsecond=0).timestamp())


def _today_start() -> datetime:
    return datetime.now(tz=_SH).replace(hour=0, minute=0, second=0, microsecond=0)


# ── optimize_dispatch ─────────────────────────────────────────
def test_optimize_dispatch_returns_24h_schedule(dispatch_env):
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({})
    assert out["status"] == "ok", out
    assert out["target_date"]
    assert len(out["schedule"]) == 24
    for seg in out["schedule"]:
        assert seg["hour"] in range(24)
        assert seg["mode"] in ("charge", "discharge", "standby")
        assert 0.0 <= seg["power_ratio"] <= 1.0
        assert 0.0 <= seg["soc_target_pct"] <= 1.0
        assert seg["period"]
    for key in ("grid_cost", "demand_charge", "carbon_kg", "green_rate",
                "charge_kwh", "discharge_kwh", "est_savings_yuan",
                "baseline_grid_cost", "baseline_demand_charge",
                "peak_load_kw", "load_total_kwh", "contract_demand_kw",
                "baseline_peak_kw"):
        assert key in out["summary"], f"summary missing {key}"
    assert out["storage"]["n_pcs"] == 2
    assert out["storage"]["total_rated_kw"] == pytest.approx(1000.0, abs=1.0)
    # 站配置(申报需量/需量电价/防逆流设定)随返回暴露,供 agent 呈现现状
    # seed 申报需量 1250(略高于无储能基线关口峰值~1222,留余量;且 ≥ LP 物理下限~1146)
    assert out["config"]["contract_demand_kw"] == pytest.approx(1250.0, abs=1.0)
    assert out["config"]["demand_price_yuan_per_kw_month"] == pytest.approx(40.0, abs=1.0)


def test_optimize_dispatch_strategy_combos(dispatch_env):
    """各策略组合(单选与多选)均可行,且权重按预期合并(可解 -> 不要求结果不同,只求各自 status ok)。"""
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    for st in ("省钱", "保电池", "绿电优先", "防逆流"):
        out = optimize_dispatch.invoke({"strategies": [st]})
        assert out["status"] == "ok", f"{st}: {out}"
        assert st in (out.get("strategies") or [])
        assert out["weights_used"]["w_carbon"] is not None
    combo = optimize_dispatch.invoke({"strategies": ["保电池", "绿电优先"]})
    assert combo["status"] == "ok", combo
    w = combo["weights_used"]
    assert w["w_degrade"] == 0.30
    # w_carbon 0.15 ≈ 150 元/吨碳价(国内碳市场),旧值 0.8 等价 800 元/吨过高
    assert w["w_carbon"] == 0.15
    anti = optimize_dispatch.invoke({"strategies": ["防逆流"]})
    assert anti["weights_used"]["anti_reverse"] == 0.0


def test_optimize_dispatch_constraint_demand_cap(dispatch_env):
    """注入 demand_cap → 求解后 peak_demand_kw ≤ 上限(+容差)。

    削峰受真实电池能量约束:seed 负荷峰值 ~1510kW,
    2000kWh 电池在保供+闭环下最多削到 ~1000kW;加 15min 保守系数 1.15 后
    dmax 物理下限升至 ~1146kW,1200 可行、1100 infeasible。
    更低的 cap 如实返回 infeasible,不靠"冻结 SOC"凭空削峰(若该路径回归,
    下方 1100 断言会失败)。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [{"type": "demand_cap", "value_kw": 1200.0}],
    })
    assert out["status"] == "ok", out
    assert out["summary"]["peak_demand_kw"] <= 1200.0 + 1.0
    # 物理削不动的 cap → 如实 infeasible(不得凭空削峰)
    low = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [{"type": "demand_cap", "value_kw": 1100.0}],
    })
    assert low["status"] == "infeasible", low


def test_optimize_dispatch_constraint_no_export(dispatch_env):
    """注入 no_export → Pex 全 0(防逆流),仍可行。"""
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "strategies": ["防逆流"],
        "constraints": [{"type": "no_export"}],
    })
    assert out["status"] == "ok", out


def test_optimize_dispatch_constraint_respect_declared_demand(dispatch_env):
    """注入 respect_declared_demand → 关口表峰值需量 ≤ 站配置申报需量。

    申报需量由工具内部从系统读取并随返回暴露(config/summary.contract_demand_kw),
    不依赖调用方(LLM)传数——杜绝猜数设上限。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [{"type": "respect_declared_demand"}],
    })
    assert out["status"] == "ok", out
    # 站配置申报需量(seed 1250)由工具内部读取并回传
    assert out["config"]["contract_demand_kw"] == pytest.approx(1250.0, abs=1.0)
    assert out["summary"]["contract_demand_kw"] == pytest.approx(1250.0, abs=1.0)
    # 硬上限生效:求解后关口表峰值需量 ≤ 申报需量(+求解容差)
    assert out["summary"]["peak_demand_kw"] <= out["summary"]["contract_demand_kw"] + 1.0


def test_optimize_dispatch_schedule_soc_tracks_energy(dispatch_env):
    """SOC 轨迹与充放电功率物理自洽(量纲正确性回归)。

    若 SOC 动态系数多除一个 cap,SOC 曲线几乎冻结(充 650kW 只动 0.0002),
    下发的 soc_target_pct 就是假的,SOC 上下界日间从不 bind。
    本用例:用 schedule 的功率按真实物理(η=√eff)回放,累计 SOC 应与
    soc_target_pct 逐小时吻合(容差内),且轨迹显著偏离初始值(不是平线)。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [{"type": "respect_declared_demand"}],
    })
    assert out["status"] == "ok", out
    cap = out["storage"]["total_cap_kwh"]
    init = out["storage"]["initial_soc"]
    eta = out["storage"]["eff"] ** 0.5

    # 按功率回放物理 SOC(kWh)
    soc_kwh = init * cap
    max_dev_kwh = 0.0
    for seg in out["schedule"]:
        if seg["mode"] == "charge":
            soc_kwh += eta * seg["power_kw"]
        elif seg["mode"] == "discharge":
            soc_kwh -= seg["power_kw"] / eta
        dev_kwh = abs(soc_kwh - seg["soc_target_pct"] * cap)
        max_dev_kwh = max(max_dev_kwh, dev_kwh)
    # 24h 功率四舍五入(0.1kW)+ SOC(4 位小数)累计误差 ≪ 1kWh;留 LP 数值容差
    assert max_dev_kwh < 20.0, \
        f"SOC 轨迹与功率不自洽,最大偏差 {max_dev_kwh:.1f} kWh"
    # 轨迹不能是平线:日间有充放时 SOC 应显著偏离初始
    swing = max(abs(s["soc_target_pct"] - init) for s in out["schedule"])
    assert swing > 0.05, f"SOC 轨迹几乎冻结,最大偏离 {swing:.4f}"


def test_optimize_dispatch_demand_cap_plus_respect_declared_min(dispatch_env):
    """同时传「需量压到 1200」与「不超申报值(1250)」→ 取较严 1200。

    两类约束若各自直接覆盖 bounds[dmax],就会变成后写覆盖先写、结果取决于顺序。
    实现上合并取 min,无论顺序,峰值需量都必须 ≤ 1200(demand_cap 比 seed 申报
    需量 1250 更严,故 demand_cap 胜出)。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    # 顺序一:先 respect,再「压到 1200」(若后写覆盖 → 上限 1200,峰值 1200)
    o1 = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [
            {"type": "respect_declared_demand"},
            {"type": "demand_cap", "value_kw": 1200.0},
        ],
    })
    assert o1["status"] == "ok", o1
    assert o1["summary"]["peak_demand_kw"] <= 1200.0 + 1.0
    # 顺序二:先「压到 1200」,再 respect(合并取 min 应顺序无关)
    o2 = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [
            {"type": "demand_cap", "value_kw": 1200.0},
            {"type": "respect_declared_demand"},
        ],
    })
    assert o2["status"] == "ok", o2
    assert o2["summary"]["peak_demand_kw"] <= 1200.0 + 1.0


def test_optimize_dispatch_constraint_reserve_binds(dispatch_env):
    """保备用约束真正抬高 SOC 下限(reserve 单位正确性回归)。

    reserve 若算成分数、却与 kWh 的 lo 比较,就永不生效;且 SOC 轨迹冻结时
    下限再低也不会 bind。本用例:加 reserve 的调度全程 SOC(kWh) ≥ 保底。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    base = optimize_dispatch.invoke({"strategies": ["省钱"]})
    assert base["status"] == "ok", base
    cap = base["storage"]["total_cap_kwh"]
    peak_load = base["summary"]["peak_load_kw"]
    hrs = 2.0
    reserve_floor_kwh = hrs * 0.3 * peak_load  # 与 _solve 内 reserve 同式(kWh)

    with_r = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [{"type": "reserve", "hours_val": hrs}],
    })
    assert with_r["status"] == "ok", with_r
    min_soc_kwh = min(s["soc_target_pct"] for s in with_r["schedule"]) * cap
    assert min_soc_kwh >= reserve_floor_kwh - 30.0, \
        f"保底 {reserve_floor_kwh:.0f}kWh,实际最低 {min_soc_kwh:.0f}kWh —— reserve 未生效"


def test_optimize_dispatch_infeasible(dispatch_env):
    """强冲突约束(需量上限极低 + 保底 SOC)→ 如实返回 infeasible,不硬造数据。"""
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [
            {"type": "demand_cap", "value_kw": 10.0},
            {"type": "reserve", "hours_val": 20.0},
        ],
    })
    assert out["status"] in ("infeasible", "error")


def test_optimize_dispatch_infeasible_demand_diagnostic(dispatch_env):
    """需量上限低于物理可行下限 → 附可行下限诊断,agent 直接据此上调,无需二分试算。

    infeasible 若只给一句「约束冲突」,子 agent 会被迫
    12 次二分试算扫需量上限(实测 169s)。故一次返回 min_feasible_demand_cap_kw,
    且该值应比请求值 800 高、又在物理上能达到的区间内。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [{"type": "demand_cap", "value_kw": 800.0}],
    })
    assert out["status"] == "infeasible", out
    assert out.get("diagnosis") == "demand_cap_below_feasible", out
    assert out["requested_demand_cap_kw"] == pytest.approx(800.0, abs=1.0)
    min_cap = out["min_feasible_demand_cap_kw"]
    assert min_cap is not None and min_cap > 800.0, out
    assert "recommendation" in out
    # 诊断值必须真实可解:按建议的 min_feasible 上调后重跑应转为可行
    retry = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [{"type": "demand_cap", "value_kw": min_cap + 1.0}],
    })
    assert retry["status"] == "ok", retry
    assert retry["summary"]["peak_demand_kw"] <= min_cap + 2.0


def test_optimize_dispatch_infeasible_other_constraint_diagnosis(dispatch_env):
    """冲突来自其它约束(放开需量上限仍不可行)→ diagnosis=other_constraints_infeasible。"""
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [
            {"type": "demand_cap", "value_kw": 10.0},
            {"type": "reserve", "hours_val": 20.0},
        ],
    })
    assert out["status"] == "infeasible", out
    if "diagnosis" in out:
        assert out["diagnosis"] == "other_constraints_infeasible", out
        assert out["min_feasible_demand_cap_kw"] is None
        assert "recommendation" in out


def test_optimize_dispatch_preview(dispatch_env):
    """preview 模式:不求解带约束策略,一次返回现状/无储能基线/无约束默认效果/需量可行域。

    回归 trace 5QJJJ...(压需量 4 解)/ MurgKX...(保电池 3 解):dispatch 子 agent 只有
    optimize_dispatch 一个数据源,想定数值约束(需量上限/吞吐上限)必须先求解学数据
    (solve-to-learn)。preview 让 agent 先一步拿到申报需量/负荷峰值/可用容量/需量物理下限,
    把数值锚定在真实区间再求解一次。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({"preview": True})
    assert out["status"] == "preview", out
    assert "schedule" not in out  # 不返回 24h 策略

    ctx = out["station_context"]
    assert ctx["contract_demand_kw"] == pytest.approx(1250.0, abs=1.0)
    assert ctx["load_peak_kw"] == pytest.approx(1510.0, abs=10.0)
    assert ctx["storage"]["n_pcs"] == 2
    # 可用容量 = 容量×(max_soc−min_soc) = 2000×(0.9−0.1),agent 据此设吞吐锚点,无需猜数
    assert ctx["storage"]["usable_capacity_kwh"] == pytest.approx(1600.0, abs=10.0)

    base = out["baseline_no_storage"]
    assert base["peak_import_kw"] == pytest.approx(1510.0, abs=10.0)

    env = out["envelope"]["demand_kw"]
    assert env["contract_demand_kw"] == pytest.approx(1250.0, abs=1.0)
    assert env["min_feasible_kw"] is not None
    assert env["min_feasible_kw"] > 1100.0  # v2 15min 保守系数下物理下限 ~1146

    # 吞吐可行域:min_feasible=守住申报需量所需最小日吞吐,低于它+需量约束 → 不可行。
    # 回归 trace e476bba(保电池):吞吐上限 2000/2200 不可行、2400 可行 —— agent 缺此
    # 锚点而撞出 2 次 infeasible;envelope 让它在第一次求解前就有 [min_feasible, unconstrained]。
    tp = out["envelope"]["throughput_kwh"]
    assert tp["min_feasible_kwh"] is not None
    assert tp["unconstrained_kwh"] is not None
    assert tp["unconstrained_kwh"] > tp["min_feasible_kwh"]
    # 语义契约:上限略低于/略高于 min_feasible → 不可行/可行(与需量约束联动)
    floor = tp["min_feasible_kwh"]
    lo = optimize_dispatch.invoke({
        "preview": False,
        "strategies": ["保电池", "省钱"],
        "constraints": [{"type": "respect_declared_demand"},
                        {"type": "throughput_cap", "kwh": round(floor - 50, 1)}],
    })
    hi = optimize_dispatch.invoke({
        "preview": False,
        "strategies": ["保电池", "省钱"],
        "constraints": [{"type": "respect_declared_demand"},
                        {"type": "throughput_cap", "kwh": round(floor + 50, 1)}],
    })
    assert lo["status"] == "infeasible", lo
    assert hi["status"] == "ok", hi
    # 安全下界已含余量:cap 直接取 min_feasible_kwh 必须可行(否则 agent 又要对边界试错)。
    # 实测原始 floor 精确值在 HiGHS 边界上不可行(floor+1 才可行)——余量消灭此坑。
    exact = optimize_dispatch.invoke({
        "preview": False,
        "strategies": ["保电池", "省钱"],
        "constraints": [{"type": "respect_declared_demand"},
                        {"type": "throughput_cap", "kwh": tp["min_feasible_kwh"]}],
    })
    assert exact["status"] == "ok", exact

    # 策略组合改变默认效果:保电池默认吞吐(充+放)显著低于省钱
    save = optimize_dispatch.invoke({"preview": True, "strategies": ["省钱"]})
    battery = optimize_dispatch.invoke({"preview": True, "strategies": ["保电池"]})
    assert save["status"] == "preview" and battery["status"] == "preview"
    thr_save = save["default"]["charge_kwh"] + save["default"]["discharge_kwh"]
    thr_bat = battery["default"]["charge_kwh"] + battery["default"]["discharge_kwh"]
    assert thr_save > thr_bat, f"省钱吞吐 {thr_save} 应大于保电池 {thr_bat}"
    # 保电池自然吞吐上限更紧 → envelope 上限随之收窄,锚点才贴近实际可操作带
    assert (battery["envelope"]["throughput_kwh"]["unconstrained_kwh"]
            < save["envelope"]["throughput_kwh"]["unconstrained_kwh"])


# ── v2: scenario / sanity_check / carbon_cost / active_constraints ──
def test_optimize_dispatch_scenario_load_scale(dispatch_env):
    """scenario.load_scale 缩放负荷:load+20% 后负荷总量与峰值都 ×1.2。

    what-if 不改变 LP 结构,只改输入数据。结果带 scenario_applied 字段透传,
    让 agent 感知"这是假设值"——避免把假设当现状叙述给用户。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    base = optimize_dispatch.invoke({"strategies": ["省钱"]})
    assert base["status"] == "ok", base
    base_load = base["summary"]["load_total_kwh"]
    base_peak = base["summary"]["peak_load_kw"]

    hi = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "scenario": {"load_scale": 1.2},
    })
    assert hi["status"] == "ok", hi
    # scenario 透传到结果
    assert hi["scenario_applied"] == {"load_scale": 1.2, "pv_scale": 1.0, "price_delta": 0.0}
    # 负荷总量 ×1.2(峰值也是,seed 负荷按比例放大)
    assert hi["summary"]["load_total_kwh"] == pytest.approx(base_load * 1.2, rel=0.01)
    assert hi["summary"]["peak_load_kw"] == pytest.approx(base_peak * 1.2, rel=0.01)
    # baseline 不变 → 假设场景下省的钱更多(负荷高,电池削峰价值更大)
    assert hi["summary"]["est_savings_yuan"] > base["summary"]["est_savings_yuan"]


def test_optimize_dispatch_scenario_pv_scale(dispatch_env):
    """scenario.pv_scale 缩放光伏:阴天 0.3 折后 pv_total_kwh ×0.3,green_rate 下降。"""
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    base = optimize_dispatch.invoke({"strategies": ["绿电优先"]})
    assert base["status"] == "ok", base
    base_pv = base["summary"]["pv_total_kwh"]

    cloudy = optimize_dispatch.invoke({
        "strategies": ["绿电优先"],
        "scenario": {"pv_scale": 0.3},
    })
    assert cloudy["status"] == "ok", cloudy
    assert cloudy["scenario_applied"]["pv_scale"] == 0.3
    assert cloudy["summary"]["pv_total_kwh"] == pytest.approx(base_pv * 0.3, rel=0.01)
    # 光伏少了 → 绿电自用率(分子)下降、买电(分母)上升 → green_rate 下降
    assert cloudy["summary"]["green_rate"] < base["summary"]["green_rate"]
    assert cloudy["summary"]["carbon_kg"] > base["summary"]["carbon_kg"]


def test_optimize_dispatch_scenario_price_delta(dispatch_env):
    """scenario.price_delta 平移电价:+0.1 元/kWh 后所有时段价格上浮。

    what-if 不改变 LP 结构,只改输入数据。结果带 scenario_applied 字段透传。
    (不直接断言 savings 变化方向——LP 在新价下会重解,结构可能改变,只验 tariff 平移。)
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    base = optimize_dispatch.invoke({"strategies": ["省钱"]})
    assert base["status"] == "ok", base
    hi = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "scenario": {"price_delta": 0.1},
    })
    assert hi["status"] == "ok", hi
    assert hi["scenario_applied"]["price_delta"] == 0.1
    # 每小时 tariff_price 都比基线 +0.1
    for bs, hs in zip(base["schedule"], hi["schedule"]):
        assert hs["tariff_price"] == pytest.approx(bs["tariff_price"] + 0.1, abs=0.01)
    # 电价上浮 → baseline_grid_cost 与 grid_cost 都应上升(每度电都更贵)
    assert hi["summary"]["baseline_grid_cost"] > base["summary"]["baseline_grid_cost"]


def test_optimize_dispatch_sanity_check_energy_conserved(dispatch_env):
    """sanity_check 能量守恒自检:ΔSOC ≈ ΣPc·η − ΣPd/η,conserved=True、warnings 空。

    回归 75s 侦探戏:子 agent 发现 SOC 轨迹异常却 rationalize 掉。solver 自检把
    物理一致性从"指望模型发现"升级为"确定性断言",warnings 透传给 agent。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [{"type": "respect_declared_demand"}],
    })
    assert out["status"] == "ok", out
    sanity = out["sanity_check"]
    assert sanity["energy_conserved"] is True, sanity
    assert sanity["warnings"] == [], sanity
    # ΔSOC 与净充入差值 < 5kWh 容差(LP 数值精度 + 功率 0.1kW 四舍五入累计误差远小)
    assert sanity["diff_kwh"] < 5.0, sanity
    # 末态 SOC ≥ 初始(日内闭环,不透支次日)→ ΔSOC ≥ 0
    assert sanity["delta_soc_kwh"] >= -1.0, sanity


def test_optimize_dispatch_carbon_cost_green_priority(dispatch_env):
    """carbon_cost:绿电优先多付的电费(w_carbon>0 时重解 w_carbon=0 对照)。

    绿电优先策略应 carbon_cost > 0(为了减碳多付了电费);省钱策略 carbon_cost = 0
    (w_carbon=0 无需对照)。让 agent 据此向用户解释"绿电优先的代价是 X 元/天"。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    save = optimize_dispatch.invoke({"strategies": ["省钱"]})
    assert save["status"] == "ok", save
    assert save["summary"]["carbon_cost"] == 0.0  # 省钱 w_carbon=0,无对照

    green = optimize_dispatch.invoke({"strategies": ["绿电优先"]})
    assert green["status"] == "ok", green
    # 绿电优先 w_carbon=0.15 → 多付电费(对照同约束 w_carbon=0 的解)
    assert green["summary"]["carbon_cost"] >= 0.0
    # 绿电优先的碳排应比省钱低(这正是多付 carbon_cost 买来的)
    assert green["summary"]["carbon_kg"] <= save["summary"]["carbon_kg"] + 5.0


def test_optimize_dispatch_active_constraints_binding(dispatch_env):
    """active_constraints:binding 约束在解处起作用(松弛=0),非 binding 有余量。

    消灭"锁了却 standby"的侦探戏:agent 直接读 binding 列表告知用户"哪些约束
    实际锁住了",无需从结果反推。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    # demand_cap 紧到接近物理下限 → 应 binding
    out = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [
            {"type": "demand_cap", "value_kw": 1200.0},
            {"type": "no_export"},
        ],
    })
    assert out["status"] == "ok", out
    active = {a["type"]: a["binding"] for a in out["active_constraints"]}
    assert "demand_cap" in active, active
    assert "no_export" in active, active
    # demand_cap=1200 接近物理下限 ~1146,peak_demand_kw 应回到 1200(或被 dmax 上限锁)
    # 若 peak_demand_kw < 1200 一截 → 非 binding(松弛>0);若 ≈ 1200 → binding
    peak = out["summary"]["peak_demand_kw"]
    if abs(peak - 1200.0) < 2.0:
        assert active["demand_cap"] is True
    else:
        assert active["demand_cap"] is False
    # no_export 强制 Pex=0 → 总是 binding
    assert active["no_export"] is True

    # demand_cap 放很宽 → 非 binding(松弛>0,根本没顶到上限)
    loose = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [{"type": "demand_cap", "value_kw": 5000.0}],
    })
    assert loose["status"] == "ok", loose
    active_loose = {a["type"]: a["binding"] for a in loose["active_constraints"]}
    assert active_loose["demand_cap"] is False, active_loose


# ── tick 同源数据层 ───────────────────────────────
def test_forecast_from_ticks_fallback_when_no_history(dispatch_env):
    """无 tick 历史 → 回退公式,source=fallback_formula / confidence=low。

    避免静默兜底出一个看似可信的数字:数据不足时必须显式标注,让 agent 感知
    "预测其实是猜的",转告用户而非当现状叙述。
    """
    from datetime import date
    from emsclaw_backend.service.ems_data import forecast_from_ticks
    from emsclaw_backend.service.station_service import StationSimService

    td = date(2026, 8, 15)
    fc = forecast_from_ticks(td)
    assert fc["source"] == "fallback_formula"
    assert fc["confidence"] == "low"
    assert fc["days_covered"] == 0
    # 与 station_service 公式同源(回退分支直接调 get_forecast_day)
    fb = StationSimService().get_forecast_day(td)
    assert fc["load_kw"] == fb["load_kw"]
    assert fc["pv_kw"] == fb["pv_kw"]
    assert len(fc["load_kw"]) == 24


def test_forecast_from_ticks_from_history(dispatch_env):
    """有 ≥3 天 tick 历史 → source=tick_history / confidence=high,load_kw=快照均值。

    手动插 3 天 meter/pv 快照(每小时 1 条),验证按 hour 桶聚合取均值正确。
    """
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo
    from emsclaw_backend.service.ems_data import forecast_from_ticks, _hour_of
    from emsclaw_backend.mapper.station_mapper import StationMapper
    from emsclaw_backend.db.models import MeterSnapshot, PvSnapshot

    _SH = ZoneInfo("Asia/Shanghai")
    td = date(2026, 8, 15)
    mapper = StationMapper()
    meter = mapper.first_meter_device()
    pv_dev = mapper.first_pv_device()
    assert meter is not None and pv_dev is not None

    # 插 3 天历史(8/12、8/13、8/14),每小时 1 条 meter + pv 快照
    # 负荷:每小时 h 的 load_kw = 1000 + h*10(便于验证均值)
    # 光伏:每小时 h 的 generation_kw = 500 + h*5(白天非零)
    target_day = datetime(2026, 8, 15, tzinfo=_SH)
    for d_back in range(1, 4):  # 1,2,3 天前
        day = target_day - timedelta(days=d_back)
        for h in range(24):
            ts = int(day.replace(hour=h, minute=15, second=0, microsecond=0).timestamp())
            mapper.insert_meter_snapshot(MeterSnapshot(
                id=f"MS-{d_back}-{h}", meter_id=meter.id, timestamp=ts,
                load_kw=1000.0 + h * 10.0, rolling_demand_kw=1100.0 + h * 10.0,
                import_kw=1000.0 + h * 10.0, export_kw=0.0,
            ))
            mapper.insert_pv_snapshot(PvSnapshot(
                id=f"PS-{d_back}-{h}", pv_id=pv_dev.id, timestamp=ts,
                generation_kw=500.0 + h * 5.0, irradiance=600.0,
            ))

    fc = forecast_from_ticks(td, days=7)
    assert fc["source"] == "tick_history"
    assert fc["confidence"] == "high"
    assert fc["days_covered"] == 3
    # hour 0 → load=1000, hour 23 → load=1230(三天均值等于单天值,因为每天同公式)
    assert fc["load_kw"][0] == pytest.approx(1000.0, abs=0.5)
    assert fc["load_kw"][23] == pytest.approx(1230.0, abs=0.5)
    # pv hour 0 → 500, hour 23 → 615
    assert fc["pv_kw"][0] == pytest.approx(500.0, abs=0.5)
    assert fc["pv_kw"][23] == pytest.approx(615.0, abs=0.5)


def test_month_max_demand_kw_empty(dispatch_env):
    """月初无 meter 快照 → 返回 0.0(不抛异常)。"""
    from emsclaw_backend.service.ems_data import month_max_demand_kw
    assert month_max_demand_kw() == 0.0


def test_month_max_demand_kw_with_history(dispatch_env):
    """有 meter 快照 → 返回当月 max(rolling_demand_kw)。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from emsclaw_backend.service.ems_data import month_max_demand_kw
    from emsclaw_backend.mapper.station_mapper import StationMapper
    from emsclaw_backend.db.models import MeterSnapshot

    _SH = ZoneInfo("Asia/Shanghai")
    mapper = StationMapper()
    meter = mapper.first_meter_device()
    now = datetime.now(tz=_SH)
    # 当月内插两条:一条 1100、一条 1300(应取 1300)
    ts1 = int(now.replace(day=5, hour=10, minute=0, second=0, microsecond=0).timestamp())
    ts2 = int(now.replace(day=10, hour=14, minute=0, second=0, microsecond=0).timestamp())
    mapper.insert_meter_snapshot(MeterSnapshot(
        id="MS-T1", meter_id=meter.id, timestamp=ts1,
        load_kw=1000.0, rolling_demand_kw=1100.0))
    mapper.insert_meter_snapshot(MeterSnapshot(
        id="MS-T2", meter_id=meter.id, timestamp=ts2,
        load_kw=1250.0, rolling_demand_kw=1300.0))
    assert month_max_demand_kw() == pytest.approx(1300.0, abs=0.5)


def test_optimize_dispatch_returns_forecast_source(dispatch_env):
    """工具返回里带 forecast_source / forecast_confidence / demand_charge_basis。

    agent 据此在叙述里告知用户:"今天的预测来自 7 天历史均值(高可信)" vs
    "历史数据不足,预测用了公式假设(低可信,建议先灌历史)"。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({"strategies": ["省钱"]})
    assert out["status"] == "ok", out
    # fresh 测试 DB 无 tick 历史 → fallback_formula / low
    assert out["forecast_source"] == "fallback_formula"
    assert out["forecast_confidence"] == "low"
    # 需量计费口径字段
    assert "demand_charge_basis" in out
    assert "month_max_so_far_kw" in out["demand_charge_basis"]
    # preview 也带这些字段
    pv = optimize_dispatch.invoke({"preview": True})
    assert pv["status"] == "preview"
    assert pv["forecast_source"] == "fallback_formula"
    assert pv["forecast_confidence"] == "low"
    assert "demand_charge_basis" in pv


# ── 输出保证链路(artifact + dispatch_preview 事件 + 兜底块)──
def test_dispatch_artifact_store_and_render():
    """artifact store:存/取/清 + render_markdown_block 生成合规 <dispatch_preview> 块。

    只要 optimize_dispatch 返回 ok,完整 schedule+summary 必然到达前端。
    artifact 是"求解成功"的确定性缓存,不依赖 LLM 输出格式正确。
    """
    from emsclaw_backend.service import dispatch_artifact

    # 构造一个 ok 求解结果
    result = {
        "status": "ok",
        "target_date": "2026-08-15",
        "strategies": ["省钱"],
        "schedule": [{"hour": h, "mode": "charge", "power_kw": 100.0,
                      "power_ratio": 0.1, "soc_target_pct": 0.5,
                      "period": "谷", "tariff_price": 0.3} for h in range(24)],
        "summary": {"grid_cost": 1000.0, "est_savings_yuan": 500.0,
                    "peak_demand_kw": 1100.0, "charge_kwh": 500.0,
                    "discharge_kwh": 480.0, "green_rate": 0.6,
                    "carbon_kg": 200.0, "carbon_cost": 0.0},
    }
    sid = "test-session-1"
    assert dispatch_artifact.get(sid) is None
    dispatch_artifact.store(sid, result)
    assert dispatch_artifact.get(sid) is result

    # render_markdown_block 生成块
    block = dispatch_artifact.render_markdown_block(result)
    assert block.startswith("<dispatch_preview>")
    assert block.endswith("</dispatch_preview>")
    assert dispatch_artifact.has_block_in_text(block)
    assert dispatch_artifact.has_block_in_text(f"some text\n{block}\nmore")
    assert not dispatch_artifact.has_block_in_text("no block here")

    # clear
    dispatch_artifact.clear(sid)
    assert dispatch_artifact.get(sid) is None


def test_runner_extract_dispatch_artifact_parsing():
    """runner._extract_dispatch_artifact:从各种 output 形态提取 status=ok 的 dict。

    output 可能是 dict(langchain 保留原始)、str(JSON)、ToolMessage(content str)。
    非 ok / 解析失败 / 缺 schedule+summary → None。
    """
    from emsclaw_backend.deepagent.runner import _extract_dispatch_artifact

    ok_dict = {"status": "ok", "schedule": [{"hour": 0}], "summary": {"a": 1}}
    assert _extract_dispatch_artifact(ok_dict) is ok_dict

    # JSON 字符串
    import json
    assert _extract_dispatch_artifact(json.dumps(ok_dict)) == ok_dict

    # 非 ok(infeasible / error) → None
    assert _extract_dispatch_artifact({"status": "infeasible"}) is None
    assert _extract_dispatch_artifact({"status": "error"}) is None

    # ok 但缺 schedule/summary → None
    assert _extract_dispatch_artifact({"status": "ok"}) is None

    # 非 dict/str/JSON → None
    assert _extract_dispatch_artifact(None) is None
    assert _extract_dispatch_artifact("not json") is None
    assert _extract_dispatch_artifact(12345) is None

    # ToolMessage-like 对象(content 是 JSON 字符串)
    class _FakeMsg:
        def __init__(self, content):
            self.content = content
    msg = _FakeMsg(json.dumps(ok_dict))
    assert _extract_dispatch_artifact(msg) == ok_dict
    # content 是 block 列表
    msg2 = _FakeMsg([{"text": json.dumps(ok_dict)}])
    assert _extract_dispatch_artifact(msg2) == ok_dict


def test_optimize_dispatch_no_storage(monkeypatch):
    """无在线储能 → no_storage,提示先录入设备(不抛异常)。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, Session
    from sqlalchemy.pool import StaticPool
    import emsclaw_backend.mapper.pcs_mapper as pcs_m
    import emsclaw_backend.mapper.station_mapper as stn_m
    import emsclaw_backend.mapper.schedule_mapper as sched_m
    import emsclaw_backend.mapper.device_mapper as dev_m
    import emsclaw_backend.service.pcs_service as pcs_svc_mod
    import emsclaw_backend.service.station_service as stn_svc_mod

    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    for tbl in (Device, PcsDevice, BatteryDevice, PcsSnapshot, BatterySnapshot,
                PvDevice, PvSnapshot, MeterDevice, MeterSnapshot,
                ElectricityTariff, DailyEnergyRecord, StationConfig):
        tbl.__table__.create(engine)
    sf = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    monkeypatch.setattr(pcs_m, "SyncSessionLocal", sf)
    monkeypatch.setattr(stn_m, "SyncSessionLocal", sf)
    monkeypatch.setattr(sched_m, "SyncSessionLocal", sf)
    monkeypatch.setattr(dev_m, "SyncSessionLocal", sf)
    reset_default_service()
    import emsclaw_backend.service.station_service as st
    st._default_service = None

    # 只播种场站(PV/表计),不播 PCS
    StationSimService().ensure_seeded()

    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({})
    assert out["status"] == "no_storage", out
    reset_default_service()
    st._default_service = None


# ── current_time ──────────────────────────────────────────────
def test_current_time_local_timestamp(dispatch_env):
    """本地时间戳工具:零沙箱往返,返回 Asia/Shanghai 当前时间与文件名时间戳。"""
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        current_time,
    )
    out = current_time.invoke({})
    assert out["status"] == "ok", out
    assert out["date"] == _today_start().date().isoformat()
    assert ":" in out["time"]
    assert 0 <= out["hour"] <= 23
    # filename_ts 可直接用于 reports/调度策略_<date>_<ts>.md
    assert out["filename_ts"].startswith(out["date"].replace("-", ""))
    assert len(out["filename_ts"]) == 15  # YYYYMMDD_HHMMSS


# ── apply_schedule ────────────────────────────────────────────
def _make_schedule(dispatch_env):
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({})
    assert out["status"] == "ok", out
    return out


def test_apply_schedule_activates_and_supersedes(dispatch_env):
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        apply_schedule,
    )
    out = _make_schedule(dispatch_env)
    td = out["target_date"]
    first = apply_schedule.invoke({
        "schedule": out["schedule"], "strategies": ["省钱"],
        "target_date": td, "objective": out["summary"],
    })
    assert first["status"] == "active", first
    assert first["schedule_id"].startswith("SCH-")

    # 二次下发 → 旧 active 被 superseded,仅新 active
    second = apply_schedule.invoke({
        "schedule": out["schedule"], "strategies": ["保电池"],
        "target_date": td, "objective": out["summary"],
    })
    assert second["status"] == "active"
    assert second["schedule_id"] != first["schedule_id"]

    sm = ScheduleMapper()
    active = sm.get_active_schedule(td)
    assert active.id == second["schedule_id"]
    assert active.strategies == ["保电池"]
    assert len(active.intervals) == 24
    old = sm.get_by_id(first["schedule_id"])
    assert old.status == "superseded"


def test_apply_schedule_rejects_bad_input(dispatch_env):
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        apply_schedule,
    )
    # 字段合法但条数非 24 → body 校验拒绝
    one = [{"hour": 0, "mode": "charge", "power_kw": 100.0,
            "power_ratio": 0.2, "soc_target_pct": 0.5, "period": "谷",
            "tariff_price": 0.3}]
    out = apply_schedule.invoke({"schedule": one})
    assert out["status"] == "rejected"
    assert "24" in out["reason"]


# ── 闭环:下发 → tick 按计划执行 → SOC 追踪 → 偏差监测 ─────────
def test_tick_closed_loop_follows_schedule(dispatch_env):
    """核心闭环:下发 active 计划 → 当日 tick 按计划充放电 → SOC 朝向 soc_target_pct、
    快照/日电量写入 → 收益可核算。"""
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch, apply_schedule,
    )
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        get_schedule_status, account_revenue,
    )
    out = _make_schedule(dispatch_env)
    td = out["target_date"]
    sched = out["schedule"]
    applied = apply_schedule.invoke({
        "schedule": sched, "strategies": ["省钱"],
        "target_date": td, "objective": out["summary"],
    })
    assert applied["status"] == "active"

    # 全 24h 逐 tick(站级 tick 内部会驱动 PCS decide_mode_and_power)
    stn = StationSimService()
    day = datetime.strptime(td, "%Y-%m-%d").replace(tzinfo=_SH)
    ts_list = [_ts(day, h) for h in range(24)]
    for ts in ts_list:
        stn.tick(ts)

    # 1) PCS 快照:每 tick 都写了,且功率符号与计划一致(抽样检查)
    pcs_mapper = PcsMapper()
    pairs = pcs_mapper.find_online_pcs_with_battery()
    pcs_id = pairs[0][0].id
    snaps = pcs_mapper.pcs_snapshots_range(pcs_id, ts_list[0], ts_list[-1])
    assert len(snaps) == 24, f"expected 24 snapshots, got {len(snaps)}"

    # 计划中任一 charge/放电小时,对应快照模式应一致
    charge_hours = [s["hour"] for s in sched if s["mode"] == "charge"]
    discharge_hours = [s["hour"] for s in sched if s["mode"] == "discharge"]
    if charge_hours:
        h = charge_hours[0]
        snap_h = [s for s in snaps if _ts(day, h) <= s.timestamp <= _ts(day, h) + 3600]
        if snap_h:
            assert snap_h[0].mode == "charge", f"hour {h} 应充电, got {snap_h[0].mode}"

    # 2) 电池 SOC 已从 seed 变化(计划有充放)
    bat = pcs_mapper.find_battery_by_device_id(pairs[0][0].battery_id)
    assert bat.soc != pytest.approx(0.5, abs=1e-3) or charge_hours or discharge_hours

    # 3) 站级快照 + 日电量累积
    stn_mapper = StationMapper()
    meter = stn_mapper.first_meter_device()
    m_snaps = stn_mapper.meter_snapshots_range(meter.id, ts_list[0], ts_list[-1])
    assert len(m_snaps) == 24
    de = stn_mapper.get_daily_energy(td)
    assert de is not None

    # 4) 被动偏差监测:读 active 计划 + 实际 SOC,返回结构化
    status = get_schedule_status.invoke({})
    assert status["status"] == "ok", status
    assert status["active_schedule"]["schedule_id"] == applied["schedule_id"]
    assert "deviation_pct" in status
    assert "on_track" in status

    # 5) 收益核算:有数据 → ok + 结构化来源
    rev = account_revenue.invoke({"date": td})
    assert rev["status"] == "ok", rev
    assert "sources" in rev
    assert "arbitrage_yuan" in rev["sources"]
    assert "energy" in rev
    assert "charge_kwh" in rev["energy"]


def test_get_schedule_status_no_active(dispatch_env):
    """无 active 计划 → status=no_active_schedule,储能待机(被动监测如实告知)。"""
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        get_schedule_status,
    )
    out = get_schedule_status.invoke({})
    assert out["status"] == "no_active_schedule"
    assert "待机" in out["reason"]


def test_account_revenue_no_data(dispatch_env):
    """无任何站级快照 → status=no_data(不做假收益)。"""
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        account_revenue,
    )
    from datetime import date
    out = account_revenue.invoke({"date": "2020-01-01"})
    assert out["status"] == "no_data"
    assert "无法核算" in out["reason"]


def test_set_station_config_feeds_optimize_dispatch(dispatch_env):
    """申报需量写路径闭环:set_station_config(device_operation 域)改值 → 落库 →
    optimize_dispatch 的 respect_declared_demand 立即读到新值作为需求上限。"""
    import json
    from emsclaw_backend.deepagent.agents.business.domains.device_operation.tools import (
        set_station_config,
    )
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )

    # 改高申报需量 → 尊重申报需量的上限放宽
    r = json.loads(set_station_config.invoke({"contract_demand_kw": 1500.0}))
    assert r["success"] is True, r
    assert r["data"]["contract_demand_kw"] == 1500.0
    out = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [{"type": "respect_declared_demand"}],
    })
    assert out["status"] == "ok", out
    assert out["config"]["contract_demand_kw"] == 1500.0
    assert out["summary"]["peak_demand_kw"] <= 1500.0 + 1.0

    # 改低 → 上限收紧,仍可行(15min 保守系数下物理下限 ~1146,1200 仍可行)
    r2 = json.loads(set_station_config.invoke({"contract_demand_kw": 1200.0}))
    assert r2["success"] is True, r2
    out2 = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [{"type": "respect_declared_demand"}],
    })
    assert out2["status"] == "ok", out2
    assert out2["config"]["contract_demand_kw"] == 1200.0
    assert out2["summary"]["peak_demand_kw"] <= 1200.0 + 1.0


# ── optimize_dispatch: sweep 敏感性扫描─────────────────
# 背景:trace c4ccd8e11dfb8e389da0ca936d5e40d3 实测,子代理用 8 轮 LLM(49.09s /
# 约 15.3 万 input token)手工二分试探 load_scale,而 13 次 LP 求解合计只跑 0.71s。
# 以下用例锁住「一次调用拿整条曲线 + 内部二分临界值」这条路径,防止退回逐值循环。
def test_sweep_points_return_curve_without_schedule(dispatch_env):
    """sweep.points 一次返回整条曲线,且每点不含 24h schedule(保持返回体紧凑)。"""
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "sweep": {"points": [
            {"load_scale": 1.0, "label": "基准"},
            {"load_scale": 1.2, "label": "负荷+20%"},
        ]},
    })
    assert out["status"] == "ok", out
    pts = out["sweep"]["points"]
    assert len(pts) == 2
    assert pts[0]["label"] == "基准"
    assert pts[1]["label"] == "负荷+20%"
    assert [p["load_scale"] for p in pts] == [1.0, 1.2]
    for p in pts:
        assert "schedule" not in p
        assert p["peak_demand_kw"] > 0
        # 无显式需量约束时,口径上限回落到站配置申报需量(seed = 1250)
        assert p["demand_limit_kw"] == pytest.approx(1250.0, abs=1.0)
        assert isinstance(p["demand_ok"], bool)


def test_sweep_points_peak_monotonic_in_load(dispatch_env):
    """负荷倍率越大 → 关口峰值需量不降(曲线单调,说明扫描结果有意义)。"""
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "sweep": {"points": [
            {"load_scale": 1.0}, {"load_scale": 1.05}, {"load_scale": 1.1},
        ]},
    })
    pts = [p for p in out["sweep"]["points"] if p.get("feasible")]
    assert len(pts) >= 2, out["sweep"]["points"]
    peaks = [p["peak_demand_kw"] for p in pts]
    assert peaks == sorted(peaks), peaks


def test_sweep_find_limit_load_scale_boundary_is_real(dispatch_env):
    """find_limit='load_scale' → 内部二分给出临界倍率;再高一点必须真的越界。

    这是核心断言:原本要 6 轮 LLM 手工二分,现在一次调用拿到,
    且临界值必须经得起「往上加一点就守不住」的交叉验证。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [{"type": "respect_declared_demand"}],
        "sweep": {"find_limit": "load_scale"},
    })
    lim = out["sweep"]["limit"]
    assert lim["param"] == "load_scale"
    assert lim["boundary_hit"] is True, lim
    v = lim["value"]
    assert isinstance(v, float) and v >= 1.0, lim
    assert lim["range"] == [1.0, 3.0]
    # 临界点自身必须守住申报需量
    assert lim["at_limit"]["peak_demand_kw"] <= lim["at_limit"]["demand_limit_kw"] + 1e-6
    # 往上加 2% 必须越界(要么 LP 不可行,要么峰值超限)
    over = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [{"type": "respect_declared_demand"}],
        "sweep": {"points": [{"load_scale": round(v * 1.02, 3)}]},
    })
    p = over["sweep"]["points"][0]
    assert (not p["feasible"]) or (not p["demand_ok"]), p


def test_sweep_find_limit_demand_cap_matches_single_point(dispatch_env):
    """find_limit='demand_cap_kw' 的临界值,与单点求解的可行性结论一致。

    已知 seed 环境(15min 保守系数)1200 可行、1100 不可行、物理下限 ~1146,
    故临界值应落在 (1100, 1250] 且「以该值为 cap」必须可行。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({"sweep": {"find_limit": "demand_cap_kw"}})
    lim = out["sweep"]["limit"]
    assert lim["boundary_hit"] is True, lim
    v = lim["value"]
    assert isinstance(v, float), lim
    assert 1100.0 < v <= 1250.0, v
    at = optimize_dispatch.invoke({
        "constraints": [{"type": "demand_cap", "value_kw": v}],
    })
    assert at["status"] == "ok", at
    assert at["summary"]["peak_demand_kw"] <= v + 1.0


def test_sweep_limit_range_override(dispatch_env):
    """limit_range 可覆盖默认区间;区间内未触界时明确告知,而不是编一个数。"""
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "constraints": [{"type": "respect_declared_demand"}],
        "sweep": {"find_limit": "load_scale", "limit_range": [1.0, 1.05]},
    })
    lim = out["sweep"]["limit"]
    assert lim["range"] == [1.0, 1.05]
    if lim.get("boundary_hit"):
        assert 1.0 <= lim["value"] <= 1.05
    else:
        assert lim["value"] == 1.05
        assert "未触界" in lim["note"]


def test_sweep_constraints_override_inheritance(dispatch_env):
    """sweep.constraints 显式给出时不继承顶层 constraints(可独立扫描)。"""
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        # 顶层约束是 1100(该场景不可行),扫描应改用 1200 并得到可行点
        "constraints": [{"type": "demand_cap", "value_kw": 1100.0}],
        "sweep": {
            "constraints": [{"type": "demand_cap", "value_kw": 1200.0}],
            "points": [{"load_scale": 1.0}],
        },
    })
    p = out["sweep"]["points"][0]
    assert p["demand_limit_kw"] == pytest.approx(1200.0, abs=1.0)
    assert p["feasible"] is True, p
    assert p["peak_demand_kw"] <= 1200.0 + 1.0


def test_sweep_takes_precedence_over_preview(dispatch_env):
    """sweep 与 preview 同时给出时以 sweep 为准(返回 sweep 而非 station_context)。"""
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "preview": True,
        "sweep": {"points": [{"load_scale": 1.0}]},
    })
    assert out["status"] == "ok", out
    assert "sweep" in out
    assert "station_context" not in out


def test_sweep_points_truncated_at_cap(dispatch_env):
    """采样点超过上限(32)时截断并显式标记,避免一次调用把求解预算打爆。"""
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "sweep": {"points": [{"load_scale": 1.0} for _ in range(40)]},
    })
    sw = out["sweep"]
    assert len(sw["points"]) == 32
    assert sw["points_truncated"] is True


# ── 需量口径统一──────────────────────
def test_demand_fields_use_billing_units(dispatch_env):
    """peak_demand_kw 必须是计费口径(×1.15),与 contract_demand_kw 同量纲。

    回归护栏:若改用"原始小时均值",余量会被高估约 9 倍(实测 180.4 vs 真实 20.0 kW)。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [{"type": "respect_declared_demand"}],
    })
    assert out["status"] == "ok", out
    s = out["summary"]
    assert s["peak_demand_kw"] == pytest.approx(1.15 * s["peak_demand_raw_kw"], abs=1.0)
    assert s["demand_margin_kw"] == pytest.approx(
        s["contract_demand_kw"] - s["peak_demand_kw"], abs=0.2)
    # 计费需量必须真的守住申报值(与 LP 的可行性口径一致)
    assert s["peak_demand_kw"] <= s["contract_demand_kw"] + 1e-6
    # 拿原始值相减会得到明显更大的"错觉余量" —— 必须避免这种口径混用
    naive = s["contract_demand_kw"] - s["peak_demand_raw_kw"]
    assert naive > s["demand_margin_kw"] * 3, (naive, s["demand_margin_kw"])
    # 基线峰值也同口径
    assert s["baseline_peak_kw"] == pytest.approx(
        1.15 * s["baseline_peak_raw_kw"], abs=1.0)


def test_demand_cap_binding_detected(dispatch_env):
    """cap 真的顶到上限时,active_constraints 必须判 binding。

    若 binding 判定拿**原始小时均值**去比**计费口径**的 cap,会恒判"未生效"。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    base = optimize_dispatch.invoke({"strategies": ["省钱"]})
    free_peak = base["summary"]["peak_demand_kw"]       # 计费口径自然峰值
    cap = round(free_peak - 30.0, 1)                    # 压在自然峰值之下 → 必然 binding
    out = optimize_dispatch.invoke({
        "strategies": ["省钱"],
        "constraints": [{"type": "demand_cap", "value_kw": cap}],
    })
    assert out["status"] == "ok", out
    active = {a["type"]: a["binding"] for a in out["active_constraints"]}
    assert out["summary"]["peak_demand_kw"] == pytest.approx(cap, abs=2.0)
    assert active["demand_cap"] is True, (out["summary"]["peak_demand_kw"], active)


def test_sweep_find_limit_demand_cap_with_reserve(dispatch_env):
    """带 reserve 约束时 find_limit='demand_cap_kw' 必须能定出临界值。

    floor 若用**空约束**算(偏低),二分区间上界会落回物理下限之下 → 返回 value=null;
    故 floor 必须用**同一约束集**,应给出 boundary_hit=True,且该 cap 下确实可行。
    """
    from emsclaw_backend.deepagent.agents.business.domains.dispatch_planning.tools import (
        optimize_dispatch,
    )
    out = optimize_dispatch.invoke({
        "constraints": [{"type": "reserve"}],
        "scenario": {"load_scale": 1.1},
        "sweep": {"find_limit": "demand_cap_kw"},
    })
    lim = out["sweep"]["limit"]
    assert lim["boundary_hit"] is True, lim
    assert isinstance(lim["value"], float), lim
    at = optimize_dispatch.invoke({
        "constraints": [{"type": "reserve"},
                        {"type": "demand_cap", "value_kw": lim["value"]}],
        "scenario": {"load_scale": 1.1},
    })
    assert at["status"] == "ok", at
    assert at["summary"]["peak_demand_kw"] <= lim["value"] + 1.0
