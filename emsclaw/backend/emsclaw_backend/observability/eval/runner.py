"""eval — 生产 Lead Agent 离线评估执行器(非 SSE,内部调用)。

把**生产 business Lead Agent**(``build_business_agent``)当作 Langfuse ``run_experiment``
的 task 函数实现 —— 跑一条测试用例,产出结构化 ``EvalResult``:
  - ``response``:最终文本回复
  - ``tool_trace``:有序 + 带子 agent 归属的工具调用序列(供 5 个通用 Code evaluator 判定)
  - ``delegates``:子 agent 派发记录(供 subagent 路由维度判定)
  - ``tool_calls``:扁平化的工具调用列表(向后兼容,= tool_trace 的简化版)

为什么用生产 Lead 而不是新造 eval Agent:Langfuse SDK 的 ``run_experiment`` task
函数是 ``(*, item, **kwargs) -> Any``,SDK 不规定 task 内部跑什么,只把返回值原样
传给 evaluator 并自动 trace。task 函数应该就是**生产 agent 的薄包装**,不要新造 agent。
跑生产 Lead 才能复现"Lead 不路由子 agent 自己 write_file→execute 反复试错"这类
真实失败模式 —— 简化 agent 没子 agent、没 ``task`` 工具、看不到域技能路径,测不到。

与 ``runner._arun_v2_stream`` 的差异:
  - 用 ``build_business_agent()`` 创建生产 Lead(含 4 个领域子 agent)
  - ``checkpointer=None``:离线评估不持久化状态,跑完即丢
  - 不 yield SSE 事件,直接收集全部输出
  - 用 ``astream_events(version="v2")`` + ``ToolTraceCollector`` 拿子 agent attribution
    (与 runner.py 共用 ``_resolve_agent_context`` + ``checkpoint_to_agent`` mapping)
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger
from langchain_core.messages import HumanMessage

from emsclaw_backend.config import settings
from emsclaw_backend.deepagent.agents.business.factory import build_business_agent
from emsclaw_backend.task_settings import TaskSettings
from ..sdk import get_langfuse_handler
from .tool_trace import ToolTraceCollector


@dataclass
class EvalResult:
    """单个 eval 测试用例的执行结果。"""
    prompt: str
    response: str = ""
    # 扁平化(向后兼容):每条 {name, args?, result?}
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    # 有序 + 带子 agent 归属(供 evaluator 判定)
    tool_trace: List[Dict[str, Any]] = field(default_factory=list)
    # 子 agent 派发记录
    delegates: List[Dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    error: Optional[str] = None


async def run_eval_task(
    session_id: str,
    query: str,
    model_config: Optional[Dict[str, Any]] = None,
    timeout: int = 300,
    user_id: str = "eval_runner",
) -> EvalResult:
    """用生产 business Lead Agent 跑一条 query,收集完整输出。

    用 ``astream_events(version="v2")`` + ``ToolTraceCollector`` 收集:
      - 有序 tool_trace(带子 agent 归属)
      - delegates(子 agent 派发记录)
      - final_content(最终文本回复)
      - token usage(从 on_chat_model_end 抽)

    Args:
        session_id: 用于 sandbox 隔离与 trace 关联
        query: 用户提问(= dataset item 的 input.query)
        model_config: 可选模型配置覆写
        timeout: 单条超时(秒)
        user_id: sandbox 用户隔离用,默认 "eval_runner"
    """
    start_time = time.time()
    result = EvalResult(prompt=query)

    try:
        # 用生产 business Lead,checkpointer=None:离线评估不持久化、跑完即丢
        agent, sse, _context_window, _extra = await build_business_agent(
            session_id=session_id,
            user_id=user_id,
            model_config=model_config,
            task_settings=TaskSettings(),
            checkpointer=None,
        )
        sse.clear()

        collector = ToolTraceCollector()
        input_messages = {"messages": [HumanMessage(content=query)]}

        _eval_callbacks = []
        _lf_handler = get_langfuse_handler()
        if _lf_handler is not None:
            _eval_callbacks.append(_lf_handler)
        astream_config = {
            "configurable": {"thread_id": session_id},
        }
        # 同 runner.py:astream_events v2 不合并图 bound config，需显式传 recursion_limit
        astream_config["recursion_limit"] = settings.agent_recursion_limit
        if _eval_callbacks:
            astream_config["callbacks"] = _eval_callbacks

        try:
            async with asyncio.timeout(timeout):
                async for ev in agent.astream_events(
                    input_messages,
                    config=astream_config,
                    version="v2",
                    durability="exit",
                ):
                    collector.handle(ev)
        except (asyncio.TimeoutError, TimeoutError):
            result.error = f"Eval timed out after {timeout}s"

        result.response = collector.final_content or collector.last_thinking or ""
        result.tool_trace = collector.tool_trace
        result.delegates = collector.delegates
        # 扁平化兼容字段:name + args + result(从 tool_trace 抽,只取 complete 阶段)
        result.tool_calls = [
            {
                "name": e.get("name", ""),
                "args": e.get("args", {}),
                "result": e.get("result", ""),
            }
            for e in collector.tool_trace
            if e.get("phase") == "complete"
        ]
        result.input_tokens = collector.input_tokens
        result.output_tokens = collector.output_tokens
        result.cached_tokens = collector.cached_tokens

    except Exception as exc:
        logger.exception(f"[EvalRunner] Failed for session={session_id}")
        result.error = f"{type(exc).__name__}: {exc}"

    result.duration_ms = int((time.time() - start_time) * 1000)
    return result
