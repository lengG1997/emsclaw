"""
Celery tasks: check_due_tasks (periodic) and run_task (execute one task).
Uses sync SQLAlchemy (psycopg) and sync HTTP so worker does not need async.
"""
import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import httpx
import shortuuid
from croniter import croniter
from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.celery_app import app
from app.core.config import settings
from app.db.models import Task, TaskRun, Webhook
from app.db.session import SyncSessionLocal
from app.services.feishu import notify_task_failed, notify_task_success, notify_task_started


def _fmt_time(ts) -> str:
    """Format an epoch-second timestamp to 'YYYY-MM-DD HH:MM:SS' in display timezone."""
    if ts is None:
        return "-"
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return "-"
    tz = _display_tz()
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")


def _display_tz() -> ZoneInfo:
    """Return the configured display timezone (used for crontab matching)."""
    tz_name = (settings.display_timezone or "").strip() or "Asia/Shanghai"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def _run_chat_sync(task_id: str, prompt: str, user_id: Optional[str] = None, model_config_id: Optional[str] = None) -> Dict[str, Any]:
    """Sync HTTP call to Chat Service. user_id: owner so the session appears in their Chats."""
    url = f"{settings.chat_service_url.rstrip('/')}/api/v1/chat"
    payload = {"input": prompt, "source": "task", "task_id": task_id}
    if user_id:
        payload["user_id"] = user_id
    if model_config_id:
        payload["model_config_id"] = model_config_id
    headers = {"Content-Type": "application/json"}
    if settings.chat_service_api_key:
        headers["X-API-Key"] = settings.chat_service_api_key
    try:
        with httpx.Client(timeout=300) as client:
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                return {"error": f"Chat service {resp.status_code}: {resp.text[:500]}"}
            data = resp.json()
            if "error" in data:
                return data
            return {"chat_id": data.get("chat_id", ""), "output": data.get("output", "")}
    except Exception as e:
        logger.exception("Chat request failed")
        return {"error": str(e)}


def _notify_feishu_sync(
    webhook_url: str, task_name: str, start_time, end_time, success: bool, result_or_error: str
) -> None:
    if not webhook_url or not webhook_url.strip():
        return
    start_str = _fmt_time(start_time)
    end_str = _fmt_time(end_time)
    if success:
        asyncio.run(notify_task_success(webhook_url, task_name, start_str, end_str, result_or_error))
    else:
        asyncio.run(notify_task_failed(webhook_url, task_name, start_str, end_str, result_or_error))


def _notify_start_sync(
    webhook_url: str, webhook_ids: list, session: Session, task_name: str, start_time
) -> None:
    """Send task-started notification to all configured webhooks."""
    from app.services.webhook_sender import send_webhook
    start_str = _fmt_time(start_time)
    if webhook_url and webhook_url.strip():
        asyncio.run(notify_task_started(webhook_url, task_name, start_str))
    if not webhook_ids:
        return
    title = f"🚀 任务开始执行：{task_name}"
    content = f"**⏱ 开始时间**\n{start_str}"
    for wid in webhook_ids:
        try:
            wh = session.get(Webhook, wid)
            if not wh:
                continue
            asyncio.run(send_webhook(wh.type or "feishu", wh.url or "", title, content))
        except Exception as e:
            logger.warning(f"Failed to notify start webhook {wid}: {e}")


def _notify_managed_webhooks_sync(
    session: Session, webhook_ids: list, task_name: str, start_time, end_time, success: bool, result_or_error: str
) -> None:
    """Send notifications to all managed webhooks."""
    if not webhook_ids:
        return
    from app.services.webhook_sender import send_webhook
    start_str = _fmt_time(start_time)
    end_str = _fmt_time(end_time)
    title = f"{'✅ 任务执行成功' if success else '❌ 任务执行失败'}：{task_name}"
    truncated = result_or_error[:500] + "..." if len(result_or_error) > 500 else result_or_error
    label = "执行结果" if success else "错误信息"
    content = f"**⏱ 开始时间**\n{start_str}\n\n**⏱ 结束时间**\n{end_str}\n\n**📋 {label}**\n\n{truncated}"
    for wid in webhook_ids:
        try:
            wh = session.get(Webhook, wid)
            if not wh:
                continue
            asyncio.run(send_webhook(wh.type or "feishu", wh.url or "", title, content))
        except Exception as e:
            logger.warning(f"Failed to notify webhook {wid}: {e}")


@app.task
def check_due_tasks() -> None:
    """Periodic: find tasks whose crontab matches current minute and dispatch run_task."""
    with SyncSessionLocal() as session:
        now = datetime.now(_display_tz())
        now = now.replace(second=0, microsecond=0)
        rows = session.execute(select(Task).where(Task.status == "enabled")).scalars().all()
        for row in rows:
            crontab_str = row.crontab or ""
            if not crontab_str:
                continue
            try:
                if croniter.match(crontab_str, now):
                    task_id = row.id
                    app.send_task("app.tasks.run_task", args=[task_id])
                    logger.info(f"Dispatched run_task for {task_id}")
            except Exception as e:
                logger.warning(f"Crontab check failed for task {row.id}: {e}")


