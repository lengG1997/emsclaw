"""get_station_overview 聚合工具 - 场站全量当前态 测试。"""
import pytest

from emsclaw_backend.db.models import Device
from emsclaw_backend.mapper.station_mapper import StationMapper
from emsclaw_backend.service.pcs_service import PcsService
from emsclaw_backend.service.station_service import StationSimService


@pytest.fixture
def seeded_station(sqlite_station_db, sqlite_pcs_db, monkeypatch):
    """用 sqlite 同时播种 station + PCS,并把两个单例 service 指过去。"""
    stn_mapper = StationMapper(session_factory=sqlite_station_db)
    stn_svc = StationSimService(mapper=stn_mapper)
    stn_svc.ensure_seeded()

    pcs_svc = PcsService()
    pcs_svc.ensure_seeded()
    pcs_svc.tick_all(now_ts=1000)

    import emsclaw_backend.service.station_service as stn_mod
    import emsclaw_backend.service.pcs_service as pcs_mod
    monkeypatch.setattr(stn_mod, "_default_service", stn_svc)
    monkeypatch.setattr(pcs_mod, "_default_service", pcs_svc)

    yield stn_svc
    stn_mod._default_service = None
    pcs_mod._default_service = None


def test_get_station_overview_aggregates(seeded_station):
    from emsclaw_backend.deepagent.agents.business.domains.station_data.tools import (
        get_station_overview,
    )
    out = get_station_overview.invoke({})
    assert "场站全量当前态" in out
    assert "储能实时" in out
    assert "光伏" in out
    assert "关口表" in out
    assert "需量控制" in out


def test_get_station_overview_handles_empty(monkeypatch):
    """无任何播种时不应抛错(全防御),仍返回标题与'暂无'。"""
    import emsclaw_backend.service.station_service as stn_mod
    import emsclaw_backend.service.pcs_service as pcs_mod
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, Session
    from sqlalchemy.pool import StaticPool
    from emsclaw_backend.db.models import (
        Device, PvDevice, PvSnapshot, MeterDevice, MeterSnapshot,
        WeatherSnapshot, ElectricityTariff, DailyEnergyRecord, StationConfig,
        PcsDevice, BatteryDevice, PcsSnapshot, BatterySnapshot,
    )
    from emsclaw_backend.mapper.pcs_mapper import PcsMapper
    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    for tbl in (Device, PvDevice, PvSnapshot, MeterDevice, MeterSnapshot,
                WeatherSnapshot, ElectricityTariff, DailyEnergyRecord,
                StationConfig, PcsDevice, BatteryDevice, PcsSnapshot,
                BatterySnapshot):
        tbl.__table__.create(engine)
    sf = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    stn_svc = StationSimService(mapper=StationMapper(session_factory=sf))
    pcs_svc = PcsService(mapper=PcsMapper(session_factory=sf))
    monkeypatch.setattr(stn_mod, "_default_service", stn_svc)
    monkeypatch.setattr(pcs_mod, "_default_service", pcs_svc)

    from emsclaw_backend.deepagent.agents.business.domains.station_data.tools import (
        get_station_overview,
    )
    out = get_station_overview.invoke({})
    assert "场站全量当前态" in out
    assert "暂无" in out
    stn_mod._default_service = None
    pcs_mod._default_service = None
