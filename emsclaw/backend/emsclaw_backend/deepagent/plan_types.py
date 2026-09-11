"""
Plan 类型定义（精简版，替代 planner_middleware.py）。

仅保留前端 SSE 事件所需的 PlanStep 和 normalize_plan_steps。
"""
import time
from typing_extensions import NotRequired, TypedDict


class PlanStep(TypedDict):
    id: str
    content: str
    status: str
    tools: list[str]
    files: list[str]
    priority: str
    inputs: NotRequired[dict]
    outputs: NotRequired[dict]
    created_at: int


def normalize_plan_steps(plan: list[PlanStep]) -> list[PlanStep]:
    """对计划步骤进行字段归一化，保证前端展示具备稳定结构。"""
    now = int(time.time())
    normalized: list[PlanStep] = []
    for index, step in enumerate(plan):
        normalized.append({
            "id": step.get("id") or f"step-{index + 1}",
            "content": step["content"],
            "status": step.get("status") or "pending",
            "priority": step.get("priority") or "medium",
            "tools": step.get("tools") or [],
            "files": step.get("files") or [],
            "created_at": step.get("created_at") or now,
            "inputs": step.get("inputs") or {},
            "outputs": step.get("outputs") or {},
        })
    return normalized


def _build_plan(description: str) -> list[PlanStep]:
    """构造一个单步 plan（ReAct agent 无需多步规划）。"""
    return normalize_plan_steps([{
        "id": "S1",
        "content": description,
        "status": "pending",
        "tools": ["terminal_execute", "file_write", "file_read"],
    }])


def _plan_for_frontend(plan: list[PlanStep]) -> list[dict]:
    return [{**step, "description": step["content"], "tools": []} for step in plan]


def _todos_to_plan_steps(todos: list[dict]) -> list[dict]:
    """
    将 agent 的 write_todos 输出转为前端 plan 步骤格式。
    这样中间件捕获的 todolist 变化可以实时推送给 PlanPanel，
    实现类似 Cursor 的 todo list 效果。
    """
    steps = []
    for i, todo in enumerate(todos):
        content = todo.get("content", "")
        status = todo.get("status", "pending")
        # 映射 todo status → plan step status
        if status in {"completed", "done"}:
            step_status = "completed"
        elif status in {"in_progress", "running"}:
            step_status = "in_progress"
        else:
            step_status = "pending"
        steps.append({
            "id": todo.get("id", f"T{i+1}"),
            "content": content,
            "description": content,
            "status": step_status,
            "tools": [],
        })
    return steps
