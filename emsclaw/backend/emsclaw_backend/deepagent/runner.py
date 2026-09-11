"""
runner.py — SSE 流式执行器。

职责：从 agent.py 获取构建好的 agent，执行对话并将结果以 SSE 事件格式推送给前端。
agent 的构建（模型、工具、提示词）全部由 agent.py 负责。

架构（参考 sample/emsclaw_agent_v5.py + sample/monitoring_v2.py）：
  - agent.py 创建 agent 时注入 SSEMonitoringMiddleware
  - 中间件的 wrap_tool_call 拦截工具执行前后，捕获参数/结果/耗时
  - 中间件事件存储在 middleware.sse_events 列表
  - runner 在每个 stream chunk 后调用 middleware.drain_events() 轮询事件
  - 中间件事件与 stream 事件合并，一起 yield 给前端

这样实现了两层事件来源：
  1. 中间件层：精确的工具前后拦截（参数、结果、精准计时、todolist 变化）
  2. Stream 层：AI 回复内容、最终消息（只有 content 需要从 stream 获取）

纯函数辅助见 stream_utils.py；eval 执行器见 eval.py；plan 构造/映射见 plan_types.py。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from emsclaw_backend.config import settings
from emsclaw_backend.deepagent.agent import deep_agent
from emsclaw_backend.deepagent.diagnostic import DIAGNOSTIC_ENABLED
from emsclaw_backend.deepagent.plan_types import (
    PlanStep,
    normalize_plan_steps,
    _build_plan,
    _plan_for_frontend,
    _todos_to_plan_steps,
)
from emsclaw_backend.deepagent.sessions import AgentSession
from emsclaw_backend.observability.sse_middleware import SSEMonitoringMiddleware
from emsclaw_backend.observability.sdk import (
    create_eval_observation,
    get_langfuse_handler,
    trace_attributes,
    set_trace_io,
)
from emsclaw_backend.deepagent.stream_utils import (
    _ThinkTagStreamFilter,
    _extract_chunk_text,
    _extract_resume_meta,
    _extract_thinking,
    _extract_token_usage,
    _resolve_agent_context,
    _resolve_interrupt_agent_context,
    _safe_str_v2,
    _strip_think_tags,  # noqa: F401 — re-export（route/sessions 等历史 import 兼容）
    _truncate_tool_args,
)
from emsclaw_backend.observability.eval.runner import EvalResult, run_eval_task  # noqa: F401 — re-export
from emsclaw_backend.task_settings import get_task_settings, TaskSettings


# ───────────────────────────────────────────────────────────────────
# v2 SSE 流(主+子 agent 区分 + LambCheck checkpoint_ns attribution)
# ───────────────────────────────────────────────────────────────────
#
# 参考:
#   - LambChat src/infra/agent/events/subagents.py:34-118 — checkpoint_ns 映射
#   - LambChat src/infra/agent/events/processor.py:220-230 — task 工具特殊路由到 agent_call/agent_result
#   - LambChat src/infra/agent/events/stream.py:147-214 — 从 on_chat_model_end 抽 token usage
#   - demo/stream_event_v2/event_processor.py:117-217 — v2 → SSE 投影
#   - AG3NT (D:\agent\AG3NT) — durability="exit" 等 HITL 模式(B3/B4 用)
#
# v2 → SSE 事件映射:
#   on_chat_model_stream      → thinking(reasoning_content + text chunk)
#   on_chat_model_end         → token usage(LambChat _handle_token_usage)
#                              + final_content 捕获(no tool_calls 的 AIMessage)
#   on_tool_start(non-task)   → tool_call
#   on_tool_end(non-task)     → tool_result
#   on_tool_start(name=task)  → agent_call(子 agent 实例注册 + LambChat 特殊路由)
#   on_tool_end(name=task)    → agent_result
#   on_tool_start(write_todos)→ plan_update(子 agent todos,工具回调直出)
#   middleware.drain_events() → plan_update(主 agent todos)
#
# 子 agent 区分(LambChat 模式,非 demo 的 lc_agent_name):
#   维护 dict[checkpoint_ns -> (instance_id, subagent_type)]
#   task 工具 on_tool_start 时注册:checkpoint_to_agent[main_ns] = (instance_id, subagent_type)
#   每个事件读 metadata.langgraph_checkpoint_ns:无 | → 主 agent (None, 0);有 | → 取第一段
#   (parent main ns)查 map 返回 (instance_id, depth=1)
#
# B2/B3/B4 在此函数扩展:interrupt detection / resume_command / auto_approve_all。
# B1 只实现 v2 转换 + 子 agent 区分 + token usage,不涉及审批流。


@dataclass
class _StreamState:
    """_arun_v2_stream 主循环与事件 handler 共享的可变状态。

    把原 _arun_v2_stream 闭包里散落的局部可变变量收拢到一个对象，
    让抽出的事件 handler 能读写同一份状态而不必都写成 generator。
    """
    checkpoint_to_agent: Dict[str, tuple[str, str]] = field(default_factory=dict)
    active_subagent: Optional[tuple[str, str]] = None
    current_todos: List[Dict] = field(default_factory=list)
    think_filters: Dict[str, "_ThinkTagStreamFilter"] = field(default_factory=dict)
    final_content: str = ""
    last_thinking: str = ""
    plan: List[Dict[str, Any]] = field(default_factory=list)
    pending_interrupts_yielded: List[str] = field(default_factory=list)
    tool_start_times: Dict[str, float] = field(default_factory=dict)  # tool_call_id -> start_time（A1: 工具耗时补全）
    # tool_call_id -> batch_id(同一次 LLM 响应派生的并发工具共享)
    # start 时缓存,end 时取出,保证 calling/called 事件 batch_id 一致(历史回放也带得上)
    tool_batch_ids: Dict[str, Optional[str]] = field(default_factory=dict)
    # (agent_id, depth) -> 最近一次 on_chat_model_end 的 run_id
    # 后续 on_tool_start 取出作为 batch_id。按 agent 上下文区分,避免子 agent 工具
    # 误用 lead 的 chat model run_id(parent_ids 链条顶层都指向 lead)。
    last_chat_model_run_id: Dict[tuple[Optional[str], int], str] = field(default_factory=dict)
    stream_terminated_by_interrupt: bool = False
    # 完整对话日志（供 Langfuse LLM-as-judge evaluator 读取工具调用+思考过程）
    messages_log: List[str] = field(default_factory=list)
    # 工具步骤计数器（跳过 write_todos，与前端 tool_steps 数组 1:1 对应）
    # judge 在评分理由里引用 "步骤 #N" 时，N 对应 tool_steps[N-1]
    tool_step_counter: int = 0
    # 当前会话 ID（dispatch artifact 存储用）
    session_id: str = ""


# ───────────────────────────────────────────────────────────────────
# 事件 handler（从原 _arun_v2_stream 的 ev_type 分支抽出）
# ───────────────────────────────────────────────────────────────────

async def _drain_middleware(
    middleware: SSEMonitoringMiddleware,
    state: _StreamState,
):
    """drain 主 middleware 事件(主 agent todos,沿用 v1 双通道)。

    子 agent 的 middleware 由 deepagents 内部持有,runner 无 handle;
    子 agent todos 通过 v2 的 write_todos on_tool_start 捕获(见 _handle_tool_start)。
    产出 0 或 1 个 plan_update 事件。

    async generator:调用处用 ``async for`` 消费(drain 本身同步,直接 yield)。
    """
    for mw_evt in middleware.drain_events():
        mw_type = mw_evt.get("event", "")
        mw_data = mw_evt.get("data", {})
        if mw_type == "middleware_todos_update":
            new_todos = mw_data.get("todos", [])
            if new_todos and new_todos != state.current_todos:
                state.current_todos = new_todos
                plan_steps = _todos_to_plan_steps(new_todos)
                yield {"event": "plan_update", "data": {"plan": plan_steps}}


def _handle_chat_model_stream(ev: Dict[str, Any], state: _StreamState) -> List[dict]:
    """on_chat_model_stream → thinking(reasoning + text chunks)。

    返回 0..n 个 SSE 事件（reasoning + 剥离 think 标签后的 text）。
    """
    out: List[dict] = []
    ev_meta = ev.get("metadata") or {}
    checkpoint_ns = ev_meta.get("langgraph_checkpoint_ns") or ""
    agent_id, depth = _resolve_agent_context(checkpoint_ns, state.checkpoint_to_agent)

    ev_data = ev.get("data") or {}
    chunk = ev_data.get("chunk")
    if chunk is None:
        return out

    reasoning = ""
    try:
        reasoning = (getattr(chunk, "additional_kwargs", {}) or {}).get(
            "reasoning_content", "",
        )
    except Exception:
        pass
    if isinstance(reasoning, str) and reasoning:
        out.append({"event": "thinking", "data": {
            "content": reasoning,
            "agent_id": agent_id, "depth": depth,
        }})
    if not getattr(chunk, "tool_call_chunks", None):
        token_text = _extract_chunk_text(chunk)
        if token_text:
            # 跨 chunk 剥离  `<think>` (每 agent 独立,残片不漏到前端)
            _tf_key = agent_id or "_main"
            _tf = state.think_filters.get(_tf_key)
            if _tf is None:
                _tf = _ThinkTagStreamFilter()
                state.think_filters[_tf_key] = _tf
            token_text = _tf.feed(token_text)
            if token_text:
                if len(token_text) > 2 and not token_text.strip() and "\n" in token_text:
                    token_text = "\n"
                out.append({"event": "thinking", "data": {
                    "content": token_text,
                    "agent_id": agent_id, "depth": depth,
                }})
    return out


def _handle_chat_model_end(
    ev: Dict[str, Any], state: _StreamState, middleware: SSEMonitoringMiddleware,
) -> List[dict]:
    """on_chat_model_end → token usage + final_content 捕获。

    LambChat _handle_token_usage(stream.py:147-214):v2 chunked stream 不带 usage,
    从 on_chat_model_end 的最终 AIMessage 抽。不做 depth filter,跨主+子 agent 累计。
    不直接产出 SSE 事件（token 写入 middleware，最终 statistics 时读出）。
    """
    ev_data = ev.get("data") or {}
    output = ev_data.get("output")
    if output is None:
        return []
    # 记录本次 LLM 响应的 run_id,作为后续 on_tool_start 的 batch_id 来源。
    # 按 (agent_id, depth) 区分:不同 agent(主+子)各自的 LLM 响应不会混淆。
    ev_meta = ev.get("metadata") or {}
    _ns = ev_meta.get("langgraph_checkpoint_ns") or ""
    _agent_id, _depth = _resolve_agent_context(_ns, state.checkpoint_to_agent)
    _run_id = ev.get("run_id")
    if _run_id:
        state.last_chat_model_run_id[(_agent_id, _depth)] = _run_id
    token_info = _extract_token_usage(output)
    if token_info["input_tokens"] or token_info["output_tokens"]:
        logger.debug(
            f"[v2] tokens from on_chat_model_end: "
            f"input={token_info['input_tokens']}, output={token_info['output_tokens']}, "
            f"cached={token_info.get('cached_tokens', 0)}"
        )
        middleware.add_tokens(
            token_info["input_tokens"], token_info["output_tokens"],
            token_info.get("cached_tokens", 0),
        )
    # 捕获 final_content:no tool_calls 的 AIMessage = 最终回复
    if isinstance(output, AIMessage):
        _thinking_text, _clean_text = _extract_thinking(output)
        tc = getattr(output, "tool_calls", None)
        if tc:
            # 中间 AI 消息（带工具调用）→ 记录思考+工具调用到对话日志
            _log_parts: List[str] = []
            if _thinking_text:
                _log_parts.append(f"[AI 思考]\n{_thinking_text[:2000]}")
            _tool_lines = []
            for t in tc:
                t_name = t.get("name", "?") if isinstance(t, dict) else getattr(t, "name", "?")
                t_args = t.get("args", {}) if isinstance(t, dict) else getattr(t, "args", {})
                _args_str = json.dumps(t_args, ensure_ascii=False, default=str)[:600]
                _tool_lines.append(f"  - {t_name}({_args_str})")
            _log_parts.append(f"[调用工具]\n" + "\n".join(_tool_lines))
            state.messages_log.append("\n".join(_log_parts))
        else:
            if _thinking_text:
                state.last_thinking = _thinking_text
            if _clean_text:
                state.final_content = _clean_text
    return []


def _handle_tool_start(ev: Dict[str, Any], state: _StreamState, protocol) -> List[dict]:
    """on_tool_start → tool_call / agent_call / plan_update。

    task 工具 → 子 agent 实例注册 + agent_call SSE（LambChat processor.py:220-230
    特殊路由,不当普通 tool_call）。write_todos → plan_update。
    """
    out: List[dict] = []
    ev_name = ev.get("name", "")
    ev_meta = ev.get("metadata") or {}
    ev_data = ev.get("data") or {}
    checkpoint_ns = ev_meta.get("langgraph_checkpoint_ns") or ""
    agent_id, depth = _resolve_agent_context(checkpoint_ns, state.checkpoint_to_agent)

    tool_call_id = ev_data.get("tool_call_id") or ev.get("run_id", "")
    name = ev_name
    # A1: 记录工具开始时间，供 _handle_tool_end 计算 duration_ms（覆盖主+子 agent）
    if tool_call_id:
        state.tool_start_times[tool_call_id] = time.time()
    # 并发批次标识: 同一次 LLM 响应派生的多个 tool_call 共享同一 batch_id。
    # 实现方式:on_chat_model_end 时记录当前 agent 上下文对应的 LLM 响应 run_id,
    # 后续 on_tool_start 取出。这比 parent_ids[0] 可靠 —— 子 agent 工具的 parent_ids
    # 链条顶层都指向 lead 的 chat model,会把整个子 agent 生命周期误判为同一批。
    batch_id = state.last_chat_model_run_id.get((agent_id, depth))
    if tool_call_id:
        state.tool_batch_ids[tool_call_id] = batch_id
    args = ev_data.get("input") or {}

    # task 工具 → 子 agent 实例注册 + agent_call SSE
    if name == "task":
        subagent_type = "general-purpose"
        if isinstance(args, dict):
            subagent_type = args.get("subagent_type") or subagent_type
        description = args.get("description", "") if isinstance(args, dict) else ""
        instance_id = f"{subagent_type}_{tool_call_id[:8]}"
        # checkpoint_ns 此时是主 agent 的 ns(无 |),注册 mapping
        # 后续子 agent 事件 ns 形如 main_ns|...|...,取第一段查 map 命中
        state.checkpoint_to_agent[checkpoint_ns] = (instance_id, subagent_type)
        state.active_subagent = (instance_id, subagent_type)
        # 主 agent 的 task 工具调用(先于子 agent 块出现,前端 handleToolEvent
        # 按 function==task 标 delegated_to,在主 agent 时间线显示「委派给 X」)
        fn_args = args if isinstance(args, dict) else {"input": args}
        out.append({"event": "tool_call", "data": {
            "tool_call_id": tool_call_id,
            "batch_id": batch_id,
            "function": name,
            "args": _truncate_tool_args(fn_args),
            "description": f"{name}: {json.dumps(fn_args, ensure_ascii=False, default=str)[:200]}",
            "tool_meta": protocol.get_tool_meta(name),
            "agent_id": agent_id, "depth": depth,
        }})
        out.append({"event": "agent_call", "data": {
            "agent_id": instance_id,
            "subagent_type": subagent_type,
            "depth": depth,
            "description": description,
            "parent_tool_call_id": tool_call_id,
        }})
        return out

    # write_todos 工具 → plan_update(工具回调直出)
    # 子 agent middleware 由 deepagents 内部持有,runner 无 handle;
    # write_todos 属普通工具调用,on_tool_start 时 args 已含 todos。
    if name == "write_todos" and isinstance(args, dict):
        todos = args.get("todos")
        if todos and todos != state.current_todos:
            state.current_todos = todos
            plan_steps = _todos_to_plan_steps(todos)
            out.append({"event": "plan_update", "data": {
                "plan": plan_steps,
                "agent_id": agent_id, "depth": depth,
            }})

    # 普通 tool_call(含 write_todos — 前端要看到调用)
    fn_args = args if isinstance(args, dict) else {"input": args}
    out.append({"event": "tool_call", "data": {
        "tool_call_id": tool_call_id,
        "batch_id": batch_id,
        "function": name,
        "args": _truncate_tool_args(fn_args),
        "description": f"{name}: {json.dumps(fn_args, ensure_ascii=False, default=str)[:200]}",
        "tool_meta": protocol.get_tool_meta(name),
        "agent_id": agent_id, "depth": depth,
    }})
    return out


def _handle_tool_end(ev: Dict[str, Any], state: _StreamState, protocol) -> List[dict]:
    """on_tool_end → tool_result / agent_result。

    task 工具 → agent_result(子 agent 结束)+ tool_result 回传 + 清理 mapping。
    """
    out: List[dict] = []
    ev_name = ev.get("name", "")
    ev_meta = ev.get("metadata") or {}
    ev_data = ev.get("data") or {}
    checkpoint_ns = ev_meta.get("langgraph_checkpoint_ns") or ""
    agent_id, depth = _resolve_agent_context(checkpoint_ns, state.checkpoint_to_agent)

    tool_call_id = ev_data.get("tool_call_id") or ev.get("run_id", "")
    name = ev_name
    output = ev_data.get("output")
    output_str = _safe_str_v2(output, 3000)

    # A1: 从 _handle_tool_start 记录的开始时间计算耗时
    _start = state.tool_start_times.pop(tool_call_id, None) if tool_call_id else None
    duration_ms = int((time.time() - _start) * 1000) if _start else None
    # 取出 start 时缓存的 batch_id,保证 calling/called 一致(含历史回放场景)
    batch_id = state.tool_batch_ids.pop(tool_call_id, None) if tool_call_id else None

    # task 工具 → agent_result(子 agent 结束)
    if name == "task":
        instance_id, subagent_type = state.checkpoint_to_agent.get(
            checkpoint_ns, ("subagent", "general-purpose"),
        )
        out.append({"event": "agent_result", "data": {
            "agent_id": instance_id,
            "subagent_type": subagent_type,
            "depth": depth,
            "result": output_str[:2000],
            "parent_tool_call_id": tool_call_id,
        }})
        # 主 agent 的 task 工具结果(子 agent 返回值回传,前端把 task 标 called)
        out.append({"event": "tool_result", "data": {
            "tool_call_id": tool_call_id,
            "batch_id": batch_id,
            "function": name,
            "content": output_str,
            "duration_ms": duration_ms,
            "tool_meta": protocol.get_tool_meta(name),
            "agent_id": agent_id, "depth": depth,
        }})
        # 清理 mapping(顺序执行模式下安全;并发会冲突,但 deepagents 不并发)
        state.checkpoint_to_agent.pop(checkpoint_ns, None)
        state.active_subagent = None
        # 子 agent 返回结果记入对话日志（与普通工具统一编号格式）
        state.tool_step_counter += 1
        _summary = output_str[:1500] if output_str else "(空)"
        state.messages_log.append(f"[工具返回 #{state.tool_step_counter}] {name}: {_summary}")
        return out

    # 普通工具返回记入对话日志
    # write_todos 是计划更新，前端 tool_steps 已排除，judge 也不需要看返回值
    if name != "write_todos":
        state.tool_step_counter += 1
        _summary = output_str[:1500] if output_str else "(空)"
        state.messages_log.append(f"[工具返回 #{state.tool_step_counter}] {name}: {_summary}")

    out.append({"event": "tool_result", "data": {
        "tool_call_id": tool_call_id,
        "batch_id": batch_id,
        "function": name,
        "content": output_str,
        "duration_ms": duration_ms,
        "tool_meta": protocol.get_tool_meta(name),
        "agent_id": agent_id, "depth": depth,
    }})

    # optimize_dispatch 求解成功 → 存 artifact + 发独立 dispatch_preview 事件
    # (完整 schedule+summary 不依赖 LLM 手打 JSON 块:工具结果 3000 字符
    # 截断对 artifact 通道不生效,走独立事件不占 message 预算)
    if name == "optimize_dispatch":
        artifact = _extract_dispatch_artifact(output)
        if artifact is not None:
            session_id = getattr(state, "session_id", None) or ""
            if session_id:
                try:
                    from emsclaw_backend.service import dispatch_artifact
                    dispatch_artifact.store(session_id, artifact)
                except Exception:
                    pass
            out.append({"event": "dispatch_preview", "data": {
                "tool_call_id": tool_call_id,
                "result": artifact,
            }})

    return out


def _extract_dispatch_artifact(output: Any) -> dict | None:
    """从工具原始 output 里提取 status=ok 的完整 result dict。

    output 可能是 dict(langchain 保留原始返回)、str(JSON)、或 ToolMessage。
    非 ok / 解析失败 → None(不存 artifact,不发事件)。
    """
    if output is None:
        return None
    obj = output
    # ToolMessage / 带 content 属性的对象 → 取 content
    if not isinstance(obj, (dict, list, str)):
        content = getattr(obj, "content", None)
        if isinstance(content, str):
            obj = content
        elif isinstance(content, list):
            # content 是 block 列表,取第一个 text
            for b in content:
                if isinstance(b, dict) and b.get("text"):
                    obj = b["text"]
                    break
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except Exception:
            return None
    if not isinstance(obj, dict):
        return None
    if obj.get("status") != "ok":
        return None
    if "schedule" not in obj or "summary" not in obj:
        return None
    return obj


# ───────────────────────────────────────────────────────────────────
# v2 主执行器
# ───────────────────────────────────────────────────────────────────


def _build_and_write_trace_io(
    state: _StreamState, query: str, mode: str, lf_handler: Any = None
) -> None:
    """构建格式化对话日志并写入 Langfuse（trace IO + evaluator 专用 observation）。

    必须在 trace_attributes() context 内调用（即 _lf_trace.__exit__ 之前），
    否则 set_trace_io / create_eval_observation 找不到 active trace。

    lf_handler: LangChain CallbackHandler 实例。stream 结束后 OTel context 里的
    active span 可能已 end（get_current_trace_id 返回 None），此时从
    handler.last_trace_id 拿当前对话的 trace id，显式传给 create_eval_observation
    以确保 eval-data observation 挂到正确的 trace。
    """
    _log_text = "\n\n".join(state.messages_log) if state.messages_log else ""
    # 清洗 AI 思考内容，避免干扰 judge 评估（judge 只需看工具调用+结果，不需要看 AI 内心独白）
    _log_text = re.sub(r"\[AI 思考\]\n.*?(\n\[调用工具\]|$)", r"\1", _log_text, flags=re.DOTALL)
    _final = state.final_content or "No response generated."
    if _log_text:
        _lf_output = f"【用户输入】\n{query}\n\n【对话过程】\n{_log_text}\n\n【最终回复】\n{_final}"
    else:
        _lf_output = f"【用户输入】\n{query}\n\n【最终回复】\n{_final}"

    # 从 CallbackHandler 拿当前对话的 trace id（stream 结束后 OTel context 可能已丢）
    trace_id: Optional[str] = None
    if lf_handler is not None:
        trace_id = getattr(lf_handler, "last_trace_id", None)

    # trace-level IO（兼容性保留，其他消费者如前端可能用到）
    set_trace_io(input=query, output=_lf_output)
    # evaluator 专用 observation（Langfuse v4 evaluator 读 observation.output）
    # 显式传 trace_id 确保 eval-data observation 挂到当前对话的 trace
    create_eval_observation(query, _lf_output, trace_id=trace_id)
    logger.debug(
        f"[v2/{mode}] Trace output written: {len(_lf_output)} chars, "
        f"log entries: {len(state.messages_log)}, trace_id={trace_id or 'unknown'}"
    )


async def _arun_v2_stream(
    session: "AgentSession", query: str, attachments: Optional[List[str]] = None,
    language: Optional[str] = None,
    mode: str = "business",
    resume_command: Optional[Command] = None,
) -> AsyncGenerator[dict, None]:
    """v2 SSE 流执行器。

    用 astream_events(version="v2") 驱动。带 checkpointer(AsyncPostgresSaver),
    从 thread_id 恢复完整 state → 只传当前 query,不手动拼 history。
    走 interrupt/HITL 检测 + auto_approve 流(B2/B3/B4);resume_command 透传。

    共用能力:
      - 子 agent 事件区分(LambCheck checkpoint_ns 映射)
      - task 工具特殊路由到 agent_call/agent_result(LambChat processor.py:220-230)
      - token usage 从 on_chat_model_end 抽(LambChat stream.py:147-214)
      - write_todos 工具 on_tool_start 时直接发 plan_update
      - durability="exit"(有 checkpointer,stream exit 写 state)

    B2(本 task):准备 interrupt 检测 + 持久化 HITL payload。
    B3:resume_command 入口 — 跳过初始事件,合成 approval_decided。
    B4:auto_approve_all — 在 stream 内遇到 interrupt 直接合成 approve Command 继续流。
    """
    stream_start_time = time.time()
    is_resume = resume_command is not None
    # B4:auto_approve flag(由 C5 endpoint 写入 session.model_config["auto_approve"])。
    # AG3NT 是内存 only 会丢;emsclaw 走 model_config JSONB 跨重启保留。
    auto_approve = bool((getattr(session, "model_config", None) or {}).get("auto_approve", False))

    # ---- 加载用户任务设置 ----
    user_id = getattr(session, "user_id", None)
    task_cfg: TaskSettings = await get_task_settings(user_id) if user_id else TaskSettings()

    # ---- 创建 agent + 中间件(会话级隔离)----
    agent, middleware, context_window, diagnostic = await deep_agent(
        session_id=session.session_id,
        model_config=getattr(session, "model_config", None),
        user_id=user_id,
        task_settings=task_cfg,
        diagnostic_enabled=DIAGNOSTIC_ENABLED,
        language=language,
        mode=mode,
    )
    middleware.clear()

    state = _StreamState()
    state.session_id = session.session_id

    # ---- 初始事件(仅非 resume 路径;resume 不重发 step_start/plan_update)----
    if not is_resume:
        yield {"event": "thinking", "data": {"content": ""}}
        state.plan = _build_plan(query[:200])
        step = state.plan[0]
        yield {"event": "step_start", "data": {"step": step}}
        state.plan = normalize_plan_steps([{**step, "status": "in_progress"}])
        yield {"event": "plan_update", "data": {"plan": _plan_for_frontend(state.plan)}}

    logger.info(
        f"[v2/{mode}] session={session.session_id}, thread_id={session.thread_id}, "
        f"context_window={context_window:,}, max_tokens={task_cfg.max_tokens:,}, "
        f"is_resume={is_resume}, auto_approve={auto_approve}"
    )

    # ---- 构造 input ----
    # 靠 checkpointer 从 thread_id 恢复完整 state → 只传当前 query,
    # 再传 history 会让模型看到重复上下文(Gotcha #3)。
    if not is_resume:
        enriched_query = query
        if attachments:
            file_list = "\n".join(f"  - {p}" for p in attachments)
            enriched_query = (
                f"{query}\n\n"
                f"[The user has uploaded the following files to the workspace. "
                f"You can read them directly using their absolute paths:\n{file_list}]"
            )
        current_input: Any = {"messages": [HumanMessage(content=enriched_query)]}
        if diagnostic:
            diagnostic.save_initial_input(current_input["messages"])
    else:
        # B3:resume — 合成 approval_decided(demo event_processor.py:7-8:resume 本身不是 v2 事件)
        # 从 resume_command 解析 interrupt_id + decision type 给前端
        ri_id, ri_decision = _extract_resume_meta(resume_command)
        yield {"event": "approval_decided", "data": {
            "interrupt_id": ri_id,
            "decision": ri_decision,
        }}
        current_input = resume_command

    from emsclaw_backend.deepagent.sse_protocol import get_protocol_manager
    protocol = get_protocol_manager()

    # ---- astream_config:thread_id 让 checkpointer 持久化 + 跨重启恢复 ----
    astream_config = {"configurable": {"thread_id": session.thread_id}}
    # recursion_limit 必须显式传：astream_events v2 不合并图 bound config(9999)，
    # 会落回 LangGraph 默认 25；主图多轮分派容易撞 GraphRecursionError。
    astream_config["recursion_limit"] = settings.agent_recursion_limit
    _callbacks = []
    if diagnostic:
        _callbacks.append(diagnostic.get_callback_handler())
    _lf_handler = get_langfuse_handler()
    if _lf_handler is not None:
        _callbacks.append(_lf_handler)
    if _callbacks:
        astream_config["callbacks"] = _callbacks

    _stream_ok = True
    _should_write_trace = True  # 正常完成时写入 trace IO；interrupt / timeout 时不写
    # 本次对话的 Langfuse trace id（finally 里捕获后随 statistics 下发前端；
    # 前端点赞/踩要靠它把反馈 score 挂到正确的 trace 上）
    _lf_trace_id: Optional[str] = None

    STREAM_TIMEOUT = task_cfg.agent_stream_timeout

    # Langfuse：把本次（含 auto-approve 多轮 resume）trace 关联到会话 / 用户
    _lf_trace = trace_attributes(
        session_id=session.session_id, user_id=user_id,
        mode=mode, query=query,
    )
    _lf_trace.__enter__()

    try:
        # B4:outer while 用于 auto_approve 自动重试 — stream 遇到 interrupt 时
        # 不交给用户,合成 approve Command 重启 stream 直到真的结束。
        # durability="exit":checkpointer 在 stream exit 写 state。
        while True:
            async with asyncio.timeout(STREAM_TIMEOUT):
                async for ev in agent.astream_events(
                    current_input, config=astream_config, version="v2",
                    durability="exit",
                ):
                    if session.is_cancelled():
                        _stream_ok = False
                        _should_write_trace = False  # 用户取消，不写 trace IO
                        logger.info(f"Session cancelled during v2/{mode} execution")
                        yield {"event": "error", "data": {"message": "Session stopped by user"}}
                        return

                    ev_type = ev.get("event", "")

                    # ── drain 主 middleware 事件 ──
                    async for mw_evt in _drain_middleware(middleware, state):
                        yield mw_evt

                    # ── on_chat_model_stream → thinking ──
                    if ev_type == "on_chat_model_stream":
                        for evt in _handle_chat_model_stream(ev, state):
                            yield evt
                        continue

                    # ── on_chat_model_end → token usage + final_content ──
                    if ev_type == "on_chat_model_end":
                        for evt in _handle_chat_model_end(ev, state, middleware):
                            yield evt
                        continue

                    # ── on_tool_start ──
                    if ev_type == "on_tool_start":
                        for evt in _handle_tool_start(ev, state, protocol):
                            yield evt
                        continue

                    # ── on_tool_end ──
                    if ev_type == "on_tool_end":
                        for evt in _handle_tool_end(ev, state, protocol):
                            yield evt
                        continue

                    # ── on_chain_end with __interrupt__ → B2 处理(task #12)──
                    # B1 暂不处理;interrupt 通过流结束后 agent.get_state(config).tasks 检测(B2)。
            # ===== B2: detect interrupts after stream ends =====

            # emsclaw 用 AsyncPostgresSaver(非 AG3NT 的 sync SqliteSaver),必须用 aget_state
            # (sync get_state 在主线程会抛 InvalidStateError)。interrupt.value 是 dict
            # (AG3NT _HITL_REQUEST_ADAPTER schema):
            #   {action_requests: [{name, args, description}], review_configs: [{action_name, allowed_decisions}]}
            try:
                _state = await agent.aget_state(astream_config)
            except Exception as _state_err:
                logger.warning(f"[v2/{mode}] aget_state failed: {_state_err!r}")
                _state = None

            _pending_interrupts: List[Any] = []
            if _state is not None:
                for _task_obj in getattr(_state, "tasks", None) or []:
                    for _intr in (getattr(_task_obj, "interrupts", None) or []):
                        # 收集 (task_obj, intr) 元组,后续反查父子 agent attribution
                        _pending_interrupts.append((_task_obj, _intr))

            if not _pending_interrupts:
                logger.debug(f"[v2/{mode}] stream ended without pending interrupts")
                break  # stream 真正结束 -> 走收尾

            # 通常只有一个 interrupt;collect 所有保证完整
            logger.info(
                f"[v2/{mode}] detected {len(_pending_interrupts)} pending interrupt(s); "
                f"auto_approve={auto_approve}"
            )

            # 取第一个 interrupt 作 resume 目标(deepagents 单 interrupt 是常见路径)
            _first_task, _first_intr = _pending_interrupts[0]
            _intr_id = getattr(_first_intr, "ns_id", "") or getattr(_first_intr, "id", "")
            _intr_value = getattr(_first_intr, "value", None) or {}
            if not isinstance(_intr_value, dict):
                _intr_value = {"raw": str(_intr_value)}
            _action_requests = _intr_value.get("action_requests", [])
            # 反查父子 agent attribution(供 ApprovalRecord 持久化用)
            _parent_agent, _subagent_type, _subagent_inst = _resolve_interrupt_agent_context(
                _first_task, state.checkpoint_to_agent, state.active_subagent,
            )

            if auto_approve:
                # B4:auto_approve_all — 合成 approve Command 继续流(AG3NT deepagents_daemon.py:821-831)
                # 对每个 action_request 一个决策(AG3NT deepagents_daemon.py:568-570)。
                _decisions = [{"type": "approve"} for _ in _action_requests] or [{"type": "approve"}]
                # 合成 approval_decided 让前端看到 auto-approval
                yield {"event": "approval_decided", "data": {
                    "interrupt_id": _intr_id,
                    "decision": "approve",
                    "auto": True,
                    "parent_agent": _parent_agent,
                    "subagent_type": _subagent_type,
                    "subagent_instance_id": _subagent_inst,
                }}
                current_input = Command(resume={_intr_id: {"decisions": _decisions}})
                # 清空 todos 缓存让新一轮 stream 重新填充
                state.current_todos = []
                continue  # outer while — 用 resume Command 重启 stream

            # 非 auto_approve:yield approval_required 给每个 interrupt,然后 return
            # session.status 由 C4(sessions.py finally 块)标 RUNNING/AWAITING_APPROVAL。
            for _task_obj, _intr in _pending_interrupts:
                _iid = getattr(_intr, "ns_id", "") or getattr(_intr, "id", "")
                _iv = getattr(_intr, "value", None) or {}
                if not isinstance(_iv, dict):
                    _iv = {"raw": str(_iv)}
                _pa, _st, _si = _resolve_interrupt_agent_context(
                    _task_obj, state.checkpoint_to_agent, state.active_subagent,
                )
                state.pending_interrupts_yielded.append(_iid)
                yield {"event": "approval_required", "data": {
                    "interrupt_id": _iid,
                    "action_requests": _iv.get("action_requests", []),
                    "review_configs": _iv.get("review_configs", []),
                    "raw_value": _iv,
                    "parent_agent": _pa,
                    "subagent_type": _st,
                    "subagent_instance_id": _si,
                }}
            state.stream_terminated_by_interrupt = True
            _should_write_trace = False  # HITL 中断——trace 继续用于 resume，此时不写 eval 数据
            return  # awaiting approval — 跳过收尾;C5 resume 会启动新 stream

    except (asyncio.TimeoutError, TimeoutError):
        _stream_ok = False
        _should_write_trace = False
        logger.warning(f"[v2/{mode}] Stream timed out after {STREAM_TIMEOUT}s")
        yield {"event": "error", "data": {"message": f"Agent execution timed out after {STREAM_TIMEOUT}s"}}
    finally:
        # Langfuse trace IO + evaluator observation 必须在 __exit__ 之前写入
        if _should_write_trace:
            _build_and_write_trace_io(state, query, mode, lf_handler=_lf_handler)
        # 取本次 trace id：stream 结束后 OTel context 里的 active span 可能已 end，
        # 只有 CallbackHandler.last_trace_id 还留着本轮的 trace id
        if _lf_handler is not None:
            _lf_trace_id = getattr(_lf_handler, "last_trace_id", None)
        _lf_trace.__exit__(None, None, None)

    # ---- stream 结束后收尾(复用 v1 的 plan/status 收尾逻辑)----
    if state.current_todos:
        final_plan_steps = _todos_to_plan_steps(state.current_todos)
        if _stream_ok:
            for step in final_plan_steps:
                if step["status"] != "completed":
                    step["status"] = "completed"
        else:
            for step in final_plan_steps:
                if step["status"] not in ("completed", "pending"):
                    step["status"] = "failed"
        yield {"event": "plan_update", "data": {"plan": final_plan_steps}}
    else:
        end_status = "completed" if _stream_ok else "failed"
        # resume 路径(B3)不 build plan,plan 可能为空 -> 跳过 plan 收尾,只发 step_end
        if state.plan:
            state.plan = normalize_plan_steps([{**state.plan[0], "status": end_status}])
            session.set_plan(state.plan)
            yield {"event": "plan_update", "data": {"plan": _plan_for_frontend(state.plan)}}
    yield {"event": "step_end", "data": {"step_id": "S1"}}

    # ---- 最终回复 ----
    if state.final_content:
        yield {"event": "planning_message", "data": {"type": "assistant", "content": state.final_content}}
    elif state.last_thinking:
        logger.warning(f"[v2/{mode}] Model returned only thinking content, using as fallback")
        yield {"event": "planning_message", "data": {"type": "assistant", "content": state.last_thinking}}
    else:
        logger.warning(f"[v2/{mode}] Model returned empty response")
        yield {"event": "planning_message", "data": {"type": "assistant", "content": "No response generated."}}

    # ---- 统计信息 ----
    total_duration_ms = int((time.time() - stream_start_time) * 1000)
    mw_stats = middleware.get_statistics()
    logger.info(
        f"[v2/{mode}] Statistics: duration={total_duration_ms}ms, "
        f"tool_calls={mw_stats.get('total_tool_calls', 0)}, "
        f"input_tokens={mw_stats.get('input_tokens', 0)}, "
        f"cached_tokens={mw_stats.get('cached_tokens', 0)}, "
        f"output_tokens={mw_stats.get('output_tokens', 0)}"
    )
    yield {"event": "statistics", "data": {
        "total_duration_ms": total_duration_ms,
        "tool_call_count": mw_stats.get("total_tool_calls", 0),
        "total_tool_duration_ms": mw_stats.get("total_tool_duration_ms", 0),
        "input_tokens": mw_stats.get("input_tokens", 0),
        "cached_tokens": mw_stats.get("cached_tokens", 0),
        "output_tokens": mw_stats.get("output_tokens", 0),
        "token_count": mw_stats.get("total_tokens", 0),
        # Langfuse trace id：前端点赞/踩时回传，后端据此写 user_feedback score
        "trace_id": _lf_trace_id,
    }}

    if diagnostic:
        try:
            diagnostic.save_summary()
        except Exception:
            logger.warning("[Diagnostic] Failed to save summary", exc_info=True)


# ───────────────────────────────────────────────────────────────────
# 对外入口（drop-in replacement）
# ───────────────────────────────────────────────────────────────────

async def arun_agent_task_stream(
    session: AgentSession, query: str, attachments: Optional[List[str]] = None,
    language: Optional[str] = None,
    resume_command: Optional[Command] = None,
) -> AsyncGenerator[dict, None]:
    """对话任务流入口。所有 mode 都走 v2 流(_arun_v2_stream):

      - business:checkpointer 持久化 + HITL/审批;
        resume_command(B3):C5 resume endpoint 把 Command(resume={...}) 透传到此,
        内部跳过初始事件 + 合成 approval_decided。
      - 其他未知 mode(含历史 team_ops 会话):normalize 后落到 business(见 agents.normalize_mode)。
    """
    from emsclaw_backend.deepagent.agents import normalize_mode
    mode = normalize_mode(getattr(session, "mode", None))
    async for evt in _arun_v2_stream(
        session, query, attachments, language=language,
        mode=mode, resume_command=resume_command,
    ):
        yield evt
