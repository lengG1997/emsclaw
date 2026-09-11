"""C5:Approval resume + auto_approve_all 路由。

从 route/sessions.py 拆出。路由路径保持 /sessions/{id}/approvals/... 不变。
AG3NT deepagents_daemon.py:543-572,568-570,821-831 是 resume / inline interrupt /
auto_approve 模式切换的范本;emsclaw 把决策状态持久化到 session.events JSONB,
把 auto_approve flag 持久化到 session.model_config JSONB(AG3NT 是内存 only 会丢)。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, Depends
from loguru import logger
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from langgraph.types import Command as _ResumeCommand

from emsclaw_backend.deepagent.sessions import (
    AgentSessionNotFoundError,
    async_get_agent_session,
)
from emsclaw_backend.user.dependencies import require_user, User

from ._common import (
    ApiResponse,
    SessionStatus,
    _now_ts,
    _new_event_id,
    _wrap_event,
    _append_session_event,
    _json_dumps,
)
from ._worker import _agent_tasks, _agent_queues, _agent_background_worker

router = APIRouter(prefix="/sessions", tags=["approvals"])


class ApprovalRequest(BaseModel):
    decision: str = Field(..., description="审批决策:approve|reject|edit|respond")
    edit_payload: Optional[Dict[str, Any]] = Field(
        default=None,
        description="decision=edit 时必填,覆盖工具调用的 args",
    )


@router.post("/{session_id}/approvals/{interrupt_id}")
async def resume_session(
    session_id: str,
    interrupt_id: str,
    body: ApprovalRequest,
    request: Request,
    current_user: User = Depends(require_user),
) -> EventSourceResponse:
    """C5:审批 resume — 用户对 pending approval 给决策,触发 resume worker 继续 stream。

    流程:
      1. 载入 session,验 ownership
      2. 从 session.events JSONB 找对应 interrupt_id 的 approval_required 事件
      3. 对每个 action_request 一个决策(AG3NT deepagents_daemon.py:568-570),
         合成 Command(resume={interrupt_id: {"decisions": decisions}})
      4. 持久化 approval_decided(非 auto)→ session.status=RUNNING → save
      5. 启动 _agent_background_worker(resume_command=...),复用 SSE queue
      6. 返回 EventSourceResponse 流剩余事件
    """
    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if body.decision not in ("approve", "reject", "edit", "respond"):
        raise HTTPException(
            status_code=400,
            detail=f"非法的决策: {body.decision};应为 approve|reject|edit|respond",
        )
    if body.decision == "edit" and body.edit_payload is None:
        raise HTTPException(
            status_code=400,
            detail="decision=edit 时必须提供 edit_payload",
        )

    # 找 pending approval_required 事件
    approval_event = None
    for ev in getattr(session, "events", None) or []:
        if ev.get("event") != "approval":
            continue
        d = ev.get("data") or {}
        if d.get("kind") == "required" and str(d.get("interrupt_id") or "") == interrupt_id:
            approval_event = ev
            break
    if approval_event is None:
        raise HTTPException(
            status_code=404,
            detail=f"没有 interrupt_id={interrupt_id} 对应的待审批项",
        )

    # 对每个 action_request 一个决策(AG3NT 568-570)
    action_reqs = (approval_event.get("data") or {}).get("action_requests") or []
    if body.decision == "edit" and body.edit_payload is not None:
        decisions = [{"type": "edit", "args": body.edit_payload} for _ in action_reqs]
    else:
        decisions = [{"type": body.decision} for _ in action_reqs]
    if not decisions:
        decisions = [{"type": body.decision}]

    resume_command = _ResumeCommand(resume={interrupt_id: {"decisions": decisions}})

    # 已有 worker 在跑 → 拒绝(审批流是顺序的)
    existing = _agent_tasks.get(session_id)
    if existing is not None and not existing.done():
        raise HTTPException(status_code=409, detail="该会话已有正在运行的任务")

    # 持久化 approval_decided 非 auto — 前端回放能看到 decided 先于后续事件
    decided_event = _wrap_event("approval", {
        "event_id": _new_event_id(),
        "timestamp": _now_ts(),
        "kind": "decided",
        "interrupt_id": interrupt_id,
        "decision": body.decision,
        "auto": False,
    })
    _append_session_event(session, decided_event)
    # 更新 ApprovalRecord 行:写 approver_user_id / decision / decided_at / status=decided
    try:
        from emsclaw_backend.service.approval_service import ApprovalService
        ApprovalService().mark_decided(
            interrupt_id,
            decision=body.decision,
            approver_user_id=current_user.id,
            auto=False,
        )
    except Exception as exc:
        logger.warning(f"[ApprovalRecord] update on resume failed interrupt={interrupt_id}: {exc!r}")
    setattr(session, "status", SessionStatus.RUNNING)
    await session.save()

    logger.info(
        f"[Resume] session={session_id} interrupt_id={interrupt_id} decision={body.decision}"
    )

    # 建 SSE queue + 启动 resume worker
    queue: "asyncio.Queue[Optional[Dict[str, str]]]" = asyncio.Queue()
    _agent_queues[session_id] = queue

    task = asyncio.create_task(
        _agent_background_worker(
            session, session_id,
            message="", attachments=[],
            resume_command=resume_command,
        )
    )
    _agent_tasks[session_id] = task

    async def event_generator():
        try:
            while True:
                evt = await queue.get()
                if evt is None:
                    break
                yield evt
        finally:
            _agent_tasks.pop(session_id, None)
            _agent_queues.pop(session_id, None)

    return EventSourceResponse(event_generator())


@router.post("/{session_id}/approvals/auto_approve_all", response_model=ApiResponse)
async def set_auto_approve_all(
    session_id: str,
    resume: bool = True,
    current_user: User = Depends(require_user),
) -> ApiResponse:
    """C5:开启 auto_approve_all — 后续 pending interrupts 自动 approve。

    AG3NT deepagents_daemon.py:821-831:auto_approve 模式切换;AG3NT 是内存 only 会丢,
    emsclaw 持久化到 session.model_config["auto_approve"] JSONB,跨重启保留。

    若当前有 pending approval 且无 worker 在跑,直接触发 resume worker(approve),
    无需用户再点 — 参考 AG3NT daemon 流程。若 worker 在跑,runner B4 会自动处理
    后续 interrupts。
    """
    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    mc = getattr(session, "model_config", None) or {}
    if not isinstance(mc, dict):
        mc = {}
    mc["auto_approve"] = True
    setattr(session, "model_config", mc)
    await session.save()
    logger.info(f"[AutoApprove] session={session_id} auto_approve persisted to JSONB")

    # 发 auto_approve_set SSE(若有 live queue 推到客户端;同时持久化让回放可见)
    auto_event = _wrap_event("approval", {
        "event_id": _new_event_id(),
        "timestamp": _now_ts(),
        "kind": "auto_approve_set",
        "enabled": True,
    })
    _append_session_event(session, auto_event)
    await session.save()

    q = _agent_queues.get(session_id)
    if q is not None:
        try:
            q.put_nowait({"event": auto_event["event"], "data": _json_dumps(auto_event["data"])})
        except Exception:
            pass

    # 若已有 worker 在跑,runner B4 会自动处理后续 interrupts — 无需手动 trigger
    # resume=False(SSE 客户端):只设 flag + 发 auto_approve_set,前端自己用
    # POST /approvals/{interrupt_id} SSE 驱动 resume(有消费者);此处起 worker 会推到
    # 无消费者的 _agent_queues(原 chat SSE 已关闭)-> 事件只落库不 live。
    if not resume:
        return ApiResponse(data={"ok": True, "auto_approve": True, "resume_triggered": False})

    existing = _agent_tasks.get(session_id)
    if existing is not None and not existing.done():
        return ApiResponse(data={"ok": True, "auto_approve": True, "resume_triggered": False})

    # 找一个 pending interrupt_id(未被 decided 的 approval_required)
    pending_intr_id = None
    evs = list(getattr(session, "events", None) or [])
    decided_ids = {
        str((ev.get("data") or {}).get("interrupt_id") or "")
        for ev in evs
        if ev.get("event") == "approval"
        and (ev.get("data") or {}).get("kind") == "decided"
    }
    for ev in evs:
        if ev.get("event") != "approval":
            continue
        d = ev.get("data") or {}
        if d.get("kind") != "required":
            continue
        iid = str(d.get("interrupt_id") or "")
        if iid and iid not in decided_ids:
            pending_intr_id = iid
            break

    if pending_intr_id is None:
        return ApiResponse(data={"ok": True, "auto_approve": True, "resume_triggered": False})

    # 持久化 approval_decided(auto=True) → trigger resume worker(approve)
    decided_event = _wrap_event("approval", {
        "event_id": _new_event_id(),
        "timestamp": _now_ts(),
        "kind": "decided",
        "interrupt_id": pending_intr_id,
        "decision": "approve",
        "auto": True,
    })
    _append_session_event(session, decided_event)
    setattr(session, "status", SessionStatus.RUNNING)
    await session.save()

    resume_command = _ResumeCommand(resume={
        pending_intr_id: {"decisions": [{"type": "approve"}]},
    })

    queue: "asyncio.Queue[Optional[Dict[str, str]]]" = asyncio.Queue()
    _agent_queues[session_id] = queue

    asyncio.create_task(
        _agent_background_worker(
            session, session_id,
            message="", attachments=[],
            resume_command=resume_command,
        )
    )

    logger.info(
        f"[AutoApprove] session={session_id} auto-triggered resume for interrupt_id={pending_intr_id}"
    )
    return ApiResponse(data={"ok": True, "auto_approve": True, "resume_triggered": True})
