"""sessions 域共享基础：响应模型、路径常量、事件编排辅助。

被 sessions.py / skills.py / tools.py / approvals.py / _worker.py 复用，
本模块不依赖其它 route 子模块（避免循环 import）。
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import shortuuid
from loguru import logger
from pydantic import BaseModel, Field

from langchain_core.messages import HumanMessage, SystemMessage

from emsclaw_backend.deepagent.engine import get_llm_model
from emsclaw_backend.deepagent.stream_utils import _strip_think_tags
from emsclaw_backend.entity.enums import EventType, ApprovalEventKind, ToolEventStatus


# ═══════════════════════════════════════════════════════════════════
# 响应模型 / 常量
# ═══════════════════════════════════════════════════════════════════

class ApiResponse(BaseModel):
    code: int = Field(default=0, description="业务状态码，0 表示成功")
    msg: str = Field(default="ok", description="业务消息")
    data: Any = Field(default=None, description="响应数据")


class SessionStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    AWAITING_APPROVAL = "awaiting_approval"  # C4:business v2 stream 终止于 approval_required（等待审批）


# skills / tools / workspace 路径常量
_EXTERNAL_SKILLS_DIR = os.environ.get("EXTERNAL_SKILLS_DIR", "/app/Skills")
_BUILTIN_SKILLS_DIR = os.environ.get("BUILTIN_SKILLS_DIR", "/app/builtin-skills")
_WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", "/home/emsclaw")


# ═══════════════════════════════════════════════════════════════════
# 基础事件辅助
# ═══════════════════════════════════════════════════════════════════

def _now_ts() -> int:
    return int(time.time())


def _new_event_id() -> str:
    return shortuuid.uuid()


def _wrap_event(event: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"event": event, "data": data}


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _append_session_event(session: Any, event: Dict[str, Any]) -> None:
    events = getattr(session, "events", None)
    if not isinstance(events, list):
        events = []
        setattr(session, "events", events)
    events.append(event)
    if event.get("event") == "message":
        data = event.get("data") or {}
        content = data.get("content")
        if isinstance(content, str) and content.strip():
            setattr(session, "latest_message", content)
            setattr(session, "latest_message_at", int(data.get("timestamp") or _now_ts()))


def _find_last_user_message(session: Any) -> str:
    """扫 session.events 倒序找最后一条 role=user 的 message content。

    用于 ApprovalRecord.original_request_message — 审批触发前的最近用户输入。
    fallback: session.latest_message(可能是 assistant 的,不理想但优于空)。
    """
    events = getattr(session, "events", None) or []
    for ev in reversed(events):
        if ev.get("event") == "message":
            d = ev.get("data") or {}
            if d.get("role") == "user":
                c = d.get("content")
                if isinstance(c, str) and c.strip():
                    return c
    lm = getattr(session, "latest_message", "") or ""
    return lm if isinstance(lm, str) else ""


def _count_user_messages(events: List[Dict[str, Any]]) -> int:
    """统计 role=user 的 message 事件数量。"""
    if not events:
        return 0
    return sum(
        1 for ev in events
        if ev.get("event") == "message" and (ev.get("data") or {}).get("role") == "user"
    )


def _round_bounds(events: List[Dict[str, Any]], anchor_idx: int) -> tuple[int, int]:
    """由某个事件下标反推它所属「轮次」的区间 [start, end)。

    一轮对话 = 上一次 done 事件之后，到本轮 done 事件为止（含）。done 事件是本轮
    所有事件（thinking / tool / agent / message / statistics）的收尾标记，因此是
    天然的轮次分隔符（见 _worker.py 的 finally 块）。
    """
    start = 0
    for i in range(anchor_idx - 1, -1, -1):
        if events[i].get("event") == EventType.DONE.value:
            start = i + 1
            break
    end = len(events)
    for i in range(anchor_idx, len(events)):
        if events[i].get("event") == EventType.DONE.value:
            end = i + 1
            break
    return start, end


def _collect_round_metadata(
    session: Any, message_event_id: Optional[str] = None
) -> Dict[str, Any]:
    """收集某一轮回复的上下文，供用户点赞/踩上报到 Langfuse score 的 metadata。

    定位策略：先用 message_event_id 在 session.events 里找到对应的 message 事件，
    再借 _round_bounds 取出整轮事件；找不到就退化为「最后一轮」（最后一个 done）。

    返回字段已做截断（工具名 ≤30、子 agent ≤10、回答预览 ≤300 字符），
    避免 metadata 过大。所有字段都是「能取到就带上」，缺失时用安全默认值。
    """
    events = getattr(session, "events", None)
    if not isinstance(events, list):
        events = []

    anchor_idx: Optional[int] = None
    if message_event_id:
        for i, ev in enumerate(events):
            d = ev.get("data") or {}
            if ev.get("event") == EventType.MESSAGE.value and d.get("event_id") == message_event_id:
                anchor_idx = i
                break
    if anchor_idx is None:
        for i in range(len(events) - 1, -1, -1):
            if events[i].get("event") == EventType.DONE.value:
                anchor_idx = i
                break

    if anchor_idx is None:
        # 会话没有任何事件（异常/极早期）——只有会话级字段可上报
        return {
            "statistics": {}, "query": "", "answer_chars": 0, "answer_preview": "",
            "tools_used": [], "tool_count_distinct": 0,
            "subagents": [], "used_subagent": False,
            "approval_count": 0, "had_error": False,
            "round_file_count": 0, "report_count": 0, "has_report": False,
        }

    start, end = _round_bounds(events, anchor_idx)
    segment = events[start:end]

    stats: Dict[str, Any] = {}
    tools: List[str] = []
    subagents: List[str] = []
    approval_count = 0
    had_error = False
    round_files: List[Any] = []
    answer = ""
    query = ""
    for ev in segment:
        name = ev.get("event")
        d = ev.get("data") or {}
        if name == EventType.DONE.value:
            stats = d.get("statistics") or {}
            round_files = d.get("round_files") or []
        elif name == EventType.TOOL.value:
            fn = d.get("name") or d.get("function")
            if isinstance(fn, str) and fn and fn not in tools:
                tools.append(fn)
        elif name == EventType.AGENT.value:
            st = d.get("subagent_type")
            if isinstance(st, str) and st and st not in subagents:
                subagents.append(st)
        elif name == EventType.APPROVAL.value:
            approval_count += 1
        elif name == EventType.ERROR.value:
            had_error = True
        elif name == EventType.MESSAGE.value and d.get("role") == "user":
            # 本轮第一个 user message = 本轮 query
            c = d.get("content")
            if not query and isinstance(c, str) and c.strip():
                query = c
        elif name == EventType.MESSAGE.value and d.get("role") == "assistant":
            # 取本轮最后一条「真实」assistant 消息（排除 <dispatch_plans> 兜底块）
            c = d.get("content")
            if isinstance(c, str) and c.strip() and not d.get("_dispatch_block"):
                answer = c

    reports = [
        f for f in round_files
        if isinstance(f, dict) and f.get("is_report")
    ]
    return {
        "statistics": stats,
        "query": query[:500],
        "answer_chars": len(answer),
        "answer_preview": answer[:300],
        "tools_used": tools[:30],
        "tool_count_distinct": len(tools),
        "subagents": subagents[:10],
        "used_subagent": bool(subagents),
        "approval_count": approval_count,
        "had_error": had_error,
        "round_file_count": len(round_files),
        "report_count": len(reports),
        "has_report": bool(reports),
    }


# ═══════════════════════════════════════════════════════════════════
# 标题生成
# ═══════════════════════════════════════════════════════════════════

async def _generate_session_title(first_message: str) -> str:
    """
    使用 LLM 根据第一条用户消息生成简短、描述性的聊天标题。
    生成失败时返回兜底值。
    """
    if not (first_message and first_message.strip()):
        return ""
    prompt = first_message.strip()
    if len(prompt) > 800:
        prompt = prompt[:800] + "..."
    system = (
        "You generate a very short chat title from the first user message of a conversation.\n"
        "Language (IMPORTANT): detect the language of the user's message and write the title "
        "in that SAME language. Chinese input -> Chinese title; English input -> English title; "
        "and so on for any other language. Never translate to a different language.\n"
        "Rules: at most 15 words; output only the title; no quotes, no explanation, no prefix."
    )
    try:
        # max_tokens 给足:推理模型(MiniMax-M3 / DeepSeek-R1 / Qwen 等)会先输出 _blk=0 推理,
        # 60 tokens 不够 -> 实际标题被截断。512 让推理+标题都放下,再剥离 _blk(模型无关)。
        llm = get_llm_model(config=None, max_tokens_override=512, streaming=False)
        response = await llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=prompt),
        ])
        # content 可能是 str 或 list(Claude 风格 blocks);统一抽成纯文本
        content = response.content
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in content
            )
        title = _strip_think_tags(content or "").strip().strip('"').strip("'")
        if title and len(title) > 80:
            title = title[:80].rstrip()
        if title:
            return title
        # 推理耗尽预算 / 模型只输出 think -> 兜底用首行(保持用户输入语言)
        first_line = prompt.split("\n")[0].strip()
        return first_line[:50] if first_line else ""
    except Exception as exc:
        logger.warning("session title generation failed: %s", exc)
        # 兜底:使用首行或截断后的消息
        first_line = prompt.split("\n")[0].strip()
        return first_line[:50] if first_line else ""


# ═══════════════════════════════════════════════════════════════════
# 审批记录持久化
# ═══════════════════════════════════════════════════════════════════

def _persist_approval_record(session: Any, mapped_event: Dict[str, Any]) -> None:
    """把 approval_required / approval_decided(auto) 事件持久化到 ApprovalRecord 表。

    - approval_required(kind=required):新建 pending 行
    - approval_decided with auto=True:把对应 interrupt_id 的行更新为 auto_approved
    - approval_decided with auto=False:由 resume endpoint 处理(那里能拿到 current_user),这里跳过

    任何 DB 异常吞掉,不影响 SSE 主流程(ApprovalRecord 是辅助索引,不阻塞审批本身)。
    """
    try:
        data = mapped_event.get("data") or {}
        kind = data.get("kind")
        interrupt_id = str(data.get("interrupt_id") or "")
        if not interrupt_id:
            return
        from emsclaw_backend.service.approval_service import ApprovalService
        svc = ApprovalService()
        if kind == "required":
            action_requests = data.get("action_requests") or []
            ar0 = action_requests[0] if action_requests else {}
            tool_args = ar0.get("args") if isinstance(ar0, dict) else None
            if not isinstance(tool_args, dict):
                tool_args = {}
            # tool_call_id:deepagents action_request 可能带 id/tool_call_id,用于回填出参时关联
            tool_call_id = None
            if isinstance(ar0, dict):
                tool_call_id = ar0.get("id") or ar0.get("tool_call_id")
            # 去重:同一 interrupt_id 已有 pending 行则不重复写
            from emsclaw_backend.mapper.approval_mapper import ApprovalMapper
            existing = ApprovalMapper().find_by_interrupt(interrupt_id)
            if existing is not None:
                return
            svc.create_pending(
                session_id=str(getattr(session, "session_id", "") or getattr(session, "id", "") or ""),
                thread_id=str(getattr(session, "thread_id", "") or ""),
                interrupt_id=interrupt_id,
                tool_name=str(ar0.get("name") or "") if isinstance(ar0, dict) else "",
                tool_args=tool_args,
                tool_call_id=str(tool_call_id) if tool_call_id else None,
                parent_agent=str(data.get("parent_agent") or "Lead"),
                subagent_type=data.get("subagent_type"),
                subagent_instance_id=data.get("subagent_instance_id"),
                initiator_user_id=str(getattr(session, "user_id", "") or ""),
                original_request_message=_find_last_user_message(session),
            )
        elif kind == "decided" and bool(data.get("auto", False)):
            # auto_approve 内联触发 — 把 pending 行更新为 auto_approved
            svc.mark_decided(
                interrupt_id,
                decision=str(data.get("decision") or "approve"),
                approver_user_id=None,
                auto=True,
            )
        # 非 auto 的 decided 由 resume endpoint 处理(那里 current_user 在手)
    except Exception as exc:
        logger.warning(f"[ApprovalRecord] persist failed for interrupt={mapped_event}: {exc!r}")


# ═══════════════════════════════════════════════════════════════════
# SSE 事件映射（runner 事件 → 前端事件）
# ═══════════════════════════════════════════════════════════════════

def _map_plan_to_steps(plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _map_status(status: str) -> str:
        status = (status or "pending").strip()
        if status in {"in_progress", "running"}:
            return "running"
        if status == "completed":
            return "completed"
        if status in {"blocked", "failed"}:
            return "failed"
        return "pending"

    return [
        {
            "event_id": _new_event_id(),
            "timestamp": _now_ts(),
            "status": _map_status(str(step.get("status") or "pending")),
            "id": str(step.get("id") or ""),
            "description": str(step.get("content") or ""),
            "tools": step.get("tools") if isinstance(step.get("tools"), list) else [],
        }
        for step in plan
    ]


def _infer_tool_name(tool_function: str) -> str:
    func = (tool_function or "").strip()
    if func in {"sandbox_exec", "terminal_execute", "terminal_session",
                "sandbox_execute_bash", "sandbox_execute_code"}:
        return func
    if func in {"sandbox_write_file", "file_write", "sandbox_file_operations",
                "sandbox_str_replace_editor"}:
        return func
    if func in {"sandbox_read_file", "file_read"}:
        return func
    if func in {"sandbox_find_files", "file_list"}:
        return func
    if func in {"file_search"}:
        return "grep"
    if func in {"file_replace"}:
        return "edit_file"
    if func in {"terminal_kill"}:
        return "execute"
    if func in {"sandbox_get_context", "sandbox_get_packages", "sandbox_convert_to_markdown"}:
        return func
    if func.startswith("sandbox_browser_") or func == "sandbox_get_browser_info":
        return func
    if func.startswith("browser_"):
        return func
    if func.startswith("markitdown_"):
        return func
    if func in {"ls", "grep", "write", "read_file", "write_file", "edit_file"}:
        return func
    return func or "info"


def _normalize_tool_args(tool_function: str, args: Any, tool_call_id: str) -> Dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    out = dict(args)
    func = (tool_function or "").strip()
    if func in {"read_file", "write_file", "edit_file", "sandbox_read_file", "sandbox_write_file",
                "file_read", "file_write", "file_replace"}:
        if "file" not in out and "file_path" in out:
            out["file"] = out.get("file_path")
    if func in {"execute", "sandbox_exec", "terminal_execute"}:
        out.setdefault("id", tool_call_id)
    return out


def _maybe_wrap_tool_content(
    tool_function: str, tool_args: Dict[str, Any], raw_content: Any, tool_call_id: str
) -> Any:
    func = (tool_function or "").strip()

    # 终端命令执行
    if func in {"execute", "sandbox_exec", "terminal_execute"}:
        if isinstance(raw_content, str):
            try:
                parsed = json.loads(raw_content)
            except (json.JSONDecodeError, TypeError):
                parsed = {"output": raw_content}
        elif isinstance(raw_content, dict):
            parsed = raw_content
        else:
            parsed = {"output": str(raw_content)}

        output = parsed.get("output", str(raw_content))
        command = tool_args.get("command", "")
        session_id = parsed.get("session_id", tool_call_id)
        return {
            "output": output,
            "session_id": session_id,
            "console": [{"ps1": "$", "command": command, "output": output}],
        }

    # 文件读取
    if func in {"read_file", "sandbox_read_file", "file_read"}:
        if isinstance(raw_content, str):
            try:
                parsed = json.loads(raw_content)
                return {"file": parsed.get("file", tool_args.get("file_path", "")), "content": parsed.get("content", "")}
            except (json.JSONDecodeError, TypeError):
                pass
        elif isinstance(raw_content, dict):
            return {"file": raw_content.get("file", tool_args.get("file_path", "")), "content": raw_content.get("content", "")}
        content = raw_content if isinstance(raw_content, str) else str(raw_content)
        return {"file": tool_args.get("file", tool_args.get("file_path", "")), "content": content}

    # 文件写入
    if func in {"write_file", "sandbox_write_file", "file_write"}:
        if isinstance(raw_content, str):
            try:
                parsed = json.loads(raw_content)
                return parsed
            except (json.JSONDecodeError, TypeError):
                pass
        return raw_content

    return raw_content


def _extract_tool_meta(data: Dict[str, Any]) -> Dict[str, Any]:
    """从 runner 事件中提取工具元数据（icon, category, description, sandbox 等）"""
    meta = data.get("tool_meta") or {}
    result: Dict[str, Any] = {
        "icon": meta.get("icon", ""),
        "category": meta.get("category", ""),
        "description": meta.get("description", ""),
    }
    if meta.get("sandbox"):
        result["sandbox"] = True
    return result


def _map_agent_stream_to_agent_event(evt: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    将 runner 产生的事件映射为前端期望的 SSE 事件格式。

    runner 现在产生自包含的事件（已在 runner 层完成中间件数据合并），
    每个事件都带有完整的 tool_meta、duration_ms，无需额外缓存。
    """
    event_type = str(evt.get("event") or "")
    data = evt.get("data") or {}
    ts = _now_ts()

    # 子 agent 归属字段(runner v2 在 thinking/tool/plan 事件 data 里带 agent_id+depth)。
    # 透传给前端,depth>=1 的事件路由到对应子 agent 卡片;主 agent depth=0。
    def _attr() -> dict:
        aid = data.get("agent_id")
        d = int(data.get("depth") or 0)
        return {"agent_id": aid, "depth": d} if (aid or d) else {}

    if event_type == "thinking":
        return _wrap_event("thinking", {
            "event_id": _new_event_id(), "timestamp": ts,
            "content": data.get("content", ""),
            **_attr(),
        })

    if event_type in {"plan", "plan_update"}:
        plan = data.get("plan") or []
        if not isinstance(plan, list):
            return None
        return _wrap_event("plan", {"event_id": _new_event_id(), "timestamp": ts, "steps": _map_plan_to_steps(plan), **_attr()})

    if event_type == "step_start":
        step = data.get("step") or {}
        return _wrap_event("step", {
            "event_id": _new_event_id(), "timestamp": ts,
            "status": "running",
            "id": str(step.get("id") or ""),
            "description": str(step.get("content") or ""),
        })

    if event_type == "step_end":
        return _wrap_event("step", {
            "event_id": _new_event_id(), "timestamp": ts,
            "status": "completed",
            "id": str(data.get("step_id") or ""),
            "description": "",
        })

    if event_type == "message_chunk":
        return _wrap_event("message_chunk", {
            "event_id": _new_event_id(), "timestamp": ts,
            "content": data.get("content", ""), "role": "assistant",
        })

    if event_type == "message_chunk_done":
        return _wrap_event("message_chunk_done", {
            "event_id": _new_event_id(), "timestamp": ts,
        })

    if event_type in {"planning_message", "step_message"}:
        content = data.get("content")
        if not isinstance(content, str):
            content = str(content)
        return _wrap_event("message", {
            "event_id": _new_event_id(), "timestamp": ts,
            "content": content, "role": "assistant", "attachments": [],
        })

    if event_type == "tool_call":
        tool_call_id = str(data.get("tool_call_id") or "")
        tool_function = str(data.get("function") or "")
        tool_args = _normalize_tool_args(tool_function, data.get("args") or {}, tool_call_id)
        tool_meta = _extract_tool_meta(data)
        return _wrap_event("tool", {
            "event_id": _new_event_id(), "timestamp": ts,
            "tool_call_id": tool_call_id,
            "batch_id": data.get("batch_id"),  # 透传并发批次标识(LangGraph parent_ids[0])
            "name": _infer_tool_name(tool_function),
            "status": "calling",
            "function": tool_function,
            "args": tool_args,
            "tool_meta": tool_meta,
            **_attr(),
        })

    if event_type == "tool_result":
        tool_call_id = str(data.get("tool_call_id") or "")
        tool_function = str(data.get("function") or "")
        raw_args = data.get("args")
        # 只在有实际 args 时才 normalize，否则不发送 args（让前端保留 calling 的 args）
        tool_args = _normalize_tool_args(tool_function, raw_args or {}, tool_call_id) if raw_args else None
        content = _maybe_wrap_tool_content(tool_function, tool_args or {}, data.get("content"), tool_call_id)
        tool_meta = _extract_tool_meta(data)
        duration_ms = data.get("duration_ms")

        result = {
            "event_id": _new_event_id(), "timestamp": ts,
            "tool_call_id": tool_call_id,
            "batch_id": data.get("batch_id"),  # 透传并发批次标识(LangGraph parent_ids[0])
            "name": _infer_tool_name(tool_function),
            "status": "called",
            "function": tool_function,
            "content": content,
            "duration_ms": duration_ms,
            "tool_meta": tool_meta,
            **_attr(),
        }
        # 只在有实际 args 时才包含，避免覆盖前端 calling 事件中保存的 args
        if tool_args:
            result["args"] = tool_args
        return _wrap_event("tool", result)

    if event_type == "statistics":
        return _wrap_event("statistics", data)

    # dispatch_preview 透传(完整 schedule+summary,独立于 message 流)
    # runner 在 optimize_dispatch 求解成功时发此事件,worker 落库 + 推 SSE
    if event_type == "dispatch_preview":
        return _wrap_event("dispatch_preview", {
            "event_id": _new_event_id(), "timestamp": ts,
            "tool_call_id": str(data.get("tool_call_id") or ""),
            "result": data.get("result") or {},
        })

    if event_type == "error":
        message = data.get("message")
        if not isinstance(message, str):
            message = str(message)
        return _wrap_event("error", {"event_id": _new_event_id(), "timestamp": ts, "error": message})

    # C2:审批事件(对齐 AG3NT HITL schema,apps/tui/widgets/approval.py 渲染数据)
    if event_type == "approval_required":
        return _wrap_event("approval", {
            "event_id": _new_event_id(), "timestamp": ts, "kind": "required",
            "interrupt_id": str(data.get("interrupt_id") or ""),
            "action_requests": data.get("action_requests", []),
            "review_configs": data.get("review_configs", []),
            "raw_value": data.get("raw_value", {}),
            "parent_agent": str(data.get("parent_agent") or "Lead"),
            "subagent_type": data.get("subagent_type"),
            "subagent_instance_id": data.get("subagent_instance_id"),
        })

    if event_type == "approval_decided":
        return _wrap_event("approval", {
            "event_id": _new_event_id(), "timestamp": ts, "kind": "decided",
            "interrupt_id": str(data.get("interrupt_id") or ""),
            "decision": str(data.get("decision") or ""),
            "auto": bool(data.get("auto", False)),
            "parent_agent": str(data.get("parent_agent") or "Lead"),
            "subagent_type": data.get("subagent_type"),
            "subagent_instance_id": data.get("subagent_instance_id"),
        })

    if event_type == "auto_approve_set":
        return _wrap_event("approval", {
            "event_id": _new_event_id(), "timestamp": ts, "kind": "auto_approve_set",
            "enabled": bool(data.get("enabled", True)),
        })

    # C2:子 agent 事件(LambChat processor.py:220-230 把 task 工具特殊路由)
    if event_type == "agent_call":
        return _wrap_event("agent", {
            "event_id": _new_event_id(), "timestamp": ts, "kind": "call",
            "agent_id": str(data.get("agent_id") or ""),
            "subagent_type": str(data.get("subagent_type") or ""),
            "depth": int(data.get("depth") or 0),
            "description": str(data.get("description") or ""),
            "parent_tool_call_id": str(data.get("parent_tool_call_id") or ""),
        })

    if event_type == "agent_result":
        return _wrap_event("agent", {
            "event_id": _new_event_id(), "timestamp": ts, "kind": "result",
            "agent_id": str(data.get("agent_id") or ""),
            "subagent_type": str(data.get("subagent_type") or ""),
            "depth": int(data.get("depth") or 0),
            "result": str(data.get("result") or ""),
            "parent_tool_call_id": str(data.get("parent_tool_call_id") or ""),
        })

    return None


