"""PCS / Battery Entity — 跨域数据契约(全局 DTO,前后端共享枚举)。"""
from __future__ import annotations
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PcsMode(str, Enum):
    CHARGE = "charge"
    DISCHARGE = "discharge"
    STANDBY = "standby"
    AUTO = "auto"


class PcsStatus(str, Enum):
    RUNNING = "running"
    STANDBY = "standby"
    FAULT = "fault"


class PcsDeviceDTO(BaseModel):
    """PCS 配置(对应 ORM PcsDevice)。"""
    model_config = ConfigDict(from_attributes=True)
    id: str
    device_id: str
    rated_power_kw: float
    rated_reactive_kvar: float
    ac_voltage_v: float
    dc_voltage_v: float
    rated_efficiency: float
    min_soc: float
    max_soc: float
    override_mode: Optional[str] = None
    override_power_kw: Optional[float] = None
    override_expires_at: int = 0
    battery_id: Optional[str] = None
    created_at: int = 0
    updated_at: int = 0


class BatteryDeviceDTO(BaseModel):
    """电池配置(对应 ORM BatteryDevice)。"""
    model_config = ConfigDict(from_attributes=True)
    id: str
    device_id: str
    rated_capacity_kwh: float
    rated_voltage_v: float
    rated_current_a: float
    soc: float
    soh: float
    cycle_count: int
    created_at: int = 0
    updated_at: int = 0


class PcsSnapshotDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    pcs_id: str
    timestamp: int
    active_power_kw: float
    reactive_power_kvar: float
    mode: str
    ac_voltage_v: float
    dc_voltage_v: float
    efficiency: float
    status: str


class BatterySnapshotDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    battery_id: str
    timestamp: int
    soc: float
    voltage: float
    current_a: float
    temperature: float
    mode: str
    cycle_count: int
