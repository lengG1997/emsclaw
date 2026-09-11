"""升级兼容性 smoke 测试 — 防止依赖回退或 API 不匹配。

每个测试断言 deepagents 0.6.x 的关键 API 仍然可用。
如果 deepagents 升级导致这些测试失败，说明 API 兼容性破坏，需要适配。
"""
from packaging.version import Version


def test_deepagents_version_at_least_0_6():
    """deepagents 必须 >= 0.6.0 才能用 interrupt_on / subgraphs / HumanInTheLoopMiddleware"""
    import deepagents
    assert Version(deepagents.__version__) >= Version("0.6.0"), (
        f"deepagents=={deepagents.__version__} too old; need >= 0.6.0"
    )


def test_create_deep_agent_signature():
    """create_deep_agent 必须支持 subagents / interrupt_on / middleware 参数"""
    import inspect
    from deepagents import create_deep_agent
    sig = inspect.signature(create_deep_agent)
    params = list(sig.parameters.keys())

    assert "subagents" in params, "create_deep_agent missing 'subagents' param"
    assert "interrupt_on" in params, "create_deep_agent missing 'interrupt_on' param (needed for HITL)"
    assert "middleware" in params, "create_deep_agent missing 'middleware' param"


def test_langgraph_subgraphs_param():
    """CompiledStateGraph.astream 必须支持 subgraphs=True 参数"""
    from langgraph.graph import StateGraph
    from typing import TypedDict

    class State(TypedDict):
        x: int

    g = StateGraph(State)
    g.add_node("a", lambda s: {"x": s["x"] + 1})
    g.set_entry_point("a")
    compiled = g.compile()

    import inspect
    sig = inspect.signature(compiled.astream)
    assert "subgraphs" in sig.parameters, "astream missing 'subgraphs' param"


def test_human_in_the_loop_middleware_importable():
    """HumanInTheLoopMiddleware 必须从 langchain.agents.middleware 可导入"""
    try:
        from langchain.agents.middleware import HumanInTheLoopMiddleware
        assert HumanInTheLoopMiddleware is not None
    except ImportError:
        # 0.6.x 可能改名或迁移
        try:
            from langchain.agents.middleware.human_in_the_loop import HumanInTheLoopMiddleware
        except ImportError as e:
            raise AssertionError(f"HumanInTheLoopMiddleware not found: {e}")


def test_subagent_prompts_importable():
    """subagent prompts 必须可导入（research profile 依赖）"""
    try:
        from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT, DEFAULT_SUBAGENT_PROMPT
        assert "description" in GENERAL_PURPOSE_SUBAGENT
        assert isinstance(DEFAULT_SUBAGENT_PROMPT, str)
    except ImportError:
        # 0.6.x 可能迁移
        from deepagents.subagents import GENERAL_PURPOSE_SUBAGENT, DEFAULT_SUBAGENT_PROMPT
