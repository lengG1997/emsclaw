"""DeviceService — 业务规则 + 状态流转 + ID 生成 集成测试(sqlite 全栈)。

Service 返回 ORM Device 行;DTO/JSON 映射由 tools/controller 层负责。
"""
import pytest

from emsclaw_backend.service.device_service import DeviceService


def test_create_success(sqlite_device_db):
    d = DeviceService().create(name="BESS_01", device_type="battery")
    assert d.id.startswith("DEV-")
    assert d.name == "BESS_01"
    assert d.status == "offline"
    assert d.network_config == {}


def test_create_rejects_invalid_type(sqlite_device_db):
    with pytest.raises(ValueError):
        DeviceService().create(name="X", device_type="unknown")


def test_create_rejects_duplicate_name(sqlite_device_db):
    DeviceService().create(name="DUP", device_type="battery")
    with pytest.raises(ValueError):
        DeviceService().create(name="DUP", device_type="meter")


def test_get_by_id_or_name(sqlite_device_db):
    s = DeviceService()
    created = s.create(name="G1", device_type="inverter")
    assert s.get(device_id=created.id).name == "G1"
    assert s.get(name="G1").id == created.id
    assert s.get(name="missing") is None


def test_get_requires_id_or_name(sqlite_device_db):
    with pytest.raises(ValueError):
        DeviceService().get()


def test_list_with_filter(sqlite_device_db):
    s = DeviceService()
    s.create(name="L1", device_type="battery")
    s.create(name="L2", device_type="meter")
    assert len(s.list()) == 2
    assert len(s.list(device_type="meter")) == 1


def test_list_rejects_invalid_filter(sqlite_device_db):
    with pytest.raises(ValueError):
        DeviceService().list(device_type="unknown")


def test_configure_network_success(sqlite_device_db):
    s = DeviceService()
    created = s.create(name="N1", device_type="battery")
    d = s.configure_network(created.id, "10.0.0.5", "ModbusTCP", port=502)
    assert d.status == "pending_online"
    assert d.network_config["ip_address"] == "10.0.0.5"
    assert d.network_config["port"] == 502


def test_configure_network_missing_device(sqlite_device_db):
    with pytest.raises(ValueError):
        DeviceService().configure_network("DEV-NOPE", "10.0.0.5", "ModbusTCP")


def test_configure_network_bad_ip(sqlite_device_db):
    s = DeviceService()
    c = s.create(name="N2", device_type="battery")
    with pytest.raises(ValueError):
        s.configure_network(c.id, "999.0.0.1", "ModbusTCP")


def test_configure_network_bad_protocol(sqlite_device_db):
    s = DeviceService()
    c = s.create(name="N3", device_type="battery")
    with pytest.raises(ValueError):
        s.configure_network(c.id, "10.0.0.1", "CAN")


def test_create_pcs_type(sqlite_device_db):
    d = DeviceService().create(name="PCS_TEST", device_type="pcs")
    assert d.device_type == "pcs"


def test_create_rejects_still_invalid_type(sqlite_device_db):
    with pytest.raises(ValueError):
        DeviceService().create(name="X", device_type="unknown")