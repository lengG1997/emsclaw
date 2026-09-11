"""create_device 工具 - 录入新设备，真实落库。"""
import json

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from emsclaw_backend.service.device_service import DeviceService
from ..schemas import DeviceDTO


class CreateDeviceArgs(BaseModel):
    name: str = Field(..., description="设备可读名称，需唯一")
    device_type: str = Field(..., description="设备类别: battery/inverter/meter")


@tool(args_schema=CreateDeviceArgs)
def create_device(name: str, device_type: str) -> str:
    """创建（录入）一个新的能源管理设备，写入设备表。返回生成的设备 ID。"""
    try:
        dto = DeviceDTO.model_validate(DeviceService().create(name, device_type))
        return json.dumps(
            {"success": True, "message": f"设备 '{name}' 创建成功", "data": dto.model_dump()},
            ensure_ascii=False, indent=2,
        )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"创建失败: {e}")


def _err(msg: str) -> str:
    return json.dumps({"success": False, "message": msg, "data": None}, ensure_ascii=False, indent=2)
