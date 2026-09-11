"""DeviceController — 设备管理 HTTP 入口。

端点:
- GET    /devices                       列表(可选 ?device_type=)
- GET    /devices/{device_id}           详情
- POST   /devices                       创建设备
- POST   /devices/{device_id}/network   配网

调用 DeviceService 完成业务逻辑;DTO 转换在 controller 边界完成。
"""
from __future__ import annotations
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field

from emsclaw_backend.deepagent.agents.business.domains.device_operation.schemas import DeviceDTO
from emsclaw_backend.service.device_service import DeviceService
from emsclaw_backend.user.dependencies import require_user, User

router = APIRouter(prefix="/devices", tags=["devices"])


class ApiResponse(BaseModel):
    code: int = Field(default=0)
    msg: str = Field(default="ok")
    data: Any = Field(default=None)


class CreateDeviceBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="设备可读名称,需唯一")
    device_type: str = Field(..., description="设备类别: battery/inverter/meter")


class ConfigureNetworkBody(BaseModel):
    ip_address: str = Field(..., description="设备静态 IP 地址")
    protocol: str = Field(..., description="通信协议: ModbusTCP / MQTT")
    port: Optional[int] = Field(default=None, description="端口号")


def _ok(data: Any, msg: str = "ok") -> ApiResponse:
    return ApiResponse(code=0, msg=msg, data=data)


@router.get("", response_model=ApiResponse, summary="列出设备")
async def list_devices(
    device_type: Optional[str] = Query(default=None, description="按类型过滤"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    """列出设备表中的全部设备,可选按 device_type 过滤。"""
    try:
        devices = DeviceService().list(device_type=device_type)
        return _ok([DeviceDTO.model_validate(d).model_dump() for d in devices],
                   msg=f"共 {len(devices)} 台设备")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{device_id}", response_model=ApiResponse, summary="设备详情")
async def get_device(
    device_id: str,
    _user: User = Depends(require_user),
) -> ApiResponse:
    """按 device_id 查询单个设备详情。"""
    d = DeviceService().get(device_id=device_id)
    if d is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="设备不存在")
    return _ok(DeviceDTO.model_validate(d).model_dump())


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED, summary="创建设备")
async def create_device(
    body: CreateDeviceBody,
    _user: User = Depends(require_user),
) -> ApiResponse:
    """录入一个新设备到设备表。业务校验失败返回 4xx。"""
    try:
        d = DeviceService().create(name=body.name, device_type=body.device_type)
        return _ok(DeviceDTO.model_validate(d).model_dump(),
                   msg=f"设备 '{body.name}' 创建成功")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{device_id}/network", response_model=ApiResponse, summary="设备配网")
async def configure_network(
    device_id: str,
    body: ConfigureNetworkBody,
    _user: User = Depends(require_user),
) -> ApiResponse:
    """为已录入设备配置 IP/协议/端口,状态转为 pending_online。"""
    try:
        d = DeviceService().configure_network(
            device_id=device_id,
            ip_address=body.ip_address,
            protocol=body.protocol,
            port=body.port,
        )
        return _ok(DeviceDTO.model_validate(d).model_dump(),
                   msg=f"设备 '{device_id}' 配网成功")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))