"""StationMapper - 场站级(光伏/关口表/天气/电价/日电量/站配置)ORM 持久化(同步)。

只负责 SQL/ORM 操作,无业务规则。每次开短 session;session_factory 可注入便于测试。
与 PcsMapper 同构。
"""
from __future__ import annotations
import time
from typing import Optional

from sqlalchemy import and_

from emsclaw_backend.db.models import (
    DailyEnergyRecord, ElectricityTariff, MeterDevice, MeterSnapshot,
    PvDevice, PvSnapshot, StationConfig, WeatherSnapshot,
)
from emsclaw_backend.db.session import SyncSessionLocal


class StationMapper:
    def __init__(self, session_factory=None):
        self._sf = session_factory or SyncSessionLocal

    # ── 设备配置 ───────────────────────────────────────────────
    def first_pv_device(self) -> Optional[PvDevice]:
        with self._sf() as s:
            return s.query(PvDevice).first()

    def first_meter_device(self) -> Optional[MeterDevice]:
        with self._sf() as s:
            return s.query(MeterDevice).first()

    def insert_pv_device(self, pv: PvDevice) -> PvDevice:
        with self._sf() as s:
            s.add(pv)
            s.commit()
            s.refresh(pv)
            return pv

    def insert_meter_device(self, m: MeterDevice) -> MeterDevice:
        with self._sf() as s:
            s.add(m)
            s.commit()
            s.refresh(m)
            return m

    # ── 站配置 ─────────────────────────────────────────────────
    def get_station_config(self) -> Optional[StationConfig]:
        with self._sf() as s:
            return s.query(StationConfig).first()

    def insert_station_config(self, cfg: StationConfig) -> StationConfig:
        with self._sf() as s:
            s.add(cfg)
            s.commit()
            s.refresh(cfg)
            return cfg

    def upsert_station_config(self, cfg: StationConfig) -> StationConfig:
        """单行站配置 upsert:已存在则按非 None 字段更新,否则插入新行。返回最新配置。"""
        with self._sf() as s:
            existing = s.query(StationConfig).first()
            if existing is None:
                s.add(cfg)
                s.commit()
                s.refresh(cfg)
                return cfg
            for f in ("region", "contract_demand_kw", "anti_reverse_export_setpoint_kw",
                      "capacity_price_yuan_per_kw_month", "demand_price_yuan_per_kw_month"):
                v = getattr(cfg, f, None)
                if v is not None:
                    setattr(existing, f, v)
            existing.updated_at = int(time.time())
            s.commit()
            s.refresh(existing)
            return existing

    # ── 电价 ───────────────────────────────────────────────────
    def list_tariffs(self, region: str = "default") -> list[ElectricityTariff]:
        with self._sf() as s:
            return (
                s.query(ElectricityTariff)
                .filter_by(region=region)
                .order_by(ElectricityTariff.start_hour.asc())
                .all()
            )

    def get_tariff_for_hour(self, region: str, hour: int) -> Optional[ElectricityTariff]:
        with self._sf() as s:
            return (
                s.query(ElectricityTariff)
                .filter(
                    and_(
                        ElectricityTariff.region == region,
                        ElectricityTariff.start_hour <= hour,
                        ElectricityTariff.end_hour > hour,
                    )
                )
                .first()
            )

    def count_tariffs(self, region: str = "default") -> int:
        with self._sf() as s:
            return s.query(ElectricityTariff).filter_by(region=region).count()

    def insert_tariff(self, t: ElectricityTariff) -> ElectricityTariff:
        with self._sf() as s:
            s.add(t)
            s.commit()
            s.refresh(t)
            return t

    # ── 快照:写入 ─────────────────────────────────────────────
    def insert_pv_snapshot(self, snap: PvSnapshot) -> PvSnapshot:
        with self._sf() as s:
            s.add(snap)
            s.commit()
            s.refresh(snap)
            return snap

    def insert_meter_snapshot(self, snap: MeterSnapshot) -> MeterSnapshot:
        with self._sf() as s:
            s.add(snap)
            s.commit()
            s.refresh(snap)
            return snap

    def insert_weather_snapshot(self, snap: WeatherSnapshot) -> WeatherSnapshot:
        with self._sf() as s:
            s.add(snap)
            s.commit()
            s.refresh(snap)
            return snap

    # ── 快照:最新 ─────────────────────────────────────────────
    def latest_pv_snapshot(self, pv_id: str) -> Optional[PvSnapshot]:
        with self._sf() as s:
            return (
                s.query(PvSnapshot)
                .filter_by(pv_id=pv_id)
                .order_by(PvSnapshot.timestamp.desc())
                .first()
            )

    def latest_meter_snapshot(self, meter_id: str) -> Optional[MeterSnapshot]:
        with self._sf() as s:
            return (
                s.query(MeterSnapshot)
                .filter_by(meter_id=meter_id)
                .order_by(MeterSnapshot.timestamp.desc())
                .first()
            )

    def latest_weather_snapshot(self) -> Optional[WeatherSnapshot]:
        with self._sf() as s:
            return (
                s.query(WeatherSnapshot)
                .order_by(WeatherSnapshot.timestamp.desc())
                .first()
            )

    # ── 快照:范围 ─────────────────────────────────────────────
    def pv_snapshots_range(self, pv_id: str, start_ts: int, end_ts: int) -> list[PvSnapshot]:
        with self._sf() as s:
            return (
                s.query(PvSnapshot)
                .filter(and_(
                    PvSnapshot.pv_id == pv_id,
                    PvSnapshot.timestamp >= start_ts,
                    PvSnapshot.timestamp <= end_ts,
                ))
                .order_by(PvSnapshot.timestamp.asc())
                .all()
            )

    def meter_snapshots_range(self, meter_id: str, start_ts: int, end_ts: int) -> list[MeterSnapshot]:
        with self._sf() as s:
            return (
                s.query(MeterSnapshot)
                .filter(and_(
                    MeterSnapshot.meter_id == meter_id,
                    MeterSnapshot.timestamp >= start_ts,
                    MeterSnapshot.timestamp <= end_ts,
                ))
                .order_by(MeterSnapshot.timestamp.asc())
                .all()
            )

    def weather_snapshots_range(self, start_ts: int, end_ts: int) -> list[WeatherSnapshot]:
        with self._sf() as s:
            return (
                s.query(WeatherSnapshot)
                .filter(and_(
                    WeatherSnapshot.timestamp >= start_ts,
                    WeatherSnapshot.timestamp <= end_ts,
                ))
                .order_by(WeatherSnapshot.timestamp.asc())
                .all()
            )

    def meter_demand_max_since(self, meter_id: str, since_ts: int) -> float:
        """今日最大滚动需量(rolling_demand_kw 最大值)。"""
        with self._sf() as s:
            row = (
                s.query(MeterSnapshot)
                .filter(and_(
                    MeterSnapshot.meter_id == meter_id,
                    MeterSnapshot.timestamp >= since_ts,
                ))
                .order_by(MeterSnapshot.rolling_demand_kw.desc())
                .first()
            )
            return row.rolling_demand_kw if row else 0.0

    # ── 日电量 ─────────────────────────────────────────────────
    def get_daily_energy(self, date_str: str) -> Optional[DailyEnergyRecord]:
        with self._sf() as s:
            return s.query(DailyEnergyRecord).filter_by(date=date_str).first()

    def upsert_daily_energy(self, rec: DailyEnergyRecord) -> DailyEnergyRecord:
        """按 date upsert(存在则累加字段更新,不存在则插入)。"""
        with self._sf() as s:
            existing = s.query(DailyEnergyRecord).filter_by(date=rec.date).first()
            if existing is None:
                s.add(rec)
                s.commit()
                s.refresh(rec)
                return rec
            existing.charge_kwh = rec.charge_kwh
            existing.discharge_kwh = rec.discharge_kwh
            existing.revenue = rec.revenue
            existing.updated_at = rec.updated_at
            s.commit()
            s.refresh(existing)
            return existing

    def list_daily_energy(self, days: int = 7) -> list[DailyEnergyRecord]:
        with self._sf() as s:
            return (
                s.query(DailyEnergyRecord)
                .order_by(DailyEnergyRecord.date.desc())
                .limit(days)
                .all()
            )
