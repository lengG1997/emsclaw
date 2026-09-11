"""PcsDevice/BatteryDevice/PcsSnapshot/BatterySnapshot ORM 集成测试(sqlite)。"""
from datetime import datetime, timezone
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from emsclaw_backend.db.models import (
    Base, PcsDevice, BatteryDevice, PcsSnapshot, BatterySnapshot,
)


@pytest.fixture
def sqlite_db():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # 只建 PCS/电池四张表,避开其他模型使用纯 JSONB 在 sqlite 上无法渲染的问题
    for tbl in (PcsDevice, BatteryDevice, PcsSnapshot, BatterySnapshot):
        tbl.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    yield SessionLocal


def test_pcs_device_round_trip(sqlite_db):
    with sqlite_db() as s:
        d = PcsDevice(
            id="PCS-00000001", device_id="DEV-PCS1",
            rated_power_kw=500.0, rated_reactive_kvar=100.0,
            ac_voltage_v=380.0, dc_voltage_v=750.0,
            rated_efficiency=0.92, min_soc=0.10, max_soc=0.90,
            battery_id="DEV-BAT1", created_at=0, updated_at=0,
        )
        s.add(d)
        s.commit()
        s.refresh(d)
        assert d.rated_power_kw == 500.0
        assert d.override_mode is None
        assert d.battery_id == "DEV-BAT1"


def test_battery_device_round_trip(sqlite_db):
    with sqlite_db() as s:
        b = BatteryDevice(
            id="BAT-00000001", device_id="DEV-BAT1",
            rated_capacity_kwh=2000.0, rated_voltage_v=750.0,
            rated_current_a=300.0, soc=0.50, soh=0.925,
            cycle_count=0, created_at=0, updated_at=0,
        )
        s.add(b)
        s.commit()
        s.refresh(b)
        assert b.soc == 0.50
        assert b.cycle_count == 0


def test_pcs_snapshot_round_trip(sqlite_db):
    with sqlite_db() as s:
        snap = PcsSnapshot(
            id="SNAP-1", pcs_id="PCS-00000001", timestamp=1000,
            active_power_kw=-500.0, reactive_power_kvar=50.0,
            mode="discharge", ac_voltage_v=380.0, dc_voltage_v=750.0,
            efficiency=0.968, status="running",
        )
        s.add(snap)
        s.commit()
        assert s.get(PcsSnapshot, "SNAP-1").mode == "discharge"


def test_battery_snapshot_round_trip(sqlite_db):
    with sqlite_db() as s:
        snap = BatterySnapshot(
            id="BSNAP-1", battery_id="BAT-00000001", timestamp=1000,
            soc=0.48, voltage=745.0, current_a=-120.0,
            temperature=28.5, mode="discharge", cycle_count=1247,
        )
        s.add(snap)
        s.commit()
        assert s.get(BatterySnapshot, "BSNAP-1").current_a == -120.0