# ═══════════════════════════════════════════════════════════════════
# 工作区文件快照 / diff / sandbox 文件辅助
# ═══════════════════════════════════════════════════════════════════

from pathlib import Path as _Path
import httpx


_FILE_OP_TOOLS = {
    "sandbox_file_operations",
    "sandbox_str_replace_editor",
    "file_write",
    "sandbox_write_file",
}

_CODE_EXEC_TOOLS = {
    "sandbox_execute_bash",
    "sandbox_execute_code",
    "terminal_execute",
}

_OPEN_WRITE_RE = re.compile(
    r"""open\s*\(\s*(?P<q>['"])(?P<path>.+?)(?P=q)\s*,\s*(?P<q2>['"])(?P<mode>[wxa][+tb]*)(?P=q2)\s*\)"""
)

_ROUND_FILES_EXCLUDE_DIRS = {"_diagnostic", "__pycache__", ".git"}
_ROUND_FILES_EXCLUDE_NAMES = {"CONTEXT.md", "planner.md", "AGENTS.md"}

# 报告类目录约定（skill 要求长报告落盘到 reports/ 下）
_REPORT_DIR_PREFIX = "reports/"
# 文档类扩展名 —— 视为「给用户看的交付物」，前端以卡片突出展示
_REPORT_EXTS = {"md", "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "html"}


def _is_report_file(relative_path: str, category: str) -> bool:
    """判定本轮文件是否为「报告/交付物」，供前端以卡片形式突出展示。

    判据（权威来源，前端仅消费不重复判定）：
    - 落在 ``reports/`` 目录下；或
    - output 类且扩展名为文档类（md/pdf/docx/pptx/xlsx/html 等）。
    """
    if relative_path.startswith(_REPORT_DIR_PREFIX):
        return True
    if category != "output":
        return False
    ext = relative_path.rsplit(".", 1)[-1].lower() if "." in relative_path else ""
    return ext in _REPORT_EXTS


def _get_sandbox_rest_base() -> str:
    """从 SANDBOX_MCP_URL 推导 sandbox REST 基础 URL。"""
    mcp_url = os.environ.get("SANDBOX_MCP_URL", "http://sandbox:8080/mcp")
    return mcp_url.rsplit("/", 1)[0]


def _snapshot_workspace_files(workspace_dir: _Path) -> Dict[str, float]:
    """返回 *workspace_dir* 下每个文件的 {相对路径: mtime} 字典。"""
    snap: Dict[str, float] = {}
    if not workspace_dir.is_dir():
        return snap
    for fp in workspace_dir.rglob("*"):
        if not fp.is_file():
            continue
        try:
            rel = str(fp.relative_to(workspace_dir))
            snap[rel] = fp.stat().st_mtime
        except (OSError, ValueError):
            continue
    return snap


def _diff_workspace_files(
    pre: Dict[str, float],
    post: Dict[str, float],
    workspace_dir: _Path,
    session_id: str,
) -> List[Dict[str, Any]]:
    """对比快照,返回新增/修改的文件,排除系统产物。"""
    changed: List[Dict[str, Any]] = []
    for rel, mtime in post.items():
        top_dir = rel.split("/", 1)[0] if "/" in rel else ""
        if top_dir in _ROUND_FILES_EXCLUDE_DIRS:
            continue
        basename = rel.rsplit("/", 1)[-1]
        if basename in _ROUND_FILES_EXCLUDE_NAMES:
            continue
        if basename.startswith("."):
            continue

        prev_mtime = pre.get(rel)
        if prev_mtime is not None and prev_mtime >= mtime:
            continue

        fp = workspace_dir / rel
        try:
            stat = fp.stat()
            upload_date = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            size = stat.st_size
        except OSError:
            continue

        category = "research_data" if top_dir == "research_data" else "output"
        abs_path = str(fp)
        changed.append({
            "file_id": abs_path,
            "filename": basename,
            "relative_path": rel,
            "size": size,
            "upload_date": upload_date,
            "file_url": f"/api/v1/sessions/{session_id}/sandbox-file/download?path={abs_path}",
            "category": category,
            "is_report": _is_report_file(rel, category),
        })
    return changed


def _extract_sandbox_file_paths(events: List[Dict[str, Any]]) -> set[str]:
    """扫描会话事件,提取被 sandbox 工具触及的文件路径。"""
    paths: set[str] = set()
    for ev in events:
        if ev.get("event") != "tool":
            continue
        data = ev.get("data") or {}
        func = (data.get("function") or "").strip()
        args = data.get("args") or {}

        if func in _FILE_OP_TOOLS:
            for key in ("path", "file_path", "file", "filename"):
                p = args.get(key)
                if isinstance(p, str) and p.strip():
                    paths.add(p.strip())
                    break

        if func in _CODE_EXEC_TOOLS:
            code = args.get("code") or args.get("command") or ""
            if isinstance(code, str):
                for m in _OPEN_WRITE_RE.finditer(code):
                    paths.add(m.group("path"))

    return paths


async def _sandbox_file_list(directory: str) -> List[Dict[str, Any]]:
    """调用 sandbox REST API 列出某目录下的文件。"""
    base = _get_sandbox_rest_base()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{base}/v1/file/list", json={"path": directory})
        if resp.status_code != 200:
            return []
        body = resp.json()
        data = body.get("data", body)
        if isinstance(data, dict):
            return data.get("files", [])
        return data if isinstance(data, list) else []


async def _sandbox_file_read(file_path: str) -> Optional[str]:
    """调用 sandbox REST API 读取一个文件。"""
    base = _get_sandbox_rest_base()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{base}/v1/file/read", json={"file": file_path})
        if resp.status_code != 200:
            return None
        body = resp.json()
        data = body.get("data", body)
        if isinstance(data, dict):
            return data.get("content", "")
        return str(data)


async def _verify_sandbox_files(paths: set[str]) -> List[Dict[str, Any]]:
    """校验哪些路径在 sandbox 中仍然存在,返回 FileInfo 兼容的字典。"""
    dirs_to_scan: Dict[str, set[str]] = {}
    for p in paths:
        parent = p.rsplit("/", 1)[0] if "/" in p else "/"
        dirs_to_scan.setdefault(parent, set()).add(p)

    existing_files: Dict[str, Dict[str, Any]] = {}
    for directory, expected_paths in dirs_to_scan.items():
        entries = await _sandbox_file_list(directory)
        for entry in entries:
            entry_path = entry.get("path", "")
            if entry_path in expected_paths:
                existing_files[entry_path] = entry

    results: List[Dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for p in sorted(paths):
        entry = existing_files.get(p)
        if entry is None:
            continue
        filename = entry.get("name", p.rsplit("/", 1)[-1] if "/" in p else p)
        mod_time = entry.get("modified_time", "")
        if mod_time and mod_time.isdigit():
            upload_date = datetime.fromtimestamp(int(mod_time), tz=timezone.utc).isoformat()
        else:
            upload_date = mod_time or now_iso
        results.append({
            "file_id": p,
            "filename": filename,
            "size": entry.get("size") or 0,
            "upload_date": upload_date,
            "content_type": "text/plain",
            "file_url": None,
            "metadata": {"sandbox_path": p},
        })
    return results


def _classify_file(rel_path: str) -> str:
    """按相对路径把 workspace 文件分类到 UI 类别。"""
    top_dir = rel_path.split("/", 1)[0] if "/" in rel_path else ""
    basename = rel_path.rsplit("/", 1)[-1]

    if top_dir in ("_diagnostic", "__pycache__"):
        return "process"
    if basename in ("CONTEXT.md", "planner.md", "AGENTS.md") or basename.startswith("."):
        return "process"
    if top_dir in ("research_data",):
        return "process"
    if basename.endswith(".pyc"):
        return "process"
    return "result"


# ═══════════════════════════════════════════════════════════════════
# skills/tools 屏蔽状态共享操作（消除对称重复）
# ═══════════════════════════════════════════════════════════════════

from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from emsclaw_backend.db.session import AsyncSessionLocal


async def _set_blocked(model, name_field: str, user_id: str, name: str, blocked: bool) -> None:
    """屏蔽或取消屏蔽一个外置 skill/tool（insert-or-delete，含竞态兜底）。

    model: BlockedSkill；name_field: name 列在模型上的属性名字符串
    （"skill_name"）。
    """
    name_col = getattr(model, name_field)
    async with AsyncSessionLocal() as s:
        if blocked:
            existing = (await s.execute(
                select(model).where(
                    model.user_id == user_id,
                    name_col == name,
                )
            )).scalar_one_or_none()
            if existing is None:
                s.add(model(
                    id=shortuuid.uuid(),
                    user_id=user_id,
                    **{name_field: name},
                ))
                try:
                    await s.commit()
                except IntegrityError:
                    # 竞态:另一个请求已先插入 —— 安全忽略
                    await s.rollback()
        else:
            await s.execute(delete(model).where(
                model.user_id == user_id,
                name_col == name,
            ))
            await s.commit()


async def _delete_blocked(model, name_field: str, name: str) -> None:
    """删除 skill/tool 后清理对应的屏蔽记录。"""
    name_col = getattr(model, name_field)
    async with AsyncSessionLocal() as s:
        await s.execute(delete(model).where(name_col == name))
        await s.commit()
