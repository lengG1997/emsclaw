"""Task CRUD and runs API."""
import time
from datetime import datetime, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

import shortuuid
from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Task, TaskRun, Webhook
from app.db.session import get_session
from app.models.task import (
    TaskCreate,
    TaskOut,
    TaskRunOut,
    TaskRunsPage,
    TaskUpdate,
    task_doc_to_out,
    task_run_doc_to_out,
)
from app.services.feishu import send_webhook_test
from app.services.schedule_parser import parse_schedule_to_crontab, ScheduleParseError

router = APIRouter(prefix="/tasks", tags=["tasks"])

# 常用时区展示名（API 返回给前端的 next_run 后缀）
_TZ_DISPLAY_NAMES = {"Asia/Shanghai": "北京时间", "UTC": "UTC"}


def _tz_display_name(tz_name: str) -> str:
    return _TZ_DISPLAY_NAMES.get(tz_name, tz_name)


def _compute_next_run_str(crontab_str: str) -> Optional[str]:
    """根据 crontab 计算下次执行时间（展示时区），失败返回 None。

    crontab 中的小时/分钟按展示时区解释，即用户输入"每天7点"生成的
    ``0 7 * * *`` 表示展示时区的 07:00，而非 UTC 07:00。
    """
    if not (crontab_str and crontab_str.strip()):
        return None
    try:
        tz_name = settings.display_timezone.strip() or "Asia/Shanghai"
        try:
            zi = ZoneInfo(tz_name)
        except Exception:
            zi = timezone.utc
            tz_name = "UTC"
        base = datetime.now(zi)
        it = croniter(crontab_str.strip(), base)
        next_run = it.get_next(datetime)
        return next_run.strftime("%Y-%m-%d %H:%M")
    except Exception as e:
        logger.debug(f"next_run compute failed for crontab {crontab_str!r}: {e}")
        return None


class VerifyWebhookBody(BaseModel):
    webhook_url: str
    task_name: str = ""


class ValidateScheduleBody(BaseModel):
    schedule_desc: str = ""
    model_config_id: Optional[str] = None


@router.post("/validate-schedule")
async def validate_schedule(body: ValidateScheduleBody) -> dict:
    """Validate schedule description and return crontab + next run time."""
    desc = (body.schedule_desc or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="schedule_desc is required")
    try:
        crontab = await parse_schedule_to_crontab(desc, model_config_id=body.model_config_id)
    except ScheduleParseError as e:
        detail = {"message": e.message, "suggestions": e.suggestions} if e.suggestions else e.message
        raise HTTPException(status_code=400, detail=detail)
    if not crontab:
        raise HTTPException(status_code=400, detail="Could not parse schedule description to crontab")
    try:
        tz_name = settings.display_timezone.strip() or "Asia/Shanghai"
        try:
            zi = ZoneInfo(tz_name)
        except Exception:
            zi = timezone.utc
            tz_name = "UTC"
        base = datetime.now(zi)
        it = croniter(crontab, base)
        next_run = it.get_next(datetime)
        next_run_str = next_run.strftime("%Y-%m-%d %H:%M")
    except Exception as e:
        logger.warning(f"croniter next run failed: {e}")
        next_run_str = ""
    return {"valid": True, "crontab": crontab, "next_run": next_run_str}


@router.post("/verify-webhook")
async def verify_webhook(body: VerifyWebhookBody) -> dict:
    """Send a test message to the given Feishu webhook URL."""
    ok, message = await send_webhook_test(body.webhook_url, (body.task_name or "").strip())
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message}


