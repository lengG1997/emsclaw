"""
FastAPI 应用入口 — 精简版。

挂载路由：auth / models / sessions / file
启动时：连接 MongoDB → 初始化系统模型 → 创建默认 admin
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from contextlib import asynccontextmanager

from emsclaw_backend.route.auth import router as auth_router
from emsclaw_backend.route.sessions import router as sessions_router, cleanup_orphaned_sessions, graceful_shutdown_agents
from emsclaw_backend.route.skills import router as skills_router
from emsclaw_backend.route.approvals import router as approvals_router
from emsclaw_backend.route.file import router as file_router
from emsclaw_backend.route.models import router as models_router
from emsclaw_backend.route.task_settings import router as task_settings_router
from emsclaw_backend.route.memory import router as memory_router
from emsclaw_backend.route.agent import router as agent_router
from emsclaw_backend.route.chat import router as chat_router
from emsclaw_backend.route.statistics import router as statistics_router
from emsclaw_backend.observability.route import router as langfuse_router
from emsclaw_backend.route.im import router as im_router, start_im_runtime, stop_im_runtime
from emsclaw_backend.controller.device_controller import router as device_router
from emsclaw_backend.controller.pcs_controller import router as pcs_router
from emsclaw_backend.controller.approval_controller import router as approval_router
from emsclaw_backend.controller.station_controller import router as station_router
from emsclaw_backend.service.pcs_service import get_default_service as _pcs_svc
from emsclaw_backend.service.station_service import get_default_service as _station_svc
from emsclaw_backend.models import init_system_models
from emsclaw_backend.user.bootstrap import ensure_admin_user
from emsclaw_backend.db.session import engine, AsyncSessionLocal, init_db, get_session


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    try:
        from emsclaw_backend.db.models import migrate_legacy
        await migrate_legacy()
    except Exception as e:
        logger.warning(f"migrate_legacy failed: {e}")
    try:
        await init_system_models()
    except Exception as e:
        logger.error(f"Failed to init system models: {e}")
    try:
        await ensure_admin_user()
    except Exception as e:
        logger.error(f"Failed to bootstrap admin user: {e}")
    try:
        await cleanup_orphaned_sessions()
    except Exception as e:
        logger.error(f"Failed to cleanup orphaned sessions: {e}")
    try:
        await start_im_runtime()
    except Exception as e:
        logger.error(f"Failed to start lark long connection: {e}")
    try:
        seeded = _pcs_svc().ensure_seeded()
        logger.info(f"pcs seed: {seeded} default device pair created")
    except Exception as e:
        logger.error(f"Failed to seed pcs: {e!r}")
    try:
        stn = _station_svc().ensure_seeded()
        logger.info(f"station seed: {stn}")
    except Exception as e:
        logger.error(f"Failed to seed station: {e!r}")
    try:
        from emsclaw_backend.mapper.device_mapper import DeviceMapper
        purged = DeviceMapper().purge_offline()
        if purged:
            logger.info(f"purged {purged} offline device(s) (test residue)")
    except Exception as e:
        logger.error(f"Failed to purge offline devices: {e!r}")
    try:
        # Langfuse 可观测性探测（非阻塞；未启用时仅打一行日志）
        from emsclaw_backend.observability.sdk import warmup as _langfuse_warmup
        _langfuse_warmup()
    except Exception as e:
        logger.error(f"Failed to init langfuse: {e!r}")
    yield
    try:
        await graceful_shutdown_agents()
    except Exception as e:
        logger.error(f"Failed to gracefully shutdown agents: {e}")
    try:
        await stop_im_runtime()
    except Exception as e:
        logger.error(f"Failed to stop lark long connection: {e}")
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="emsclaw Agent Backend", lifespan=lifespan)

    cors_origins = [
        o.strip()
        for o in os.environ.get(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/ready")
    async def ready():
        try:
            from sqlalchemy import select
            from emsclaw_backend.db.models import Session as SessionModel
            async with AsyncSessionLocal() as s:
                await s.execute(select(SessionModel.id).limit(1))
            return {"status": "ready", "postgres": "ok"}
        except Exception as exc:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "postgres": str(exc)},
            )

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(sessions_router, prefix="/api/v1")
    app.include_router(skills_router, prefix="/api/v1")
    app.include_router(approvals_router, prefix="/api/v1")
    app.include_router(file_router, prefix="/api/v1")
    app.include_router(models_router, prefix="/api/v1")
    app.include_router(task_settings_router, prefix="/api/v1")
    app.include_router(memory_router, prefix="/api/v1")
    app.include_router(agent_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(statistics_router, prefix="/api/v1")
    app.include_router(langfuse_router, prefix="/api/v1")
    app.include_router(im_router, prefix="/api/v1")
    app.include_router(device_router, prefix="/api/v1")
    app.include_router(pcs_router, prefix="/api/v1")
    app.include_router(approval_router, prefix="/api/v1")
    app.include_router(station_router, prefix="/api/v1")

    logger.info("FastAPI initialized with /api/v1 endpoints")
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
