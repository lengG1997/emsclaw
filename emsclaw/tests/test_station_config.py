"""StationConfig 写路径 - mapper upsert + service 更新校验。

方案2(申报需量/防逆流/电价可配置)的持久化与校验层。
dispatch 闭环(set_station_config 工具 → optimize_dispatch 读到新值)在
test_dispatch_planning.py::test_set_station_config_feeds_optimize_dispatch。
"""
import time

import pytest

from emsclaw_backend.db.models import StationConfig
from emsclaw_backend.mapper.station_mapper import StationMapper
from emsclaw_backend.service.station_service import StationSimService


def _seed(sf) -> None:
    with sf() as s:
        s.add(StationConfig(id="STN-DEFAULT", region="default",
                            contract_demand_kw=1000.0,
                            anti_reverse_export_setpoint_kw=50.0,
                            capacity_price_yuan_per_kw_month=30.0,
                            demand_price_yuan_per_kw_month=40.0,
                            updated_at=1000))
        s.commit()


# ── mapper upsert ───────────────────────────────────────────────
def test_mapper_upsert_inserts_when_missing(sqlite_station_db):
    m = StationMapper(session_factory=sqlite_station_db)
    cfg = StationConfig(id="STN-DEFAULT", contract_demand_kw=1500.0, updated_at=2000)
    got = m.upsert_station_config(cfg)
    assert got.id == "STN-DEFAULT"
    assert got.contract_demand_kw == 1500.0
    assert got.anti_reverse_export_setpoint_kw == 50.0  # 未传字段取模型默认
    assert m.get_station_config().contract_demand_kw == 1500.0


def test_mapper_upsert_updates_existing_keeps_others(sqlite_station_db):
    _seed(sqlite_station_db)
    m = StationMapper(session_factory=sqlite_station_db)
    cfg = StationConfig(id="STN-DEFAULT", contract_demand_kw=1500.0, updated_at=2000)
    got = m.upsert_station_config(cfg)
    assert got.contract_demand_kw == 1500.0
    assert got.anti_reverse_export_setpoint_kw == 50.0   # 未传字段保留原值
    assert got.demand_price_yuan_per_kw_month == 40.0    # 未传字段保留原值
    assert got.updated_at > 1000                          # 更新时时间戳刷新(原 seed 为 1000)
    # 仍是单行
    with sqlite_station_db() as s:
        assert s.query(StationConfig).count() == 1


# ── service 更新与校验 ──────────────────────────────────────────
def test_service_update_single_field(sqlite_station_db):
    _seed(sqlite_station_db)
    svc = StationSimService()
    got = svc.update_station_config({"contract_demand_kw": 1500.0})
    assert got["contract_demand_kw"] == 1500.0
    assert got["anti_reverse_export_setpoint_kw"] == 50.0
    assert got["demand_price_yuan_per_kw_month"] == 40.0
    # 需量状态立刻读到新申报值
    assert svc.get_demand()["contract_demand_kw"] == 1500.0


def test_service_update_inserts_when_not_seeded(sqlite_station_db):
    svc = StationSimService()
    got = svc.update_station_config({"contract_demand_kw": 1200.0})
    assert got["contract_demand_kw"] == 1200.0


def test_service_update_rejects_empty(sqlite_station_db):
    svc = StationSimService()
    with pytest.raises(ValueError, match="至少提供一项"):
        svc.update_station_config({})


def test_service_update_rejects_negative(sqlite_station_db):
    svc = StationSimService()
    with pytest.raises(ValueError, match="不能为负"):
        svc.update_station_config({"contract_demand_kw": -5.0})
    with pytest.raises(ValueError, match="不能为负"):
        svc.update_station_config({"demand_price_yuan_per_kw_month": -1.0})
