"""Assembly smoke: both agents must build a usable agent via build_agent.

Locks in the deferred-risk resolution: create_deep_agent(subagents=+memory=
+backend=+skills=) is accepted by deepagents 0.4.4 for both modes.
Uses a dummy model config + local WORKSPACE_DIR so it runs without live LLM/sandbox.

Notes on env stubs:
- WORKSPACE_DIR is patched at the module level (base._WORKSPACE_DIR) AND on
  build_sandbox's default argument, because the default `workspace_dir=_WORKSPACE_DIR`
  is bound at function-definition time; monkeypatching the module attribute alone
  would not change the already-bound default.
- The session workspace dir (WORKSPACE_DIR/<session_id>) is pre-created because
  ensure_memory() writes CONTEXT.md into actual_workspace locally; in production
  the remote sandbox provides that path, but here we run without a sandbox.
- get_blocked_skills already swallows DB errors and returns set().
- FullSandboxBackend.get_context() returns {"success": False} when no sandbox is
  reachable on :18080; the builders guard `if ctx.get("success")` so assembly
  still succeeds with sandbox_info=None.
"""
import os
import tempfile
import pytest


@pytest.mark.asyncio
async def test_all_modes_assemble(monkeypatch):
    # dummy model config pointing at a fake endpoint; create_deep_agent only
    # constructs the graph, it does not call the model at build time
    dummy_model_config = {
        "provider": "openai",
        "base_url": "http://127.0.0.1:1",
        "api_key": "dummy",
        "model_name": "dummy-model",
        "context_window": 128000,
    }
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["WORKSPACE_DIR"] = tmp
        # Patch the module-level constant captured at import time so ensure_memory
        # resolves to our temp dir.
        from emsclaw_backend.deepagent.agents import base as profiles_base
        monkeypatch.setattr(profiles_base, "_WORKSPACE_DIR", tmp)
        # build_sandbox's default arg `workspace_dir=_WORKSPACE_DIR` was bound at
        # def time; patch the default so the sandbox workspace lands under tmp.
        # __defaults__ is a tuple of positional defaults in def order.
        if profiles_base.build_sandbox.__defaults__:
            new_defaults = list(profiles_base.build_sandbox.__defaults__)
            # workspace_dir is the last positional default (index -1)
            new_defaults[-1] = tmp
            monkeypatch.setattr(
                profiles_base.build_sandbox, "__defaults__", tuple(new_defaults)
            )

        from emsclaw_backend.task_settings import TaskSettings
        from emsclaw_backend.deepagent.agents import build_agent
        for mode in ("business",):  # 单一 mode,保留循环结构以便后续扩展
            session_id = f"asm-{mode}"
            # Pre-create the session workspace dir: FullSandboxBackend.workspace is
            # os.path.join(base_dir, session_id) and ensure_memory writes
            # CONTEXT.md into it locally (no remote sandbox in CI).
            os.makedirs(os.path.join(tmp, session_id), exist_ok=True)
            agent, sse, cw, diag = await build_agent(
                mode, session_id, "default_user", dummy_model_config, TaskSettings()
            )
            assert agent is not None, f"{mode} agent is None"
            assert sse is not None, f"{mode} sse is None"
            assert isinstance(cw, int) and cw > 0, f"{mode} ctx_window bad: {cw}"


def test_business_all_ems_experts_register():
    """3 个 EMS 专家全部自注册成功。"""
    from emsclaw_backend.deepagent.agents.business.registry import AgentRegistry

    expected = {
        "StationDataExpert", "DeviceOperationExpert", "DispatchPlanningExpert",
    }
    actual = set(AgentRegistry.get_names())
    assert expected == actual, f"expected {expected}, got {actual}"

    for n in expected:
        cfg = AgentRegistry.get(n).to_subagent_config()
        assert cfg["name"] == n
        assert len(cfg["description"]) >= 10
        assert len(cfg["system_prompt"]) >= 10
        assert isinstance(cfg["tools"], list) and cfg["tools"]
