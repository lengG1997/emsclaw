"""PcsMapper — 4 表持久化测试(sqlite + monkeypatch SyncSessionLocal)。"""
import pytest

from emsclaw_backend.db.models import PcsDevice, BatteryDevice, PcsSnapshot, BatterySnapshot
from emsclaw_backend.mapper.pcs_mapper import PcsMapper


@pytest.fixture
def mapper(sqlite_pcs_db):
    # sqlite_pcs_db monkeypatches emsclaw_backend.mapper.pcs_mapper.SyncSessionLocal
    return PcsMapper()


def _seed_pcs_and_battery(mapper):
    mapper.insert_pcs(PcsDevice(
        id="PCS-1", device_id="DEV-PCS1", rated_power_kw=500.0,
        rated_reactive_kvar=100.0, ac_voltage_v=380.0, dc_voltage_v=750.0,
        rated_efficiency=0.92, min_soc=0.10, max_soc=0.90,
        battery_id="DEV-BAT1", created_at=0, updated_at=0,
    ))
    mapper.insert_battery(BatteryDevice(
        id="BAT-1", device_id="DEV-BAT1", rated_capacity_kwh=2000.0,
        rated_voltage_v=750.0, rated_current_a=300.0,
        soc=0.50, soh=0.925, cycle_count=0, created_at=0, updated_at=0,
    ))


def test_find_pcs_by_device_id(mapper):
    _seed_pcs_and_battery(mapper)
    pcs = mapper.find_pcs_by_device_id("DEV-PCS1")
    assert pcs is not None
    assert pcs.id == "PCS-1"


def test_find_battery_by_device_id(mapper):
    _seed_pcs_and_battery(mapper)
    bat = mapper.find_battery_by_device_id("DEV-BAT1")
    assert bat is not None
    assert bat.soc == 0.50


def test_find_online_pcs_with_battery(mapper, sqlite_pcs_db):
    # 需要 Device 表标记 online;这里直接构造 Device 行
    from emsclaw_backend.db.models import Device, Base
    from sqlalchemy import create_engine
    # sqlite_pcs_db fixture 返回 SessionLocal;复用之
    _seed_pcs_and_battery(mapper)
    # 插入 device 行(online pcs + online battery)
    sf = sqlite_pcs_db
    with sf() as s:
        s.add(Device(id="DEV-PCS1", name="PCS-001", device_type="pcs",
                     status="online", network_config={}, created_at=0, updated_at=0))
        s.add(Device(id="DEV-BAT1", name="BAT-001", device_type="battery",
                     status="online", network_config={}, created_at=0, updated_at=0))
        s.commit()
    rows = mapper.find_online_pcs_with_battery()
    assert len(rows) == 1
    pcs, bat = rows[0]
    assert pcs.id == "PCS-1"
    assert bat.id == "BAT-1"


def test_update_battery_soc(mapper):
    _seed_pcs_and_battery(mapper)
    mapper.update_battery_soc("DEV-BAT1", soc=0.55, cycle_count=3, updated_at=100)
    bat = mapper.find_battery_by_device_id("DEV-BAT1")
    assert bat.soc == 0.55
    assert bat.cycle_count == 3


def test_insert_and_latest_snapshot(mapper):
    _seed_pcs_and_battery(mapper)
    mapper.insert_pcs_snapshot(PcsSnapshot(
        id="SN-1", pcs_id="PCS-1", timestamp=1000, active_power_kw=-500.0,
        reactive_power_kvar=50.0, mode="discharge", ac_voltage_v=380.0,
        dc_voltage_v=750.0, efficiency=0.968, status="running",
    ))
    snap = mapper.latest_pcs_snapshot("PCS-1")
    assert snap is not None
    assert snap.active_power_kw == -500.0


def test_pcs_snapshots_range(mapper):
    _seed_pcs_and_battery(mapper)
    for i, ts in enumerate([1000, 1060, 1120]):
        mapper.insert_pcs_snapshot(PcsSnapshot(
            id=f"SN-{i}", pcs_id="PCS-1", timestamp=ts, active_power_kw=float(ts),
            reactive_power_kvar=0.0, mode="standby", ac_voltage_v=380.0,
            dc_voltage_v=750.0, efficiency=0.92, status="standby",
        ))
    rows = mapper.pcs_snapshots_range("PCS-1", 1000, 1120)
    assert len(rows) == 3


def test_update_pcs_override(mapper):
    _seed_pcs_and_battery(mapper)
    mapper.update_pcs_override("PCS-1", override_mode="charge",
                               override_power_kw=400.0, override_expires_at=9999,
                               updated_at=100)
    pcs = mapper.find_pcs_by_id("PCS-1")
    assert pcs.override_mode == "charge"
    assert pcs.override_power_kw == 400.0


def test_find_all_pcs_with_latest(mapper, sqlite_pcs_db):
    from emsclaw_backend.db.models import Device, PcsDevice, BatteryDevice, PcsSnapshot, BatterySnapshot
    _seed_pcs_and_battery(mapper)  # PCS-1 / DEV-PCS1 / BAT-1 / DEV-BAT1
    # seed a snapshot so latest is non-null
    mapper.insert_pcs_snapshot(PcsSnapshot(
        id="SN-A", pcs_id="PCS-1", timestamp=1000, active_power_kw=-500.0,
        reactive_power_kvar=50.0, mode="discharge", ac_voltage_v=380.0,
        dc_voltage_v=750.0, efficiency=0.968, status="running",
    ))
    sf = sqlite_pcs_db
    with sf() as s:
        s.add(Device(id="DEV-PCS1", name="PCS-001", device_type="pcs",
                     status="online", network_config={}, created_at=0, updated_at=0))
        s.commit()
    rows = mapper.find_all_pcs_with_latest()
    assert len(rows) == 1
    r = rows[0]
    assert r["pcs"].id == "PCS-1"
    assert r["battery"] is not None
    assert r["battery"].id == "BAT-1"
    assert r["latest_pcs_snapshot"] is not None
    assert r["latest_pcs_snapshot"].active_power_kw == -500.0
    assert r["latest_battery_snapshot"] is None  # no battery snapshot seeded


def test_find_all_pcs_with_latest_empty(mapper):
    rows = mapper.find_all_pcs_with_latest()
    assert rows == []
