"""AgentRegistry — 收集 DomainAgent 配置，输出 deepagents SubAgent 列表。"""
from __future__ import annotations
from typing import Dict, List, Optional
import logging
from .domain_agent import DomainAgent

logger = logging.getLogger(__name__)


class AgentRegistry:
    _agents: Dict[str, DomainAgent] = {}

    @classmethod
    def register(cls, agent: DomainAgent) -> None:
        if not isinstance(agent, DomainAgent):
            raise TypeError(f"只能注册 DomainAgent 子类实例，收到: {type(agent).__name__}")
        if agent.name in cls._agents:
            logger.warning(f"Agent '{agent.name}' 已注册，将被覆盖")
        cls._agents[agent.name] = agent
        logger.info(f"已注册领域 Agent: {agent.name}")

    @classmethod
    def get(cls, name: str) -> Optional[DomainAgent]: return cls._agents.get(name)
    @classmethod
    def get_all(cls) -> List[DomainAgent]: return list(cls._agents.values())
    @classmethod
    def get_names(cls) -> List[str]: return list(cls._agents.keys())
    @classmethod
    def get_subagent_configs(cls, language: Optional[str] = None, workspace: Optional[str] = None) -> list:
        return [a.to_subagent_config(language=language, workspace=workspace) for a in cls._agents.values()]
    @classmethod
    def count(cls) -> int: return len(cls._agents)
    @classmethod
    def clear(cls) -> None: cls._agents.clear()
    @classmethod
    def is_registered(cls, name: str) -> bool: return name in cls._agents
