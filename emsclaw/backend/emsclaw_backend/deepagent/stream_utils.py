"""stream_utils — SSE 流式执行所需的纯函数 / 无状态辅助。

从 runner.py 抽出，供 _arun_v2_stream 及外部（route/sessions 的 _strip_think_tags）复用。
包含：
  - thinking 标签剥离（跨 chunk 流式 + 整段）
  - token usage 提取（多种模型格式）
  - v2 chunk 文本提取 / resume meta 解析
  - 子 agent attribution（checkpoint_ns 映射）
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger

try:
    from langchain_core.messages import AIMessage  # noqa: F401 (类型注解用)
except Exception:  # pragma: no cover
    AIMessage = None  # type: ignore


# ───────────────────────────────────────────────────────────────────
# thinking 标签剥离
# ───────────────────────────────────────────────────────────────────

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_CONTENT_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)
# 未闭合的 <think>...(到末尾) 与孤立的 </think> 残片 - 模型无关兜底
_THINK_OPEN_TAIL_RE = re.compile(r"<think>.*", re.DOTALL)
_THINK_CLOSE_ORPHAN_RE = re.compile(r"</think>")


def _strip_think_tags(text: str) -> str:
    """剥离 <think> 标签(模型无关):完整块 + 孤立闭合标签 + 末尾未闭合开标签。"""
    if not text:
        return text
    text = _THINK_TAG_RE.sub("", text)
    text = _THINK_CLOSE_ORPHAN_RE.sub("", text)
    text = _THINK_OPEN_TAIL_RE.sub("", text)
    return text


class _ThinkTagStreamFilter:
    """流式剥离 <think>...</think>(跨 chunk,模型无关)。

    推理模型(DeepSeek-R1 / Qwen / MiniMax 等)可能把推理放在 <think>...</think>。
    流式分片会让标签跨 chunk 残缺(如 '<think>reason' + 'ing</think>answer'),
    逐片正则匹配不到 -> 标签漏到前端。本类缓冲跨片标签:进入 <think> 后暂存到
    </think> 闭合,整段推理丢弃,只输出标签外的正文。每个 agent 用独立实例。
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False

    def feed(self, chunk: str) -> str:
        """喂入一个 chunk,返回可安全输出的文本(已剥离 <think> 段)。"""
        if not chunk:
            return ""
        self._buf += chunk
        out: list[str] = []
        while True:
            if self._in_think:
                idx = self._buf.find(self._CLOSE)
                if idx == -1:
                    # 未闭合:丢弃推理正文,仅保留可能是 </think> 前缀的末尾(跨片)
                    self._buf = self._keep_tail_prefix(self._buf, self._CLOSE)
                    break
                # 闭合:丢弃 [0..idx+len(_CLOSE)] 的推理段,继续处理剩余
                self._buf = self._buf[idx + len(self._CLOSE):]
                self._in_think = False
                continue
            # 不在 think 内:找开标签
            idx = self._buf.find(self._OPEN)
            if idx == -1:
                # 没有开标签:清掉孤立的 </think>(模型散落闭合标签 / 开标签在跨片剥离中已处理)
                if self._CLOSE in self._buf:
                    self._buf = self._buf.replace(self._CLOSE, "")
                # 输出安全前缀,保留可能是 <think> 前缀的末尾(跨片防漏)
                keep = self._tail_prefix_len(self._buf, self._OPEN)
                out.append(self._buf[:len(self._buf) - keep])
                self._buf = self._buf[len(self._buf) - keep:] if keep else ""
                break
            # 输出开标签之前的正文,进入 think
            out.append(self._buf[:idx])
            self._buf = self._buf[idx + len(self._OPEN):]
            self._in_think = True
        return "".join(out)

    @staticmethod
    def _tail_prefix_len(buf: str, tag: str) -> int:
        """buf 末尾是 tag 的某个非空前缀时返回其长度,否则 0(跨片防漏)。"""
        max_k = min(len(tag) - 1, len(buf))
        for k in range(max_k, 0, -1):
            if tag.startswith(buf[-k:]):
                return k
        return 0

    @classmethod
    def _keep_tail_prefix(cls, buf: str, tag: str) -> str:
        keep = cls._tail_prefix_len(buf, tag)
        return buf[len(buf) - keep:] if keep else ""


