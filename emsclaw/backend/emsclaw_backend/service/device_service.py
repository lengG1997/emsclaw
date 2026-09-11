"""DeviceService — 设备业务规则层。

职责:
- ID 生成(DEV-<8hex upper>)
- 校验:设备类型枚举、IP 格式、协议白名单、重名校验
- 状态流转:create → offline;configure_network → pending_online
- 编排 mapper 完成持久化

不接触 HTTP、不写 SQL。mapper 可注入便于测试。
"""
from __future__ import annotations
import shortuuid
import time
from typing import Optional

from emsclaw_backend.db.models import Device
from emsclaw_backend.mapper.device_mapper import DeviceMapper

_DEVICE_TYPES = {"battery", "inverter", "meter", "pcs"}
_PROTOCOLS = {"ModbusTCP", "MQTT"}


def _now() -> int:
    return int(time.time())


def _validate_ip(ip: str) -> None:
    parts = ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        raise ValueError(f"非法 IP 地址: {ip}")


def _validate_device_type(device_type: str) -> None:
    if device_type not in _DEVICE_TYPES:
        raise ValueError(f"非法设备类型: {device_type}(允许 battery/inverter/meter/pcs)")


def _validate_protocol(protocol: str) -> None:
    if protocol not in _PROTOCOLS:
        raise ValueError(f"非法协议: {protocol}(允许 ModbusTCP/MQTT)")


class DeviceService:
    def __init__(self, mapper: Optional[DeviceMapper] = None):
        self._mapper = mapper or DeviceMapper()

    def create(self, name: str, device_type: str) -> Device:
        _validate_device_type(device_type)
        if self._mapper.find_by_name(name) is not None:
            raise ValueError(f"设备名称 '{name}' 已存在")
        now = _now()
        device = Device(
            id=f"DEV-{shortuuid.uuid()[:8].upper()}",
            name=name, device_type=device_type,
            status="offline", network_config={},
            created_at=now, updated_at=now,
        )
        return self._mapper.insert(device)

    def get(self, device_id: Optional[str] = None, name: Optional[str] = None) -> Optional[Device]:
        if not device_id and not name:
            raise ValueError("必须提供 device_id 或 name 之一")
        d = self._mapper.find_by_id(device_id) if device_id else None
        if d is None and name:
            d = self._mapper.find_by_name(name)
        return d

    def list(self, device_type: Optional[str] = None) -> list[Device]:
        if device_type:
            _validate_device_type(device_type)
        return self._mapper.find_all(device_type)

    def configure_network(self, device_id: str, ip_address: str,
                          protocol: str, port: Optional[int] = None) -> Device:
        if self._mapper.find_by_id(device_id) is None:
            raise ValueError(f"设备 '{device_id}' 不存在")
        _validate_ip(ip_address)
        _validate_protocol(protocol)
        network_config = {
            "ip_address": ip_address, "protocol": protocol,
            "configured_at": _now(),
        }
        if port is not None:
            network_config["port"] = port
        updated = self._mapper.update_network(device_id, network_config, "pending_online", _now())
        if updated is None:
            raise ValueError(f"设备 '{device_id}' 不存在")
        return updated