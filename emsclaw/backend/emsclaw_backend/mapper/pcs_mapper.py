"""PcsMapper — PCS/电池配置表 + 快照表 ORM 持久化(同步)。

只负责 SQL/ORM 操作,无业务规则。每次开短 session;session_factory 可注入便于测试。
"""
from __future__ import annotations
from typing import Optional

from sqlalchemy import and_

from emsclaw_backend.db.models import (
    BatteryDevice, BatterySnapshot, Device, PcsDevice, PcsSnapshot,
)
from emsclaw_backend.db.session import SyncSessionLocal


class PcsMapper:
    def __init__(self, session_factory=None):
        self._sf = session_factory or SyncSessionLocal

    # ── 配置表:写入 ───────────────────────────────────────────
    def insert_pcs(self, pcs: PcsDevice) -> PcsDevice:
        with self._sf() as s:
            s.add(pcs)
            s.commit()
            s.refresh(pcs)
            return pcs

    def insert_battery(self, bat: BatteryDevice) -> BatteryDevice:
        with self._sf() as s:
            s.add(bat)
            s.commit()
            s.refresh(bat)
            return bat

    # ── 配置表:查询 ───────────────────────────────────────────
    def find_pcs_by_id(self, pcs_id: str) -> Optional[PcsDevice]:
        with self._sf() as s:
            return s.get(PcsDevice, pcs_id)

    def find_pcs_by_device_id(self, device_id: str) -> Optional[PcsDevice]:
        with self._sf() as s:
            return s.query(PcsDevice).filter_by(device_id=device_id).first()

    def find_battery_by_id(self, battery_id: str) -> Optional[BatteryDevice]:
        with self._sf() as s:
            return s.get(BatteryDevice, battery_id)

    def find_battery_by_device_id(self, device_id: str) -> Optional[BatteryDevice]:
        with self._sf() as s:
            return s.query(BatteryDevice).filter_by(device_id=device_id).first()

    def find_online_pcs_with_battery(self) -> list[tuple[PcsDevice, BatteryDevice]]:
        """返回所有 online PCS 及其关联电池(无电池则跳过该 PCS)。

        通过 Device 表 status='online' AND device_type='pcs' 筛选,
        再按 pcs_devices.battery_id join battery_devices。
        """
        with self._sf() as s:
            online_pcs_ids = (
                s.query(PcsDevice.id)
                .join(Device, PcsDevice.device_id == Device.id)
                .filter(Device.status == "online", Device.device_type == "pcs")
                .all()
            )
            out: list[tuple[PcsDevice, BatteryDevice]] = []
            for (pcs_id,) in online_pcs_ids:
                pcs = s.get(PcsDevice, pcs_id)
                if pcs is None or not pcs.battery_id:
                    continue
                bat = (
                    s.query(BatteryDevice)
                    .filter_by(device_id=pcs.battery_id)
                    .first()
                )
                if bat is not None:
                    out.append((pcs, bat))
            return out

    # ── 配置表:更新 ───────────────────────────────────────────
    def update_battery_soc(self, device_id: str, soc: float,
                           cycle_count: int, updated_at: int) -> Optional[BatteryDevice]:
        with self._sf() as s:
            b = s.query(BatteryDevice).filter_by(device_id=device_id).first()
            if b is None:
                return None
            b.soc = soc
            b.cycle_count = cycle_count
            b.updated_at = updated_at
            s.commit()
            s.refresh(b)
            return b

    def update_pcs_override(self, pcs_id: str, override_mode: Optional[str],
                            override_power_kw: Optional[float],
                            override_expires_at: int, updated_at: int) -> Optional[PcsDevice]:
        with self._sf() as s:
            p = s.get(PcsDevice, pcs_id)
            if p is None:
                return None
            p.override_mode = override_mode
            p.override_power_kw = override_power_kw
            p.override_expires_at = override_expires_at
            p.updated_at = updated_at
            s.commit()
            s.refresh(p)
            return p

    # ── 快照表 ────────────────────────────────────────────────
    def insert_pcs_snapshot(self, snap: PcsSnapshot) -> PcsSnapshot:
        with self._sf() as s:
            s.add(snap)
            s.commit()
            s.refresh(snap)
            return snap

    def insert_battery_snapshot(self, snap: BatterySnapshot) -> BatterySnapshot:
        with self._sf() as s:
            s.add(snap)
            s.commit()
            s.refresh(snap)
            return snap

    def latest_pcs_snapshot(self, pcs_id: str) -> Optional[PcsSnapshot]:
        with self._sf() as s:
            return (
                s.query(PcsSnapshot)
                .filter_by(pcs_id=pcs_id)
                .order_by(PcsSnapshot.timestamp.desc())
                .first()
            )

    def latest_battery_snapshot(self, battery_id: str) -> Optional[BatterySnapshot]:
        with self._sf() as s:
            return (
                s.query(BatterySnapshot)
                .filter_by(battery_id=battery_id)
                .order_by(BatterySnapshot.timestamp.desc())
                .first()
            )

    def pcs_snapshots_range(self, pcs_id: str, start_ts: int,
                            end_ts: int) -> list[PcsSnapshot]:
        with self._sf() as s:
            return (
                s.query(PcsSnapshot)
                .filter(and_(
                    PcsSnapshot.pcs_id == pcs_id,
                    PcsSnapshot.timestamp >= start_ts,
                    PcsSnapshot.timestamp <= end_ts,
                ))
                .order_by(PcsSnapshot.timestamp.asc())
                .all()
            )

    def battery_snapshots_range(self, battery_id: str, start_ts: int,
                               end_ts: int) -> list[BatterySnapshot]:
        with self._sf() as s:
            return (
                s.query(BatterySnapshot)
                .filter(and_(
                    BatterySnapshot.battery_id == battery_id,
                    BatterySnapshot.timestamp >= start_ts,
                    BatterySnapshot.timestamp <= end_ts,
                ))
                .order_by(BatterySnapshot.timestamp.asc())
                .all()
            )

    def count_pcs(self) -> int:
        with self._sf() as s:
            return s.query(PcsDevice).count()

    def find_all_pcs_with_latest(self) -> list[dict]:
        """返回所有 PCS(含 offline),每个带配置 + 关联电池(by device_id)+ 各自最新快照。"""
        with self._sf() as s:
            all_pcs = s.query(PcsDevice).all()
            out: list[dict] = []
            for pcs in all_pcs:
                battery = None
                if pcs.battery_id:
                    battery = (
                        s.query(BatteryDevice)
                        .filter_by(device_id=pcs.battery_id)
                        .first()
                    )
                latest_pcs = (
                    s.query(PcsSnapshot)
                    .filter_by(pcs_id=pcs.id)
                    .order_by(PcsSnapshot.timestamp.desc())
                    .first()
                )
                latest_bat = None
                if battery is not None:
                    latest_bat = (
                        s.query(BatterySnapshot)
                        .filter_by(battery_id=battery.id)
                        .order_by(BatterySnapshot.timestamp.desc())
                        .first()
                    )
                out.append({
                    "pcs": pcs,
                    "battery": battery,
                    "latest_pcs_snapshot": latest_pcs,
                    "latest_battery_snapshot": latest_bat,
                })
            return out
