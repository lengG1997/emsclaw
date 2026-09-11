"""optimize_dispatch - 用调度优化生成本场站 24h 最优充放电策略。

工具薄壳(从 v2 拆分):schema 校验 → gather_inputs → apply_scenario → solver.solve
→ 返回。所有数学(LP 构建/求解/自检/对偶推断)在 solver.py,IO(数据聚合)在 _shared.py。
本文件只负责 LangChain @tool 装配与 schema 定义。

调度优化(加权多目标,scipy HiGHS 求解器):
- 变量(每小时):Pc/Pd(充/放)、Pim/Pex(购/售电)、Pcurt(弃光)、soc、dmax(需量)、rup/rdn(波动)
- 目标:min Σ[tariff·Pim - sell·Pex + w_degrade·(Pc+Pd) + w_ramp·(rup+rdn)]
        + (demand_price/30)·dmax + w_carbon·carbon_factor·ΣPim
- 约束:功率平衡、SOC 动态(η=√eff)、SOC/功率界、防逆流、需量 epigraph(15min 保守系数)、
  末态 SOC、波动平滑
- 策略组合(省钱/保电池/绿电优先/防逆流)决定权重,可自由组合;支持 8 类自然语言
  约束注入(见 ConstraintSpec)。
- scenario(what-if 缩放)、sanity_check(能量守恒自检)、active_constraints
  (binding 推断)、summary.carbon_cost(绿电优先代价)。
"""
from __future__ import annotations

from datetime import date as _date
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from .. import strategies as strategies_mod
from ..solver import (
    ConstraintSpec,
    ScenarioSpec,
    SweepSpec,
    _SCIPY_AVAILABLE,
    _preview,
    _solve,
    apply_scenario,
    run_sweep,
)
from ._shared import _today, gather_inputs


class OptimizeDispatchSchema(BaseModel):
    strategies: list[Literal["省钱", "保电池", "绿电优先", "防逆流"]] = Field(
        default_factory=list,
        description="策略组合,按需求可多选:省钱(默认,电费优先)/保电池(少循环延寿命)/"
                    "绿电优先(消纳光伏减碳)/防逆流(严禁上网+平滑)。空列表=省钱")
    target_date: str | None = Field(
        default=None, description="目标日期 YYYY-MM-DD,缺省=今天")
    constraints: list[ConstraintSpec] = Field(
        default_factory=list, description="额外约束(用户自然语言要求翻译而成)")
    plan_label: str | None = Field(
        default=None,
        description="**多方案对比时必填**:本次求解的**方案名**(如「省钱优先」「保电池少循环」"
                    "「省钱+不超申报」),2~8 字、能唯一区分本组方案。前端对比卡按它显示、"
                    "用户点选时原样回传,因此**正文里的叫法必须与它完全一致**;"
                    "多个方案是并行求解的,卡片按到达顺序排,不填 label 会因顺序错位而歧义。")
    preview: bool = Field(
        default=False,
        description="只取现状/基线/可行域,不求带约束的解。设 True 时忽略 constraints,"
                    "返回 station_context(站级现状)/baseline_no_storage(无储能基线)/"
                    "default(无约束默认效果)/envelope.demand_kw(需量可行域)/"
                    "envelope.throughput_kwh(日吞吐可行域)。"
                    "用于把数值类约束锚定到真实可行区间,避免先猜数求解再试错。")
    scenario: ScenarioSpec | None = Field(
        default=None,
        description="what-if 场景假设(可选):负荷缩放/光伏缩放/电价平移。"
                    "「假设负荷+20%」→ {load_scale:1.2};「阴天」→ {pv_scale:0.3}。"
                    "preview 与正式求解均生效。")
    sweep: SweepSpec | None = Field(
        default=None,
        description="敏感性/边界扫描,一次调用拿整条曲线(禁止逐值循环试探)。\n"
                    "points=[{'load_scale':1.1}, ...] 显式采样(最多 32 个);"
                    "find_limit='load_scale' 由内部二分定临界值,可选 'pv_scale' / "
                    "'demand_cap_kw';limit_range=[lo,hi] 可指定二分区间。\n"
                    "约束默认继承顶层 constraints,可用 sweep.constraints 覆盖;"
                    "与 preview 同时给出时以本参数为准。\n"
                    "**返回键是 `scan_status` 而非 `status`** —— 它只表示「扫描执行完成」,"
                    "**不代表约束可解**:整体看 `sweep.any_feasible`,单点看 `points[i].feasible`。")


