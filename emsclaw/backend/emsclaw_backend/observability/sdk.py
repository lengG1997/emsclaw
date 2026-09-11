"""
Langfuse 可观测性集成（可选）。

通过 LangChain CallbackHandler 把 Agent 的 LLM 调用、工具调用、子 agent 派发等
以 trace 形式上报到 Langfuse（自托管或云端），用于调试 / 成本 / 质量分析。

启用方式（环境变量，见 docker-compose.langfuse.yml）：
  LANGFUSE_ENABLED=true
  LANGFUSE_PUBLIC_KEY=pk-lf-...
  LANGFUSE_SECRET_KEY=sk-lf-...
  LANGFUSE_BASE_URL=http://langfuse-web:3000   # 容器内；本机浏览器 http://localhost:3000

设计要点：
  - 未启用 / SDK 未安装 / 鉴权失败时，get_langfuse_handler() 返回 None，
    runner 不往 callbacks 里加任何东西，Agent 运行零影响。
  - 鉴权结果缓存：成功永久缓存；失败每 30s 重试一次（Langfuse 启动慢时不永久卡死）。
  - trace_attributes() 返回一个 context manager，把 session_id / user_id / metadata
    附加到本次 trace 的所有 span（用 propagate_attributes）。未启用时返回 nullcontext。
"""
from __future__ import annotations

import time
from contextlib import nullcontext
from typing import Any, Optional

from loguru import logger

from emsclaw_backend.config import settings

# ── 延迟导入 langfuse SDK：未安装时降级为「不可用」，不阻断 backend 启动 ──
_LF: Any = None
_CallbackHandler: Any = None
try:
    from langfuse import get_client as _get_client, propagate_attributes as _propagate_attributes  # type: ignore
    from langfuse.langchain import CallbackHandler as _CallbackHandler  # type: ignore

    _LF = True
    _CallbackHandler = _CallbackHandler
except Exception as _e:  # pragma: no cover - 仅当 langfuse 未装时触发
    logger.debug(f"[Langfuse] SDK 未安装或导入失败，可观测性集成关闭: {_e}")
    _LF = None

# SDK 是否可用 + 总开关
_AVAILABLE: bool = _LF is not None and settings.langfuse_enabled

# 鉴权状态缓存（进程级）
_client_state: dict[str, Any] = {
    "ok": None,        # None=未检查 / True=已鉴权 / False=上次失败
    "last_check": 0.0,
    "cooldown": 30.0,  # 失败后重试间隔（秒）
}


def is_enabled() -> bool:
    """Langfuse tracing 是否启用（SDK 可用 + 总开关打开）。"""
    return _AVAILABLE


def is_ready() -> bool:
    """Langfuse 是否就绪可用于拉取/同步提示词（启用 + 鉴权通过/缓存命中）。

    鉴权失败的 cooldown 内返回 False，调用方据此短路、直接用本地兜底，
    避免 Langfuse 宕机时每个 session build 都卡在网络重试上。
    """
    return is_enabled() and _check_client()


def get_langfuse_client() -> Optional[Any]:
    """返回 Langfuse 单例 client；未启用/SDK 不可用时返回 None。

    供提示词管理（get_prompt/create_prompt）等非 tracing 场景使用。
    注意：调用方应先用 is_ready() 短路，避免在 Langfuse 不可用时反复构造。
    """
    if not _AVAILABLE:
        return None
    try:
        return _get_client()
    except Exception as e:
        logger.warning(f"[Langfuse] 获取 client 失败: {e}")
        return None


