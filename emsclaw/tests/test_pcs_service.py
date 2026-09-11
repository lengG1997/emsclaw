"""PcsService — 调度状态机(读 active 计划)/SOC 积分/override/seed 测试。"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from emsclaw_backend.db.models import PcsDevice, BatteryDevice, Device, ChargeSchedule
from emsclaw_backend.service.pcs_service import PcsService

_SH = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def svc(sqlite_pcs_db):
    return PcsService()


def _today_str() -> str:
    return datetime.now(tz=_SH).strftime("%Y-%m-%d")


def _seed_one(svc, sqlite_pcs_db, *, soc=0.50):
    svc._mapper.insert_pcs(PcsDevice(
        id="PCS-1", device_id="DEV-PCS1", rated_power_kw=500.0,
        rated_reactive_kvar=100.0, ac_voltage_v=380.0, dc_voltage_v=750.0,
        rated_efficiency=0.92, min_soc=0.10, max_soc=0.90,
        battery_id="DEV-BAT1", created_at=0, updated_at=0,
    ))
    svc._mapper.insert_battery(BatteryDevice(
        id="BAT-1", device_id="DEV-BAT1", rated_capacity_kwh=2000.0,
        rated_voltage_v=750.0, rated_current_a=300.0,
        soc=soc, soh=0.925, cycle_count=0, created_at=0, updated_at=0,
    ))
    sf = sqlite_pcs_db
    with sf() as s:
        s.add(Device(id="DEV-PCS1", name="PCS-001", device_type="pcs",
                     status="online", network_config={}, created_at=0, updated_at=0))
        s.add(Device(id="DEV-BAT1", name="BAT-001", device_type="battery",
                     status="online", network_config={}, created_at=0, updated_at=0))
        s.commit()


def _seed_schedule(sqlite_pcs_db, segments: dict[int, dict]):
    """建 charge_schedules 表并插一条当日 active 计划(segments: hour -> interval 字段覆盖)。

    其余小时默认 standby。decide_mode_and_power 用真实今天日期查计划。
    """
    sf = sqlite_pcs_db
    ChargeSchedule.__table__.create(sf().bind)
    intervals = []
    for h in range(24):
        base = {"hour": h, "mode": "standby", "power_kw": 0.0, "power_ratio": 0.0,
                "soc_target_pct": 0.5, "period": "平", "tariff_price": 0.75}
        base.update(segments.get(h, {}))
        intervals.append(base)
    with sf() as s:
        s.add(ChargeSchedule(
            id="SCH-T", target_date=_today_str(), status="active", perspective="业主",
            intervals=intervals, objective={}, created_at=0, updated_at=0,
        ))
        s.commit()


def _pcs(**over) -> PcsDevice:
    base = dict(id="PCS-1", device_id="D", rated_power_kw=500.0,
                rated_reactive_kvar=100.0, ac_voltage_v=380.0, dc_voltage_v=750.0,
                rated_efficiency=0.92, min_soc=0.10, max_soc=0.90,
                battery_id=None, created_at=0, updated_at=0)
    base.update(over)
    return PcsDevice(**base)


def test_decide_mode_valley_charge(svc, sqlite_pcs_db):
    _seed_schedule(sqlite_pcs_db, {3: {"mode": "charge", "power_kw": 350.0,
                                       "power_ratio": 0.7}})
    mode, power = svc.decide_mode_and_power(hour=3, pcs=_pcs())
    assert mode == "charge"
    assert abs(power - 500.0 * 0.7) < 1e-6  # ratio × rated


def test_decide_mode_peak_discharge(svc, sqlite_pcs_db):
    _seed_schedule(sqlite_pcs_db, {10: {"mode": "discharge", "power_kw": 400.0,
                                        "power_ratio": 0.8}})
    mode, power = svc.decide_mode_and_power(hour=10, pcs=_pcs())
    assert mode == "discharge"
    assert abs(power - (-500.0 * 0.8)) < 1e-6


def test_decide_mode_no_schedule_standby(svc):
    # 无 active 计划且无 tariff 表(sqlite fixture 未建) → 待机
    mode, power = svc.decide_mode_and_power(hour=3, pcs=_pcs())
    assert mode == "standby"
    assert power == 0.0


def _seed_tariffs(sqlite_pcs_db, rows: list[tuple[str, int, int, float]]):
    """建 electricity_tariffs 表并插时段行(rows: period_type, lo, hi, price)。"""
    from emsclaw_backend.db.models import ElectricityTariff
    sf = sqlite_pcs_db
    ElectricityTariff.__table__.create(sf().bind)
    with sf() as s:
        for i, (ptype, lo, hi, price) in enumerate(rows):
            s.add(ElectricityTariff(
                id=f"TF-{i}", region="default", period_type=ptype,
                start_hour=lo, end_hour=hi, energy_price=price,
                created_at=0, updated_at=0,
            ))
        s.commit()


def test_decide_mode_no_schedule_tariff_fallback(svc, sqlite_pcs_db):
    """无当日计划 → 按电价时段兜底:谷充/峰尖放/平待机(不能孤岛待机)。"""
    _seed_tariffs(sqlite_pcs_db, [
        ("valley", 0, 7, 0.35),
        ("flat", 7, 9, 0.75),
        ("peak", 9, 12, 1.05),
        ("sharp", 17, 19, 1.25),
    ])
    mode, power = svc.decide_mode_and_power(hour=3, pcs=_pcs())
    assert mode == "charge"
    assert power == 500.0  # 谷段 → 满额充电
    mode, power = svc.decide_mode_and_power(hour=10, pcs=_pcs())
    assert mode == "discharge"
    assert power == -500.0  # 峰段 → 满额放电
    mode, power = svc.decide_mode_and_power(hour=18, pcs=_pcs())
    assert mode == "discharge"  # 尖段也放电
    mode, power = svc.decide_mode_and_power(hour=8, pcs=_pcs())
    assert mode == "standby"  # 平段 → 待机
    assert power == 0.0


def test_decide_mode_schedule_overrides_tariff_fallback(svc, sqlite_pcs_db):
    """有当日 active 计划时以计划为准,兜底不生效(显式 standby 段也生效)。"""
    _seed_tariffs(sqlite_pcs_db, [("peak", 9, 12, 1.05)])
    # hour=10 在 peak 段本应放电,但计划显式 standby → 待机
    _seed_schedule(sqlite_pcs_db, {10: {"mode": "standby", "power_ratio": 0.0}})
    mode, power = svc.decide_mode_and_power(hour=10, pcs=_pcs())
    assert mode == "standby"
    assert power == 0.0


def test_decide_mode_standby_segment(svc, sqlite_pcs_db):
    _seed_schedule(sqlite_pcs_db, {8: {"mode": "standby", "power_ratio": 0.0}})
    mode, power = svc.decide_mode_and_power(hour=8, pcs=_pcs())
    assert mode == "standby"
    assert power == 0.0


def test_decide_mode_override_wins(svc, sqlite_pcs_db):
    _seed_schedule(sqlite_pcs_db, {10: {"mode": "discharge", "power_ratio": 0.8}})
    pcs = _pcs(override_mode="charge", override_power_kw=300.0,
               override_expires_at=99999999999)
    mode, power = svc.decide_mode_and_power(hour=10, pcs=pcs)
    # hour=10 本应 discharge,但 override 未过期 → charge
    assert mode == "charge"
    assert power == 300.0


def test_tick_follows_schedule_charge(svc, sqlite_pcs_db):
    _seed_one(svc, sqlite_pcs_db, soc=0.30)
    _seed_schedule(sqlite_pcs_db, {8: {"mode": "charge", "power_ratio": 0.7}})
    # tick 在 now_ts=1000 → 上海 08:16 → hour=8,计划充电
    # 2000kWh 容量,500kW×0.7×1min/3600 → SOC +0.0029
    svc.tick_all(now_ts=1000)
    bat = svc._mapper.find_battery_by_device_id("DEV-BAT1")
    assert bat.soc > 0.30
    snap = svc._mapper.latest_pcs_snapshot("PCS-1")
    assert snap.mode == "charge"


def test_tick_soc_clamp_to_max(svc, sqlite_pcs_db):
    _seed_one(svc, sqlite_pcs_db, soc=0.895)  # 接近上限 0.90
    svc._mapper.update_pcs_override("PCS-1", override_mode="charge",
                                     override_power_kw=500.0,
                                     override_expires_at=99999999999, updated_at=0)
    svc.tick_all(now_ts=1000)
    bat = svc._mapper.find_battery_by_device_id("DEV-BAT1")
    assert bat.soc <= 0.90


def test_tick_writes_snapshots(svc, sqlite_pcs_db):
    _seed_one(svc, sqlite_pcs_db)
    svc.tick_all(now_ts=5000)
    snap = svc._mapper.latest_pcs_snapshot("PCS-1")
    assert snap is not None
    assert snap.timestamp == 5000
    bsnap = svc._mapper.latest_battery_snapshot("BAT-1")
    assert bsnap is not None


def test_tick_idempotent_structure(svc, sqlite_pcs_db):
    _seed_one(svc, sqlite_pcs_db)
    r1 = svc.tick_all(now_ts=1000)
    r2 = svc.tick_all(now_ts=1000)
    assert r1["ticked"] == r2["ticked"] == 1


def test_set_mode(svc, sqlite_pcs_db):
    _seed_one(svc, sqlite_pcs_db)
    svc.set_mode("PCS-1", mode="discharge", power_kw=450.0, expires_at=99999999999)
    pcs = svc._mapper.find_pcs_by_id("PCS-1")
    assert pcs.override_mode == "discharge"
    assert pcs.override_power_kw == 450.0


def test_ensure_seeded_creates_defaults(svc, sqlite_pcs_db):
    assert svc._mapper.count_pcs() == 0
    n = svc.ensure_seeded()
    assert n >= 1
    assert svc._mapper.count_pcs() >= 1
    # 重复 seed 不重复创建(场站模型 2 台 PCS)
    svc.ensure_seeded()
    assert svc._mapper.count_pcs() == 2
