"""ToolTraceCollector — eval 流的 tool_trace + delegates 收集器。

监听 ``astream_events(version="v2")`` 事件,产出一个**有序、带子 agent 归属**
的 ``tool_trace`` 列表(供 5 个通用 Code evaluator 判定)。

与 ``emsclaw_backend/deepagent/runner.py`` 的差异:
  - runner.py 的 ``_handle_tool_start``/``_handle_tool_end`` 产 SSE 事件(给前端)。
  - 本 collector 不产 SSE,只产结构化 ``tool_trace`` dict 列表(给 evaluator)。
  - 共用的子 agent attribution 逻辑(``_resolve_agent_context`` + ``checkpoint_to_agent``
    mapping)直接复用 ``stream_utils._resolve_agent_context``,不重复实现。

子 agent mapping 逻辑(与 runner.py 一致):
  - task 工具 ``on_tool_start`` → 注册 ``checkpoint_to_agent[main_ns] = (instance_id, subagent_type)``
    + 记 delegate。
  - 后续子 agent 的工具事件 ``metadata.langgraph_checkpoint_ns`` 形如 ``main_ns|...``,
    取第一段查 map 命中 → 拿到 ``instance_id`` + ``subagent_type``。
  - task 工具 ``on_tool_end`` → 清理 mapping + delegate 收尾。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage

from emsclaw_backend.deepagent.stream_utils import (
    _extract_thinking,
    _extract_token_usage,
    _resolve_agent_context,
    _safe_str_v2,
    _truncate_tool_args,
)


@dataclass
class ToolTraceCollector:
    """收集有序 tool_trace + delegates + 最终文本 + token 统计。

    用法:
        collector = ToolTraceCollector()
        async for ev in agent.astream_events(input, config=config, version="v2", durability="exit"):
            collector.handle(ev)
        # collector.tool_trace / collector.delegates / collector.final_content / collector.tokens
    """

    # tool_call_id -> 开始时间(算 duration_ms)
    tool_start_times: Dict[str, float] = field(default_factory=dict)
    # checkpoint_ns -> (instance_id, subagent_type),与 runner.py 一致
    checkpoint_to_agent: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    active_subagent: Optional[Tuple[str, str]] = None

    # 产出
    tool_trace: List[Dict[str, Any]] = field(default_factory=list)
    delegates: List[Dict[str, str]] = field(default_factory=list)
    final_content: str = ""
    last_thinking: str = ""

    # token 累计(从 on_chat_model_end 抽,与 runner.py 一致)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    def handle(self, ev: Dict[str, Any]) -> None:
        """分发 v2 事件到对应 handler。"""
        ev_type = ev.get("event", "")
        if ev_type == "on_tool_start":
            self._on_tool_start(ev)
        elif ev_type == "on_tool_end":
            self._on_tool_end(ev)
        elif ev_type == "on_chat_model_end":
            self._on_chat_model_end(ev)

    # ── on_chat_model_end → token usage + final_content 捕获 ──

    def _on_chat_model_end(self, ev: Dict[str, Any]) -> None:
        """与 runner.py 的 _handle_chat_model_end 一致:抽 token + 捕获最终文本。

        final_content = 没有 tool_calls 的 AIMessage 的 clean text(即最终回复)。
        """
        ev_data = ev.get("data") or {}
        output = ev_data.get("output")
        if output is None:
            return
        token_info = _extract_token_usage(output)
        if token_info["input_tokens"] or token_info["output_tokens"]:
            self.input_tokens += token_info["input_tokens"]
            self.output_tokens += token_info["output_tokens"]
            self.cached_tokens += token_info.get("cached_tokens", 0)
        if isinstance(output, AIMessage) and not getattr(output, "tool_calls", None):
            _thinking, _clean = _extract_thinking(output)
            if _thinking:
                self.last_thinking = _thinking
            if _clean:
                self.final_content = _clean

    # ── on_tool_start / on_tool_end → tool_trace + delegates ──

    def _on_tool_start(self, ev: Dict[str, Any]) -> None:
        ev_name = ev.get("name", "")
        ev_meta = ev.get("metadata") or {}
        ev_data = ev.get("data") or {}
        checkpoint_ns = ev_meta.get("langgraph_checkpoint_ns") or ""
        agent_id, depth = _resolve_agent_context(checkpoint_ns, self.checkpoint_to_agent)

        tool_call_id = ev_data.get("tool_call_id") or ev.get("run_id", "")
        name = ev_name
        if tool_call_id:
            self.tool_start_times[tool_call_id] = time.time()
        args = ev_data.get("input") or {}

        # task 工具 → 注册子 agent + 记 delegate(不进 tool_trace,因为它本身是路由工具)
        if name == "task":
            subagent_type = "general-purpose"
            if isinstance(args, dict):
                subagent_type = args.get("subagent_type") or subagent_type
            description = args.get("description", "") if isinstance(args, dict) else ""
            instance_id = f"{subagent_type}_{tool_call_id[:8]}"
            self.checkpoint_to_agent[checkpoint_ns] = (instance_id, subagent_type)
            self.active_subagent = (instance_id, subagent_type)
            self.delegates.append({
                "subagent_type": subagent_type,
                "instance_id": instance_id,
                "description": description,
                "tool_call_id": tool_call_id,
                "ts": time.time(),
            })
            return

        # 普通工具 → 进 tool_trace(有序)
        fn_args = args if isinstance(args, dict) else {"input": args}
        # 子 agent 归属:从 active_subagent 取(若有);否则 None(主 agent)
        subagent_type = self.active_subagent[1] if self.active_subagent else None
        self.tool_trace.append({
            "agent": "DeepAgent" if subagent_type else "EvalAgent",
            "parent_agent": None,
            "subagent_type": subagent_type,
            "agent_id": agent_id,
            "depth": depth,
            "name": name,
            "args": _truncate_tool_args(fn_args),
            "tool_call_id": tool_call_id,
            "start_time": self.tool_start_times.get(tool_call_id),
            "ts": time.time(),
            "phase": "start",
        })

    def _on_tool_end(self, ev: Dict[str, Any]) -> None:
        ev_name = ev.get("name", "")
        ev_meta = ev.get("metadata") or {}
        ev_data = ev.get("data") or {}
        checkpoint_ns = ev_meta.get("langgraph_checkpoint_ns") or ""

        tool_call_id = ev_data.get("tool_call_id") or ev.get("run_id", "")
        name = ev_name
        output = ev_data.get("output")
        output_str = _safe_str_v2(output, 3000)

        _start = self.tool_start_times.pop(tool_call_id, None) if tool_call_id else None
        duration_ms = int((time.time() - _start) * 1000) if _start else None

        # task 工具 → 清理 mapping + delegate 收尾(不进 tool_trace)
        if name == "task":
            self.checkpoint_to_agent.pop(checkpoint_ns, None)
            self.active_subagent = None
            # 给最近的 delegate 补 end 信息
            for d in reversed(self.delegates):
                if d.get("tool_call_id") == tool_call_id and "duration_ms" not in d:
                    d["duration_ms"] = duration_ms
                    d["end_ts"] = time.time()
                    break
            return

        # 普通工具 → 找到对应 start 条目,补 result + duration_ms
        for entry in reversed(self.tool_trace):
            if entry.get("tool_call_id") == tool_call_id and entry.get("phase") == "start":
                entry["result"] = output_str
                entry["duration_ms"] = duration_ms
                entry["phase"] = "complete"
                break

    # ── 统计 ──

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "tool_call_count": len(self.tool_trace),
            "delegate_count": len(self.delegates),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
        }
