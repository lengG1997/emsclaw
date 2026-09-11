"""configure_network 工具 - 为已录入设备配置网络参数。"""
import json
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from emsclaw_backend.service.device_service import DeviceService
from ..schemas import DeviceDTO


class ConfigureNetworkArgs(BaseModel):
    device_id: str = Field(..., description="目标设备 ID")
    ip_address: str = Field(..., description="设备静态 IP 地址")
    protocol: str = Field(..., description="通信协议: ModbusTCP / MQTT")
    port: Optional[int] = Field(default=None, description="端口号")


@tool(args_schema=ConfigureNetworkArgs)
def configure_network(device_id: str, ip_address: str, protocol: str,
                      port: Optional[int] = None) -> str:
    """为指定设备配置 IP/协议/端口，写入 network_config，状态转为 pending_online。"""
    try:
        dto = DeviceDTO.model_validate(
            DeviceService().configure_network(device_id, ip_address, protocol, port))
        return json.dumps(
            {"success": True, "message": f"设备 '{device_id}' 配网成功", "data": dto.model_dump()},
            ensure_ascii=False, indent=2,
        )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"配网失败: {e}")


def _err(msg: str) -> str:
    return json.dumps({"success": False, "message": msg, "data": None}, ensure_ascii=False, indent=2)
