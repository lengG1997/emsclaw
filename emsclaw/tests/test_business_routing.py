"""Smoke tests for business domain experts - skill 路径 + 工具集 + 注册行为。"""
import os


def test_device_operation_skill_file_resolves():
    """DeviceOperationExpert 的 skills 挂到干净虚拟路径 /domain-skills/device_operation/，
    源目录含 device-sop/SKILL.md（factory 路由的 FilesystemBackend 按需读真实文件）。"""
    import importlib
    from pathlib import Path
    from emsclaw_backend.deepagent.agents.business.registry import AgentRegistry
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


def test_station_data_skill_file_resolves():
    """StationDataExpert 的 skills 挂到干净虚拟路径 /domain-skills/station_data/，
    源目录含 station-analysis/SKILL.md（factory 路由的 FilesystemBackend 按需读真实文件）。"""
    import importlib
    from pathlib import Path
    from emsclaw_backend.deepagent.agents.business.registry import AgentRegistry
    from emsclaw_backend.deepagent.agents.business.domain_agent import domain_skills_route

    cfg = AgentRegistry.get("StationDataExpert").to_subagent_config()
    skills = cfg.get("skills") or []
    # get_skills 返回虚拟挂载点（非源码绝对路径），解耦 backend 源码树布局
    assert skills == [domain_skills_route("station_data")], f"Got: {skills}"
    # 真实 SKILL.md 在源码 skills/ 目录下（factory 的 FilesystemBackend root_dir 指向它）
    agent_mod = importlib.import_module(
        "emsclaw_backend.deepagent.agents.business.domains.station_data.agent"
    )
    skill_md = Path(agent_mod.__file__).parent / "skills" / "station-analysis" / "SKILL.md"
    assert skill_md.is_file(), f"Missing skill file: {skill_md}"


def test_dispatch_planning_registered():
    """DispatchPlanningExpert 已注册(dispatch_planning/__init__ 自注册)。"""
    from emsclaw_backend.deepagent.agents.business.registry import AgentRegistry
    assert AgentRegistry.is_registered("DispatchPlanningExpert")


def test_dispatch_planning_interrupt_on_apply_schedule():
    """apply_schedule 是唯一 HITL 写操作(下发计划影响硬件);只读/优化工具不审批。"""
    from emsclaw_backend.deepagent.agents.business.registry import AgentRegistry
    cfg = AgentRegistry.get("DispatchPlanningExpert").to_subagent_config()
    interrupt_on = cfg.get("interrupt_on") or {}
    assert set(interrupt_on.keys()) == {"apply_schedule"}
    entry = interrupt_on["apply_schedule"]
    assert "approve" in entry["allowed_decisions"]
    assert "reject" in entry["allowed_decisions"]
    assert entry.get("description")


def test_no_duplicate_read_tools_across_experts():
    """验证消除重复:同名 get_* 读工具不应出现在多个专家里。"""
    from emsclaw_backend.deepagent.agents.business.registry import AgentRegistry
    read_overlap = {"get_tariff", "get_meter_status", "get_daily_energy",
                    "get_station_overview", "get_pv_status", "get_demand_status"}
    owners: dict[str, list[str]] = {}
    for name in AgentRegistry.get_names():
        cfg = AgentRegistry.get(name).to_subagent_config()
        for t in cfg["tools"]:
            tn = getattr(t, "name", str(t))
            owners.setdefault(tn, []).append(name)
    for tool_name in read_overlap:
        assert owners.get(tool_name), f"{tool_name} 未注册"
        assert len(owners[tool_name]) == 1, (
            f"{tool_name} 重复出现在 {owners[tool_name]} -- 读工具应只归 StationDataExpert"
        )
        assert owners[tool_name][0] == "StationDataExpert", (
            f"{tool_name} 应归 StationDataExpert, 实际 {owners[tool_name]}"
        )


def test_lead_and_experts_have_no_get_current_time_tool():
    """get_current_time 已不再作为工具注入（日期由提示词 _append_date 注入）。

    Lead（factory.tools）与每个子 agent（to_subagent_config.tools）都不应含 get_current_time。
    """
    from emsclaw_backend.deepagent.agents.business.registry import AgentRegistry
    for name in AgentRegistry.get_names():
        cfg = AgentRegistry.get(name).to_subagent_config()
        tool_names = [getattr(t, "name", str(t)) for t in cfg["tools"]]
        assert "get_current_time" not in tool_names, (
            f"{name} 仍注入了 get_current_time: {tool_names}"
        )


def _posix(p: str) -> str:
    """转 POSIX 正斜杠，对齐容器内绝对路径的匹配方式。"""
    return p.replace("\\", "/")


def test_business_backend_routes_only_skills_dirs(monkeypatch, tmp_path):
    """_build_business_backend 把各域 skills/ 目录路由到干净虚拟路径 /domain-skills/，
    root_dir 仍指向源码 skills 真实目录（不暴露 domains 源码）。"""
    from pathlib import Path
    from emsclaw_backend.deepagent.agents.business import factory as factory_mod
    from emsclaw_backend.deepagent.agents.business.domain_agent import DOMAIN_SKILLS_ROUTE_PREFIX
    from deepagents.backends import CompositeBackend

    domains = tmp_path / "domains"
    (domains / "station_data" / "skills").mkdir(parents=True)
    (domains / "station_data" / "skills" / "station_analysis.md").write_text("# s\n")
    (domains / "dispatch_planning").mkdir(parents=True)
    (domains / "dispatch_planning" / "agent.py").write_text("")

    monkeypatch.setattr(factory_mod, "_DOMAINS_DIR", str(domains))

    backend = factory_mod._build_business_backend(None)
    assert isinstance(backend, CompositeBackend)

    # 路由 key 是干净虚拟前缀 /domain-skills/，而非源码绝对路径（解耦 backend 源码树，#2 的核心）
    route_keys = list(backend.routes.keys())
    assert route_keys == [f"{DOMAIN_SKILLS_ROUTE_PREFIX}/"], f"Got routes: {route_keys}"
    assert all(k.startswith(DOMAIN_SKILLS_ROUTE_PREFIX + "/") for k in route_keys)

    # 虚拟挂载的每个包 backend 仍指向源码 skills 真实目录，FilesystemBackend 按需读真实文件
    route_be = backend.routes[route_keys[0]]
    assert route_be._packages.keys() == {"station_data"}
    pkg_be = route_be._packages["station_data"]
    assert pkg_be.virtual_mode is True
    expected_root = (Path(str(domains)) / "station_data" / "skills").resolve()
    assert pkg_be.cwd == expected_root

    # 只有含 skills/ 子目录的域被路由；dispatch_planning 无 skills/ → 不建路由
    assert "dispatch_planning" not in route_be._packages
    # 源码路径不被虚拟路由前缀覆盖 → 落默认 sandbox（domains 下非 skills 内容不可读）
    agent_path = _posix(str(domains / "dispatch_planning" / "agent.py"))
    assert not any(agent_path.startswith(_posix(k)) for k in route_keys)


def test_business_backend_returns_sandbox_when_no_skills(monkeypatch, tmp_path):
    """domains 下没有任何 skills/ 目录时，直接返回原 sandbox（不建本地路由）。"""
    from emsclaw_backend.deepagent.agents.business import factory as factory_mod

    domains = tmp_path / "domains"
    (domains / "dispatch_planning").mkdir(parents=True)
    (domains / "dispatch_planning" / "agent.py").write_text("")

    monkeypatch.setattr(factory_mod, "_DOMAINS_DIR", str(domains))

    sentinel = object()
    assert factory_mod._build_business_backend(sentinel) is sentinel
