"""跨域共享枚举 — 前后端字段值的唯一真相源。

把散落在 route/service/runner 里的魔法字符串集中到这里。所有事件名、审批
分支 kind、工具状态等字面量都应引用本模块的枚举，避免打错无法被静态检查
发现。作为项目约定：entity 枚举为权威来源。

新增成员时同步检查前端 TS 类型定义。
"""
from __future__ import annotations
from enum import Enum


class EventType(str, Enum):
    """SSE 事件类型（agent 流 → 前端）。"""
    MESSAGE = "message"
    MESSAGE_CHUNK = "message_chunk"             # 流式文本片段
    MESSAGE_CHUNK_DONE = "message_chunk_done"   # 一段流式消息结束
    STATISTICS = "statistics"                    # 运行统计（不落库，仅中转）
    THINKING = "thinking"
    PLAN = "plan"
    TOOL = "tool"
    STEP = "step"
    AGENT = "agent"
    APPROVAL = "approval"                        # 审批事件（required/decided）
    TITLE = "title"                              # 会话标题生成
    SKILL_SAVE_PROMPT = "skill_save_prompt"      # 发现新 skill，提示保存
    ERROR = "error"
    DONE = "done"
    DISPATCH_PREVIEW = "dispatch_preview"  # 调度策略求解成功,完整 schedule+summary(独立于 message 流)


class ApprovalEventKind(str, Enum):
    """approval 事件 data.kind 的取值。

    与 ApprovalStatus（pending/decided/auto_approved，记录级状态）区分：
    本枚举只描述流式 approval 事件的分支语义。
    """
    REQUIRED = "required"   # approval_required：interrupt 触发，待用户决策
    DECIDED = "decided"     # approval_decided：已决策（auto=True 时为自动批准）


class ToolEventStatus(str, Enum):
    """tool 事件 data.status 的取值。"""
    CALLING = "calling"   # 工具调用中（tool_call）
    CALLED = "called"     # 工具已返回（tool_result）


# 需要中途立即落库（mid-stream save）的事件类型 —— approval/tool 等终止性或
# 关键状态事件必须即时持久化，否则进程崩溃后 resume endpoint 读不到、跨重启
# 无法重建 pending 状态。子 agent 事件不在此列（跟着主流程通信，由 finally 兜底）。
MID_STREAM_SAVE_EVENTS: frozenset = frozenset({
    EventType.MESSAGE,
    EventType.TOOL,
    EventType.STEP,
    EventType.PLAN,
    EventType.APPROVAL,
})
