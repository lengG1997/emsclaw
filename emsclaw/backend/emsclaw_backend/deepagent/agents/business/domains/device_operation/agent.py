"""设备操作专家 Agent - 所有设备操作统一入口(台账管理 + 运行控制)。

继承 DomainAgent,合并原 device_management + command_execution + energy_storage 的控制工具。
安全靠 HITL 审批兜底(不保留原 command_execution 的安全审查子链)。
运行时由 deepagents SubAgentMiddleware 负责编译和执行。
"""
from typing import Any, Dict, List

from ...domain_agent import DomainAgent, domain_skills_route
from ...registry import AgentRegistry
from .tools import (
    create_device,
    configure_network,
    list_devices,
    get_device,
    reset_station_defaults,
    set_station_config,
    execute_device_command,
    emergency_stop,
)
from .prompts import DEVICE_OPERATION_SYSTEM_PROMPT


class DeviceOperationExpert(DomainAgent):
    """设备操作专家:设备台账管理(录入/配网/查询/重置)+ 运行控制(充放电/指令/急停)。"""

    def __init__(self):
        super().__init__(
            name="DeviceOperationExpert",
            description=(
                "设备操作专家:对所有 EMS 设备执行操作。"
                "处理:① 设备台账管理--录入新设备、配置网络(IP/协议/端口)、查询/列出设备、"
                "调整站配置(申报需量/防逆流上网阈值/容量与需量电价)、重置场站为标准默认配置;"
                "② 运行控制--储能充放电模式与功率设置、通用设备控制指令下发(MCP)、紧急停止所有储能。"
                "触发:用户问『录入设备/配网/设备列表/调整申报需量/调整站配置/重置场站/充放电模式/充电/放电/急停/下发指令』时交本专家。"
                "不处理:场站运行数据查询、策略分析--超出范围直接返回不支持,由主 agent 重新分配。"
            ),
        )

    def get_tools(self) -> List:
        return [
            create_device,
            configure_network,
            list_devices,
            get_device,
            reset_station_defaults,
            set_station_config,
            execute_device_command,
            emergency_stop,
        ]

    def get_system_prompt(self) -> str:
        return DEVICE_OPERATION_SYSTEM_PROMPT

    def get_skills(self) -> List[str]:
        from pathlib import Path
        skills_dir = Path(__file__).parent / "skills"
        # 返回虚拟挂载点 /domain-skills/<pkg>/，避免暴露后端源码树路径；factory 同名路由保证命中。
        if not skills_dir.exists():
            return None
        return [domain_skills_route(Path(__file__).parent.name)]

    def get_interrupt_on(self) -> Dict[str, Dict[str, Any]]:
        """所有写/控制操作需 HITL 审批;list_devices / get_device 只读,不审批。"""
        return {
            "create_device": {
                "allowed_decisions": ["approve", "reject"],
                "description": "录入新设备到设备表,影响设备台账,需要审批",
            },
            "configure_network": {
                "allowed_decisions": ["approve", "reject"],
                "description": "配置设备网络参数(IP/协议/端口),影响设备通信,需要审批",
            },
            "reset_station_defaults": {
                "allowed_decisions": ["approve", "reject"],
                "description": "清空并重建场站标准默认设备配置(2×500kW PCS+2×1000kWh 电池+2MWp 光伏),破坏性操作,必须审批",
            },
            "set_station_config": {
                "allowed_decisions": ["approve", "reject"],
                "description": "更新场站配置(申报需量/防逆流/容量与需量电价),影响调度与计费口径,需要审批",
            },
            "execute_device_command": {
                "allowed_decisions": ["approve", "reject"],
                "description": "经 MCP 下发设备控制指令,可能影响实际硬件,需要审批",
            },
            "emergency_stop": {
                "allowed_decisions": ["approve", "reject"],
                "description": "紧急停止储能设备,高风险熔断操作,需要审批",
            },
        }


# 自动注册到 AgentRegistry
AgentRegistry.register(DeviceOperationExpert())