def _extract_thinking(msg: "AIMessage") -> tuple[str, str]:
    """从 AIMessage 中提取思考内容和干净的正文。

    支持三种模型格式：
      1. DeepSeek（OpenAI 兼容 API）: additional_kwargs["reasoning_content"]
      2. Claude: content blocks 中 type="thinking" 的块
      3. DeepSeek / Qwen（原生 API）: <think>...</think> 标签

    Returns:
        (thinking_content, clean_text_content)
    """
    thinking = ""

    # ① additional_kwargs.reasoning_content（DeepSeek via OpenAI API）
    reasoning = (msg.additional_kwargs or {}).get("reasoning_content", "")
    if isinstance(reasoning, str) and reasoning.strip():
        thinking = reasoning.strip()

    content = msg.content
    if not content:
        return thinking, ""

    # ② content 是 list（Claude 风格 content blocks）
    if isinstance(content, list):
        thinking_parts: list[str] = []
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                btype = block.get("type", "")
                if btype == "thinking":
                    thinking_parts.append(block.get("thinking", ""))
                elif btype == "text":
                    text_parts.append(block.get("text", ""))
            elif isinstance(block, str):
                text_parts.append(block)
        if thinking_parts and not thinking:
            thinking = "\n".join(p for p in thinking_parts if p)
        return thinking, "\n".join(text_parts).strip()

    # ③ content 是 str（可能含 <think> 标签）
    if isinstance(content, str):
        if not thinking:
            matches = _THINK_CONTENT_RE.findall(content)
            if matches:
                thinking = "\n".join(m.strip() for m in matches if m.strip())
        clean = _strip_think_tags(content).strip()
        return thinking, clean

    return thinking, str(content)


# ───────────────────────────────────────────────────────────────────
# token usage 提取
# ───────────────────────────────────────────────────────────────────

def _extract_cached_tokens(usage_meta: dict) -> int:
    """提取「输入缓存命中 token」（LangChain 已规整到 input_token_details.cache_read）。"""
    details = (usage_meta or {}).get("input_token_details") or {}
    if isinstance(details, dict) and details.get("cache_read"):
        return int(details["cache_read"])
    return 0


def _extract_token_usage(msg) -> Dict[str, int]:
    """Extract input/output/cached token counts from a LangChain message.

    Returns dict with 'input_tokens', 'output_tokens', 'cached_tokens' keys.
    cached_tokens 是 input_tokens 中命中 prompt 缓存的部分（已包含在 input_tokens 内）。
    """
    input_tokens = 0
    output_tokens = 0
    cached_tokens = 0
    resp_meta = getattr(msg, "response_metadata", {}) or {}
    add_kwargs = getattr(msg, "additional_kwargs", {}) or {}

    # 方式1: usage_metadata (LangChain 标准)
    usage_meta = getattr(msg, "usage_metadata", None)
    if usage_meta:
        input_tokens = usage_meta.get("input_tokens", 0)
        output_tokens = usage_meta.get("output_tokens", 0)
        if input_tokens or output_tokens:
            cached_tokens = _extract_cached_tokens(usage_meta)
            logger.debug(f"[DeepAgent] Got tokens from usage_metadata: {usage_meta}, cached={cached_tokens}")
            return {"input_tokens": input_tokens, "output_tokens": output_tokens, "cached_tokens": cached_tokens}

    # 方式2: response_metadata.token_usage (OpenAI 风格)
    token_usage = resp_meta.get("token_usage", {})
    if token_usage:
        input_tokens = token_usage.get("prompt_tokens", 0)
        output_tokens = token_usage.get("completion_tokens", 0)
        if input_tokens or output_tokens:
            cached_tokens = _extract_cached_tokens(usage_meta)
            logger.debug(f"[DeepAgent] Got tokens from response_metadata.token_usage: {token_usage}, cached={cached_tokens}")
            return {"input_tokens": input_tokens, "output_tokens": output_tokens, "cached_tokens": cached_tokens}

    # 方式3: response_metadata.usage (某些 API)
    usage = resp_meta.get("usage", {})
    if usage:
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        if input_tokens or output_tokens:
            cached_tokens = _extract_cached_tokens(usage_meta)
            logger.debug(f"[DeepAgent] Got tokens from response_metadata.usage: {usage}, cached={cached_tokens}")
            return {"input_tokens": input_tokens, "output_tokens": output_tokens, "cached_tokens": cached_tokens}

    # 方式4: additional_kwargs.usage (某些 API)
    usage = add_kwargs.get("usage", {})
    if usage:
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        if input_tokens or output_tokens:
            cached_tokens = _extract_cached_tokens(usage_meta)
            logger.debug(f"[DeepAgent] Got tokens from additional_kwargs.usage: {usage}, cached={cached_tokens}")
            return {"input_tokens": input_tokens, "output_tokens": output_tokens, "cached_tokens": cached_tokens}

    return {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0}


# ───────────────────────────────────────────────────────────────────
# 通用工具
# ───────────────────────────────────────────────────────────────────

def _truncate_tool_args(args: dict, max_chars: int = 500) -> dict:
    """Truncate large values in tool call args to prevent context bloat."""
    truncated = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > max_chars:
            truncated[k] = v[:max_chars] + f"... ({len(v)} chars total, truncated)"
        else:
            truncated[k] = v
    return truncated


