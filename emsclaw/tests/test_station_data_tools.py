"""station_data 读工具 - 读库而非硬编码 测试。"""
import pytest

from emsclaw_backend.db.models import PcsDevice, BatteryDevice, Device
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


def test_get_storage_status_reads_db(seeded):
    """合并后的 get_storage_status 应同时返回 PCS + 电池信息。"""
    from emsclaw_backend.deepagent.agents.business.domains.station_data.tools import (
        get_storage_status,
    )
    pairs = seeded._mapper.find_online_pcs_with_battery()
    pcs = seeded._mapper.find_pcs_by_device_id(pairs[0][0].device_id)
    out = get_storage_status.invoke({"device_id": pcs.id})
    assert "储能状态" in out
    assert "PCS" in out
    assert "电池" in out
    assert "SOC" in out


def test_get_charge_schedule_no_schedule(seeded):
    """get_charge_schedule 调 PcsService.get_charge_schedule() 单一真相源。
    无 active 计划 → 告知待机。"""
    from emsclaw_backend.deepagent.agents.business.domains.station_data.tools import (
        get_charge_schedule,
    )
    out = get_charge_schedule.invoke({})
    assert "充放电调度计划" in out
    assert "无已下发" in out
    assert "待机" in out
