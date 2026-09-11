"""ScheduleMapper — ChargeSchedule ORM 持久化(同步)。

只负责 SQL/ORM 操作:insert / get_active / supersede_active / get_active_segment /
list_recent。无业务规则(调度优化求解/校验由 dispatch_planning 工具负责)。

每次开短 session(同步),与上层 service 解耦;session_factory 可注入便于测试。
同一 target_date 仅一条 status='active';下发时由 supersede_active 把旧 active
置 superseded,再 insert 新 active(调用方负责顺序)。
"""
from __future__ import annotations
from typing import Any, Optional

from sqlalchemy import and_

from emsclaw_backend.db.models import ChargeSchedule
from emsclaw_backend.db.session import SyncSessionLocal


class ScheduleMapper:
    def __init__(self, session_factory=None):
        self._sf = session_factory or SyncSessionLocal

    def insert(self, schedule: ChargeSchedule) -> ChargeSchedule:
        with self._sf() as s:
            s.add(schedule)
            s.commit()
            s.refresh(schedule)
            return schedule

    def get_active_schedule(self, target_date: str) -> Optional[ChargeSchedule]:
        with self._sf() as s:
            return (
                s.query(ChargeSchedule)
                .filter(and_(
                    ChargeSchedule.target_date == target_date,
                    ChargeSchedule.status == "active",
                ))
                .order_by(ChargeSchedule.updated_at.desc())
                .first()
            )

    def get_draft_or_active(self, target_date: str) -> Optional[ChargeSchedule]:
        """取该日最新一条 draft 或 active(供状态查询/继续编辑)。"""
        with self._sf() as s:
            return (
                s.query(ChargeSchedule)
                .filter(and_(
                    ChargeSchedule.target_date == target_date,
                    ChargeSchedule.status.in_(["draft", "active"]),
                ))
                .order_by(ChargeSchedule.updated_at.desc())
                .first()
            )

    def supersede_active(self, target_date: str, now_ts: int) -> int:
        """把该日所有 active 计划置 superseded。返回受影响行数。"""
        with self._sf() as s:
            rows = (
                s.query(ChargeSchedule)
                .filter(and_(
                    ChargeSchedule.target_date == target_date,
                    ChargeSchedule.status == "active",
                ))
                .all()
            )
            for r in rows:
                r.status = "superseded"
                r.updated_at = now_ts
            s.commit()
            return len(rows)

    def activate(self, schedule_id: str, target_date: str, now_ts: int) -> Optional[ChargeSchedule]:
        """原子地把旧 active→superseded,再把指定 draft→active。"""
        with self._sf() as s:
            olds = (
                s.query(ChargeSchedule)
                .filter(and_(
                    ChargeSchedule.target_date == target_date,
                    ChargeSchedule.status == "active",
                ))
                .all()
            )
            for r in olds:
                r.status = "superseded"
                r.updated_at = now_ts
            target = s.get(ChargeSchedule, schedule_id)
            if target is None:
                s.commit()
                return None
            target.status = "active"
            target.updated_at = now_ts
            s.commit()
            s.refresh(target)
            return target

    def get_active_segment(self, target_date: str, hour: int) -> Optional[dict[str, Any]]:
        """读该日 active 计划中 hour 对应的 DispatchInterval;无计划返回 None。"""
        sched = self.get_active_schedule(target_date)
        if sched is None or not sched.intervals:
            return None
        for seg in sched.intervals:
            if seg.get("hour") == hour:
                return seg
        return None

    def get_by_id(self, schedule_id: str) -> Optional[ChargeSchedule]:
        with self._sf() as s:
            return s.get(ChargeSchedule, schedule_id)

    def list_recent(self, days: int = 7) -> list[ChargeSchedule]:
        with self._sf() as s:
            return (
                s.query(ChargeSchedule)
                .order_by(ChargeSchedule.created_at.desc())
                .limit(days)
                .all()
            )
