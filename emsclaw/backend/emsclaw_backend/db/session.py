"""backend PostgreSQL connection layer."""
from collections.abc import AsyncIterator
from typing import Optional

from loguru import logger
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from emsclaw_backend.config import settings
from emsclaw_backend.db.models import Base


def _build_url(async_: bool = True) -> str:
    driver = "postgresql+asyncpg" if async_ else "postgresql+psycopg"
    return (
        f"{driver}://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def _psycopg_dsn() -> str:
    """libpq DSN for psycopg/AsyncPostgresSaver (NOT SQLAlchemy URL)."""
    return (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"dbname={settings.postgres_db} user={settings.postgres_user} "
        f"password={settings.postgres_password}"
    )


engine: AsyncEngine = create_async_engine(_build_url(async_=True), echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ─── langgraph checkpointer (AsyncPostgresSaver) ─────────────────────────
# Gotcha: AsyncPostgresSaver.from_conn_string 是 @asynccontextmanager (用完关连接),
# 不能做 app 单例 — 所以这里直接构造 + 自管 AsyncConnectionPool。
# business profile 的 checkpointer 通过此单例取。

_checkpointer_pool: Optional[AsyncConnectionPool] = None


async def get_checkpointer():
    """获取 AsyncPostgresSaver 单例(business profile 用)。

    第一次调用时构造 AsyncConnectionPool + AsyncPostgresSaver;后续调用复用。
    pool 在 init_db() 时已 open + setup(),这里只是返回 saver 包装。
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # 延迟 import

    global _checkpointer_pool
    if _checkpointer_pool is None:
        _checkpointer_pool = AsyncConnectionPool(
            conninfo=_psycopg_dsn(),
            max_size=10,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=False,
        )
        await _checkpointer_pool.open()
        logger.info("backend AsyncConnectionPool opened for AsyncPostgresSaver")
    return AsyncPostgresSaver(conn=_checkpointer_pool)


async def close_checkpointer() -> None:
    """app shutdown 时关 pool(可选,大多数场景进程退出即可)。"""
    global _checkpointer_pool
    if _checkpointer_pool is not None:
        await _checkpointer_pool.close()
        _checkpointer_pool = None
        logger.info("backend AsyncConnectionPool closed")


async def init_db() -> None:
    """启动时建表(幂等)。包括 SQLAlchemy ORM 表 + langgraph checkpointer 4 张表。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 幂等补列:create_all 只建缺失的表,不会给已存在的表加新列。
        # approval_records 新增 tool_call_id / tool_result(Postgres 支持 IF NOT EXISTS)。
        await conn.execute(text(
            "ALTER TABLE approval_records ADD COLUMN IF NOT EXISTS tool_call_id TEXT"
        ))
        await conn.execute(text(
            "ALTER TABLE approval_records ADD COLUMN IF NOT EXISTS tool_result TEXT"
        ))
        # meter_snapshots 新增 total_active_power_kw(关口表一级有功功率)。
        # create_all 不会给已存在的表加新列,需手动 ALTER,否则 insert_meter_snapshot
        # 会因列不存在抛错、被 tick 里的 except: pass 静默吞掉 → 关口表/有功功率不再写入。
        await conn.execute(text(
            "ALTER TABLE meter_snapshots ADD COLUMN IF NOT EXISTS "
            "total_active_power_kw DOUBLE PRECISION NOT NULL DEFAULT 0.0"
        ))
        # charge_schedules 新增 strategies(策略组合,替代旧四方视角 perspective 列)。
        await conn.execute(text(
            "ALTER TABLE charge_schedules ADD COLUMN IF NOT EXISTS "
            "strategies JSONB DEFAULT '[]'"
        ))
    logger.info("backend PG tables ensured")

    # business profile 用 AsyncPostgresSaver:setup() 用 CREATE TABLE IF NOT EXISTS 建
    # checkpoint_blobs / checkpoint_writes / checkpoint_migrations / checkpoints (幂等)。

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: F401

        checkpointer = await get_checkpointer()
        await checkpointer.setup()
        logger.info("backend AsyncPostgresSaver tables ensured")
    except Exception as e:
        # 不让 checkpointer 失败阻断启动
        logger.warning(f"checkpointer setup skipped: {e!r}")


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

sync_engine = create_engine(_build_url(async_=False), pool_pre_ping=True, future=True)
SyncSessionLocal = sessionmaker(bind=sync_engine, class_=Session, expire_on_commit=False)
