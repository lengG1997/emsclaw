"""Station Entity - 场站级数据契约(光伏 / 关口表 / 天气 / 电价 / 日电量 / 站配置)。

跨域共享,前后端共用枚举(PeriodType / PvStatus)。ORM ↔ DTO 转换在 service/controller 边界。
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PeriodType(str, Enum):
    SHARP = "sharp"    # 尖
    PEAK = "peak"      # 峰
    FLAT = "flat"      # 平
    VALLEY = "valley"  # 谷


class PvStatus(str, Enum):
    RUNNING = "running"
    STANDBY = "standby"
    FAULT = "fault"


# ── 光伏 ──


class PvDeviceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    device_id: str
    rated_capacity_kwp: float
    orientation_deg: float = 180.0
    tilt_deg: float = 30.0
    created_at: int = 0
    updated_at: int = 0


class PvSnapshotDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    pv_id: str
    timestamp: int
    generation_kw: float
    irradiance: float
    temperature: float
    status: str


# ── 关口表 ──


class MeterDeviceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    device_id: str
    rated_kw: float
    created_at: int = 0
    updated_at: int = 0


class MeterSnapshotDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    meter_id: str
    timestamp: int
    import_kw: float
    export_kw: float
    load_kw: float
    reverse_flow: bool
    rolling_demand_kw: float
    frequency: float
    power_factor: float
    total_active_power_kw: float = 0.0  # 关口表一级有功(带符号,正=下网/负=上网)


# ── 天气 ──


class WeatherSnapshotDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    timestamp: int
    irradiance: float
    temperature: float
    cloud_cover: float
    wind_speed: float


# ── 电价 ──


class ElectricityTariffDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    region: str
    period_type: str
    start_hour: int
    end_hour: int
    energy_price: float
    created_at: int = 0
    updated_at: int = 0


# ── 日电量 ──


class DailyEnergyDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    date: str
    charge_kwh: float
    discharge_kwh: float
    revenue: float
    updated_at: int = 0


# ── 站配置 ──


class StationConfigDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    region: str
    contract_demand_kw: float
    anti_reverse_export_setpoint_kw: float
    capacity_price_yuan_per_kw_month: float
    demand_price_yuan_per_kw_month: float
    updated_at: int = 0


class StationConfigUpdateDTO(BaseModel):
    """站配置更新入参:全可选项,至少传一项;值 ≥ 0。未传字段保持不变。"""
    contract_demand_kw: Optional[float] = Field(
        default=None, ge=0, description="申报需量(kW),基本电费(需量)计费基准,超了按 2 倍计收")
    anti_reverse_export_setpoint_kw: Optional[float] = Field(
        default=None, ge=0, description="防逆流上网功率阈值(kW),上网超了判违规")
    capacity_price_yuan_per_kw_month: Optional[float] = Field(
        default=None, ge=0, description="基本电费(容量),元/kW·月")
    demand_price_yuan_per_kw_month: Optional[float] = Field(
        default=None, ge=0, description="基本电费(需量),元/kW·月")


# ── 聚合(供总览页一次拿全) ──


class StationOverviewDTO(BaseModel):
    """场站总览聚合:光伏 / 关口表 / 天气 / 今日电量 / 当前电价时段。"""
    pv: Optional[PvSnapshotDTO] = None
    pv_rated_kwp: float = 0.0
    meter: Optional[MeterSnapshotDTO] = None
    weather: Optional[WeatherSnapshotDTO] = None
    energy_today: Optional[DailyEnergyDTO] = None
    tariff_current: Optional[dict] = None  # {period_type, energy_price, start, end}
    station_config: Optional[StationConfigDTO] = None
