"""task-service ORM models (PostgreSQL)."""
from sqlalchemy import BigInteger, String, Integer, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # shortuuid
    name: Mapped[str] = mapped_column(Text, default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    schedule_desc: Mapped[str] = mapped_column(Text, default="")
    crontab: Mapped[str] = mapped_column(Text, default="")
    webhook: Mapped[str] = mapped_column(Text, default="")
    webhook_ids: Mapped[list] = mapped_column(JSONB, default=list)
    event_config: Mapped[list] = mapped_column(JSONB, default=list)
    model_config_id: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    user_id: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_updated_at", "updated_at"),
    )


class TaskRun(Base):
    __tablename__ = "task_runs"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # shortuuid（原 ObjectId）
    task_id: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="")
    chat_id: Mapped[str] = mapped_column(Text, default="")
    start_time: Mapped[int] = mapped_column(BigInteger, default=0)
    end_time: Mapped[int] = mapped_column(BigInteger, default=0)
    result: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (
        Index("ix_task_runs_task_id", "task_id"),
        Index("ix_task_runs_start_time", "start_time"),
    )


class Webhook(Base):
    __tablename__ = "webhooks"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # shortuuid
    name: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(String(32), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
