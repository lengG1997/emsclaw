"""场站数据专家 Agent - 唯一场站运行数据读取入口(纯读)。

继承 DomainAgent,声明所有 get_* 读工具。运行时由 deepagents SubAgentMiddleware
负责编译和执行。只读:可做现状诊断与风险识别报告(见 station-analysis 技能),不做策略制定、不下发控制指令。
"""
from typing import List

from ...domain_agent import DomainAgent, domain_skills_route
from ...registry import AgentRegistry
from .tools import (
    get_station_overview,
    get_storage_status,
    get_pv_status,
    get_meter_status,
    get_demand_status,
    get_tariff,
    get_daily_energy,
    get_charge_schedule,
    get_storage_history,
    get_meter_history,
    get_daily_energy_history,
    get_forecast,
)
from .prompts import STATION_DATA_SYSTEM_PROMPT


class StationDataExpert(DomainAgent):
    """场站数据专家:查询并返回场站运行数据(实时/历史/预测)。纯读。"""

    def __init__(self):
        super().__init__(
            name="StationDataExpert",
            description=(
                "场站运行数据读取专家:查询本场站实时/历史/预测数据。"
                "处理:储能(PCS/电池 SOC/SOH)、光伏、关口表、需量、电价时段表、"
                "今日电量收益、充放电计划、场站全量总览、历史趋势、负荷·光伏预测。"
                "触发:用户问『场站怎么样/查 SOC/查电价/查关口表/历史趋势/预测/充放电计划』时交本专家。"
                "纯读查询:可做现状诊断与风险识别报告,不做策略制定、不下发控制。"
                "不处理:策略制定与下发、设备控制指令、设备录入配网"
                "--超出范围直接返回不支持,由主 agent 重新分配。"
            ),
        )

    def get_tools(self) -> list:
        """返回场站数据读取专属工具集(纯读)。"""
        return [
            get_station_overview,
            get_storage_status,
            get_pv_status,
            get_meter_status,
            get_demand_status,
            get_tariff,
            get_daily_energy,
            get_charge_schedule,
            get_storage_history,
            get_meter_history,
            get_daily_energy_history,
            get_forecast,
        ]

    def get_system_prompt(self) -> str:
        return STATION_DATA_SYSTEM_PROMPT

    def get_skills(self) -> List[str]:
        """挂载场站分析 skill（干净虚拟路径，解耦源码树）。"""
        from pathlib import Path
        skills_dir = Path(__file__).parent / "skills"
        # 返回虚拟挂载点 /domain-skills/<pkg>/，避免暴露后端源码树路径；factory 同名路由保证命中。
        if not skills_dir.exists():
            return None
        return [domain_skills_route(Path(__file__).parent.name)]


# 自动注册到 AgentRegistry
AgentRegistry.register(StationDataExpert())
