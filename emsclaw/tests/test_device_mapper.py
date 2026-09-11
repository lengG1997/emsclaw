"""DeviceMapper — 纯 ORM 持久化层测试(sqlite 全栈)。

无业务规则:只验证 insert/find_by_id/find_by_name/find_all/update_network 的 SQL 行为。
"""
import pytest

from emsclaw_backend.db.models import Device
from emsclaw_backend.mapper.device_mapper import DeviceMapper


def _make_device(**overrides) -> Device:
    base = dict(
        id="DEV-ABCDEFGH", name="X", device_type="battery",
        status="offline", network_config={}, created_at=1, updated_at=1,
    )
    base.update(overrides)
    return Device(**base)


def test_insert_and_find_by_id(sqlite_device_db):
    m = DeviceMapper()
    inserted = m.insert(_make_device(name="ins1"))
    assert m.find_by_id(inserted.id).name == "ins1"


def test_find_by_id_returns_none_when_missing(sqlite_device_db):
    assert DeviceMapper().find_by_id("DEV-NOPE") is None


def test_find_by_name(sqlite_device_db):
    m = DeviceMapper()
    m.insert(_make_device(name="n1"))
    assert m.find_by_name("n1").id == "DEV-ABCDEFGH"
    assert m.find_by_name("missing") is None


def test_find_all_no_filter(sqlite_device_db):
    m = DeviceMapper()
    m.insert(_make_device(id="DEV-AAAA0001", name="a"))
    m.insert(_make_device(id="DEV-AAAA0002", name="b", device_type="meter"))
    assert len(m.find_all()) == 2


def test_find_all_with_type_filter(sqlite_device_db):
    m = DeviceMapper()
    m.insert(_make_device(id="DEV-AAAA0001", name="a"))
    m.insert(_make_device(id="DEV-AAAA0002", name="b", device_type="meter"))
    assert len(m.find_all(device_type="meter")) == 1


def test_update_network_sets_fields(sqlite_device_db):
    m = DeviceMapper()
    m.insert(_make_device(name="u1"))
    updated = m.update_network(
        "DEV-ABCDEFGH",
        network_config={"ip_address": "10.0.0.1", "protocol": "ModbusTCP"},
        status="pending_online",
        updated_at=999,
    )
    assert updated is not None
    assert updated.status == "pending_online"
    assert updated.network_config["ip_address"] == "10.0.0.1"
    assert updated.updated_at == 999


def test_update_network_missing_returns_none(sqlite_device_db):
    assert DeviceMapper().update_network(
        "DEV-NOPE", network_config={}, status="x", updated_at=0,
    ) is None