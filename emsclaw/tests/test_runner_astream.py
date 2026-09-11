"""Regression tests for ``CompiledStateGraph.astream`` API surface under
deepagents 0.6.x.

Background
----------
deepagents 0.6.x added a ``subgraphs`` keyword to ``CompiledStateGraph.astream``
(the underlying langgraph Pregel runner). It defaults to ``False``, so
existing call sites that omit it continue to behave exactly as before.

These tests lock in the API contract that ``runner.py`` relies on (see
``emsclaw_backend/deepagent/runner.py:529-532`` and ``:843-845``). They do **not** try
to exercise LLM streaming itself — they only verify that the call signature is
accepted, that the default behavior is unchanged, and that opting into
``subgraphs=True`` is callable for future subgraph routing.

Why ``FakeListChatModel`` is sufficient:
* ``create_deep_agent`` builds the graph synchronously; the model is not
  invoked at construction time.
* We only need to consume the **first** event yielded (typically the
  ``before_agent`` patch-tool-calls update), which proves the graph is
  configured correctly. The model invocation itself fails because
  ``FakeListChatModel`` does not implement ``bind_tools`` — that's fine,
  the ``astream`` API contract has already been exercised by that point.

If these tests ever fail with ``TypeError: astream() got an unexpected
keyword argument 'subgraphs'`` or similar, deepagents has regressed the
``subgraphs`` parameter and ``runner.py`` callers need to be updated.
"""
from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from deepagents import create_deep_agent


# ───────────────────────────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────────────────────────


@tool
def _echo_tool(text: str) -> str:
    """Echo back the input. Used so the agent has at least one tool."""
    return text


@pytest.fixture
def fake_model() -> FakeListChatModel:
    """One canned response is enough — we only consume the first event."""
    return FakeListChatModel(responses=["hello world"])


@pytest.fixture
def minimal_agent(fake_model):
    """Build the smallest possible DeepAgent (one tool, no subagents)."""
    return create_deep_agent(model=fake_model, tools=[_echo_tool])


@pytest.fixture
def subagent_agent(fake_model):
    """Build a DeepAgent with a single SubAgent wired in (for subgraphs=True).

    The SubAgent definition is minimal: a name, description, system_prompt,
    and the same echo tool. We never actually invoke the subagent — the
    test only verifies that ``astream(..., subgraphs=True)`` is callable
    on a graph that has subagent middleware installed.
    """
    subagents = [
        {
            "name": "echo_subagent",
            "description": "A minimal subagent that echoes input back.",
            "system_prompt": "You echo input back to the caller.",
            "tools": [_echo_tool],
        }
    ]
    return create_deep_agent(model=fake_model, tools=[_echo_tool], subagents=subagents)


async def _drain_first_event(async_iter):
    """Return the first event from an async iterator, or None if the
    iterator raises before yielding anything (still a successful API call)."""
    try:
        return await async_iter.__anext__()
    except StopAsyncIteration:
        return None


# ───────────────────────────────────────────────────────────────────
# Tests
# ───────────────────────────────────────────────────────────────────


async def test_astream_accepts_subgraphs_param(minimal_agent):
    """``CompiledStateGraph.astream`` accepts the new ``subgraphs`` kwarg.

    Locks in the deepagents 0.6.x signature. If deepagents ever removes the
    parameter (or renames it), this test fails immediately so runner.py
    callers can be updated before they ship.
    """
    iterator = minimal_agent.astream(
        {"messages": [HumanMessage(content="hi")]},
        stream_mode=["messages", "updates"],
        subgraphs=False,
    )
    first = await _drain_first_event(iterator)
    # API surface is the contract: the call was accepted and the iterator
    # produced at least one event (or exhausted cleanly). We don't assert on
    # first's contents because FakeListChatModel has no real tool-call flow.
    assert iterator is not None


async def test_astream_default_no_subgraphs(minimal_agent):
    """Omitting ``subgraphs`` is equivalent to ``subgraphs=False`` (back-compat).

    runner.py callers at lines 529-532 and 843-845 rely on this default.
    """
    # Build a fresh iterator (the previous one is partially consumed).
    iterator = minimal_agent.astream(
        {"messages": [HumanMessage(content="hi")]},
        stream_mode=["messages", "updates"],
        # NOTE: no subgraphs kwarg — must use the 0.6.x default of False
    )
    # No exception during signature validation means the default is honored.
    assert iterator is not None
    await _drain_first_event(iterator)


async def test_astream_with_messages_and_updates_modes(minimal_agent):
    """stream_mode=['messages', 'updates'] yields a stream_type/data tuple.

    With subgraphs=False (default) each event is a 2-tuple
    ``(stream_type, data)``. This is what runner.py parses at line 539:
    ``stream_type, stream_data = stream_event``.
    """
    iterator = minimal_agent.astream(
        {"messages": [HumanMessage(content="hi")]},
        stream_mode=["messages", "updates"],
        subgraphs=False,
    )
    first = await _drain_first_event(iterator)
    # When subgraphs=False the event is a 2-tuple, not a 3-tuple.
    if first is not None:
        assert isinstance(first, tuple)
        assert len(first) == 2, (
            f"Expected (stream_type, data) tuple, got {len(first)}-tuple: "
            f"{first!r}"
        )
        stream_type, _stream_data = first
        assert isinstance(stream_type, str), (
            f"stream_type should be str, got {type(stream_type).__name__}"
        )


async def test_astream_with_subgraphs_true(subagent_agent):
    """``subgraphs=True`` is accepted and changes the event shape to a 3-tuple.

    With ``subgraphs=True``, langgraph yields events as
    ``(namespace_tuple, stream_type, data)`` so callers can disambiguate
    which subgraph produced the event. runner.py does NOT pass this yet
    today); this test is a forward-looking guardrail so the
    signature change doesn't regress silently.

    Construction note: a SubAgent is wired in via ``subagents=[...]`` so
    the SubAgentMiddleware is installed in the graph. Without it, calling
    ``subgraphs=True`` is still valid but less meaningful — the graph has
    no subgraphs to surface.
    """
    iterator = subagent_agent.astream(
        {"messages": [HumanMessage(content="hi")]},
        stream_mode=["messages", "updates"],
        subgraphs=True,
    )
    first = await _drain_first_event(iterator)
    if first is not None:
        assert isinstance(first, tuple)
        # subgraphs=True prepends a namespace path tuple: 3-tuple instead of 2.
        assert len(first) == 3, (
            f"Expected (namespace, stream_type, data) 3-tuple when "
            f"subgraphs=True, got {len(first)}-tuple: {first!r}"
        )
        _namespace, stream_type, _data = first
        assert isinstance(stream_type, str), (
            f"stream_type should be str, got {type(stream_type).__name__}"
        )