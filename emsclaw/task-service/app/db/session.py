"""task-service PostgreSQL connection layer (async + sync)."""
from collections.abc import AsyncIterator
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from loguru import logger

from app.core.config import settings
from app.db.models import Base


def _build_url(async_: bool) -> str:
    driver = "postgresql+asyncpg" if async_ else "postgresql+psycopg"
    return (
        f"{driver}://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


async_engine: AsyncEngine = create_async_engine(_build_url(True), pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

sync_engine = create_engine(_build_url(False), pool_pre_ping=True, future=True)
SyncSessionLocal = sessionmaker(sync_engine, class_=Session, expire_on_commit=False)


async def init_db() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("task-service PG tables ensured")


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
