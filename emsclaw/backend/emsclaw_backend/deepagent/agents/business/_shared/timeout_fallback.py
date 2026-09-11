"""
Agent 工具执行的韧性与容错机制。
包含超时熔断、重试等企业级生产保护装饰器。

搬自 ems-agent-flow-main/src/agents/core/resilience.py（verbatim），
用于 business profile 的 5 个领域工具（energy_storage/power/pypsa_modeling/search/command_execution）。
"""

import functools
import concurrent.futures
import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)

def timeout_fallback(timeout_seconds: float = 15.0, fallback_msg: str = "【系统提示】后端接口响应超时(>15s)拉取失败，请告知用户稍后重试。"):
    """
    为同步工具执行添加强制超时熔断机制。

    使用线程池执行同步函数，如果超过 timeout_seconds 未返回，则直接打断并返回降级信息。
    对于 LLM Agent，向其返回“明确的失败文本”往往比直接抛出系统级崩溃异常更好，
    这样大模型能够读取到“拉取失败”的状态，并根据系统提示词自行组织合适的对客回复，
    而不会导致整个服务端 Worker 线程挂断。

    Args:
        timeout_seconds: 强制超时的秒数。
        fallback_msg: 发生超时或崩溃时返回给大模型的 fallback 文本说明。
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # 使用临时线程池隔离执行逻辑，实现同步阻塞调用的超时阻断
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func, *args, **kwargs)
                try:
                    # 阻塞等待，如果超时则抛出 TimeoutError
                    return future.result(timeout=timeout_seconds)
                except concurrent.futures.TimeoutError:
                    error_str = f"⚠️ 熔断器触发: 工具 '{func.__name__}' 超过 {timeout_seconds}s 未响应后端接口。"
                    logger.error(error_str)
                    return fallback_msg
                except Exception as e:
                    error_str = f"⚠️ 工具异常: '{func.__name__}' 发生错误: {str(e)}"
                    logger.error(error_str)
                    return f"【系统提示】接口执行异常: {str(e)}。无法获取数据，请根据当前状况灵活回复。"
        return wrapper
    return decorator
