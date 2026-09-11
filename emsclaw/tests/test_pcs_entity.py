"""PCS entity 枚举与 DTO 测试。"""
from emsclaw_backend.entity.pcs import PcsMode, PcsStatus, PcsDeviceDTO, BatteryDeviceDTO
from emsclaw_backend.entity.device import DeviceType


def test_pcs_mode_values():
    assert PcsMode.CHARGE.value == "charge"
    assert PcsMode.DISCHARGE.value == "discharge"
    assert PcsMode.STANDBY.value == "standby"
    assert PcsMode.AUTO.value == "auto"


def test_pcs_status_values():
    assert PcsStatus.RUNNING.value == "running"
    assert PcsStatus.FAULT.value == "fault"


def test_device_type_has_pcs():
    assert DeviceType.PCS.value == "pcs"


def test_pcs_device_dto_from_orm_like():
    class Fake:
        id = "PCS-1"
        device_id = "DEV-1"
        rated_power_kw = 500.0
        rated_reactive_kvar = 100.0
        ac_voltage_v = 380.0
        dc_voltage_v = 750.0
        rated_efficiency = 0.92
        min_soc = 0.10
        max_soc = 0.90
        override_mode = None
        override_power_kw = None
        override_expires_at = 0
        battery_id = None
        created_at = 0
        updated_at = 0
    dto = PcsDeviceDTO.model_validate(Fake())
    assert dto.id == "PCS-1"
    assert dto.rated_power_kw == 500.0
