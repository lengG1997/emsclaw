"""sessions 域后台 Agent worker：SSE 队列共享态 + background worker + 步骤 helper。

被 sessions.py（chat 端点）与 approvals.py（resume 端点）共用，避免两者互相循环 import。
纯事件编排逻辑放在 _common.py，本模块只做后台任务编排与状态机。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path as _Path
from typing import Any, Dict, List, Optional

from loguru import logger

from langgraph.types import Command as _ResumeCommand

from emsclaw_backend.deepagent.runner import arun_agent_task_stream
from emsclaw_backend.deepagent.sessions import AgentSession
from emsclaw_backend.db.session import AsyncSessionLocal
from emsclaw_backend.db.models import Session as SessionRow
from emsclaw_backend.entity.enums import (
    EventType,
    ApprovalEventKind,
    ToolEventStatus,
    MID_STREAM_SAVE_EVENTS,
)
from sqlalchemy import select, or_, func

import shortuuid

from ._common import (
    SessionStatus,
    _EXTERNAL_SKILLS_DIR,
    _WORKSPACE_DIR,
    _now_ts,
    _new_event_id,
    _wrap_event,
    _json_dumps,
    _append_session_event,
    _count_user_messages,
    _generate_session_title,
    _map_agent_stream_to_agent_event,
    _persist_approval_record,
    _snapshot_workspace_files,
    _diff_workspace_files,
)


# ═══════════════════════════════════════════════════════════════════
# SSE 队列 / 后台任务共享态（chat 与 approval-resume 共用）
# ═══════════════════════════════════════════════════════════════════

_agent_tasks: "Dict[str, asyncio.Task[None]]" = {}
_agent_queues: "Dict[str, asyncio.Queue[Optional[Dict[str, str]]]]" = {}


async def cleanup_orphaned_sessions() -> int:
    """启动时把孤儿会话标记为已完成。

    在 lifespan 启动阶段调用 —— 进程重启后,任何 RUNNING 的会话,或带有事件的
    PENDING 会话,都一定是孤儿(因进程被重启过)。全新的 PENDING 会话(无事件)
    保持原样不动。
    """
    now = _now_ts()
    async with AsyncSessionLocal() as s:
        # 匹配 RUNNING 会话,或带非空 events 数组的 PENDING 会话。
        q = select(SessionRow).where(
            or_(
                SessionRow.status == SessionStatus.RUNNING,
                (SessionRow.status == SessionStatus.PENDING)
                & (func.jsonb_array_length(SessionRow.events) > 0),
            )
        )
        rows = (await s.execute(q)).scalars().all()
        modified = 0
        for row in rows:
            done_event = {
                "event": "done",
                "data": {
                    "event_id": shortuuid.uuid(),
                    "timestamp": now,
                    "statistics": {},
                    "interrupted": True,
                },
            }
            ev = list(row.events or [])
            ev.append(done_event)
            row.events = ev  # 必须整体重新赋值 list,否则 JSONB 变更不生效
            row.status = SessionStatus.COMPLETED
            row.updated_at = now
            modified += 1
        if modified:
            await s.commit()
            logger.info(
                f"[Startup] Cleaned up {modified} orphaned session(s) "
                "(running/pending → completed)"
            )
    return modified


async def graceful_shutdown_agents() -> None:
    """取消每个运行中的 agent 任务,并批量更新数据库状态。

    在 lifespan 关闭阶段调用,确保正常重启不会在数据库中留下孤儿会话。
    """
    tasks_to_cancel = [
        (sid, t) for sid, t in list(_agent_tasks.items()) if not t.done()
    ]
    for sid, task in tasks_to_cancel:
        task.cancel()
    for sid, task in tasks_to_cancel:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    _agent_tasks.clear()
    _agent_queues.clear()

    now = _now_ts()
    async with AsyncSessionLocal() as s:
        q = select(SessionRow).where(
            SessionRow.status.in_([SessionStatus.RUNNING, SessionStatus.PENDING])
        )
        rows = (await s.execute(q)).scalars().all()
        orphaned = 0
        for row in rows:
            done_event = {
                "event": "done",
                "data": {
                    "event_id": shortuuid.uuid(),
                    "timestamp": now,
                    "statistics": {},
                    "interrupted": True,
                },
            }
            ev = list(row.events or [])
            ev.append(done_event)
            row.events = ev  # 必须整体重新赋值 list,否则 JSONB 变更不生效
            row.status = SessionStatus.COMPLETED
            row.updated_at = now
            orphaned += 1
        if orphaned:
            await s.commit()
    cancelled = len(tasks_to_cancel)
    if cancelled or orphaned:
        logger.info(
            f"[Shutdown] Cancelled {cancelled} agent task(s), "
            f"cleaned up {orphaned} orphaned session(s)"
        )


def _emit_to_sse(session_id: str, event: Dict[str, str]) -> None:
    """把一个 SSE 事件字典推送到活跃队列（若有客户端已连接）。"""
    q = _agent_queues.get(session_id)
    if q is not None:
        try:
            q.put_nowait(event)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# 后台 worker
# ═══════════════════════════════════════════════════════════════════

async def _agent_background_worker(
    session: AgentSession,
    session_id: str,
    message: str,
    attachments: List[str],
    event_id: Optional[str] = None,
    timestamp: Optional[int] = None,
    language: Optional[str] = None,
    resume_command: Optional[_ResumeCommand] = None,
) -> None:
    """在后台任务中运行 agent。结果保存到数据库并推送到 SSE。

    当 `resume_command` 被设置时（审批-resume 路径），worker 跳过标题生成与
    用户事件回显，直接调 `arun_agent_task_stream` 传 resume_command ——
    runner 会跳过 history build，走 Command(resume=...) 流。

    本函数只做编排，各步骤实现在下方独立 helper 中，便于单测与复用。
    """
    from emsclaw_backend.notifications import publish as _notify

    user_attachments = attachments or []
    ctx = _WorkerCtx(
        session=session, session_id=session_id,
        is_im=session.source in ("wechat", "lark"),
        im_user_id=session.user_id,
        notify=_notify,
    )

    # 1) 回显用户消息（resume 路径跳过 —— 前一轮已走完用户输入）
    if resume_command is None and message.strip():
        await _echo_user_message(ctx, message, user_attachments, event_id, timestamp)

    # 2) 标记 RUNNING + 工作区快照（用于轮次级文件追踪）
    session.reset_cancel()
    session.status = SessionStatus.RUNNING
    await session.save()
    pre_file_snapshot = _snapshot_workspace_files(session.vm_root_dir)

    statistics: Dict[str, Any] = {}
    chunk_buffer: List[str] = []
    # approval/tool 出参回填状态机：记录待回填 tool_result 的 interrupt_id
    capture_interrupt_id = _init_capture_interrupt_id(resume_command)

    try:
        # 3) 首条用户消息后生成标题（resume 路径不做）
        if message.strip() and not (session.title or "").strip():
            events = session.events or []
            if _count_user_messages(events) <= 1:
                await _maybe_generate_title(ctx, message)

        # 4) 消费 agent 事件流
        async for evt in arun_agent_task_stream(
            session=session, query=message or "", attachments=user_attachments,
            language=language, resume_command=resume_command,
        ):
            if session.is_cancelled():
                ctx.emit(EventType.ERROR, {
                    "event_id": _new_event_id(), "timestamp": _now_ts(),
                    "error": "会话已被用户停止",
                })
                return

            mapped = _map_agent_stream_to_agent_event(evt)
            if mapped is None:
                continue

            evt_name = mapped.get("event")
            data = mapped.get("data") or {}

            if evt_name == EventType.STATISTICS.value:
                statistics = data
                continue

            if evt_name == EventType.MESSAGE_CHUNK.value:
                chunk_buffer.append(data.get("content", ""))
                ctx.emit_raw(evt_name, _json_dumps(data))
                continue

            if evt_name == EventType.MESSAGE_CHUNK_DONE.value:
                _flush_chunks(ctx, chunk_buffer)
                ctx.emit_raw(evt_name, _json_dumps(data))
                continue

            _append_session_event(session, mapped)
            # 关键事件（approval/tool 等）中途立即落库：approval_required 是
            # stream 终止事件，不立即持久化则 resume endpoint 读不到、跨重启
            # 无法重建 pending 状态。子 agent 事件不在此列，由 finally 兜底。
            if evt_name in MID_STREAM_SAVE_EVENTS:
                await session.save()

            capture_interrupt_id = _handle_approval_and_tool(
                ctx, mapped, capture_interrupt_id,
            )
            ctx.emit_raw(evt_name, _json_dumps(data))

    except Exception as exc:
        logger.exception(f"[AgentWorker] session={session_id} failed")
        error_event = _wrap_event(EventType.ERROR.value, {
            "event_id": _new_event_id(), "timestamp": _now_ts(), "error": str(exc),
        })
        _append_session_event(session, error_event)
        ctx.emit_raw(error_event["event"], _json_dumps(error_event["data"]))

    finally:
        _flush_chunks(ctx, chunk_buffer)
        # 兜底:若有 ok 求解 artifact 且最终 assistant 消息无
        # <dispatch_preview> 块 → 后端确定性追加该块(用 artifact 原文,非 LLM 生成)
        # 只要 optimize_dispatch 返回 ok,前端必然收到图表数据
        await _maybe_append_dispatch_block(ctx)
        # status guard：stream 若终止于未决的 approval_required，必须标
        # AWAITING_APPROVAL 而非 COMPLETED（否则前端误判任务完成，
        # cleanup_orphaned_sessions 也会误标 interrupted）。
        if _has_pending_approval(session):
            session.status = SessionStatus.AWAITING_APPROVAL
        else:
            session.status = SessionStatus.COMPLETED

        _detect_new_skills(ctx)
        round_files = _compute_round_files(session, pre_file_snapshot, session_id)

        done_event = _wrap_event(EventType.DONE.value, {
            "event_id": _new_event_id(),
            "timestamp": _now_ts(),
            "statistics": statistics,
            "round_files": round_files,
        })
        _append_session_event(session, done_event)
        await session.save()
        ctx.emit_raw(done_event["event"], _json_dumps(done_event["data"]))

        # 通知 SSE 流已完成 + 清理本会话的 task/queue 注册
        q = _agent_queues.get(session_id)
        if q is not None:
            try:
                q.put_nowait(None)
            except Exception:
                pass
        _agent_tasks.pop(session_id, None)
        _agent_queues.pop(session_id, None)
        logger.info(f"[AgentWorker] session={session_id} completed")


# ───────────────────────────────────────────────────────────────────
# _agent_background_worker 的各步骤 helper
# ───────────────────────────────────────────────────────────────────

class _WorkerCtx:
    """worker 贯穿参数的轻量容器，避免把 session_id/is_im/notify 反复传参。"""

    __slots__ = ("session", "session_id", "is_im", "im_user_id", "notify")

    def __init__(self, session: AgentSession, session_id: str, is_im: bool,
                 im_user_id: Optional[str], notify: Any) -> None:
        self.session = session
        self.session_id = session_id
        self.is_im = is_im
        self.im_user_id = im_user_id
        self.notify = notify

    def emit(self, evt: EventType, data: Dict[str, Any]) -> None:
        """推送一个事件到 SSE（+ IM 镜像），data 接受原始 dict。"""
        self.emit_raw(evt.value, _json_dumps(data))

    def emit_raw(self, evt_name: str, data_json: str) -> None:
        """推送已序列化的事件（避免在 message_chunk 高频路径重复 dumps）。"""
        _emit_to_sse(self.session_id, {"event": evt_name, "data": data_json})
        if self.is_im and self.im_user_id:
            self.notify("session_updated", {
                "session_id": self.session_id,
                "user_id": self.im_user_id,
                "session_event": {"event": evt_name, "data": json.loads(data_json)},
            })


async def _echo_user_message(
    ctx: _WorkerCtx, message: str, attachments: List[str],
    event_id: Optional[str], timestamp: Optional[int],
) -> None:
    """回显用户消息：落库 + 推 SSE/IM。"""
    user_event = _wrap_event(EventType.MESSAGE.value, {
        "event_id": event_id or _new_event_id(),
        "timestamp": timestamp or _now_ts(),
        "content": message,
        "role": "user",
        "attachments": attachments,
    })
    _append_session_event(ctx.session, user_event)
    await ctx.session.save()
    if ctx.is_im and ctx.im_user_id:
        ctx.notify("session_updated", {
            "session_id": ctx.session_id,
            "user_id": ctx.im_user_id,
            "session_event": user_event,
        })


async def _maybe_generate_title(ctx: _WorkerCtx, message: str) -> None:
    """首条用户消息后生成会话标题并广播 title 事件。失败仅告警不中断。"""
    try:
        gen_title = await _generate_session_title(message)
        if gen_title:
            ctx.session.title = gen_title
            await ctx.session.save()
            ctx.emit(EventType.TITLE, {
                "event_id": _new_event_id(),
                "timestamp": _now_ts(),
                "title": gen_title,
            })
    except Exception as exc:
        logger.warning("Title generation failed: %s", exc)


def _init_capture_interrupt_id(
    resume_command: Optional[_ResumeCommand],
) -> Optional[str]:
    """resume 路径：从 resume_command 取被审批的 interrupt_id，用于后续
    首个 tool_result 回填 ApprovalRecord.tool_result。auto_approve 路径
    在收到 approval_decided(auto) 时由 _handle_approval_and_tool 记录。"""
    if resume_command is None:
        return None
    rc_resume = getattr(resume_command, "resume", None)
    if isinstance(rc_resume, dict) and rc_resume:
        return next(iter(rc_resume.keys()), None)
    return None


def _handle_approval_and_tool(
    ctx: _WorkerCtx, mapped: Dict[str, Any],
    capture_interrupt_id: Optional[str],
) -> Optional[str]:
    """处理 approval / tool 事件的审批记录持久化与出参回填状态机。

    - approval(required)  → 新建 pending 行，清空旧捕获上下文
    - approval(decided,auto) → 更新为 auto_approved，记录 interrupt_id 等回填
    - tool(called) + 待回填 interrupt_id → 把出参写回 ApprovalRecord，单次即清空
    手动 resume 的 approval_decided 由 resume endpoint 处理（那里有 current_user）。
    返回（可能更新后的）capture_interrupt_id。
    """
    evt_name = mapped.get("event")
    session = ctx.session

    if evt_name == EventType.APPROVAL.value:
        _persist_approval_record(session, mapped)
        ad = mapped.get("data") or {}
        kind = ad.get("kind")
        if kind == ApprovalEventKind.DECIDED.value and ad.get("auto"):
            # auto_approve 内联触发：记录 interrupt_id，等后续 tool_result 回填出参
            return ad.get("interrupt_id") or capture_interrupt_id
        if kind == ApprovalEventKind.REQUIRED.value:
            # 新 pending 审批出现，清空旧捕获上下文
            return None
        return capture_interrupt_id

    if evt_name == EventType.TOOL.value and capture_interrupt_id:
        td = mapped.get("data") or {}
        if td.get("status") == ToolEventStatus.CALLED.value:
            result_txt = td.get("content")
            try:
                from emsclaw_backend.service.approval_service import ApprovalService
                ApprovalService().attach_tool_result(
                    str(capture_interrupt_id),
                    result_txt if isinstance(result_txt, str) else str(result_txt),
                )
            except Exception as ae:
                logger.warning(
                    f"[ApprovalRecord] attach_tool_result failed "
                    f"interrupt={capture_interrupt_id}: {ae!r}"
                )
            return None  # 单 interrupt 单工具，捕获后清空

    return capture_interrupt_id


def _flush_chunks(ctx: _WorkerCtx, chunk_buffer: List[str]) -> None:
    """把已累积的流式文本片段落库为一条 assistant message 并清空缓冲。"""
    if not chunk_buffer:
        return
    full_content = "".join(chunk_buffer)
    persist_event = _wrap_event(EventType.MESSAGE.value, {
        "event_id": _new_event_id(), "timestamp": _now_ts(),
        "content": full_content, "role": "assistant", "attachments": [],
    })
    _append_session_event(ctx.session, persist_event)
    chunk_buffer.clear()


async def _maybe_append_dispatch_block(ctx: _WorkerCtx) -> None:
    """兜底:若有 ok 求解 artifact 且最终 assistant 消息无调度预览块
    → 后端确定性追加(用 artifact 原文,非 LLM 生成)。

    契约:只要 optimize_dispatch 返回 status=ok,前端必然收到图表数据。
    - 单方案 → <dispatch_preview> 块
    - 多方案(同一轮多次 ok 调用,用户偏好"多方案比对") → <dispatch_plans> 数组块
    LLM 已手写块时(虽 SKILL v2 不要求)不重复追加。
    """
    try:
        from emsclaw_backend.service import dispatch_artifact
        plans = dispatch_artifact.get_all(ctx.session_id)
        if not plans:
            return
        # 扫本会话所有 assistant message,看是否已有块
        existing_text = ""
        for ev in (ctx.session.events or []):
            if ev.get("event") != EventType.MESSAGE.value:
                continue
            data = ev.get("data") or {}
            if data.get("role") == "assistant":
                existing_text += str(data.get("content") or "")
        if dispatch_artifact.has_block_in_text(existing_text):
            return  # LLM 已手写块,不重复
        # 追加补块 message(SSE + 落库)
        if len(plans) >= 2:
            block_text = dispatch_artifact.render_plans_block(plans)
        else:
            block_text = dispatch_artifact.render_markdown_block(plans[0])
        block_event = _wrap_event(EventType.MESSAGE.value, {
            "event_id": _new_event_id(), "timestamp": _now_ts(),
            "content": block_text, "role": "assistant",
            "attachments": [], "_dispatch_block": True,  # 标记:后端确定性补块
        })
        _append_session_event(ctx.session, block_event)
        # SSE 用 message_chunk + message_chunk_done 流式发(前端按现有逻辑渲染)
        chunk_evt = _wrap_event(EventType.MESSAGE_CHUNK.value, {
            "event_id": _new_event_id(), "timestamp": _now_ts(),
            "content": block_text,
        })
        ctx.emit_raw(chunk_evt["event"], _json_dumps(chunk_evt["data"]))
        done_evt = _wrap_event(EventType.MESSAGE_CHUNK_DONE.value, {
            "event_id": _new_event_id(), "timestamp": _now_ts(),
        })
        ctx.emit_raw(done_evt["event"], _json_dumps(done_evt["data"]))
        # 清理本会话 artifact(已兜底完,避免内存泄漏)
        dispatch_artifact.clear(ctx.session_id)
    except Exception:
        logger.exception(f"[DispatchBlock] session={ctx.session_id} append failed")


def _has_pending_approval(session: AgentSession) -> bool:
    """扫 session.events：是否存在 approval(required) 但无对应
    approval(decided) 的 interrupt_id（即仍有未决审批）。扫描失败按无 pending 处理。"""
    try:
        evs = session.events or []
        decided_intr_ids = {
            str((ev.get("data") or {}).get("interrupt_id") or "")
            for ev in evs
            if ev.get("event") == EventType.APPROVAL.value
            and (ev.get("data") or {}).get("kind") == ApprovalEventKind.DECIDED.value
        }
        for ev in evs:
            if (ev.get("event") == EventType.APPROVAL.value
                    and (ev.get("data") or {}).get("kind") == ApprovalEventKind.REQUIRED.value):
                iid = str((ev.get("data") or {}).get("interrupt_id") or "")
                if iid and iid not in decided_intr_ids:
                    return True
    except Exception:
        logger.debug("[AgentWorker] pending approval scan failed", exc_info=True)
    return False


# 会话级 skills/tools 候选目录（相对 _WORKSPACE_DIR/<session_id>）
_SESSION_SKILL_SUBDIRS = (".agents/skills", "skills")


def _detect_new_skills(ctx: _WorkerCtx) -> None:
    """扫描工作区发现新 skill（含 SKILL.md 且未保存），逐个发 skill_save_prompt。"""
    try:
        saved_skills = {
            d.name for d in _Path(_EXTERNAL_SKILLS_DIR).iterdir()
            if d.is_dir() and not d.name.startswith(".")
        } if _Path(_EXTERNAL_SKILLS_DIR).is_dir() else set()
        detected: set = set()
        for sub in _SESSION_SKILL_SUBDIRS:
            skills_dir = _Path(_WORKSPACE_DIR) / ctx.session_id / sub
            if not skills_dir.is_dir():
                continue
            for child in sorted(skills_dir.iterdir()):
                if (child.is_dir()
                        and not child.name.startswith(".")
                        and (child / "SKILL.md").is_file()
                        and child.name not in saved_skills
                        and child.name not in detected):
                    detected.add(child.name)
                    ctx.emit(EventType.SKILL_SAVE_PROMPT, {
                        "event_id": _new_event_id(),
                        "timestamp": _now_ts(),
                        "skill_name": child.name,
                    })
    except Exception:
        logger.debug("skill auto-detect skipped", exc_info=True)


def _compute_round_files(
    session: AgentSession, pre_snapshot: Any, session_id: str,
) -> List[Dict[str, Any]]:
    """对比执行前后工作区快照，算出本轮创建/修改的文件。失败返回空列表。"""
    try:
        post_snapshot = _snapshot_workspace_files(session.vm_root_dir)
        return _diff_workspace_files(
            pre_snapshot, post_snapshot,
            session.vm_root_dir, session_id,
        )
    except Exception:
        logger.debug("round_files diff failed", exc_info=True)
        return []
