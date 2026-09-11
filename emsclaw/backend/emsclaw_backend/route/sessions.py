"""
Sessions 路由。

仅保留会话生命周期与 chat / 文件 / Agent 清单路由。skills/tools/approval/worker
已拆到同目录的 skills.py / tools.py / approvals.py / _worker.py / _common.py。

路由：
  PUT    /sessions                          → 创建会话
  GET    /sessions                          → 会话列表
  GET    /sessions/shared/{session_id}      → 获取已分享会话（无需认证）
  GET    /sessions/{session_id}             → 会话详情
  DELETE /sessions/{session_id}             → 删除会话
  POST   /sessions/{session_id}/chat                      → 聊天（SSE）
  POST   /sessions/{session_id}/stop                      → 停止会话
  POST   /sessions/{session_id}/feedback                   → 点赞/踩上报（写 Langfuse score）
  POST   /sessions/{session_id}/clear_unread_message_count → 清零未读消息计数
  POST   /sessions/{session_id}/share       → 开启分享
  DELETE /sessions/{session_id}/share       → 取消分享
  GET    /sessions/{session_id}/files       → 沙盒文件列表
  GET    /sessions/{session_id}/sandbox-file → 读取沙盒文件
  GET    /sessions/notifications            → 会话通知 SSE
  GET    /sessions/agents                   → 父子 Agent 清单（只读）
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path as _Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Depends, UploadFile, File as FastAPIFile
from fastapi.responses import FileResponse, Response
from loguru import logger
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from emsclaw_backend.config import settings
from emsclaw_backend.deepagent.sessions import (
    AgentSession,
    AgentSessionNotFoundError,
    async_create_agent_session,
    async_delete_agent_session,
    async_get_agent_session,
    async_list_agent_sessions,
)
from emsclaw_backend.models import get_model_config
from emsclaw_backend.observability.sdk import record_user_feedback
from emsclaw_backend.user.dependencies import get_current_user, require_user, User

from ._common import (
    ApiResponse,
    SessionStatus,
    _now_ts,
    _new_event_id,
    _wrap_event,
    _json_dumps,
    _append_session_event,
    _classify_file,
    _collect_round_metadata,
    _sandbox_file_read,
)
from ._worker import (
    _agent_tasks,
    _agent_queues,
    _agent_background_worker,
    cleanup_orphaned_sessions,
    graceful_shutdown_agents,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ═══════════════════════════════════════════════════════════════════
# Pydantic 模型
# ═══════════════════════════════════════════════════════════════════

class CreateSessionRequest(BaseModel):
    mode: str = Field(default="business", description="会话模式：business")
    model_config_id: Optional[str] = Field(default=None, description="模型配置 ID")


class CreateSessionData(BaseModel):
    session_id: str = Field(..., description="会话 ID")
    mode: str = Field(default="business", description="会话模式")


class ListSessionItem(BaseModel):
    session_id: str = Field(..., description="会话 ID")
    title: Optional[str] = Field(default=None, description="会话标题")
    latest_message: Optional[str] = Field(default=None, description="最新消息内容")
    latest_message_at: Optional[int] = Field(default=None, description="最新消息时间戳")
    status: str = Field(default=SessionStatus.PENDING, description="会话状态")
    unread_message_count: int = Field(default=0, description="未读消息计数")
    is_shared: bool = Field(default=False, description="是否已分享")
    mode: str = Field(default="business", description="会话模式")
    pinned: bool = Field(default=False, description="是否置顶")
    source: Optional[str] = Field(default=None, description="会话来源（如 wechat、lark）")


class ListSessionData(BaseModel):
    sessions: List[ListSessionItem] = Field(..., description="会话列表")


class GetSessionData(BaseModel):
    session_id: str = Field(..., description="会话 ID")
    title: Optional[str] = Field(default=None, description="会话标题")
    status: str = Field(default=SessionStatus.PENDING, description="会话状态")
    events: List[Dict[str, Any]] = Field(default_factory=list, description="会话事件列表")
    is_shared: bool = Field(default=False, description="是否已分享")
    mode: str = Field(default="business", description="会话模式")
    model_config_id: Optional[str] = Field(default=None, description="模型配置 ID")


class ChatRequest(BaseModel):
    message: str = Field(default="", description="用户消息内容")
    timestamp: Optional[int] = Field(default=None, description="消息时间戳")
    event_id: Optional[str] = Field(default=None, description="事件 ID（SSE 协议为 evt_<hex>_<n> 字符串，重连游标用）")
    attachments: Optional[List[str]] = Field(default=None, description="附件路径列表")
    language: Optional[str] = Field(default=None, description="用户界面语言（如 'zh'、'en'）")
    model_config_id: Optional[str] = Field(default=None, description="要使用的模型配置 ID（覆盖会话默认值）")


class FeedbackRequest(BaseModel):
    """用户对某一轮回复的点赞 / 踩上报（写入 Langfuse score）。"""

    value: str = Field(..., description="like | dislike | none（none=取消之前的选择）")
    trace_id: Optional[str] = Field(default=None, description="本轮 Langfuse trace id（done 事件的 statistics 里带出）")
    message_event_id: Optional[str] = Field(default=None, description="被评价的 assistant 消息 event_id，用于后端反查本轮上下文")
    reasons: List[str] = Field(default_factory=list, description="点踩原因标签，如 ['事实错误','答非所问']")
    comment: Optional[str] = Field(default=None, description="用户补充说明")
    previous_value: Optional[str] = Field(default=None, description="切换前的取值，用于记录 like↔dislike 变更")
    client_ts: Optional[int] = Field(default=None, description="前端点击时间戳（秒）")


# ═══════════════════════════════════════════════════════════════════
# 内部辅助函数
# ═══════════════════════════════════════════════════════════════════

def normalize_session_mode(mode: Optional[str]) -> str:
    """规范化 session mode：business 原样返回，其余（含历史 team_ops 会话）兜底 business。"""
    if mode == "business":
        return mode
    return "business"


def _session_to_list_item(session) -> ListSessionItem:
    return ListSessionItem(
        session_id=session.session_id,
        title=getattr(session, "title", None),
        latest_message=getattr(session, "latest_message", None),
        latest_message_at=getattr(session, "latest_message_at", None),
        status=getattr(session, "status", SessionStatus.PENDING),
        unread_message_count=getattr(session, "unread_message_count", 0),
        is_shared=getattr(session, "is_shared", False),
        mode=getattr(session, "mode", "business"),
        pinned=getattr(session, "pinned", False),
        source=getattr(session, "source", None),
    )


# ═══════════════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════════════

@router.put("", response_model=ApiResponse)
async def create_session(
    body: CreateSessionRequest = CreateSessionRequest(),
    current_user: User = Depends(require_user),
) -> ApiResponse:
    try:
        model_config_dict = None
        if body.model_config_id:
            mc = await get_model_config(body.model_config_id)
            if mc:
                if not mc.is_system and mc.user_id != current_user.id:
                    raise HTTPException(status_code=403, detail="不能使用此模型")
                model_config_dict = mc.model_dump()

        session = await async_create_agent_session(
            mode=normalize_session_mode(body.mode),
            user_id=current_user.id,
            model_config=model_config_dict,
        )
        return ApiResponse(data=CreateSessionData(session_id=session.session_id, mode=session.mode).model_dump())
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("create_session failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("", response_model=ApiResponse)
async def list_sessions(current_user: User = Depends(require_user)) -> ApiResponse:
    sessions = await async_list_agent_sessions(user_id=current_user.id)
    items = [_session_to_list_item(s) for s in sessions]
    return ApiResponse(data=ListSessionData(sessions=items).model_dump())


@router.get("/shared/{session_id}", response_model=ApiResponse)
async def get_shared_session(session_id: str) -> ApiResponse:
    """获取已分享的会话（无需认证）"""
    try:
        session = await async_get_agent_session(session_id)
        if not getattr(session, "is_shared", False):
            raise HTTPException(status_code=404, detail="已分享的会话不存在")

        events = getattr(session, "events", []) or []
        return ApiResponse(data=GetSessionData(
            session_id=session.session_id,
            title=getattr(session, "title", None),
            status=getattr(session, "status", SessionStatus.PENDING),
            events=events,
            is_shared=True,
            mode=getattr(session, "mode", "business"),
        ).model_dump())
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="已分享的会话不存在") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_shared_session failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ═══════════════════════════════════════════════════════════════════
# 文件上传（保存到 session workspace，让 Agent 可以直接访问）
# ═══════════════════════════════════════════════════════════════════

@router.post("/{session_id}/upload", response_model=ApiResponse)
async def upload_session_file(
    session_id: str,
    file: UploadFile = FastAPIFile(...),
    current_user: User = Depends(require_user),
) -> ApiResponse:
    """上传文件到会话 workspace（/home/emsclaw/{session_id}/）。"""
    _WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", "/home/emsclaw")
    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")

        workspace_dir = _Path(_WORKSPACE_DIR) / session_id
        workspace_dir.mkdir(parents=True, exist_ok=True)
        workspace_dir.chmod(0o777)

        safe_filename = _Path(file.filename or "upload").name
        if not safe_filename or safe_filename in {".", ".."}:
            safe_filename = "upload"

        target_path = workspace_dir / safe_filename
        if target_path.exists():
            stem = target_path.stem
            suffix = target_path.suffix
            i = 1
            while target_path.exists():
                target_path = workspace_dir / f"{stem}_{i}{suffix}"
                i += 1

        content = await file.read()
        target_path.write_bytes(content)

        abs_path = str(target_path)
        stat = target_path.stat()
        logger.info(f"[Upload] Saved file to {abs_path} ({stat.st_size} bytes)")

        return ApiResponse(data={
            "file_id": abs_path,
            "filename": target_path.name,
            "size": stat.st_size,
            "upload_date": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "content_type": file.content_type or "application/octet-stream",
            "file_url": f"/api/v1/sessions/{session_id}/sandbox-file/download?path={abs_path}",
            "metadata": {"sandbox_path": abs_path, "session_id": session_id},
        })
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("upload_session_file failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ═══════════════════════════════════════════════════════════════════
# Real-time session notifications (SSE)
# ═══════════════════════════════════════════════════════════════════

@router.get("/notifications")
async def session_notifications(
    request: Request,
    current_user: User = Depends(require_user),
) -> EventSourceResponse:
    """推送 session_created / session_updated 事件的 SSE 流。"""
    from emsclaw_backend.notifications import subscribe, unsubscribe

    sub_id, events = await subscribe()
    user_id = current_user.id

    async def event_generator():
        try:
            async for event in events:
                if await request.is_disconnected():
                    break
                evt_data = event.get("data", {})
                if evt_data.get("user_id") and evt_data["user_id"] != user_id:
                    continue
                yield {
                    "event": event["event"],
                    "data": _json_dumps(evt_data),
                }
        except asyncio.CancelledError:
            pass
        finally:
            await unsubscribe(sub_id)

    return EventSourceResponse(event_generator())


# ═══════════════════════════════════════════════════════════════════
# Agent 清单（父子 Agent 的 tools / skills / 提示词一览，只读）
# ═══════════════════════════════════════════════════════════════════

def _agent_tool_meta(t: Any) -> Dict[str, Any]:
    """从 LangChain tool 对象抽 name / description / args（参数 schema properties）。"""
    name = getattr(t, "name", None) or getattr(t, "__name__", None) or ""
    desc = (getattr(t, "description", None) or "").strip()
    args: Dict[str, Any] = {}
    try:
        schema = getattr(t, "args_schema", None)
        if schema is not None and hasattr(schema, "model_json_schema"):
            args = schema.model_json_schema().get("properties", {}) or {}
    except Exception:
        pass
    return {"name": name, "description": desc, "args": args}


def _collect_agent_roster() -> Dict[str, Any]:
    """收集父子 Agent 清单（Lead + 领域子 agent），含 tools / skills / 提示词。

    提示词返回**本地源**（git 真相源 / Langfuse 种子）+ prompt_name + langfuse_enabled；
    运行时若 Langfuse 可用则用其 production 版本（版本细节在 Langfuse UI 看，
    本端点不额外拉 Langfuse，保持快、零外部依赖）。
    """
    # 内置能力加载 + internal skills 收集复用 skills.py 的实现
    from .skills import _ensure_business_domains_loaded, _collect_internal_skills
    _ensure_business_domains_loaded()
    try:
        from emsclaw_backend.deepagent.agents.business.registry import AgentRegistry
    except Exception as e:
        logger.warning("agent roster: AgentRegistry 不可用: %r", e)
        return {"agents": [], "langfuse_enabled": False}

    # Lead 信息
    try:
        from emsclaw_backend.deepagent.agents.business.factory import BUSINESS_LEAD_PROMPT
        from emsclaw_backend.observability.prompts import LEAD_PROMPT_NAME
        from emsclaw_backend.observability.sdk import is_enabled as _lf_enabled
        lead_prompt, lead_name = BUSINESS_LEAD_PROMPT, LEAD_PROMPT_NAME
        lf_enabled = bool(_lf_enabled())
    except Exception as e:
        logger.warning("agent roster: Lead 信息不可用: %r", e)
        lead_prompt, lead_name, lf_enabled = "", "", False

    agents: List[Dict[str, Any]] = []
    agents.append({
        "name": "BusinessLead",
        "label": "首席协调 Agent",
        "kind": "lead",
        "description": "EMS 多智能体首席协调 Agent，负责任务拆解、计划与分派给领域子 agent。",
        "prompt_name": lead_name,
        "prompt": lead_prompt,
        "prompt_is_template": False,
        "tools": [],
        "skills": [],
        "interrupt_on": {},
        "subagents": AgentRegistry.get_names(),
    })

    # 领域 skills 按 domain 分组（_collect_internal_skills 已遍历全部 agent，只调一次）
    skills_by_domain: Dict[str, List[Dict[str, Any]]] = {}
    for s in _collect_internal_skills():
        d = s.get("domain")
        if not d:
            continue
        skills_by_domain.setdefault(d, []).append({
            "name": s.get("name", ""),
            "description": s.get("description", ""),
            "files": s.get("files", []),
        })

    for agent in AgentRegistry.get_all():
        tools: List[Dict[str, Any]] = []
        try:
            tools = [_agent_tool_meta(t) for t in (agent.get_tools() or [])]
        except Exception as e:
            logger.debug("agent roster: get_tools(%s) failed: %r", agent.name, e)
        try:
            prompt = agent.get_system_prompt() or ""
        except Exception:
            prompt = ""
        try:
            prompt_name = agent.get_prompt_name() or ""
        except Exception:
            prompt_name = ""
        try:
            interrupt_on = agent.get_interrupt_on() or {}
        except Exception:
            interrupt_on = {}
        agents.append({
            "name": agent.name,
            "label": agent.name,
            "kind": "domain",
            "description": agent.description or "",
            "prompt_name": prompt_name,
            "prompt": prompt,
            "prompt_is_template": False,
            "tools": tools,
            "skills": skills_by_domain.get(agent.name, []),
            "interrupt_on": interrupt_on,
        })

    return {"agents": agents, "langfuse_enabled": lf_enabled}


@router.get("/agents", response_model=ApiResponse)
async def list_agents(current_user: User = Depends(require_user)) -> ApiResponse:
    """列出父子 Agent 清单（Lead + 领域子 agent），含每个 agent 的 tools/skills/提示词。只读。"""
    try:
        return ApiResponse(data=_collect_agent_roster())
    except Exception as exc:
        logger.exception("list_agents failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ═══════════════════════════════════════════════════════════════════
# Session CRUD（/{session_id} 路由必须在 /skills, /tools 之后）
# ═══════════════════════════════════════════════════════════════════

@router.get("/{session_id}", response_model=ApiResponse)
async def get_session(session_id: str, current_user: User = Depends(require_user)) -> ApiResponse:
    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")

        events = getattr(session, "events", []) or []
        # 从 session.model_config 中提取 model_config_id
        mc = getattr(session, "model_config", None)
        mc_id = mc.get("id") if isinstance(mc, dict) else None
        return ApiResponse(data=GetSessionData(
            session_id=session.session_id,
            title=getattr(session, "title", None),
            status=getattr(session, "status", SessionStatus.PENDING),
            events=events,
            is_shared=getattr(session, "is_shared", False),
            mode=getattr(session, "mode", "business"),
            model_config_id=mc_id,
        ).model_dump())
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_session failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{session_id}", response_model=ApiResponse)
async def remove_session(session_id: str, current_user: User = Depends(require_user)) -> ApiResponse:
    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")
        await async_delete_agent_session(session_id)
        return ApiResponse(data={"ok": True})
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("remove_session failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Session Update Endpoints (Pin, Archive, Title) ──

class PinRequest(BaseModel):
    pinned: bool

class TitleRequest(BaseModel):
    title: str


@router.patch("/{session_id}/pin", response_model=ApiResponse)
async def update_session_pin(
    session_id: str,
    request: PinRequest,
    current_user: User = Depends(require_user)
) -> ApiResponse:
    """置顶或取消置顶一个会话。"""
    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")
        session.pinned = request.pinned
        await session.save()
        return ApiResponse(data={"session_id": session_id, "pinned": request.pinned})
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("update_session_pin failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/{session_id}/title", response_model=ApiResponse)
async def update_session_title(
    session_id: str,
    request: TitleRequest,
    current_user: User = Depends(require_user)
) -> ApiResponse:
    """更新会话标题。"""
    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")
        session.title = request.title
        await session.save()
        return ApiResponse(data={"session_id": session_id, "title": request.title})
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("update_session_title failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{session_id}/clear_unread_message_count", response_model=ApiResponse)
async def clear_unread_message_count(session_id: str, current_user: User = Depends(require_user)) -> ApiResponse:
    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")
        session.unread_message_count = 0
        await session.save()
        return ApiResponse(data={"ok": True})
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("clear_unread_message_count failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{session_id}/stop", response_model=ApiResponse)
async def stop_session(session_id: str, current_user: User = Depends(require_user)) -> ApiResponse:
    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")
        session.cancel()
        setattr(session, "status", SessionStatus.COMPLETED)
        await session.save()
        return ApiResponse(data={"ok": True})
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("stop_session failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{session_id}/feedback", response_model=ApiResponse)
async def submit_feedback(
    session_id: str,
    body: FeedbackRequest,
    current_user: User = Depends(require_user),
) -> ApiResponse:
    """上报用户对某轮回复的点赞 / 踩 → 写入 Langfuse score(user_feedback)。

    - trace_id 优先用前端传的；缺失时从本轮 done 事件的 statistics 里取
      （runner 已把 trace_id 随 statistics 下发并落库）。
    - 上下文参数（模型 / token / 耗时 / 工具 / 子 agent / 产物 …）由后端从
      session.events 反查本轮区间补齐，避免只信任前端。
    - Langfuse 未启用 / 取不到 trace_id 时返回 recorded=False，不报错。
    """
    value = (body.value or "").strip().lower()
    if value not in ("like", "dislike", "none"):
        raise HTTPException(status_code=422, detail="value 必须是 like / dislike / none")

    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")

        ctx = _collect_round_metadata(session, body.message_event_id)
        stats: Dict[str, Any] = ctx.get("statistics") or {}
        trace_id = (body.trace_id or stats.get("trace_id") or "").strip()

        mc = getattr(session, "model_config", None)
        mc = mc if isinstance(mc, dict) else {}
        # 会话未显式绑模型时，实际生效的是全局默认模型（见 engine.get_llm_model）
        # ——上报时回退到默认值，并标记是否来自会话配置，便于按模型对比反馈质量
        mc_model = mc.get("model_name") or mc.get("name")
        metadata: Dict[str, Any] = {
            # ── 会话与来源 ──
            "session_id": session.session_id,
            "user_id": getattr(session, "user_id", None),
            "thread_id": getattr(session, "thread_id", None),
            "source": getattr(session, "source", None) or "emsclaw",
            "mode": getattr(session, "mode", None),
            "agent_version": settings.agent_version,
            # ── 模型与成本 ──
            "model_name": mc_model or settings.model_ds_name,
            "provider": mc.get("provider"),
            "model_config_id": mc.get("id"),
            "model_is_default": not bool(mc_model),
            "total_duration_ms": stats.get("total_duration_ms"),
            "tool_call_count": stats.get("tool_call_count"),
            "total_tool_duration_ms": stats.get("total_tool_duration_ms"),
            "input_tokens": stats.get("input_tokens"),
            "cached_tokens": stats.get("cached_tokens"),
            "output_tokens": stats.get("output_tokens"),
            "total_tokens": stats.get("token_count"),
            # ── 内容与产物 ──
            "query": ctx.get("query"),
            "answer_chars": ctx.get("answer_chars"),
            "answer_preview": ctx.get("answer_preview"),
            "round_file_count": ctx.get("round_file_count"),
            "report_count": ctx.get("report_count"),
            "has_report": ctx.get("has_report"),
            # ── 流程与路由 ──
            "tools_used": ctx.get("tools_used"),
            "tool_count_distinct": ctx.get("tool_count_distinct"),
            "subagents": ctx.get("subagents"),
            "used_subagent": ctx.get("used_subagent"),
            "approval_count": ctx.get("approval_count"),
            "had_error": ctx.get("had_error"),
            # ── 交互 ──
            "reasons": body.reasons or [],
            "previous_value": body.previous_value,
            "client_ts": body.client_ts,
        }

        if not trace_id:
            logger.info(
                f"[Feedback] session={session_id} 无 trace_id，跳过 Langfuse 写入"
                f"（可能未启用 tracing）"
            )
            return ApiResponse(data={"ok": True, "recorded": False, "reason": "no_trace_id"})

        # 原因标签兜底进 comment，便于在 Langfuse scores 列表直接看到原因
        comment = (body.comment or "").strip()
        if not comment and body.reasons:
            comment = "原因: " + ", ".join(body.reasons)

        # create_score 是同步阻塞调用（含 flush 等待），丢到线程池避免卡事件循环
        recorded = await asyncio.to_thread(
            record_user_feedback,
            trace_id,
            value,
            comment=comment or None,
            metadata=metadata,
            message_event_id=body.message_event_id,
        )
        return ApiResponse(data={"ok": True, "recorded": recorded, "trace_id": trace_id})
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("submit_feedback failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{session_id}/chat")
async def chat_with_session(
    session_id: str,
    body: ChatRequest,
    request: Request,
    current_user: User = Depends(require_user)
) -> EventSourceResponse:

    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # 若用户在对话中途切换了模型,则热替换 model config
    if body.model_config_id:
        current_mc = getattr(session, "model_config", None)
        current_mc_id = current_mc.get("id") if isinstance(current_mc, dict) else None
        if body.model_config_id != current_mc_id:
            mc = await get_model_config(body.model_config_id)
            if mc:
                if not mc.is_system and mc.user_id != current_user.id:
                    raise HTTPException(status_code=403, detail="不能使用此模型")
                session.model_config = mc.model_dump()
                await session.save()
                logger.info(f"[Chat] Model switched for session {session_id}: {current_mc_id} → {body.model_config_id}")

    existing_task = _agent_tasks.get(session_id)
    is_reconnect = existing_task is not None and not existing_task.done()

    # 孤儿检测:会话数据库状态是 RUNNING 但没有活跃 agent 任务
    # （服务器重启后会出现）。此时不要启动幻影 agent —— 直接标记为
    # 已完成并立即通知客户端。
    # 只有 RUNNING 会话可能成为孤儿;PENDING 会话从未启动过 agent,
    # 因此只是空闲（不算孤儿）。
    is_orphan = (
        not is_reconnect
        and session.status == SessionStatus.RUNNING
        and not body.message
    )
    if is_orphan:
        session.status = SessionStatus.COMPLETED
        done_data = {
            "event_id": _new_event_id(),
            "timestamp": _now_ts(),
            "statistics": {},
            "interrupted": True,
        }
        _append_session_event(session, _wrap_event("done", done_data))
        await session.save()
        logger.info(f"[Chat] Orphaned session {session_id} recovered → completed")

        async def _orphan_generator():
            yield {"event": "done", "data": _json_dumps(done_data)}

        return EventSourceResponse(_orphan_generator())

    # 为本次连接创建全新的 SSE 队列
    queue: "asyncio.Queue[Optional[Dict[str, str]]]" = asyncio.Queue()
    _agent_queues[session_id] = queue

    if not is_reconnect:
        task = asyncio.create_task(
            _agent_background_worker(
                session, session_id,
                body.message or "", body.attachments or [],
                event_id=body.event_id, timestamp=body.timestamp,
                language=body.language,
            )
        )
        _agent_tasks[session_id] = task
    else:
        logger.info(f"[Chat] Reconnecting SSE to running agent for session {session_id}")

    # 记录游标,以便重连时回放客户端错过的事件
    client_cursor = body.event_id if is_reconnect else None

    async def event_generator():
        try:
            # 重连时:回放客户端错过的事件（介于 getSession 和当前之间）
            if client_cursor:
                found_cursor = False
                for evt in list(session.events):
                    evt_data = evt.get("data", {})
                    if not found_cursor:
                        if evt_data.get("event_id") == client_cursor:
                            found_cursor = True
                        continue
                    yield {"event": evt["event"], "data": _json_dumps(evt_data)}

            # 从后台 worker 流式推送实时事件
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=600)
                except asyncio.TimeoutError:
                    break
                if event is None:
                    break
                yield event
        except asyncio.CancelledError:
            pass
        finally:
            if _agent_queues.get(session_id) is queue:
                _agent_queues.pop(session_id, None)

    return EventSourceResponse(event_generator())


@router.post("/{session_id}/share", response_model=ApiResponse)
async def share_session(session_id: str, current_user: User = Depends(require_user)) -> ApiResponse:
    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")
        session.is_shared = True
        await session.save()
        return ApiResponse(data={"session_id": session_id, "is_shared": True})
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("share_session failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{session_id}/share", response_model=ApiResponse)
async def unshare_session(session_id: str, current_user: User = Depends(require_user)) -> ApiResponse:
    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")
        session.is_shared = False
        await session.save()
        return ApiResponse(data={"session_id": session_id, "is_shared": False})
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("unshare_session failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ═══════════════════════════════════════════════════════════════════
# 沙盒文件管理
# ═══════════════════════════════════════════════════════════════════

@router.get("/{session_id}/files", response_model=ApiResponse)
async def list_session_files(session_id: str, current_user: User = Depends(require_user)) -> ApiResponse:
    """列出 session workspace 目录（/home/emsclaw/{session_id}/）下的所有文件。"""
    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")

        workspace_dir = session.vm_root_dir
        if not workspace_dir.is_dir():
            return ApiResponse(data=[])

        file_list: List[Dict[str, Any]] = []
        for file_path in sorted(workspace_dir.rglob("*")):
            if not file_path.is_file():
                continue
            abs_path = str(file_path)
            try:
                rel_path = str(file_path.relative_to(workspace_dir))
            except ValueError:
                rel_path = file_path.name
            try:
                stat = file_path.stat()
                upload_date = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                file_size = stat.st_size
            except OSError:
                upload_date = datetime.now(timezone.utc).isoformat()
                file_size = 0
            file_list.append({
                "file_id": abs_path,
                "filename": file_path.name,
                "size": file_size,
                "upload_date": upload_date,
                "content_type": "text/plain",
                "file_url": f"/api/v1/sessions/{session_id}/sandbox-file/download?path={abs_path}",
                "category": _classify_file(rel_path),
                "metadata": {"sandbox_path": abs_path, "session_id": session_id},
            })

        return ApiResponse(data=file_list)
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("list_session_files failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{session_id}/sandbox-file")
async def read_sandbox_file(
    session_id: str,
    path: str,
    current_user: User = Depends(require_user),
):
    """代理读取沙盒文件内容。path 必须在 session workspace 目录下。"""
    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")

        workspace_prefix = str(session.vm_root_dir) + "/"
        if not path.startswith(workspace_prefix):
            raise HTTPException(status_code=403, detail="文件路径不在会话 workspace 下")

        local_path = _Path(path)
        if local_path.is_file():
            try:
                content = local_path.read_text(encoding="utf-8", errors="replace")
                return ApiResponse(data={"file": path, "content": content})
            except Exception:
                pass

        content = await _sandbox_file_read(path)
        if content is None:
            raise HTTPException(status_code=404, detail="文件不存在")

        return ApiResponse(data={"file": path, "content": content})
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("read_sandbox_file failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{session_id}/sandbox-file/download")
async def download_sandbox_file(
    session_id: str,
    path: str = Query(...),
    current_user: User = Depends(require_user),
):
    """直接返回沙盒文件原始内容（用于下载/预览）。优先本地文件系统，回退 sandbox API。"""
    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")

        workspace_prefix = str(session.vm_root_dir) + "/"
        if not path.startswith(workspace_prefix):
            raise HTTPException(status_code=403, detail="文件路径不在会话 workspace 下")

        local_path = _Path(path)
        if local_path.is_file():
            return FileResponse(
                path=str(local_path),
                filename=local_path.name,
                media_type="application/octet-stream",
            )

        content = await _sandbox_file_read(path)
        if content is None:
            raise HTTPException(status_code=404, detail="文件不存在")

        filename = path.rsplit("/", 1)[-1] if "/" in path else path
        from urllib.parse import quote
        try:
            filename.encode("ascii")
            cd_header = f'attachment; filename="{filename}"'
        except UnicodeEncodeError:
            encoded = quote(filename)
            cd_header = f"attachment; filename*=UTF-8''{encoded}"
        return Response(
            content=content.encode("utf-8") if isinstance(content, str) else content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": cd_header},
        )
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("download_sandbox_file failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
