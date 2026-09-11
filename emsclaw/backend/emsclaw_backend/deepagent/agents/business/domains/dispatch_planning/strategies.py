"""策略组合 -> 多目标调度优化权重。

按需求命名(不是身份视角),可自由组合。权重作用于目标函数的各惩罚项:
- w_degrade: 充放电吞吐惩罚(抑制循环,保电池寿命)
- w_carbon:  碳排放惩罚(绿电优先,鼓励多用光伏少买电)
- w_ramp:    功率波动惩罚(平滑出力)
- anti_reverse: 防逆流设定(防逆流=0 严禁上网,其余沿用站配置 setpoint)

省钱:  默认组合,电费优先,轻循环惩罚。
保电池:少循环延长寿命,重循环惩罚。
绿电优先:多用光伏少买电,重碳惩罚。
防逆流:严禁反送、平滑出力,中等循环惩罚+波动惩罚。
"""
from __future__ import annotations

STRATEGIES = {
    "省钱": {"w_degrade": 0.05, "w_carbon": 0.0, "w_ramp": 0.0,
             "anti_reverse": None},   # None = 沿用站配置 setpoint
    "保电池": {"w_degrade": 0.30, "w_carbon": 0.0, "w_ramp": 0.0,
               "anti_reverse": None},
    # w_carbon 语义 = 碳价(元/kgCO2)。0.15 ≈ 150 元/吨,贴近国内碳市场价格;
    # 旧值 0.8 等价 800 元/吨隐含碳价,会让绿电优先付出过高的电费代价。
    "绿电优先": {"w_degrade": 0.10, "w_carbon": 0.15, "w_ramp": 0.0,
                 "anti_reverse": None},
    "防逆流": {"w_degrade": 0.10, "w_carbon": 0.0, "w_ramp": 0.5,
               "anti_reverse": 0.0},    # 严禁上网
}

DEFAULT_STRATEGY = "省钱"


def resolve(strategies: list[str]) -> dict:
    """把策略组合列表合并为一组权重;空列表回落「省钱」。

    合并规则:w_* 取各组合的最大值;anti_reverse 任一为 0(严禁上网)则为 0,
    否则沿用站配置(None)。未知组合名忽略。
    """
    valid = [STRATEGIES[s] for s in (strategies or []) if s in STRATEGIES]
    if not valid:
        return dict(STRATEGIES[DEFAULT_STRATEGY])
    merged = {
        "w_degrade": max(v["w_degrade"] for v in valid),
        "w_carbon": max(v["w_carbon"] for v in valid),
        "w_ramp": max(v["w_ramp"] for v in valid),
        # 任一组合要求严禁上网 -> 0;否则全 None -> None(沿用站配置)
        "anti_reverse": 0.0 if any(v["anti_reverse"] == 0.0 for v in valid) else None,
    }
    return merged
