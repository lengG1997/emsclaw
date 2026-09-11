"""get_device 工具 - 按 id 或名称查询单个设备详情。"""
import json
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field, model_validator

from emsclaw_backend.service.device_service import DeviceService
from ..schemas import DeviceDTO


class GetDeviceArgs(BaseModel):
    device_id: Optional[str] = Field(default=None, description="设备 ID")
    name: Optional[str] = Field(default=None, description="设备名称")

    @model_validator(mode="after")
    def _require_one(self):
        if not self.device_id and not self.name:
            raise ValueError("必须提供 device_id 或 name 之一")
        return self


@tool(args_schema=GetDeviceArgs)
def get_device(device_id: Optional[str] = None, name: Optional[str] = None) -> str:
    """按 device_id 或 name 查询单个设备详情（含网络配置）。"""
    try:
        d = DeviceService().get(device_id=device_id, name=name)
        if d is None:
            return _err("未找到对应设备")
        return json.dumps(
            {"success": True, "message": "查询成功", "data": DeviceDTO.model_validate(d).model_dump()},
            ensure_ascii=False, indent=2,
        )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"查询失败: {e}")


def _err(msg: str) -> str:
    return json.dumps({"success": False, "message": msg, "data": None}, ensure_ascii=False, indent=2)
