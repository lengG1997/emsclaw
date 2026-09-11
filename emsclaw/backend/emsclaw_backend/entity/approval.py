"""Approval Entity — 审批记录数据契约(全局 DTO,跨域共享)。

枚举为权威来源:
- ApprovalDecision:approve/reject/edit/respond(对齐 sessions.py ApprovalRequest)
- ApprovalStatus:pending/decided/auto_approved

前端 TS 类型与后端共用。
"""
from __future__ import annotations
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ApprovalDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"
    RESPOND = "respond"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    DECIDED = "decided"
    AUTO_APPROVED = "auto_approved"


class ApprovalActionRequestDTO(BaseModel):
    """单个工具调用请求(对齐 AG3NT HITL schema action_requests[0])。"""
    name: str
    args: dict = Field(default_factory=dict)
    description: Optional[str] = None


class ApprovalRecordDTO(BaseModel):
    """审批记录 DTO — ORM ApprovalRecord ↔ API/前端通用契约。"""
    model_config = ConfigDict(from_attributes=True)
    id: str
    session_id: str
    thread_id: str = ""
    interrupt_id: str
    tool_name: str = ""
    tool_args: dict = Field(default_factory=dict)
    tool_call_id: Optional[str] = None
    tool_result: Optional[str] = None
    parent_agent: str = "Lead"
    subagent_type: Optional[str] = None
    subagent_instance_id: Optional[str] = None
    initiator_user_id: str = ""
    approver_user_id: Optional[str] = None
    decision: Optional[str] = None
    original_request_message: str = ""
    auto: bool = False
    status: str = "pending"
    created_at: int = 0
    decided_at: Optional[int] = None
    # 读时拼装(不持久化)
    initiator_username: Optional[str] = None
    approver_username: Optional[str] = None
