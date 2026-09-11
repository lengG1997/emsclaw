from emsclaw_backend.deepagent.agents.business.registry import AgentRegistry
from emsclaw_backend.deepagent.agents.business.domain_agent import DomainAgent

import pytest


class _FakeTool:
    def __init__(self, name): self.name = name


class _Demo(DomainAgent):
    def get_tools(self): return [_FakeTool("t1")]
    def get_system_prompt(self): return "你是演示专家，负责 X。"


@pytest.fixture(autouse=True)
def _restore_registry():
    """每个测试前后恢复自注册 domain agent,避免 clear() 污染其它测试。

    AgentRegistry 是类级单例,test_* 内的 clear() 会清掉所有自注册的 domain
    expert,导致同进程后续测试(如 test_device_management_agent)拿不到 agent。
    显式触发 domains import(幂等,首次填充 registry)-> 保存快照 -> 跑测试 -> 恢复。
    """
    import emsclaw_backend.deepagent.agents.business.domains  # noqa: F401 触发自注册
    snapshot = dict(AgentRegistry._agents)
    yield
    AgentRegistry._agents.clear()
    AgentRegistry._agents.update(snapshot)


def test_register_and_get_all():
    AgentRegistry.clear()
    AgentRegistry.register(_Demo("DemoExpert", "演示用专家，处理演示任务"))
    assert [a.name for a in AgentRegistry.get_all()] == ["DemoExpert"]


def test_subagent_config_shape():
    AgentRegistry.clear()
    AgentRegistry.register(_Demo("DemoExpert", "演示用专家，处理演示任务"))
    cfgs = AgentRegistry.get_subagent_configs()
    assert len(cfgs) == 1
    c = cfgs[0]
    assert c["name"] == "DemoExpert"
    assert c["system_prompt"].startswith("你是演示专家")
    assert c["tools"][0].name == "t1"


def test_clear():
    AgentRegistry.clear()
    AgentRegistry.register(_Demo("A", "演示用专家，处理演示任务 A"))
    AgentRegistry.clear()
    assert AgentRegistry.count() == 0
