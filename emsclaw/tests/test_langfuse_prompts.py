"""Langfuse 提示词版本化 -- 加载器/命名/装配测试。

测试环境 Langfuse 关闭（LANGFUSE_ENABLED 未设），load_* 必须走本地兜底、零网络，
行为与未接入 Langfuse 前一致。
"""
import pytest


@pytest.fixture(autouse=True)
def _langfuse_off(monkeypatch):
    """强制 Langfuse 未就绪：load_text_prompt 直接返回本地兜底。"""
    from emsclaw_backend.observability import prompts as langfuse_prompts
    monkeypatch.setattr(langfuse_prompts, "is_ready", lambda: False)


def test_load_lead_prompt_appends_sandbox_no_capabilities():
    """load_lead_prompt 不再注入 capabilities(subagents 已作为 task 工具注入),
    只追加 sandbox_info。"""
    from emsclaw_backend.observability.prompts import load_lead_prompt
    tmpl = "你是 Lead。\n"
    out = load_lead_prompt(tmpl, sandbox_info="BOX-INFO")
    assert "你是 Lead。" in out
    assert "BOX-INFO" in out
    assert "Sandbox Environment" in out


def test_get_prompt_name_derived_from_module():
    """domain_device_operation/agent.py -> domain_device_operation。"""
    from emsclaw_backend.deepagent.agents.business.domains.device_operation.agent import (
        DeviceOperationExpert,
    )
    assert DeviceOperationExpert().get_prompt_name() == "domain_device_operation"


def test_get_prompt_name_override_via_class_attr():
    from emsclaw_backend.deepagent.agents.business.domain_agent import DomainAgent

    class _Custom(DomainAgent):
        PROMPT_NAME = "my_custom_prompt"

        def get_tools(self): return []
        def get_system_prompt(self): return "本地提示词，至少十个字"

    assert _Custom("X", "合法长度描述，至少十个字").get_prompt_name() == "my_custom_prompt"


def test_lead_prompt_name_constant():
    from emsclaw_backend.observability.prompts import LEAD_PROMPT_NAME
    assert LEAD_PROMPT_NAME == "business_lead"
