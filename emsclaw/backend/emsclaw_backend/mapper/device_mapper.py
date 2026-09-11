"""DeviceMapper — 设备表 ORM 持久化。

只负责 SQL/ORM 操作:insert / find_by_id / find_by_name / find_all / update_network。
无业务规则(校验/ID 生成/状态流转由 device_service 负责)。

每次开短 session(同步),与上层 service 解耦;service 可注入 session_factory 便于测试。
"""
from __future__ import annotations
from typing import Optional

from emsclaw_backend.db.models import Device
from emsclaw_backend.db.session import SyncSessionLocal


class DeviceMapper:
    def __init__(self, session_factory=None):
        self._sf = session_factory or SyncSessionLocal

    def insert(self, device: Device) -> Device:
        with self._sf() as s:
            s.add(device)
            s.commit()
            s.refresh(device)
            return device

    def find_by_id(self, device_id: str) -> Optional[Device]:
        with self._sf() as s:
            return s.get(Device, device_id)

    def find_by_name(self, name: str) -> Optional[Device]:
        with self._sf() as s:
            return s.query(Device).filter_by(name=name).first()

    def find_all(self, device_type: Optional[str] = None) -> list[Device]:
        with self._sf() as s:
            q = s.query(Device)
            if device_type:
                q = q.filter_by(device_type=device_type)
            return q.all()

    def delete(self, device_id: str) -> bool:
        with self._sf() as s:
            d = s.get(Device, device_id)
            if d is None:
                return False
            s.delete(d)
            s.commit()
            return True

    def purge_offline(self) -> int:
        """删除所有 status=offline 的设备(seed 建的设备均为 online,不会被删)。

        用于启动期清理历史测试残留的孤立设备,使总览设备清单干净。
        返回删除条数。
        """
        with self._sf() as s:
            rows = s.query(Device).filter_by(status="offline").all()
            for r in rows:
                s.delete(r)
            s.commit()
            return len(rows)

    def update_network(self, device_id: str, network_config: dict,
                       status: str, updated_at: int) -> Optional[Device]:
        with self._sf() as s:
            d = s.get(Device, device_id)
            if d is None:
                return None
            d.network_config = network_config
            d.status = status
            d.updated_at = updated_at
            s.commit()
            s.refresh(d)
            return d