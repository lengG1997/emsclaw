"""Celery application for task-service."""
from celery import Celery
from celery.schedules import crontab as celery_crontab

from app.core.config import settings

app = Celery(
    "task_service",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks"],
)
app.conf.update(
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    beat_schedule={
        "check-due-tasks": {
            "task": "app.tasks.check_due_tasks",
            "schedule": 60.0,  # every 60 seconds
        },
        "pcs-sim-tick": {
            "task": "app.tasks.pcs_sim_tick",
            "schedule": 60.0,  # every 60 seconds
        },
        "daily-revenue-report": {
            "task": "app.tasks.daily_revenue_report",
            "schedule": celery_crontab(hour=1, minute=5),  # 每天 01:05 生成昨日收益报告
        },
    },
)
