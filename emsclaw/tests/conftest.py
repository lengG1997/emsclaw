"""pytest 公共配置。"""
import sys
from pathlib import Path

# import 包 emsclaw_backend 位于 emsclaw/backend/ 下，需把该目录加入 sys.path
_BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


import pytest


@pytest.fixture
def sqlite_device_db(monkeypatch):
    """注入 sqlite in-memory session 工厂到 DeviceMapper，建好 devices 表。

    DeviceService 默认构造 DeviceMapper(),后者会读取 monkeypatch 过的
    SyncSessionLocal — 因此业务规则(create/get/list/configure_network)
    测试不需要显式传 mapper,直接 DeviceService() 即可。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, Session
    from sqlalchemy.pool import StaticPool
    from emsclaw_backend.db.models import Device
    import emsclaw_backend.mapper.device_mapper as mapper_mod

    # StaticPool 让所有 connection 共享同一个 in-memory db(否则每次新 connection 拿到空 db,无 devices 表)
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Device.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    monkeypatch.setattr(mapper_mod, "SyncSessionLocal", SessionLocal)
    yield engine


@pytest.fixture
def sqlite_pcs_db(monkeypatch):
    """注入 sqlite in-memory session 工厂到 PcsMapper,建好全部 PCS 相关表。

    返回 SessionLocal(供测试直接插 Device 行等)。

    偏差说明(此处逐表 create,而非 Base.metadata.create_all(engine)):
    models.py 中 Session / IMSystemSetting / WeChatBridgeState 等表直接使用裸
    JSONB(无 sqlite variant),Base.metadata.create_all 会在 sqlite 上失败。
    遵循 test_device_orm.py 的既定约定,这里只创建 PCS 4 表 + Device
    (find_online_pcs_with_battery 会 join devices)。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, Session
    from sqlalchemy.pool import StaticPool
    from emsclaw_backend.db.models import (
        Base, PcsDevice, BatteryDevice, PcsSnapshot, BatterySnapshot, Device,
    )
    import emsclaw_backend.mapper.pcs_mapper as pcs_mapper_mod

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # 逐表创建(避免命中裸 JSONB 表导致 sqlite 报错)
    for tbl in (Device, PcsDevice, BatteryDevice, PcsSnapshot, BatterySnapshot):
        tbl.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    monkeypatch.setattr(pcs_mapper_mod, "SyncSessionLocal", SessionLocal)
    yield SessionLocal


@pytest.fixture
def sqlite_approval_db(monkeypatch):
    """注入 sqlite in-memory session 工厂到 ApprovalMapper,建好 approval_records 表。

    ApprovalRecord 用了 JSONB().with_variant(JSON, "sqlite"),sqlite 上能直接建表。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, Session
    from sqlalchemy.pool import StaticPool
    from emsclaw_backend.db.models import ApprovalRecord
    import emsclaw_backend.mapper.approval_mapper as approval_mapper_mod

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ApprovalRecord.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    monkeypatch.setattr(approval_mapper_mod, "SyncSessionLocal", SessionLocal)
    yield SessionLocal


@pytest.fixture
def sqlite_schedule_db(monkeypatch):
    """注入 sqlite in-memory session 工厂到 ScheduleMapper,建好 charge_schedules 表。

    ChargeSchedule 用 JSONB().with_variant(JSON, "sqlite"),sqlite 可直接建表。
    返回 SessionLocal,供测试直接插行或与 pcs/station fixture 共享同一 engine。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, Session
    from sqlalchemy.pool import StaticPool
    from emsclaw_backend.db.models import ChargeSchedule
    import emsclaw_backend.mapper.schedule_mapper as schedule_mapper_mod

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ChargeSchedule.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    monkeypatch.setattr(schedule_mapper_mod, "SyncSessionLocal", SessionLocal)
    yield SessionLocal


@pytest.fixture
def sqlite_station_db(monkeypatch):
    """注入 sqlite in-memory session 工厂到 StationMapper,建好全部 station 表 + Device。

    station 模型均用标量列(无 JSONB),sqlite 可直接建表。
    Device 表供 ensure_seeded 插入 PCS/PV/Meter 设备行(find_*_device 会 join)。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, Session
    from sqlalchemy.pool import StaticPool
    from emsclaw_backend.db.models import (
        Device, PvDevice, PvSnapshot, MeterDevice, MeterSnapshot,
        WeatherSnapshot, ElectricityTariff, DailyEnergyRecord, StationConfig,
    )
    import emsclaw_backend.mapper.station_mapper as station_mapper_mod

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for tbl in (Device, PvDevice, PvSnapshot, MeterDevice, MeterSnapshot,
                WeatherSnapshot, ElectricityTariff, DailyEnergyRecord, StationConfig):
        tbl.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    monkeypatch.setattr(station_mapper_mod, "SyncSessionLocal", SessionLocal)
    yield SessionLocal