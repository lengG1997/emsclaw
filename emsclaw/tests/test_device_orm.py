"""Device ORM + 同步 session 工厂基础测试。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from emsclaw_backend.db.models import Device, Base
from emsclaw_backend.db import session as db_session


def test_device_table_creates_on_sqlite():
    """network_config 用 JSONB().with_variant(JSON,'sqlite')，sqlite 上应建表成功。"""
    engine = create_engine("sqlite:///:memory:", future=True)
    Device.__table__.create(engine)  # 只建 devices 表，避开其他模型的纯 JSONB
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with SessionLocal() as s:
        d = Device(id="DEV-TEST0001", name="BESS_01", device_type="battery",
                   status="offline", network_config={}, created_at=1, updated_at=1)
        s.add(d)
        s.commit()
        got = s.query(Device).filter_by(name="BESS_01").first()
        assert got is not None
        assert got.device_type == "battery"
        assert got.network_config == {}


def test_sync_session_local_exists():
    assert hasattr(db_session, "SyncSessionLocal")
    assert callable(db_session.SyncSessionLocal)