@app.task
def pcs_sim_tick() -> None:
    """周期推进后端 PCS 模拟一帧(每分钟由 beat 调度)。

    HTTP POST backend /api/v1/pcs/sim/tick,带 X-API-Key 头(若配置)。
    """
    url = f"{settings.chat_service_url.rstrip('/')}/api/v1/pcs/sim/tick"
    headers = {"Content-Type": "application/json"}
    if settings.chat_service_api_key:
        headers["X-API-Key"] = settings.chat_service_api_key
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json={}, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"pcs_sim_tick non-200: {resp.status_code} {resp.text[:200]}")
                return
            data = resp.json()
            logger.info(f"pcs_sim tick: {data}")
    except Exception as e:
        logger.warning(f"pcs_sim_tick failed: {e}")


@app.task
def daily_revenue_report() -> None:
    """每日自动推送昨日收益报告(每早由 beat 调度)。

    归属给 admin 用户(共享 ai_agent DB 的 users 表,raw SQL 查 role='admin'),
    调后端 /api/v1/chat 发『生成昨日收益报告』→ business Lead 路由到
    DispatchPlanningExpert → account_revenue(昨日) → <revenue_breakdown> 写入会话。
    """
    owner_user_id = None
    try:
        with SyncSessionLocal() as session:
            row = session.execute(
                text("SELECT id FROM users WHERE role = 'admin' AND is_active = TRUE ORDER BY created_at LIMIT 1")
            ).first()
            if row:
                owner_user_id = row[0]
    except Exception:
        logger.warning("daily_revenue_report: 查找 admin 用户失败", exc_info=True)
    result = _run_chat_sync("daily-revenue-report", "生成昨日收益报告", user_id=owner_user_id)
    if "error" in result:
        logger.warning(f"daily_revenue_report 失败: {result['error']}")
        return
    logger.info(f"daily_revenue_report 完成: chat_id={result.get('chat_id')}")


@app.task(bind=True)
def run_task(self, task_id: str) -> None:
    """
    Execute a single task: create task_run, call Chat API, update task_run, push Feishu.
    """
    with SyncSessionLocal() as session:
        row = session.get(Task, task_id)
        if not row:
            logger.warning(f"run_task: task {task_id} not found")
            return
        name = row.name or "未命名"
        prompt = row.prompt or ""
        webhook = row.webhook or ""
        webhook_ids = row.webhook_ids or []
        event_config = row.event_config or []
        model_config_id = (row.model_config_id or "").strip() or None
        notify_start = "notify_on_start" in event_config
        user_id = (row.user_id or "").strip() or None
        start_time = int(time.time())
        run_id = shortuuid.uuid()
        inserted = False
        try:
            run = TaskRun(
                id=run_id,
                task_id=task_id,
                status="pending",
                chat_id="",
                start_time=start_time,
                end_time=0,
                result="",
                error="",
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            inserted = True

            run.status = "running"
            session.commit()

            if notify_start:
                _notify_start_sync(webhook, webhook_ids, session, name, start_time)

            result = _run_chat_sync(task_id, prompt, user_id=user_id, model_config_id=model_config_id)
            end_time = int(time.time())
            if "error" in result:
                run.status = "failed"
                run.end_time = end_time
                run.error = result["error"]
                session.commit()
                _notify_feishu_sync(webhook, name, start_time, end_time, False, result["error"])
                _notify_managed_webhooks_sync(session, webhook_ids, name, start_time, end_time, False, result["error"])
                return
            run.status = "success"
            run.chat_id = result.get("chat_id", "") or ""
            run.end_time = end_time
            run.result = result.get("output", "") or ""
            run.error = ""
            session.commit()
            _notify_feishu_sync(webhook, name, start_time, end_time, True, result.get("output", ""))
            _notify_managed_webhooks_sync(session, webhook_ids, name, start_time, end_time, True, result.get("output", ""))
        except Exception as e:
            logger.exception(f"run_task failed for {task_id}")
            end_time = int(time.time())
            if inserted:
                # Re-fetch the run in case the session was rolled back by the exception.
                run_row = session.get(TaskRun, run_id)
                if run_row is not None:
                    run_row.status = "failed"
                    run_row.end_time = end_time
                    run_row.error = str(e)
                    session.commit()
            _notify_feishu_sync(webhook, name, start_time, end_time, False, str(e))
            _notify_managed_webhooks_sync(session, webhook_ids, name, start_time, end_time, False, str(e))