def _check_client() -> bool:
    """检查 Langfuse 客户端鉴权。成功永久缓存；失败每 cooldown 秒重试。"""
    if not _AVAILABLE:
        return False
    st = _client_state
    if st["ok"]:
        return True
    now = time.time()
    if now - st["last_check"] < st["cooldown"]:
        return False
    st["last_check"] = now
    try:
        ok = bool(_get_client().auth_check())
    except Exception as e:  # 网络异常 / Langfuse 未就绪
        logger.warning(f"[Langfuse] 鉴权失败，tracing 暂不可用: {e}")
        ok = False
    st["ok"] = ok
    if ok:
        st["cooldown"] = 0.0  # 成功后不再重试（永久缓存）
        logger.info("[Langfuse] 鉴权成功，tracing 已启用")
    return ok


def warmup() -> None:
    """启动时调用一次：做一次非阻塞鉴权探测并打日志。失败不阻断启动。"""
    if not _AVAILABLE:
        logger.info("[Langfuse] 未启用（LANGFUSE_ENABLED 未设为 true 或 SDK 不可用）")
        return
    logger.info(
        f"[Langfuse] 已启用，base_url={settings.langfuse_base_url or '(default)'}，"
        "正在探测连接..."
    )
    _check_client()


def get_langfuse_handler() -> Optional[Any]:
    """返回一个 Langfuse LangChain CallbackHandler；未启用则返回 None。

    CallbackHandler() 自身很轻量，构造时不发网络请求；trace 上报由 SDK 内部
    OTel exporter 异步批量完成。鉴权失败也会返回 handler（SDK 会重试上报），
    以便 Langfuse 稍后就绪时自动恢复——除非显式禁用。
    """
    if not _AVAILABLE:
        return None
    try:
        return _CallbackHandler()
    except Exception as e:
        logger.warning(f"[Langfuse] 创建 CallbackHandler 失败: {e}")
        return None


def trace_attributes(
    session_id: str,
    user_id: Optional[str] = None,
    *,
    mode: Optional[str] = None,
    query: Optional[str] = None,
) -> Any:
    """返回一个 context manager，把 session_id/user_id/metadata 附加到本次 trace。

    用法（包住 agent 的流式调用）：
        with trace_attributes(session_id, user_id, mode=mode, query=query):
            async for ev in agent.astream(...):
                ...

    未启用时返回 nullcontext()，调用方可无脑 with。
    """
    if not _AVAILABLE:
        return nullcontext()
    version = settings.agent_version
    metadata: dict[str, Any] = {"source": "emsclaw", "agent_version": version}
    if mode:
        metadata["mode"] = mode
    if query:
        metadata["query"] = query[:500]
    tags = ["emsclaw", f"v{version}"]
    if mode:
        tags.append(mode)
    try:
        return _propagate_attributes(
            session_id=session_id,
            user_id=user_id or "anonymous",
            tags=tags,
            metadata=metadata,
        )
    except Exception:
        # propagate_attributes 签名异常时降级为无附加属性（trace 仍会生成）
        return nullcontext()


def set_trace_io(input: Any = None, output: Any = None) -> None:
    """写入 trace 级 input/output，供 LLM-as-judge evaluator 读取。

    评估器（rule target=observation, name=LangGraph）的 mapping source 只有
    observation.input/output/metadata，但 root observation `LangGraph` 由
    LangChain CallbackHandler 创建时不带 input/output。Langfuse 提供
    set_current_trace_io 把数据写到 trace 级，evaluator 评 root observation
    时会 fallback 读 trace 级 input/output（legacy 路径，专为 LLM-as-judge 保留）。

    必须在 trace_attributes() 的 context 内调用，否则无 active trace 可写。
    未启用 Langfuse 时静默 no-op。
    """
    if not _AVAILABLE:
        return
    try:
        _get_client().set_current_trace_io(input=input, output=output)
    except Exception as e:
        # 不阻断主流程；trace 仍会生成，只是缺 input/output
        logger.debug(f"[Langfuse] set_current_trace_io 失败: {e}")


# 用户反馈 score 名（Langfuse 里按此名聚合；前端点赞/踩写入）
USER_FEEDBACK_SCORE_NAME = "user_feedback"


