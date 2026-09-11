"""ApprovalController — 审批记录 HTTP 入口。

端点:
- GET /approvals                分页列表(可选 ?status=&initiator=&session_id=)
- GET /approvals/{record_id}    单条详情

调用 ApprovalService 完成业务逻辑;DTO 转换在 controller 边界完成。
"""
from __future__ import annotations
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from emsclaw_backend.entity.approval import ApprovalRecordDTO
from emsclaw_backend.service.approval_service import ApprovalService
from emsclaw_backend.user.dependencies import require_user, User

router = APIRouter(prefix="/approvals", tags=["approvals"])


class ApiResponse(BaseModel):
    code: int = Field(default=0)
    msg: str = Field(default="ok")
    data: Any = Field(default=None)


def _ok(data: Any, msg: str = "ok") -> ApiResponse:
    return ApiResponse(code=0, msg=msg, data=data)


@router.get("", response_model=ApiResponse, summary="分页查询审批记录")
async def list_approvals(
    page: int = Query(default=1, ge=1, description="页码,1-based"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    status_filter: Optional[str] = Query(default=None, alias="status",
                                         description="按状态过滤:pending/decided/auto_approved"),
    initiator: Optional[str] = Query(default=None, description="按发起人 user_id 过滤"),
    session_id: Optional[str] = Query(default=None, description="按会话 ID 过滤"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    """分页查询审批记录,按 created_at desc 排序。"""
    from emsclaw_backend.entity.approval import ApprovalStatus
    if status_filter and status_filter not in [s.value for s in ApprovalStatus]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"非法 status: {status_filter}(允许 pending/decided/auto_approved)",
        )
    items, total = ApprovalService().list_approvals(
        page=page,
        page_size=page_size,
        status=status_filter,
        initiator_user_id=initiator,
        session_id=session_id,
    )
    return _ok({
        "items": [i.model_dump() for i in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }, msg=f"共 {total} 条审批记录")


@router.get("/{record_id}", response_model=ApiResponse, summary="审批记录详情")
async def get_approval(
    record_id: str,
    _user: User = Depends(require_user),
) -> ApiResponse:
    """按 ID 查询单条审批记录。"""
    from emsclaw_backend.mapper.approval_mapper import ApprovalMapper
    rec = ApprovalMapper().find_by_id(record_id)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"审批记录 {record_id} 不存在")
    dto = ApprovalRecordDTO.model_validate(rec)
    # 反查用户名
    user_ids = {x for x in [rec.initiator_user_id, rec.approver_user_id] if x}
    if user_ids:
        from emsclaw_backend.db.session import SyncSessionLocal
        from emsclaw_backend.db.models import User
        with SyncSessionLocal() as s:
            rows = s.query(User.id, User.username).filter(User.id.in_(list(user_ids))).all()
            m = {uid: uname for uid, uname in rows}
            dto = dto.model_copy(update={
                "initiator_username": m.get(rec.initiator_user_id),
                "approver_username": m.get(rec.approver_user_id) if rec.approver_user_id else None,
            })
    return _ok(dto.model_dump())
