"""Task and task_run models."""
from datetime import datetime, timezone
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_serializer


# ─── API schemas ───────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    name: str = Field(..., description="Task name")
    prompt: str = Field(..., description="Prompt input for LLM")
    schedule_desc: str = Field(..., description="Natural language schedule description")
    crontab: Optional[str] = Field(None, description="Crontab expression (auto-filled from schedule_desc if not set)")
    webhook: Optional[str] = Field(None, description="Legacy single Feishu webhook URL")
    webhook_ids: Optional[List[str]] = Field(default_factory=list, description="Managed webhook IDs")
    event_config: Optional[List[str]] = Field(default_factory=list, description="Events to notify")
    model_config_id: Optional[str] = Field(None, description="Model config ID for this task")
    status: str = Field(default="enabled", description="enabled | disabled")
    user_id: Optional[str] = Field(None, description="Owner user_id so task-run sessions appear in their Chats")


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    schedule_desc: Optional[str] = None
    crontab: Optional[str] = None
    webhook: Optional[str] = None
    webhook_ids: Optional[List[str]] = None
    event_config: Optional[List[str]] = None
    model_config_id: Optional[str] = None
    status: Optional[str] = None
    user_id: Optional[str] = None


class TaskOut(BaseModel):
    id: str
    name: str
    prompt: str
    schedule_desc: str
    crontab: str
    webhook: Optional[str] = None
    webhook_ids: List[str] = Field(default_factory=list)
    event_config: List[str] = Field(default_factory=list)
    model_config_id: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    next_run: Optional[str] = Field(None, description="下次执行时间（展示时区）")
    total_runs: int = Field(0, description="累计执行次数")
    success_runs: int = Field(0, description="成功执行次数")
    success_rate: str = Field("", description="成功率（如 95%）")
    recent_runs: List[str] = Field(default_factory=list, description="最近7次执行状态")


class TaskRunOut(BaseModel):
    id: str
    task_id: str
    status: str  # success | failed
    chat_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    result: Optional[str] = None
    error: Optional[str] = None

    @field_serializer("start_time", "end_time")
    def _serialize_datetime_utc(self, dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")


class TaskRunsPage(BaseModel):
    items: List[TaskRunOut] = Field(default_factory=list)
    total: int = Field(..., description="Total count of runs for the task")


# ─── Internal (ORM row → Pydantic) ───────────────────────────────────────────

def _epoch_to_dt(ts: Any) -> Optional[datetime]:
    """Convert an epoch-second int (or falsy) to an aware UTC datetime."""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _row_id(row: Any) -> str:
    """Return a row's id as a plain string (already a str for ORM rows)."""
    rid = getattr(row, "id", None)
    if rid is None:
        return ""
    # ORM id is already a string (shortuuid); guard against ObjectId leftovers.
    if hasattr(rid, "hex"):
        return str(rid)
    return str(rid)


def task_doc_to_out(doc: Any) -> TaskOut:
    """Convert a Task ORM row (or compatible mapping) to TaskOut."""
    if isinstance(doc, dict):
        # Backwards-compatible dict path (legacy callers / tests).
        tid = doc.get("_id", doc.get("id"))
        if hasattr(tid, "hex"):
            tid = str(tid)
        return TaskOut(
            id=str(tid) if tid is not None else "",
            name=doc.get("name", ""),
            prompt=doc.get("prompt", ""),
            schedule_desc=doc.get("schedule_desc", ""),
            crontab=doc.get("crontab", ""),
            webhook=doc.get("webhook"),
            webhook_ids=doc.get("webhook_ids") or [],
            event_config=doc.get("event_config") or [],
            model_config_id=doc.get("model_config_id"),
            status=doc.get("status", "enabled"),
            created_at=doc.get("created_at"),
            updated_at=doc.get("updated_at"),
        )
    # ORM row path: id is already a string; timestamps are epoch-second ints.
    return TaskOut(
        id=_row_id(doc),
        name=getattr(doc, "name", "") or "",
        prompt=getattr(doc, "prompt", "") or "",
        schedule_desc=getattr(doc, "schedule_desc", "") or "",
        crontab=getattr(doc, "crontab", "") or "",
        webhook=getattr(doc, "webhook", "") or None,
        webhook_ids=getattr(doc, "webhook_ids", None) or [],
        event_config=getattr(doc, "event_config", None) or [],
        model_config_id=getattr(doc, "model_config_id", "") or None,
        status=getattr(doc, "status", "enabled") or "enabled",
        created_at=_epoch_to_dt(getattr(doc, "created_at", None)),
        updated_at=_epoch_to_dt(getattr(doc, "updated_at", None)),
    )


def task_run_doc_to_out(doc: Any) -> TaskRunOut:
    """Convert a TaskRun ORM row (or compatible mapping) to TaskRunOut."""
    if isinstance(doc, dict):
        rid = doc.get("_id", doc.get("id"))
        if hasattr(rid, "hex"):
            rid = str(rid)
        return TaskRunOut(
            id=str(rid) if rid is not None else "",
            task_id=doc.get("task_id", ""),
            status=doc.get("status", "failed"),
            chat_id=doc.get("chat_id"),
            start_time=doc.get("start_time"),
            end_time=doc.get("end_time"),
            result=doc.get("result"),
            error=doc.get("error"),
        )
    # ORM row path: id is already a string; start_time/end_time are epoch ints.
    return TaskRunOut(
        id=_row_id(doc),
        task_id=getattr(doc, "task_id", "") or "",
        status=getattr(doc, "status", "failed") or "failed",
        chat_id=getattr(doc, "chat_id", "") or None,
        start_time=_epoch_to_dt(getattr(doc, "start_time", None)),
        end_time=_epoch_to_dt(getattr(doc, "end_time", None)),
        result=getattr(doc, "result", "") or None,
        error=getattr(doc, "error", "") or None,
    )
