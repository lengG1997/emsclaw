"""调度规划专家 Agent - 生成最优充放电策略,用户确认后下发执行。

继承 DomainAgent。暴露策略生成工具(optimize_dispatch,只读)与下发工具(apply_schedule,写,触发 HITL 审批)。
执行监测/收益核算不属本专家职责,工具函数保留供测试与复用但不再注入本 Agent。
运行时由 deepagents SubAgentMiddleware 负责编译执行。
"""
from typing import Any, Dict, List

from ...domain_agent import DomainAgent, domain_skills_route
from ...registry import AgentRegistry
from .tools import optimize_dispatch, apply_schedule, current_time
from .prompts import DISPATCH_PLANNING_SYSTEM_PROMPT


class DispatchPlanningExpert(DomainAgent):
    """调度规划专家:生成最优充放电策略,用户确认后下发执行。"""

    def __init__(self):
        super().__init__(
            name="DispatchPlanningExpert",
            description=(
                "调度规划专家:为单场站生成 24h 最优能源调度策略,用户确认后下发执行。"
                "处理:① 峰谷套利策略--低谷充电高峰放电赚价差;② 需量管理--压低关口表最大需量省基本电费;"
                "③ 绿电消纳--优先消纳光伏减少弃光;④ 防逆流--控制上网功率不超设定;"
                "⑤ 多目标权衡--省钱/保电池/绿电优先/防逆流按需组合(可多选);"
                "⑥ 约束响应--保供/压需量/限循环/防逆流/限电费/保备用转调度约束;"
                "⑦ 策略解释与 what-if 对比;⑧ 用户认可后下发计划生效。"
                "基础数据(负荷/光伏预测、分时电价、储能状态、申报需量)由策略生成工具内部自动聚合并在返回中给出,无需读取工作目录或数据文件。"
                "触发:用户要『生成充放电策略/优化调度/怎么省钱/少循环/不反送/多用绿电/压需量/保供电/策略解释/下发计划』时交本专家。"
                "不处理:执行监测、收益核算、原始数据逐项查询、设备录入配网--超出范围直接返回不支持,由主 agent 重新分配。"
            ),
        )

    def get_tools(self) -> list:
        return [optimize_dispatch, apply_schedule, current_time]

    def get_system_prompt(self) -> str:
        return DISPATCH_PLANNING_SYSTEM_PROMPT

    def get_skills(self) -> List[str]:
        """挂载调度策略 skill（干净虚拟路径，解耦源码树）。"""
        from pathlib import Path
        skills_dir = Path(__file__).parent / "skills"
        # 返回虚拟挂载点 /domain-skills/<pkg>/（非源码绝对路径），避免把
        # /app/emsclaw_backend/.../domains/<d>/skills 暴露给 Agent。factory 同名路由保证 ls/read 命中。
        if not skills_dir.exists():
            return None
        return [domain_skills_route(Path(__file__).parent.name)]

    def get_interrupt_on(self) -> Dict[str, Dict[str, Any]]:
        """下发充放电计划影响实际硬件运行,需 HITL 审批。生成类工具只读不审批。"""
        return {
            "apply_schedule": {
                "allowed_decisions": ["approve", "reject"],
                "description": "下发充放电计划到 PCS 实际调度,影响硬件运行,需要审批",
            }
        }


# 自动注册到 AgentRegistry
AgentRegistry.register(DispatchPlanningExpert())