@tool(args_schema=OptimizeDispatchSchema)
@timeout_fallback(timeout_seconds=30)
def optimize_dispatch(
    strategies: list[str] | None = None,
    target_date: str | None = None,
    constraints: list[dict] | None = None,
    plan_label: str | None = None,
    preview: bool = False,
    scenario: ScenarioSpec | None = None,
    sweep: SweepSpec | None = None,
) -> dict:
    """生成本场站 24h 最优充放电策略(调度优化)。返回结构化数字 JSON,不含人读叙述。

    全部基础数据(负荷/光伏预测、24h 分时电价、储能聚合参数、站配置含申报需量)由工具内部
    自动聚合——**无需也不应**另行读取工作目录或查询数据文件,调用即拿到完整现状。

    **调用前先读 `dispatch-strategy` skill**:需求解析、约束翻译规则、保供档位取舍、
    infeasible 的处理方式、preview 与 sweep 的选用时机都在那里写全了。本段只讲调用契约。

    参数分工:
    - `strategies` 软偏好,可多选叠加;`constraints` 硬约束,字段语义见 ConstraintSpec。
    - `preview=True` 只取现状·基线·可行域,不求带约束的解(此时忽略 `constraints`)。
    - `sweep` 敏感性·边界扫描,一次拿整条曲线;与 `preview` 同时给出时以 `sweep` 为准,
      顶层 `scenario` 作为扫描基准先生效。
    - `scenario` what-if 缩放,`preview` 与正式求解均生效。
    - `plan_label` 多方案对比时必填,把本次求解与你在回复里的方案名绑定(与到达顺序无关)。

    **需量口径(必须遵守)**:本工具所有"需量"字段 —— `demand_cap.value_kw` /
    `contract_demand_kw` / `peak_demand_kw` / `demand_margin_kw` / `envelope.demand_kw` /
    `min_feasible_demand_cap_kw` —— 统一为**计费口径 kW**(国内 15 分钟滑窗最大需量的保守
    折算,LP 以小时为分辨率故乘 1.15)。叙述余量直接用 `summary.demand_margin_kw`;
    `*_raw_kw` 是原始小时均值,仅供追溯,**不得**用于相减(会高估约 9 倍)。

    正常返回(status="ok"):
    - `status` / `strategies` / `plan_label` / `target_date` / `weights_used`
    - `schedule[24]`:mode / power_kw / power_ratio / soc_target_pct / period / tariff_price
    - `summary`:grid_cost、demand_charge、peak_demand_kw(计费需量)、
      peak_demand_raw_kw(原始小时均值,仅追溯)、demand_margin_kw(申报值−计费需量)、
      contract_demand_kw、baseline_peak_kw、baseline_peak_raw_kw、
      est_savings_yuan、carbon_kg、carbon_cost
    - `storage` / `config`(contract_demand_kw、demand_price_yuan_per_kw_month、
      anti_reverse_setpoint_kw)
    - `sanity_check`:energy_conserved + warnings(warnings 非空必须如实转告用户)
    - `active_constraints`:各约束在解里是否 binding
    - `forecast_source` / `forecast_confidence` / `demand_charge_basis` / `scenario_applied`

    不可行时返回 `status="infeasible"`,附可复算的冲突证据 —— 这些字段是**上报用户决策**
    的依据,**不是**自行改参重试的依据:
    - `diagnosis`:`demand_cap_below_feasible`(需量上限低于物理可行下限)/
      `other_constraints_infeasible`(放开需量上限仍不可行,冲突来自其它约束)
    - `min_feasible_demand_cap_kw`:其余约束不变时电池可削到的物理最小关口峰值(kW)
    - `requested_demand_cap_kw`:本次请求的需量上限(kW)
    - `reserve_floor`:`{level, source, hours, critical_load_kw, reserve_soc_floor_kwh,
      reserve_soc_floor_pct}` —— 让"保供有多贵"可见
    - `recommendation`:人读建议(含应上调到的最小值)

    计划下发执行请调用 `apply_schedule`。
    """
    if not _SCIPY_AVAILABLE:
        return {"status": "solver_unavailable",
                "reason": "后端未安装 scipy 求解器,无法运行调度优化。请联系管理员安装 scipy。"}
    try:
        td = _today()
        if target_date:
            td = _date.fromisoformat(target_date)
        inputs = gather_inputs(td)
        inputs = apply_scenario(inputs, scenario)
        used = list(strategies or [])
        weights = strategies_mod.resolve(used)
        if sweep is not None:
            # 敏感性/边界扫描一次算完,不让 LLM 逐值循环试探
            cons0 = [c.model_dump() if isinstance(c, BaseModel) else c
                     for c in (constraints or [])]
            return run_sweep(inputs, weights, used, sweep, cons0)
        if preview:
            return _preview(inputs, weights, used)
        # schema 会把每项约束校验成 ConstraintSpec,这里统一转 dict 供 _solve 使用
        cons = []
        for c in (constraints or []):
            cons.append(c.model_dump() if isinstance(c, BaseModel) else c)
        result = _solve(inputs, weights, cons)
        if isinstance(result, dict):  # 不可行/无储能
            result["strategies"] = used
            result["target_date"] = td.isoformat()
            # 多方案卡片靠 plan_label 绑定,不可行方案同样要标名(它也是选项之一)
            if plan_label:
                result["plan_label"] = plan_label
            if scenario is not None:
                result["scenario_applied"] = inputs.get("scenario_applied")
            return result
        schedule, summary, sanity, active = result
        return {
            "status": "ok",
            "strategies": used or ["省钱"],
            "plan_label": plan_label,
            "target_date": td.isoformat(),
            "schedule": schedule,
            "summary": summary,
            "weights_used": weights,
            "storage": {
                "total_rated_kw": round(inputs["storage"]["total_rated_kw"], 1),
                "total_cap_kwh": round(inputs["storage"]["total_cap_kwh"], 1),
                "initial_soc": round(inputs["storage"]["initial_soc"], 4),
                "min_soc": round(inputs["storage"]["min_soc"], 4),
                "max_soc": round(inputs["storage"]["max_soc"], 4),
                "eff": round(inputs["storage"]["eff"], 4),
                "n_pcs": inputs["storage"]["n_pcs"],
            },
            "config": {
                "contract_demand_kw": round(inputs["config"]["contract_demand_kw"], 1),
                "demand_price_yuan_per_kw_month": round(inputs["config"]["demand_price_yuan_per_kw_month"], 1),
                "anti_reverse_setpoint_kw": round(inputs["config"]["anti_reverse_setpoint_kw"], 1),
            },
            "sanity_check": sanity,
            "active_constraints": active,
            # v2:数据来源标注(让 agent 感知"预测其实是猜的") + 需量计费口径
            "forecast_source": inputs.get("forecast_source"),
            "forecast_confidence": inputs.get("forecast_confidence"),
            "demand_charge_basis": inputs.get("demand_charge_basis"),
            "scenario_applied": inputs.get("scenario_applied"),
        }
    except Exception as e:  # pragma: no cover
        return {"status": "error", "reason": f"优化调度失败:{e}"}
