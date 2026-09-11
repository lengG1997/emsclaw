"""
SSE 中间件兼容性回归测试 — deepagents 0.6.x。

锁定 SSEMonitoringMiddleware 与新 API 契约的兼容性，防止未来 deepagents
升级破坏该中间件。

覆盖点：
  - AgentMiddleware 继承关系
  - ToolCallRequest dataclass 解析（_extract_tool_info）
  - 字典格式向后兼容
  - wrap_tool_call / awrap_tool_call 同步异步路径
  - _handle_todos_change 事件触发
  - clear() 状态重置
"""
import asyncio

import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest

from emsclaw_backend.observability.sse_middleware import SSEMonitoringMiddleware


# ───────────────────────────────────────────────────────────────────
# 测试辅助
# ───────────────────────────────────────────────────────────────────

class FakeRuntime:
    """ToolCallRequest.runtime 的占位实现。"""


class FakeTool:
    """ToolCallRequest.tool 的占位实现（BaseTool 子类未必要）。"""


def _make_request(
    name: str = "terminal_execute",
    args: dict | None = None,
    call_id: str = "call_1",
) -> ToolCallRequest:
    """构造一个最小可用的 ToolCallRequest 实例。"""
    return ToolCallRequest(
        tool_call={"name": name, "args": args or {"q": "hi"}, "id": call_id, "type": "tool_call"},
        tool=FakeTool(),
        state={"messages": []},
        runtime=FakeRuntime(),
    )


@pytest.fixture
def middleware():
    """每次测试都得到一个干净的中间件实例。"""
    mw = SSEMonitoringMiddleware(agent_name="test_agent", verbose=False)
    yield mw
    mw.clear()


# ───────────────────────────────────────────────────────────────────
# 兼容性与继承
# ───────────────────────────────────────────────────────────────────

def test_init_succeeds_with_new_api(middleware):
    """SSEMonitoringMiddleware 必须继承自 AgentMiddleware，并能正常构造。"""
    assert isinstance(middleware, AgentMiddleware)
    assert middleware.agent_name == "test_agent"
    assert middleware.total_tool_calls == 0
    assert middleware.sse_events == []


# ───────────────────────────────────────────────────────────────────
# _extract_tool_info：同时支持 ToolCallRequest dataclass 与 dict
# ───────────────────────────────────────────────────────────────────

def test_extract_tool_info_with_toolcallrequest(middleware):
    """新 API：ToolCallRequest dataclass → 提取 (name, args, id)。"""
    req = _make_request(name="terminal_execute", args={"q": "hi"}, call_id="call_abc")
    name, args, call_id = middleware._extract_tool_info(req)
    assert name == "terminal_execute"
    assert args == {"q": "hi"}
    assert call_id == "call_abc"


def test_extract_tool_info_with_dict(middleware):
    """向后兼容：直接传入 dict → 同样能提取 (name, args, id)。"""
    req_dict = {"name": "write_todos", "args": {"todos": []}, "id": "call_xyz"}
    name, args, call_id = middleware._extract_tool_info(req_dict)
    assert name == "write_todos"
    assert args == {"todos": []}
    assert call_id == "call_xyz"


# ───────────────────────────────────────────────────────────────────
# wrap_tool_call / awrap_tool_call
# ───────────────────────────────────────────────────────────────────

def test_wrap_tool_call_sync(middleware):
    """同步路径：handler 被调用一次，发出 start + complete 两个事件。"""
    req = _make_request(name="terminal_execute", call_id="sync_call")
    handler_called = {"count": 0}

    def fake_handler(r):
        handler_called["count"] += 1
        return {"content": "result", "status": "ok"}

    result = middleware.wrap_tool_call(req, fake_handler)

    # handler 必须被调用一次
    assert handler_called["count"] == 1
    # handler 的返回值原样透传
    assert result == {"content": "result", "status": "ok"}
    # 统计已记录一次工具调用
    assert middleware.total_tool_calls == 1
    # 应该有 start + complete 两个事件
    events = middleware.drain_events()
    assert [e["event"] for e in events] == [
        "middleware_tool_start",
        "middleware_tool_complete",
    ]
    assert events[0]["data"]["function"] == "terminal_execute"
    assert events[0]["data"]["tool_call_id"] == "sync_call"
    assert events[1]["data"]["tool_call_id"] == "sync_call"


def test_awrap_tool_call_async(middleware):
    """异步路径：handler 被 await 一次，发出 start + complete 事件。"""
    req = _make_request(name="async_tool", call_id="async_call")
    handler_called = {"count": 0}

    async def fake_async_handler(r):
        handler_called["count"] += 1
        return "async_result"

    result = asyncio.run(middleware.awrap_tool_call(req, fake_async_handler))

    assert handler_called["count"] == 1
    assert result == "async_result"
    assert middleware.total_tool_calls == 1
    events = middleware.drain_events()
    assert [e["event"] for e in events] == [
        "middleware_tool_start",
        "middleware_tool_complete",
    ]
    assert events[0]["data"]["function"] == "async_tool"


# ───────────────────────────────────────────────────────────────────
# _handle_todos_change
# ───────────────────────────────────────────────────────────────────

def test_handle_todos_change_emits_event(middleware):
    """write_todos 触发后，发出 middleware_todos_update 事件。"""
    new_todos = [
        {"content": "task A", "status": "pending"},
        {"content": "task B", "status": "in_progress"},
    ]
    middleware._handle_todos_change({"todos": new_todos})

    events = middleware.drain_events()
    assert len(events) == 1
    assert events[0]["event"] == "middleware_todos_update"
    assert events[0]["data"]["todos"] == new_todos
    assert events[0]["data"]["agent"] == "test_agent"
    # todos_log 也应被记录
    assert len(middleware.todos_log) == 1


# ───────────────────────────────────────────────────────────────────
# clear()
# ───────────────────────────────────────────────────────────────────

def test_clear_resets_state(middleware):
    """clear() 必须重置计数器、事件、日志与 previous_todos。"""
    # 先产生一些状态
    req = _make_request()
    middleware.wrap_tool_call(req, lambda r: "x")
    middleware._handle_todos_change({"todos": [{"content": "t", "status": "pending"}]})
    middleware.add_tokens(input_tokens=10, output_tokens=5)

    assert middleware.total_tool_calls == 1
    assert middleware.total_tool_duration_ms >= 0
    assert len(middleware.sse_events) > 0
    assert len(middleware.tool_calls_log) > 0
    assert len(middleware.todos_log) > 0
    assert middleware.input_tokens == 10
    assert middleware.output_tokens == 5

    middleware.clear()

    assert middleware.total_tool_calls == 0
    assert middleware.total_tool_duration_ms == 0
    assert middleware.sse_events == []
    assert middleware.tool_calls_log == []
    assert middleware.todos_log == []
    assert middleware.previous_todos == []
    assert middleware.input_tokens == 0
    assert middleware.output_tokens == 0
    assert middleware.cached_tokens == 0