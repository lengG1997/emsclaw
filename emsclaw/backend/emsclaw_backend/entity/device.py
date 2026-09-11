"""Device Entity — 设备数据契约(全局 DTO,跨域共享)。

ORM 行 ↔ DeviceDTO 的转换在 service / controller / tool 边界完成。
枚举作为权威来源,前端 TS 类型和后端字段共用。
"""
from __future__ import annotations
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class DeviceType(str, Enum):
    BATTERY = "battery"
    INVERTER = "inverter"
    METER = "meter"
    PCS = "pcs"


class DeviceStatus(str, Enum):
    OFFLINE = "offline"
    PENDING_ONLINE = "pending_online"
    ONLINE = "online"


class NetworkConfig(BaseModel):
    ip_address: str
    protocol: str  # ModbusTCP / MQTT
    port: Optional[int] = None
    configured_at: int


class DeviceDTO(BaseModel):
    """设备数据传输对象 — ORM Device ↔ API/工具/DTO 通用契约。"""
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    device_type: str
    status: str
    network_config: dict
    created_at: int
    updated_at: int