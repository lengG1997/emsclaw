"""device_operation.schemas - 设备领域 schemas(向后兼容 re-export)。

权威定义在 emsclaw_backend.entity.device;这里只 re-export,保持工具 import 路径可用。
"""
from emsclaw_backend.entity.device import (
    DeviceType,
    DeviceStatus,
    NetworkConfig,
    DeviceDTO,
)

__all__ = ["DeviceType", "DeviceStatus", "NetworkConfig", "DeviceDTO"]
