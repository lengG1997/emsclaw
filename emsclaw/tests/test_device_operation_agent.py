"""DeviceOperationExpert 注册与配置测试(合并自 device_management + command_execution)。"""
from emsclaw_backend.deepagent.agents.business.registry import AgentRegistry


def test_device_operation_registered():
    assert AgentRegistry.is_registered("DeviceOperationExpert")


def test_device_operation_exposes_8_tools():
    cfg = AgentRegistry.get("DeviceOperationExpert").to_subagent_config()
    names = [getattr(t, "name", str(t)) for t in cfg["tools"]]
    # 台账 5 + 站配置 1 + 控制 2 = 8(set_charge_mode 已删除,策略下发归 dispatch_planning)
    expected = {
        "create_device", "configure_network", "list_devices", "get_device",
        "reset_station_defaults", "set_station_config", "execute_device_command", "emergency_stop",
    }
    assert expected <= set(names), f"missing: {expected - set(names)}"
    assert len(names) == 8, f"expected 8 tools, got {len(names)}: {names}"
    assert "set_charge_mode" not in names


def test_device_operation_skill_file_resolves():
    """DeviceOperationExpert 的 skills 挂到干净虚拟路径 /domain-skills/device_operation/，
    源目录含 device-sop/SKILL.md（factory 路由的 FilesystemBackend 按需读真实文件）。"""
    import importlib
    from pathlib import Path
    from emsclaw_backend.deepagent.agents.business.domain_agent import domain_skills_route

    cfg = AgentRegistry.get("DeviceOperationExpert").to_subagent_config()
    skills = cfg.get("skills") or []
    # get_skills 返回虚拟挂载点（非源码绝对路径），解耦 backend 源码树布局
    assert skills == [domain_skills_route("device_operation")], f"Got: {skills}"
    # 真实 SKILL.md 在源码 skills/ 目录下（factory 的 FilesystemBackend root_dir 指向它）
    agent_mod = importlib.import_module(
        "emsclaw_backend.deepagent.agents.business.domains.device_operation.agent"
    )
    skill_md = Path(agent_mod.__file__).parent / "skills" / "device-sop" / "SKILL.md"
    assert skill_md.is_file(), f"Missing skill file: {skill_md}"


def test_device_operation_interrupt_on_all_writes_and_controls():
    """所有写/控制操作(台账写 + 运行控制)必须 HITL;只读查询(list/get_device)不审批。"""
    cfg = AgentRegistry.get("DeviceOperationExpert").to_subagent_config()
    interrupt_on = cfg.get("interrupt_on") or {}
    expected_hitl = {
        "create_device", "configure_network", "reset_station_defaults",
        "set_station_config", "execute_device_command", "emergency_stop",
    }
    assert expected_hitl == set(interrupt_on.keys()), (
        f"HITL 集合不符, got: {sorted(interrupt_on.keys())}"
    )
    for name in expected_hitl:
        cfg_entry = interrupt_on[name]
        assert "approve" in cfg_entry["allowed_decisions"]
        assert "reject" in cfg_entry["allowed_decisions"]
        assert cfg_entry.get("description"), "每个 interrupt 工具需 description"
    # 只读工具不入审批
    assert "get_device" not in interrupt_on
    assert "list_devices" not in interrupt_on
