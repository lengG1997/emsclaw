"""dispatch_planning 求解结果 artifact 存储(输出保证链路的核心)。

设计要点：
- 只要 optimize_dispatch 返回 status=ok,完整 schedule+summary 必然到达前端
- artifact 在 tool 执行时立即存入(内存 dict[session_id] + 完整 result)
- SSE 推专用 dispatch_preview 事件(独立于 message/thinking 流,不被 3000 字符截断)
- chat 路由在流结束后检查最终 assistant 消息:若有 ok artifact 且消息中
  无 <dispatch_preview> 块 → 后端确定性追加该块(用 artifact 原文,非 LLM 生成)

会话重启时从 session.events 里的 dispatch_preview 事件重建 artifact(向前兼容)。
"""
from __future__ import annotations

import json
import threading
from typing import Any, Dict, List, Optional

# session_id -> 本轮累积的 optimize_dispatch result 列表(status=ok 的,按调用顺序)
# 累积而非覆盖:支持"多方案对比"(用户偏好)。LLM 在一轮内对同一工况多次调用
# optimize_dispatch(如不同 reserve 档位/策略)时,全部方案都要能到达前端。
_store: Dict[str, List[dict]] = {}
_lock = threading.Lock()

# 单轮最多保留的对比方案数,防止 LLM 反复调用导致消息体膨胀(约 3-5KB/方案)
_MAX_PLANS = 4


def store(session_id: str, result: dict) -> None:
    """累积一次成功的 optimize_dispatch 求解结果(同一轮多次调用 → 多方案)。"""
    with _lock:
        plans = _store.setdefault(session_id, [])
        plans.append(result)
        if len(plans) > _MAX_PLANS:
            del plans[: len(plans) - _MAX_PLANS]


def get(session_id: str) -> Optional[dict]:
    """取本会话最近一次 ok 求解结果;无则 None。(单方案兼容路径)"""
    with _lock:
        plans = _store.get(session_id)
        return plans[-1] if plans else None


def get_all(session_id: str) -> List[dict]:
    """取本会话本轮全部 ok 求解结果(按调用顺序);无则 []。"""
    with _lock:
        return list(_store.get(session_id) or [])


def clear(session_id: str) -> None:
    """清理本会话 artifact(worker 结束时调用,避免内存泄漏)。"""
    with _lock:
        _store.pop(session_id, None)


def _payload(result: dict) -> dict:
    """统一 artifact 载荷。`plan_label` 是多方案对比的**权威标识**。"""
    return {
        "plan_label": result.get("plan_label"),
        "target_date": result.get("target_date"),
        "strategies": result.get("strategies"),
        "schedule": result.get("schedule"),
        "summary": result.get("summary"),
    }


def render_markdown_block(result: dict) -> str:
    """把 artifact 渲染成 <dispatch_preview> JSON 块(chathandler 兜底用)。

    与前端 DispatchPreview.vue 的解析契约对齐:schedule[24] + summary。
    用紧凑 JSON 避免消息体过大(典型 ~3-5KB,远小于 LLM 输出预算)。
    """
    body = json.dumps(_payload(result), ensure_ascii=False, separators=(",", ":"))
    return f"<dispatch_preview>\n{body}\n</dispatch_preview>"


def render_plans_block(results: List[dict]) -> str:
    """把多个方案渲染成 <dispatch_plans> JSON 数组块(多方案对比用)。

    与前端 DispatchCompare.vue 的解析契约对齐:数组,每项含
    plan_label + target_date + strategies + schedule[24] + summary。
    仅在 len(results) >= 2 时使用;单方案仍走 render_markdown_block。

    注意:顺序即**求解完成顺序**,与 LLM 正文里的方案编号**未必一致** ——
    这正是必须带 `plan_label` 的原因(卡片按 label 显示与回传,不依赖编号)。
    """
    payload = [_payload(r) for r in results]
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"<dispatch_plans>\n{body}\n</dispatch_plans>"


def has_block_in_text(text: str) -> bool:
    """检查文本里是否已有调度预览块(单方案或多方案,避免重复追加)。"""
    return "<dispatch_preview>" in text or "<dispatch_plans>" in text