def _safe_str_v2(obj: Any, max_len: int = 2000) -> str:
    """把 v2 工具输出转为字符串,截断到 max_len(参考 demo _safe_str)。"""
    try:
        if obj is None:
            return ""
        if isinstance(obj, str):
            s = obj
        elif isinstance(obj, (dict, list)):
            s = json.dumps(obj, ensure_ascii=False, default=str)
        else:
            content = getattr(obj, "content", None)
            if content is not None:
                if isinstance(content, list):
                    parts = []
                    for block in content:
                        if isinstance(block, dict):
                            parts.append(block.get("text") or block.get("content") or "")
                        else:
                            parts.append(str(block))
                    s = "\n".join(parts)
                else:
                    s = str(content)
            else:
                s = str(obj)
        return s if len(s) <= max_len else s[:max_len] + "... (truncated)"
    except Exception as e:
        return f"(unprintable: {e})"


# ───────────────────────────────────────────────────────────────────
# v2 chunk / resume 解析
# ───────────────────────────────────────────────────────────────────

def _extract_chunk_text(chunk_msg) -> str:
    """从 on_chat_model_stream 的 AIMessageChunk 中提取可显示文本(排除 thinking 标签)。"""
    content = chunk_msg.content
    if not content:
        return ""
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    if isinstance(content, str):
        return _THINK_TAG_RE.sub("", content)
    return ""


def _extract_resume_meta(resume_command) -> tuple[str, str]:
    """从 Command(resume={interrupt_id: {"decisions": [{"type": decision_type}, ...]}}) 抽
    (interrupt_id, decision_type)。

    AG3NT deepagents_daemon.py:568-570:对每个 action_request 一个决策;这里取首个决策类型作
    前端展示用(decision 类型一致是常见路径,前端只关心 approve/reject/edit/respond)。
    """
    try:
        resume_payload = getattr(resume_command, "resume", None)
        if not resume_payload:
            return "", ""
        # resume 是 dict: {interrupt_id: {"decisions": [...]}}
        if isinstance(resume_payload, dict):
            for iid, body in resume_payload.items():
                decisions = (body or {}).get("decisions", []) if isinstance(body, dict) else []
                if decisions:
                    first = decisions[0]
                    return str(iid), str(first.get("type", "")) if isinstance(first, dict) else ""
                return str(iid), ""
    except Exception:
        pass
    return "", ""


# ───────────────────────────────────────────────────────────────────
# 子 agent attribution（LambCheck checkpoint_ns 映射）
# ───────────────────────────────────────────────────────────────────

def _resolve_agent_context(
    checkpoint_ns: str,
    checkpoint_to_agent: Dict[str, tuple[str, str]],
) -> tuple[Optional[str], int]:
    """LambCheck checkpoint_ns based attribution(参考 subagents.py:40-70)。

    Returns:
        (agent_id, depth):
          - 主 agent(无 |): (None, 0)
          - 子 agent(有 |): 取第一段(parent main ns)查 map;
            找到 → (instance_id, 1);未找到 → (None, 1) for unknown subagent

    deepagents 0.6.x task 工具顺序执行子 agent(memory: deepagents_concurrent_subagents),
    同一时刻只有一个子 agent 活动,所以 parent main ns 作为 key 不会冲突。
    """
    if not checkpoint_ns or "|" not in checkpoint_ns:
        return None, 0
    parent_ns = checkpoint_ns.split("|", 1)[0]
    mapping = checkpoint_to_agent.get(parent_ns)
    if mapping:
        return mapping[0], 1
    return None, 1


def _resolve_interrupt_agent_context(
    task_obj: Any,
    checkpoint_to_agent: Dict[str, tuple[str, str]],
    active_subagent: Optional[tuple[str, str]] = None,
) -> tuple[str, Optional[str], Optional[str]]:
    """从 PregelTask 反查审批所属的父子 agent。

    Returns:
      (parent_agent, subagent_type, subagent_instance_id):
        - 直调 Lead 的工具(无 task 调用): ("Lead", None, None)
        - 子 agent 内触发: ("DeepAgent", subagent_type, instance_id)

    优先用 active_subagent(task 工具 on_tool_start 注册、on_tool_end 清理):
    interrupt 发生在子 agent 内时 task 工具尚未返回,active_subagent 必然仍在,
    比 task.path 更可靠 -- task.path 在部分 LangGraph 版本(如 1.2.x)可能缺失,
    原实现会静默回退 ("Lead", None, None),导致审批记录无子 agent。
    """
    if active_subagent:
        instance_id, subagent_type = active_subagent
        return "DeepAgent", subagent_type, instance_id
    try:
        task_path = getattr(task_obj, "path", "") or ""
    except Exception:
        task_path = ""
    if not task_path or "|" not in task_path:
        return "Lead", None, None
    parent_ns = task_path.split("|", 1)[0]
    mapping = checkpoint_to_agent.get(parent_ns)
    if mapping:
        instance_id, subagent_type = mapping
        return "DeepAgent", subagent_type, instance_id
    return "Lead", None, None
