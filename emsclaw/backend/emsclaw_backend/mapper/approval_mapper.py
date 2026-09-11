"""ApprovalMapper — 审批记录表 ORM 持久化。

只负责 SQL/ORM 操作:insert / find_by_interrupt / update / list_page。
无业务规则(决策校验/ID 生成由 service 负责)。

每次开短 session(同步),与上层 service 解耦;service 可注入 session_factory 便于测试。
"""
from __future__ import annotations
from typing import Any, Optional

from emsclaw_backend.db.models import ApprovalRecord
from emsclaw_backend.db.session import SyncSessionLocal


class ApprovalMapper:
    def __init__(self, session_factory=None):
        self._sf = session_factory or SyncSessionLocal

    def insert(self, record: ApprovalRecord) -> ApprovalRecord:
        with self._sf() as s:
            s.add(record)
            s.commit()
            s.refresh(record)
            return record

    def find_by_interrupt(self, interrupt_id: str) -> Optional[ApprovalRecord]:
        with self._sf() as s:
            return (
                s.query(ApprovalRecord)
                .filter_by(interrupt_id=interrupt_id)
                .order_by(ApprovalRecord.created_at.desc())
                .first()
            )

    def find_by_id(self, record_id: str) -> Optional[ApprovalRecord]:
        with self._sf() as s:
            return s.get(ApprovalRecord, record_id)

    def update(self, record: ApprovalRecord) -> Optional[ApprovalRecord]:
        """合并 detached 实例并 commit。"""
        with self._sf() as s:
            merged = s.merge(record)
            s.commit()
            s.refresh(merged)
            return merged

    def list_page(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        initiator_user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> tuple[list[ApprovalRecord], int]:
        """分页 + 过滤,按 created_at desc。返回 (rows, total)。"""
        with self._sf() as s:
            q = s.query(ApprovalRecord)
            if status:
                q = q.filter(ApprovalRecord.status == status)
            if initiator_user_id:
                q = q.filter(ApprovalRecord.initiator_user_id == initiator_user_id)
            if session_id:
                q = q.filter(ApprovalRecord.session_id == session_id)
            total = q.count()
            rows = (
                q.order_by(ApprovalRecord.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return rows, total
