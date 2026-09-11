"""
Langfuse 模型总览路由 - 给前端「模型总览」页取数。

路由：
  GET /langfuse/status    -> 是否启用 / 是否配置齐全（不发网络请求、不泄露 key）
  GET /langfuse/overview  -> 整页数据（KPI + 模型维度 + 日趋势），后端聚合 + 缓存

数据来自 Langfuse REST API（用 settings 里的 public_key/secret_key 做 Basic auth），
key 只在后端，绝不下发前端。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select

from emsclaw_backend.user.dependencies import require_user, User
from . import http_client as langfuse_client
from emsclaw_backend.db.models import Session as SessionRow
from emsclaw_backend.db.session import AsyncSessionLocal

router = APIRouter(prefix="/langfuse", tags=["Langfuse"])


class ApiResponse(BaseModel):
    code: int = 0
    msg: str = "ok"
    data: Any = None


def _ok(data: Any, msg: str = "ok") -> ApiResponse:
    return ApiResponse(code=0, msg=msg, data=data)


@router.get("/status", response_model=ApiResponse, summary="Langfuse 启用状态")
async def langfuse_status(_user: User = Depends(require_user)) -> ApiResponse:
    """前端据此判断显示「可观测性未启用」空状态。"""
    return _ok(langfuse_client.get_status())


@router.get("/overview", response_model=ApiResponse, summary="模型总览数据")
async def langfuse_overview(
    window: str = Query("7d", description="today | 7d | 30d"),
    model: Optional[str] = Query(None, description="按模型过滤；空=全部模型"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    """返回 KPI / by_model / daily 整页数据。后端聚合并缓存 5 分钟。"""
    if window not in ("today", "7d", "30d"):
        window = "7d"

    # 未启用 / 未配置 -> 返回 enabled:false，前端优雅降级
    if not langfuse_client.is_configured():
        return _ok({
            "enabled": False,
            "configured": False,
            "msg": "Langfuse 未启用或缺少 base_url/public_key/secret_key 配置",
        })

    try:
        payload = await langfuse_client.get_overview(window=window, model=model)
        return _ok(payload)
    except Exception as e:
        logger.error(f"[Langfuse] overview 取数失败: {e!r}")
        # 取数失败也以 enabled:true 但空数据返回，避免前端整页崩；附带错误信息
        return _ok({
            "enabled": True,
            "configured": True,
            "error": str(e),
            "kpi": None,
            "by_model": [],
            "daily": [],
        })


@router.get("/scores", response_model=ApiResponse, summary="质量评分数据（LLM-as-judge）")
async def langfuse_scores(
    window: str = Query("7d", description="today | 7d | 30d"),
    name: Optional[str] = Query(None, description="按评分维度过滤；空=全部维度"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    """返回评分 KPI / by_name / by_model / daily / distribution。后端聚合并缓存 5 分钟。"""
    if window not in ("today", "7d", "30d"):
        window = "7d"

    if not langfuse_client.is_configured():
        return _ok({
            "enabled": False,
            "configured": False,
            "msg": "Langfuse 未启用或缺少 base_url/public_key/secret_key 配置",
        })

    try:
        payload = await langfuse_client.get_scores_overview(window=window, name=name)
        return _ok(payload)
    except Exception as e:
        logger.error(f"[Langfuse] scores 取数失败: {e!r}")
        return _ok({
            "enabled": True,
            "configured": True,
            "error": str(e),
            "kpi": None,
            "by_name": [],
            "by_model": [],
            "daily": [],
            "distribution": [],
        })


@router.get("/tools", response_model=ApiResponse, summary="工具调用数据（耗时/错误率）")
async def langfuse_tools(
    window: str = Query("7d", description="today | 7d | 30d"),
    name: Optional[str] = Query(None, description="按工具名过滤；空=全部工具"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    """返回工具调用 KPI / by_tool / daily。后端聚合并缓存 5 分钟。"""
    if window not in ("today", "7d", "30d"):
        window = "7d"

    if not langfuse_client.is_configured():
        return _ok({
            "enabled": False,
            "configured": False,
            "msg": "Langfuse 未启用或缺少 base_url/public_key/secret_key 配置",
        })

    try:
        payload = await langfuse_client.get_tools_overview(window=window, tool_name=name)
        return _ok(payload)
    except Exception as e:
        logger.error(f"[Langfuse] tools 取数失败: {e!r}")
        return _ok({
            "enabled": True,
            "configured": True,
            "error": str(e),
            "supported": True,
            "kpi": None,
            "by_tool": [],
            "daily": [],
        })


@router.get("/score-traces", response_model=ApiResponse, summary="按会话列出每个 trace 的评分及理由")
async def langfuse_score_traces(
    window: str = Query("7d", description="today | 7d | 30d"),
    version: Optional[str] = Query(None, description="按 Agent 版本过滤；空=全部版本"),
    session_id: Optional[str] = Query(None, description="按 sessionId 精确过滤；空=全部 session"),
    limit: int = Query(50, ge=1, le=200, description="最多返回的 session 数"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    """按会话列出每个 trace 的评分维度、值、理由（comment）。

    数据来源：v2/observations(type=CHAIN, name=LangGraph) + v3/scores(join by traceId)。
    给前端「评分会话列表」页用，可在版本/sessionId 筛选下钻到具体会话看每条评分理由。
    """
    if window not in ("today", "7d", "30d"):
        window = "7d"

    if not langfuse_client.is_configured():
        return _ok({
            "enabled": False,
            "configured": False,
            "msg": "Langfuse 未启用或缺少 base_url/public_key/secret_key 配置",
        })

    try:
        payload = await langfuse_client.get_score_traces(
            window=window, version=version, session_id=session_id, limit=limit
        )
        return _ok(payload)
    except Exception as e:
        logger.error(f"[Langfuse] score-traces 取数失败: {e!r}")
        return _ok({
            "enabled": True,
            "configured": True,
            "error": str(e),
            "available_versions": [],
            "sessions": [],
        })


@router.get("/session-by-thread/{thread_id}", response_model=ApiResponse, summary="按 thread_id 反查会话 id")
async def langfuse_session_by_thread(
    thread_id: str,
    _user: User = Depends(require_user),
) -> ApiResponse:
    """前端「会话评分」页点击进入对应聊天时调用。

    Langfuse 的 session_id 实际是 LangGraph 的 thread_id；
    DB Session 表的主键是 shortuuid id，thread_id 是普通列。这里做反查。
    """
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is required")

    async with AsyncSessionLocal() as session:
        row = await session.execute(
            select(SessionRow.id).where(SessionRow.thread_id == thread_id).limit(1)
        )
        row_id = row.scalar_one_or_none()

    if not row_id:
        raise HTTPException(status_code=404, detail=f"未找到 thread_id={thread_id} 对应的会话")

    return _ok({"session_id": row_id, "thread_id": thread_id})


# ── Experiment 评估(离线 skill 评估闭环)──────────────────────────────


@router.get("/datasets", response_model=ApiResponse, summary="列出 Langfuse dataset(= skill 评估对象)")
async def langfuse_datasets(_user: User = Depends(require_user)) -> ApiResponse:
    """前端「评估」页用:左侧 dataset 下拉(= skill 选择器)。"""
    if not langfuse_client.is_configured():
        return _ok({"enabled": False, "configured": False, "datasets": []})
    datasets = await langfuse_client.list_datasets()
    return _ok({"enabled": True, "configured": True, "datasets": datasets})


@router.get("/experiments", response_model=ApiResponse, summary="按 dataset 列出各 run 的分数对比")
async def langfuse_experiments(
    dataset: Optional[str] = Query(None, description="dataset 名(= skill 标识);不传则取全部"),
    _user: User = Depends(require_user),
) -> ApiResponse:
    """前端「评估」页用:选 dataset 后取各版本(experiment run)分数对比。

    返回:
      {
        "enabled", "configured", "dataset",
        "runs": [
          {
            experiment_id, experiment_name, started_at, ended_at,
            item_count, scored_count,
            overall_pass_rate,
            dimensions: [{name, total, passed, pass_rate}, ...]
          }, ...
        ]
      }
    """
    if not langfuse_client.is_configured():
        return _ok({"enabled": False, "configured": False, "dataset": dataset, "runs": []})
    payload = await langfuse_client.get_experiment_overview(dataset_name=dataset)
    return _ok(payload)


@router.get("/prompts/{name}", response_model=ApiResponse, summary="拉 Langfuse prompt 所有版本内容")
async def langfuse_prompt_versions(
    name: str,
    _user: User = Depends(require_user),
) -> ApiResponse:
    """前端「评估」页「查看提示词」按钮用:列 prompt 所有版本 + 内容。

    用于对照 experiment run 与它当时用的 prompt 版本(命名约定:
    experimentName 后缀 vN ↔ prompt version N,但 Langfuse 不强绑,靠人工对照)。
    """
    if not langfuse_client.is_configured():
        return _ok({"enabled": False, "configured": False, "name": name, "versions": []})
    payload = await langfuse_client.list_prompt_versions(name)
    return _ok(payload)
