import pytest
from pydantic import ValidationError
from emsclaw_backend.deepagent.agents.business.domain_agent import DomainAgent


class _Ok(DomainAgent):
    def get_tools(self): return []
    def get_system_prompt(self): return "合法长度提示词，至少十个字"


def test_to_subagent_config_minimal():
    a = _Ok("OkExpert", "合法长度描述文字，至少十个字")
    c = a.to_subagent_config()
    assert c["name"] == "OkExpert"
    assert "model" not in c and "skills" not in c


def test_short_description_rejected():
    with pytest.raises(ValidationError):
        _Ok("X", "短").to_subagent_config()
