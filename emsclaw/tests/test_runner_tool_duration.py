"""A1: runner 把 duration_ms 塞进 tool_result 事件。"""
from emsclaw_backend.deepagent.runner import _StreamState, _handle_tool_start, _handle_tool_end


def _ev(name: str, tool_call_id: str, input_=None, output=None):
    return {
        "name": name,
        "data": {"tool_call_id": tool_call_id, "input": input_ or {}, "output": output},
        "metadata": {"langgraph_checkpoint_ns": ""},
    }


class _Protocol:
    def get_tool_meta(self, name):
        return {"name": name, "icon": "🔧", "category": "misc", "description": ""}


def test_tool_result_carries_duration_ms():
    state = _StreamState()
    proto = _Protocol()
    tid = "call_123"

    # on_tool_start -> 记录 start_time + 产出 tool_call
    start_events = _handle_tool_start(_ev("get_device", tid, {"device_id": "d1"}), state, proto)
    assert any(e["event"] == "tool_call" for e in start_events)
    assert tid in state.tool_start_times

    # on_tool_end -> 产出 tool_result 且含 duration_ms
    end_events = _handle_tool_end(_ev("get_device", tid, output="ok"), state, proto)
    tool_result = [e for e in end_events if e["event"] == "tool_result"][0]
    assert tool_result["data"]["duration_ms"] is not None
    assert isinstance(tool_result["data"]["duration_ms"], int)
    # start_time 已被 pop
    assert tid not in state.tool_start_times


def test_task_tool_result_carries_duration_ms():
    state = _StreamState()
    proto = _Protocol()
    tid = "call_task_1"
    _handle_tool_start(_ev("task", tid, {"subagent_type": "search", "description": "q"}), state, proto)
    end_events = _handle_tool_end(_ev("task", tid, output="done"), state, proto)
    # task 分支产出 agent_result + tool_result，两者都要有；这里只验 tool_result
    tool_results = [e for e in end_events if e["event"] == "tool_result"]
    assert tool_results
    assert tool_results[0]["data"]["duration_ms"] is not None
