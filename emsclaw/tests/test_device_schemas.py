"""schemas.py DTO/枚举测试。"""
import pytest
from pydantic import ValidationError

from emsclaw_backend.deepagent.agents.business.domains.device_operation.schemas import (
    DeviceType, DeviceStatus, NetworkConfig, DeviceDTO,
)


def test_device_type_values():
    assert DeviceType.BATTERY.value == "battery"
    assert {e.value for e in DeviceType} == {"battery", "inverter", "meter", "pcs"}


def test_device_status_values():
    assert {e.value for e in DeviceStatus} == {"offline", "pending_online", "online"}


def test_network_config_required_fields():
    nc = NetworkConfig(ip_address="10.0.0.1", protocol="ModbusTCP", configured_at=100)
    assert nc.port is None
    with pytest.raises(ValidationError):
        NetworkConfig(ip_address="10.0.0.1", configured_at=100)  # 缺 protocol


def test_device_dto_from_dict():
    dto = DeviceDTO(id="DEV-1", name="A", device_type="battery",
                    status="offline", network_config={}, created_at=1, updated_at=1)
    assert dto.id == "DEV-1"
    assert dto.model_dump()["device_type"] == "battery"


def test_device_dto_from_orm(sqlite_device_db):
    """回归:DeviceDTO.model_validate(ORM Device 对象) 必须工作(from_attributes)。"""
    from emsclaw_backend.service.device_service import DeviceService

    orm_device = DeviceService().create(name="ORM_DTO", device_type="battery")
    dto = DeviceDTO.model_validate(orm_device)
    assert dto.id == orm_device.id
    assert dto.name == "ORM_DTO"
    assert dto.device_type == "battery"
    assert dto.status == "offline"
