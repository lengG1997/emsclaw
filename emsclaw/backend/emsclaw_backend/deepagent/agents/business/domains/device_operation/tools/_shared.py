"""device_operation 工具共享辅助。

提供 PcsService 句柄(储能控制)与 MCP 桥接器(通用设备指令)。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from emsclaw_backend.service.pcs_service import PcsService, get_default_service as _get_pcs_svc

logger = logging.getLogger(__name__)


def _pcs() -> PcsService:
    return _get_pcs_svc()


# ========================================================================
# MCP 桥接器 - 通用设备指令下发/查询(非 PCS 类设备走 MCP 网关)
# ========================================================================

async def _call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> Any:
    """通过 MCP (Model Context Protocol) 协议调用外部设备网关。

    本仓库未携带真实 MCP 网关,此处为 stub(保留 schema 形状),
    保证上层工具可工作。生产部署应替换为真实 MCP 网关调用。
    """
    logger.warning(
        "[device_operation] _call_mcp_tool STUB: %s %s - prod 部署应替换为真实 MCP 网关调用",
        tool_name, arguments,
    )
    if tool_name == "update_record":
        return {
            "status": "MOCK",
            "device_id": arguments.get("record_id"),
            "command": arguments.get("updated_fields", {}).get("metadata", {}).get("last_command"),
            "note": "MCP stub - prod 替换为真实网关",
        }
    if tool_name == "get_record_detail":
        return {
            "status": "MOCK",
            "device_id": arguments.get("record_id"),
            "online": True,
            "note": "MCP stub - prod 替换为真实网关",
        }
    return {"error": f"unknown mcp method {tool_name}"}
