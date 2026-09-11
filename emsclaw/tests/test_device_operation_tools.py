"""device_operation 控制工具 - 急停/指令写 override 测试。"""
import pytest

from emsclaw_backend.service.pcs_service import PcsService


@pytest.fixture
def seeded(sqlite_pcs_db):
    svc = PcsService()
    svc.ensure_seeded()
    svc.tick_all(now_ts=1000)
    import emsclaw_backend.service.pcs_service as ps
    ps._default_service = svc
    yield svc
    ps._default_service = None


def test_emergency_stop_sets_all_pcs_standby(seeded):
    """emergency_stop 应真实把所有在线 PCS 置 standby(override 写)。"""
    from emsclaw_backend.deepagent.agents.business.domains.device_operation.tools import (
        emergency_stop,
    )
    out = emergency_stop.invoke({"reason": "test"})
    assert "紧急停止已执行" in out
    pairs = seeded._mapper.find_online_pcs_with_battery()
    for pcs, _ in pairs:
        refreshed = seeded._mapper.find_pcs_by_id(pcs.id)
        assert refreshed.override_mode == "standby"
        assert refreshed.override_power_kw == 0.0


def test_override_priority_over_schedule(seeded, sqlite_pcs_db):
    """override 未过期时优先于 active 计划。"""
    from emsclaw_backend.db.models import ChargeSchedule
    # sqlite_pcs_db 已 patch PcsMapper;PcsService 的 ScheduleMapper 共用其 session_factory,
    # 这里只补建 charge_schedules 表即可。
    sf = sqlite_pcs_db
    ChargeSchedule.__table__.create(sf().bind)

    with sf() as s:
        s.add(ChargeSchedule(
            id="SCH-T1", target_date="2026-08-07", status="active",
            strategies=["省钱"],
            intervals=[{"hour": 10, "mode": "discharge", "power_kw": 500.0,
                        "power_ratio": 1.0, "soc_target_pct": 0.5,
                        "period": "峰", "tariff_price": 1.05}] * 24,
            objective={}, created_at=0, updated_at=0,
        ))
        s.commit()

    svc = seeded
    pcs = svc._mapper.find_online_pcs_with_battery()[0][0]
    # 先有 active 计划(放电),再写 override(充电),override 生效
    svc.set_mode(pcs.id, mode="charge", power_kw=400.0, expires_at=99999999999)
    mode, power = svc.decide_mode_and_power(hour=10, pcs=svc._mapper.find_pcs_by_id(pcs.id))
    assert mode == "charge"
    assert 380.0 <= power <= 420.0