def record_user_feedback(
    trace_id: str,
    value: str,
    *,
    comment: Optional[str] = None,
    metadata: Optional[dict] = None,
    message_event_id: Optional[str] = None,
) -> bool:
    """把用户对某一轮回复的点赞 / 踩写入 Langfuse score。

    value: "like" | "dislike" | "none"
        none = 用户取消了之前的选择（Langfuse score 的 value 不能为空，
        所以用 none 表达「无态度」；它作为最新一条 score 覆盖展示时，
        dashboard 里的 like/dislike 计数仍可按 value 过滤）。

    ⚠️ 每次调用都是**追加一条新 score**（不传 score_id）。
    实测 Langfuse v4：显式传 score_id 时，重复 id 的第二笔会被静默忽略
    （value/comment 保留第一次的值），无法实现「改主意后覆盖」，
    因此这里刻意不传 score_id —— 最新一条即当前态度，切换历史完整保留。

    未启用 Langfuse / trace_id 缺失 / 写入异常时返回 False，绝不抛异常阻断业务。
    """
    if not _AVAILABLE or not trace_id or not value:
        return False
    payload: dict[str, Any] = {
        "name": USER_FEEDBACK_SCORE_NAME,
        "value": value,
        "trace_id": trace_id,
        "data_type": "CATEGORICAL",
    }
    if comment:
        payload["comment"] = comment[:2000]
    meta = {k: v for k, v in (metadata or {}).items() if v is not None}
    if message_event_id:
        meta["message_event_id"] = message_event_id
    if meta:
        payload["metadata"] = meta
    try:
        _get_client().create_score(**payload)
        logger.info(
            f"[Langfuse] user_feedback={value} trace={trace_id} "
            f"meta_keys={sorted(meta.keys())}"
        )
        return True
    except Exception as e:
        # 反馈是旁路能力，失败不影响用户继续使用
        logger.warning(f"[Langfuse] record_user_feedback 失败: {e}")
        return False


def create_eval_observation(query: str, output: str, trace_id: Optional[str] = None) -> None:
    """在当前 trace 内创建名为 'eval-data' 的 observation，供 LLM-as-judge evaluator 评分。

    Langfuse v4 的 evaluator 读取 observation.output（而非 trace-level output）。
    由于 LangChain CallbackHandler 会把压缩后的 LangGraph state 写入 root
    observation 的 output（约 10 条消息，不包含完整工具调用历史），
    evaluator 看不到真实的工具调用序列。

    本函数在**当前 trace** 上创建一个独立的 observation，output 为完整对话日志，
    evaluator rules 通过 filter name="eval-data" 定位到这个 observation。

    必须在 trace_attributes() 的 context 内调用，否则无 active trace 可写。
    未启用 Langfuse 时静默 no-op。

    Args:
        query: 用户原始问题（observation input）
        output: 格式化对话日志（observation output）
        trace_id: 可选 trace ID。优先用 get_current_trace_id() 自动拿当前 trace；
                  显式传入时覆盖。都没有时降级为创建独立 trace（不推荐）。
    """
    if not _AVAILABLE:
        return
    try:
        client = _get_client()
        # 优先用显式传入的 trace_id；否则自动拿当前 OTel context 的 trace id
        if not trace_id:
            try:
                trace_id = client.get_current_trace_id()
            except Exception as e:
                logger.debug(f"[Langfuse] get_current_trace_id 失败: {e}")
        kwargs: dict = {
            "name": "eval-data",
            "input": query,
            "output": output,
        }
        if trace_id:
            kwargs["trace_context"] = {"trace_id": trace_id}
        # trace_context=None 时会创建独立 trace（fallback，不推荐）
        obs = client.start_observation(**kwargs)
        obs.end()
        logger.debug(
            f"[Langfuse] eval-data observation created (trace_id={trace_id or 'new'}, "
            f"output_len={len(output)})"
        )
    except Exception as e:
        logger.warning(f"[Langfuse] create_eval_observation 失败: {e}")
