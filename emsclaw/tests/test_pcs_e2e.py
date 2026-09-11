"""PCS 模拟端到端冒烟:seed -> tick -> tools 读到数据。"""
import pytest

from emsclaw_backend.service.pcs_service import PcsService, reset_default_service
from emsclaw_backend.deepagent.agents.business.domains.station_data.tools import (
    get_storage_status, get_charge_schedule,
)
from emsclaw_backend.deepagent.agents.business.domains.device_operation.tools import (
    emergency_stop,
)


@pytest.fixture
def e2e(sqlite_pcs_db):
    reset_default_service()
    svc = PcsService()
    import emsclaw_backend.service.pcs_service as ps
    ps._default_service = svc
    svc.ensure_seeded()
    svc.tick_all(now_ts=1000)
    svc.tick_all(now_ts=1060)
    yield svc
    reset_default_service()


def test_full_flow(e2e):
    pairs = e2e._mapper.find_online_pcs_with_battery()
    assert len(pairs) == 2
    pcs_id = pairs[0][0].id
    bat_id = pairs[0][1].id

    # 合并后的 get_storage_status 同时返回 PCS + 电池信息
    out = get_storage_status.invoke({"device_id": pcs_id})
    assert "储能状态" in out
    assert "PCS" in out
    assert "电池" in out
    assert "SOC" in out

    # 无 active 计划 → 调度计划查询返回"无已下发",储能待机
    out_sched = get_charge_schedule.invoke({})
    assert "充放电调度计划" in out_sched
    assert "无已下发" in out_sched

    # 无计划时 tick 全待机(SOC 不漂移)
    e2e.tick_all(now_ts=1120)
    for snap in e2e._mapper.pcs_snapshots_range(pcs_id, 0, 99999):
        assert snap.mode == "standby"
        assert snap.active_power_kw == 0.0

    # emergency_stop 写 override,优先级高于计划(计划缺省时本就是待机)
    out_stop = emergency_stop.invoke({"reason": "e2e"})
    assert "紧急停止已执行" in out_stop
    pcs = e2e._mapper.find_pcs_by_id(pcs_id)
    assert pcs.override_mode == "standby"

    # 多次 tick 后快照累积
    n_before = len(e2e._mapper.pcs_snapshots_range(pcs_id, 0, 9999))
    e2e.tick_all(now_ts=1180)
    n_after = len(e2e._mapper.pcs_snapshots_range(pcs_id, 0, 9999))
    assert n_after == n_before + 1