@router.post("", response_model=TaskOut)
async def create_task(body: TaskCreate, session: AsyncSession = Depends(get_session)) -> TaskOut:
    """Create a new scheduled task. Converts schedule_desc to crontab if needed."""
    crontab = body.crontab
    if not crontab and body.schedule_desc:
        try:
            crontab = await parse_schedule_to_crontab(body.schedule_desc, model_config_id=body.model_config_id)
        except ScheduleParseError as e:
            detail = {"message": e.message, "suggestions": e.suggestions} if e.suggestions else e.message
            raise HTTPException(status_code=400, detail=detail)
        if not crontab:
            raise HTTPException(status_code=400, detail="Could not parse schedule description to crontab")
    now = int(time.time())
    task_id = shortuuid.uuid()
    row = Task(
        id=task_id,
        name=body.name,
        prompt=body.prompt,
        schedule_desc=body.schedule_desc,
        crontab=crontab or "",
        webhook=body.webhook or "",
        webhook_ids=body.webhook_ids or [],
        event_config=body.event_config or [],
        model_config_id=(body.model_config_id or "").strip() or "",
        status=body.status or "enabled",
        user_id=(body.user_id or "").strip() or "",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    logger.info(f"Task created: {task_id} crontab={crontab}")
    return task_doc_to_out(row)


@router.get("", response_model=List[TaskOut])
async def list_tasks(session: AsyncSession = Depends(get_session)) -> List[TaskOut]:
    """List all tasks with stats: next_run, total_runs, success_rate, recent_runs."""
    q_tasks = select(Task).order_by(Task.created_at.desc())
    tasks = (await session.execute(q_tasks)).scalars().all()
    valid_wh_ids: set | None = None
    result = []
    for row in tasks:
        out = task_doc_to_out(row)
        data = out.model_dump()
        tid = row.id
        # Filter out deleted webhook_ids (lazy-load valid set once)
        raw_wh_ids = data.get("webhook_ids") or []
        if raw_wh_ids:
            if valid_wh_ids is None:
                wid_rows = (await session.execute(select(Webhook.id))).scalars().all()
                valid_wh_ids = set(wid_rows)
            data["webhook_ids"] = [wid for wid in raw_wh_ids if wid in valid_wh_ids]
        data["next_run"] = _compute_next_run_str(row.crontab or "")
        total = (
            await session.execute(
                select(func.count()).select_from(TaskRun).where(TaskRun.task_id == tid)
            )
        ).scalar_one()
        success = (
            await session.execute(
                select(func.count())
                .select_from(TaskRun)
                .where(TaskRun.task_id == tid, TaskRun.status == "success")
            )
        ).scalar_one()
        data["total_runs"] = total
        data["success_runs"] = success
        data["success_rate"] = f"{round(success * 100 / total)}%" if total > 0 else ""
        recent_q = (
            select(TaskRun.status)
            .where(TaskRun.task_id == tid)
            .order_by(TaskRun.start_time.desc())
            .limit(7)
        )
        recent_statuses = [st or "failed" for st in (await session.execute(recent_q)).scalars().all()]
        data["recent_runs"] = recent_statuses
        result.append(TaskOut(**data))
    return result


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: str, session: AsyncSession = Depends(get_session)) -> TaskOut:
    """Get a task by id."""
    row = await session.get(Task, task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return task_doc_to_out(row)


@router.put("/{task_id}", response_model=TaskOut)
async def update_task(task_id: str, body: TaskUpdate, session: AsyncSession = Depends(get_session)) -> TaskOut:
    """Update a task."""
    row = await session.get(Task, task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    now = int(time.time())
    row.updated_at = now
    if body.name is not None:
        row.name = body.name
    if body.prompt is not None:
        row.prompt = body.prompt
    if body.schedule_desc is not None:
        row.schedule_desc = body.schedule_desc
        if body.crontab is not None:
            row.crontab = body.crontab
        else:
            try:
                mid = body.model_config_id or row.model_config_id
                crontab = await parse_schedule_to_crontab(body.schedule_desc, model_config_id=mid)
                if crontab:
                    row.crontab = crontab
            except ScheduleParseError as e:
                detail = {"message": e.message, "suggestions": e.suggestions} if e.suggestions else e.message
                raise HTTPException(status_code=400, detail=detail)
    elif body.crontab is not None:
        row.crontab = body.crontab
    if body.webhook is not None:
        row.webhook = body.webhook
    if body.webhook_ids is not None:
        row.webhook_ids = body.webhook_ids  # reassign whole list
    if body.event_config is not None:
        row.event_config = body.event_config  # reassign whole list
    if body.model_config_id is not None:
        row.model_config_id = (body.model_config_id or "").strip() or ""
    if body.status is not None:
        row.status = body.status
    if body.user_id is not None:
        row.user_id = (body.user_id or "").strip() or ""
    await session.commit()
    return task_doc_to_out(row)


@router.delete("/{task_id}")
async def delete_task(task_id: str, session: AsyncSession = Depends(get_session)) -> None:
    """Delete a task."""
    row = await session.get(Task, task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    await session.delete(row)
    await session.commit()
    logger.info(f"Task deleted: {task_id}")


@router.get("/{task_id}/runs", response_model=TaskRunsPage)
async def list_task_runs(
    task_id: str,
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> TaskRunsPage:
    """Get execution history for a task with pagination. Default 20 per page."""
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = (
        await session.execute(
            select(func.count()).select_from(TaskRun).where(TaskRun.task_id == task_id)
        )
    ).scalar_one()
    q = (
        select(TaskRun)
        .where(TaskRun.task_id == task_id)
        .order_by(TaskRun.start_time.desc())
        .offset(offset)
        .limit(limit)
    )
    items = [task_run_doc_to_out(r) for r in (await session.execute(q)).scalars().all()]
    return TaskRunsPage(items=items, total=total)
