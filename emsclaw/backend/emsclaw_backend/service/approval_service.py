"""ApprovalService — 审批记录业务层。

职责:
- ID 生成(shortuuid)
- 分页查询编排 + 用户名反查(Option A:读时拼,不持久化)
- 决策更新(approve/reject/edit/respond)与状态流转

不接触 HTTP、不写 SQL。mapper 可注入便于测试。
"""
from __future__ import annotations
import shortuuid
import time
from typing import Optional

from emsclaw_backend.db.models import ApprovalRecord, User
from emsclaw_backend.entity.approval import ApprovalRecordDTO
from emsclaw_backend.mapper.approval_mapper import ApprovalMapper


def _now() -> int:
    return int(time.time())


class ApprovalService:
    def __init__(self, mapper: Optional[ApprovalMapper] = None):
        self._mapper = mapper or ApprovalMapper()

    def create_pending(
        self,
        *,
        session_id: str,
        thread_id: str,
        interrupt_id: str,
        tool_name: str,
        tool_args: dict,
        tool_call_id: Optional[str] = None,
        parent_agent: str,
        subagent_type: Optional[str],
        subagent_instance_id: Optional[str],
        initiator_user_id: str,
        original_request_message: str,
    ) -> ApprovalRecord:
        """runner yield approval_required 时调用,写一行 pending 记录。"""
        rec = ApprovalRecord(
            id=shortuuid.uuid(),
            session_id=session_id,
            thread_id=thread_id,
            interrupt_id=interrupt_id,
            tool_name=tool_name,
            tool_args=tool_args or {},
            tool_call_id=tool_call_id,
            parent_agent=parent_agent,
            subagent_type=subagent_type,
            subagent_instance_id=subagent_instance_id,
            initiator_user_id=initiator_user_id,
            original_request_message=original_request_message,
            auto=False,
            status="pending",
            created_at=_now(),
            decided_at=None,
        )
        return self._mapper.insert(rec)

    def mark_decided(
        self,
        interrupt_id: str,
        *,
        decision: str,
        approver_user_id: Optional[str],
        auto: bool = False,
    ) -> Optional[ApprovalRecord]:
        """resume / auto_approve 决策后更新记录。"""
        rec = self._mapper.find_by_interrupt(interrupt_id)
        if rec is None:
            return None
        rec.decision = decision
        rec.approver_user_id = approver_user_id
        rec.auto = auto
        rec.status = "auto_approved" if auto else "decided"
        rec.decided_at = _now()
        return self._mapper.update(rec)

    def attach_tool_result(
        self,
        interrupt_id: str,
        tool_result: str,
    ) -> Optional[ApprovalRecord]:
        """resume / auto_approve 后工具执行完成,把结果(出参)回填到记录。

        interrupt_id 关联:同一 interrupt 的 pending/decided 行,写 tool_result 字段。
        """
        rec = self._mapper.find_by_interrupt(interrupt_id)
        if rec is None:
            return None
        rec.tool_result = tool_result
        return self._mapper.update(rec)

    def list_approvals(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        initiator_user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> tuple[list[ApprovalRecordDTO], int]:
        rows, total = self._mapper.list_page(
            page=page,
            page_size=page_size,
            status=status,
            initiator_user_id=initiator_user_id,
            session_id=session_id,
        )
        if not rows:
            return [], total
        # Option A:批量反查用户名
        user_ids: set[str] = set()
        for r in rows:
            if r.initiator_user_id:
                user_ids.add(r.initiator_user_id)
            if r.approver_user_id:
                user_ids.add(r.approver_user_id)
        username_map = self._lookup_usernames(user_ids)
        dtos = [ApprovalRecordDTO.model_validate(r).model_copy(
            update={
                "initiator_username": username_map.get(r.initiator_user_id),
                "approver_username": username_map.get(r.approver_user_id) if r.approver_user_id else None,
            }
        ) for r in rows]
        return dtos, total

    def _lookup_usernames(self, user_ids: set[str]) -> dict[str, str]:
        """同步查 User 表,返回 {id: username}。"""
        if not user_ids:
            return {}
        from emsclaw_backend.db.session import SyncSessionLocal
        with SyncSessionLocal() as s:
            rows = (
                s.query(User.id, User.username)
                .filter(User.id.in_(list(user_ids)))
                .all()
            )
            return {uid: uname for uid, uname in rows}
