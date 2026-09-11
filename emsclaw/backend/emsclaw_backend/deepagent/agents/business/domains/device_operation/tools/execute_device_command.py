"""execute_device_command - 经 MCP 网关下发设备控制指令。"""
import logging
from typing import Any, Dict

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from emsclaw_backend.deepagent.agents.business._shared import timeout_fallback
from ._shared import _call_mcp_tool

logger = logging.getLogger(__name__)


class ExecuteDeviceCommandSchema(BaseModel):
    """设备执行参数"""
    command_type: str = Field(..., description="指令类型")
    device_id: str = Field(..., description="目标设备ID")
    parameters: Dict[str, Any] = Field(..., description="指令参数")
    operator: str = Field(default="system", description="操作者标识")


@tool(args_schema=ExecuteDeviceCommandSchema)
@timeout_fallback(timeout_seconds=15)
async def execute_device_command(
    command_type: str,
    device_id: str,
    parameters: Dict[str, Any],
    operator: str = "system"
) -> str:
    """
    向设备下发控制指令并执行（通过 MCP 协议网关，用于非储能充放电类设备）。

    本工具面向通用设备指令下发；储能充放电策略由调度规划专家负责，不在本工具范围。
    """
    mcp_args = {
        "entity_name": "device",
        "record_id": device_id,
        "updated_fields": {
            "status": "online" if command_type != "stop" else "offline",
            "metadata": {
                "last_command": command_type,
                "command_params": parameters,
                "executed_by": operator
            }
        }
    }

    logger.info(f"[device_operation] MCP 下发指令 {command_type} -> {device_id}")
    result = await _call_mcp_tool("update_record", mcp_args)

    if isinstance(result, dict) and "error" in result:
        return f"❌ 指令下发失败 (MCP Error): {result['error']}"

    return (
        f"✅ 指令执行成功 (经 MCP 层)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 执行反馈: {result if isinstance(result, str) else '已成功通过 MCP 更新网关状态'}\n"
        f"🔹 设备ID: {device_id}\n"
        f"🔹 指令: {command_type}\n"
        f"🔹 后端节点已同步"
    )
