"""list_devices 工具 - 列出设备表中的设备。"""
import json
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from emsclaw_backend.service.device_service import DeviceService
from ..schemas import DeviceDTO


class ListDevicesArgs(BaseModel):
    device_type: Optional[str] = Field(default=None, description="按类型过滤: battery/inverter/meter")


@tool(args_schema=ListDevicesArgs)
def list_devices(device_type: Optional[str] = None) -> str:
    """列出全部设备，或按 device_type 过滤。"""
    try:
        dtos = [DeviceDTO.model_validate(d).model_dump() for d in DeviceService().list(device_type)]
        return json.dumps(
            {"success": True, "message": f"共 {len(dtos)} 台设备", "data": dtos},
            ensure_ascii=False, indent=2,
        )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"查询失败: {e}")


def _err(msg: str) -> str:
    return json.dumps({"success": False, "message": msg, "data": None}, ensure_ascii=False, indent=2)
