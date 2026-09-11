"""DomainAgent — 领域 Agent 配置基类（搬自 ems-agent-flow，适配 deepagents 0.4.4）。

每个业务领域继承 DomainAgent，声明 name/description/tools/prompt，
通过 to_subagent_config() 输出 deepagents SubAgent 配置。
运行时由 deepagents SubAgentMiddleware 负责。
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict
from deepagents.middleware.subagents import SubAgent

# 域技能在 CompositeBackend 中的虚拟挂载前缀。各域 skills/ 目录挂到这个路径下，
# 而非源码树绝对路径 /app/emsclaw_backend/.../domains/<d>/skills——避免把后端源码布局暴露给
# Agent 上下文/trace，重组 skill 文件也不必改路径。与镜像 /builtin-skills/、/skills/ 虚拟挂载同理。
DOMAIN_SKILLS_ROUTE_PREFIX = "/domain-skills"


def domain_skills_route(pkg: str) -> str:
    """返回某域 skills 在 CompositeBackend 中的虚拟挂载点（无尾斜杠）。

    factory._build_business_backend 与各域 get_skills() 共用此函数，保证路由 key 与
    get_skills 返回值前缀一致：factory 用 os.listdir(_DOMAINS_DIR) 得 entry，
    各域用 ``Path(__file__).parent.name`` 得同名，二者必然相等。
    """
    return f"{DOMAIN_SKILLS_ROUTE_PREFIX}/{pkg}"


class DomainAgentSchema(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    name: str = Field(..., max_length=50)
    description: str = Field(..., min_length=10)
    system_prompt: str = Field(..., min_length=10)
    tools: list[Any] = Field(...)
    skills: Optional[List[str]] = Field(default=None)
    model: Optional[str] = Field(default=None)
    middleware: Optional[list[Any]] = Field(default=None)


class DomainAgent(ABC):
    # 提示词在 Langfuse 中的名字；None -> 由 get_prompt_name() 从模块路径派生。
    PROMPT_NAME: Optional[str] = None

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    @abstractmethod
    def get_tools(self) -> list: ...
    @abstractmethod
    def get_system_prompt(self) -> str:
        """本地提示词源（兜底 + 同步种子）。

        返回写在 prompts.py / 内联的常量。运行时实际使用的提示词由
        ``to_subagent_config`` 经 Langfuse 版本化拉取（失败回落此值）。
        """
        ...

    def get_prompt_name(self) -> str:
        """该 agent 提示词在 Langfuse 中的名字。

        默认从类所在模块派生：``domains/<pkg>/agent.py`` -> ``domain_<pkg>``。
        子类可用 ``PROMPT_NAME`` 类属性覆盖。
        """
        if self.PROMPT_NAME:
            return self.PROMPT_NAME
        parts = type(self).__module__.split(".")
        pkg = parts[-1]
        if "domains" in parts:
            idx = parts.index("domains")
            if idx + 1 < len(parts):
                pkg = parts[idx + 1]
        return f"domain_{pkg}"

    def get_skills(self) -> Optional[List[str]]: return None
    def get_model(self) -> Optional[str]: return None
    def get_middleware(self) -> Optional[list]: return None
    def get_interrupt_on(self) -> Dict[str, Dict[str, Any]]:
        """声明子 agent 哪些工具触发审批 interrupt。

        AG3NT config dict 形式(非裸 True): {tool_name: {"allowed_decisions": [...], "description": ...}}。
        默认空 dict — 不触发 interrupt;DeviceOperationExpert 等需要审批的子 agent override。
        Lead 的 create_deep_agent 必须传 checkpointer,interrupt 状态才可持久化。
        """
        return {}

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tools": [getattr(t, "name", str(t)) for t in self.get_tools()],
            "model_override": self.get_model(),
        }

    def to_subagent_config(self, language: Optional[str] = None, workspace: Optional[str] = None) -> SubAgent:
        # 提示词走 Langfuse 版本化拉取（production 标签），本地 get_system_prompt() 作兜底。
        # Langfuse 关闭/不可用时 is_ready()=False，load_text_prompt 直接返回兜底，零网络。
        # 所有子 Agent 自动获得语言约束 + 日期后缀（日期由 _append_date 注入，无需时间工具）。
        from emsclaw_backend.observability.prompts import load_text_prompt, workspace_section

        local_prompt = self.get_system_prompt()
        system_prompt = load_text_prompt(
            self.get_prompt_name(), fallback=local_prompt, language=language,
        )
        # 工作目录告知：子 agent 若不被告知会话工作目录，被拒绝写入后会反复 ls 错误路径
        # 去猜根目录。把真实工作目录注入后，它要 ls 就 ls 正确目录、要写就直接写对路径。
        ws = workspace_section(workspace)
        if ws:
            system_prompt = f"{system_prompt}\n\n{ws}"
        tools = list(self.get_tools())
        schema = DomainAgentSchema(
            name=self.name, description=self.description,
            system_prompt=system_prompt, tools=tools,
            skills=self.get_skills(), model=self.get_model(), middleware=self.get_middleware(),
        )
        config: dict = {
            "name": schema.name, "description": schema.description,
            "system_prompt": schema.system_prompt, "tools": schema.tools,
        }
        if schema.model is not None: config["model"] = schema.model
        if schema.skills is not None: config["skills"] = schema.skills
        if schema.middleware is not None: config["middleware"] = schema.middleware
        interrupt_on = self.get_interrupt_on()
        if interrupt_on:
            config["interrupt_on"] = interrupt_on
        return config  # type: ignore[return-value]
