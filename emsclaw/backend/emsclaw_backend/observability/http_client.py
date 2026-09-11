"""
Langfuse 取数客户端（供 route/langfuse.py 调用）。

Langfuse v4 events_only 模式下，v3 的 /observations /traces /sessions 端点全部不可用，
只能用 **/api/public/v2/metrics** 这一个聚合查询端点（cursor 翻页的 /v2/observations 列表
不含 token/cost/模型名，没法做模型总览）。本模块把 metrics 查询封装成「模型总览」页需要的数据。

metrics 端点用法：
  GET /api/public/v2/metrics?query=<urlencoded JSON>
  query = {
    "view": "observations",
    "fromTimestamp": ISO, "toTimestamp": ISO,
    "metrics": [{"measure": <m>, "aggregation": <agg>}, ...],
    "dimensions": [{"field": <f>}, ...],          # 可选，分组
    "filters": [{"type":"string","column":<f>,"operator":"=","value":<v>}, ...]  # AND
  }
  返回 {"data": [ {<dimension>:..., "<agg>_<measure>": number, ...}, ... ]}

合法 measure：count / inputTokens / outputTokens / totalTokens /
             inputCost / outputCost / totalCost / latency / timeToFirstToken /
             uniqueSessionIds / tokensPerSecond ...
合法 aggregation：sum / avg / count / max / min / p50 / p75 / p90 / p95 / p99 / uniq
合法 dimension（常用的）：providedModelName（模型名）/ type / level / sessionId / userId
注：metrics 返回的 latency / timeToFirstToken 单位已是**毫秒**，无需换算。

结果按 (window, model) 缓存 CACHE_TTL 秒。
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import httpx
from loguru import logger

from emsclaw_backend.config import settings

CACHE_TTL = 300             # 模型总览/评分总览缓存 5 分钟（聚合查询贵，且数据变化不快）
SCORE_TRACES_CACHE_TTL = 30  # 会话评分缓存 30 秒（用户主动看具体评分/理由，要尽快看到新对话结果）
SHANGHAI = ZoneInfo("Asia/Shanghai")
DAILY_CONCURRENCY = 8        # 按日查询并发上限

# (window, model) -> (写入时间戳, payload)
_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}


class LangfuseNotConfigured(RuntimeError):
    """Langfuse 未启用或缺配置。"""


def get_langfuse_config() -> Dict[str, Any]:
    enabled = bool(settings.langfuse_enabled)
    base_url = (settings.langfuse_base_url or "").rstrip("/")
    pk = settings.langfuse_public_key
    sk = settings.langfuse_secret_key
    if not (enabled and base_url and pk and sk):
        raise LangfuseNotConfigured("langfuse 未启用或缺 base_url/public_key/secret_key")
    return {"base_url": base_url, "api_base": f"{base_url}/api/public", "auth": (pk, sk)}


def is_configured() -> bool:
    try:
        get_langfuse_config()
        return True
    except LangfuseNotConfigured:
        return False


def _window_range(window: str) -> Tuple[datetime, datetime]:
    """window -> (from, to) UTC。today 按 Asia/Shanghai 当天零点算。"""
    now_utc = datetime.now(timezone.utc)
    if window == "today":
        now_sh = datetime.now(SHANGHAI)
        start_sh = now_sh.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_sh.astimezone(timezone.utc), now_utc
    days = 7 if window == "7d" else 30
    return now_utc - timedelta(days=days), now_utc


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ── metrics 查询原语 ──
def _gen_filter(column: str, value: str) -> Dict[str, Any]:
    return {"type": "string", "column": column, "operator": "=", "value": value}


async def _metrics_query(
    client: httpx.AsyncClient,
    from_ts: datetime,
    to_ts: datetime,
    metrics: List[Dict[str, str]],
    dimensions: Optional[List[Dict[str, str]]] = None,
    filters: Optional[List[Dict[str, Any]]] = None,
    view: str = "observations",
) -> List[Dict[str, Any]]:
    """发起一次 /v2/metrics 查询，返回 data 行列表。失败返回 []。
    view: observations | scores-numeric | scores-categorical | scores-boolean
    """
    query: Dict[str, Any] = {
        "view": view,
        "fromTimestamp": _iso(from_ts),
        "toTimestamp": _iso(to_ts),
        "metrics": metrics,
    }
    if dimensions:
        query["dimensions"] = dimensions
    if filters:
        query["filters"] = filters
    try:
        r = await client.get("/v2/metrics", params={"query": json.dumps(query)})
        if r.status_code != 200:
            logger.warning(f"[Langfuse] metrics -> {r.status_code}: {r.text[:300]}")
            return []
        body = r.json() or {}
        return body.get("data") or []
    except Exception as e:
        logger.warning(f"[Langfuse] metrics 查询异常: {e}")
        return []


def _row_num(row: Dict[str, Any], agg: str, measure: str, default: float = 0.0) -> float:
    """从一行里取 {agg}_{measure} 字段的数值。"""
    v = row.get(f"{agg}_{measure}")
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ── 指标规格 ──
GEN_FILTER = lambda: [_gen_filter("type", "GENERATION")]
ERROR_FILTER = lambda: [_gen_filter("type", "GENERATION"), _gen_filter("level", "ERROR")]

KPI_METRICS = [
    {"measure": "count", "aggregation": "sum"},
    {"measure": "totalTokens", "aggregation": "sum"},
    {"measure": "inputTokens", "aggregation": "sum"},
    {"measure": "outputTokens", "aggregation": "sum"},
    {"measure": "totalCost", "aggregation": "sum"},
    {"measure": "latency", "aggregation": "p50"},
    {"measure": "latency", "aggregation": "p95"},
    {"measure": "timeToFirstToken", "aggregation": "avg"},
    {"measure": "uniqueSessionIds", "aggregation": "uniq"},
]
MODEL_METRICS = [
    {"measure": "count", "aggregation": "sum"},
    {"measure": "inputTokens", "aggregation": "sum"},
    {"measure": "outputTokens", "aggregation": "sum"},
    {"measure": "totalTokens", "aggregation": "sum"},
    {"measure": "totalCost", "aggregation": "sum"},
    {"measure": "latency", "aggregation": "p50"},
    {"measure": "latency", "aggregation": "p95"},
    {"measure": "timeToFirstToken", "aggregation": "avg"},
    {"measure": "latency", "aggregation": "sum"},        # 用于算 tokens_per_sec
]
DAILY_METRICS = [
    {"measure": "count", "aggregation": "sum"},
    {"measure": "totalTokens", "aggregation": "sum"},
    {"measure": "totalCost", "aggregation": "sum"},
    {"measure": "latency", "aggregation": "p50"},
]
COUNT_ONLY = [{"measure": "count", "aggregation": "sum"}]

# ── 工具调用指标（B1）──
# NOTE: 工具调用 observation 的 type/分组字段名是据 Langfuse LangChain CallbackHandler
# 的默认行为假设的默认值，pending 运行时探查验证（见 task-B1 Step 1，本任务未执行探查）。
# 若探查发现工具 observation 实际 type 不是 CHAIN 或维度字段不是 name，修正以下两个常量即可。
TOOL_TYPE_FILTER_VALUE = "CHAIN"   # 工具 observation 的 type 过滤值（默认 CHAIN，待探查确认）
TOOL_DIMENSION_FIELD = "name"      # 工具名分组维度字段（默认 name，待探查确认）

TOOL_KPI_METRICS = [
    {"measure": "count", "aggregation": "sum"},
    {"measure": "latency", "aggregation": "avg"},
    {"measure": "latency", "aggregation": "p95"},
]
TOOL_BY_METRICS = [
    {"measure": "count", "aggregation": "sum"},
    {"measure": "latency", "aggregation": "avg"},
    {"measure": "latency", "aggregation": "p95"},
]
# 工具按日趋势指标（B1 内联 daily 用，避开 _fetch_daily 里 GENERATION 专属的 tokens/cost 字段）
TOOL_DAILY_METRICS = [
    {"measure": "count", "aggregation": "sum"},
    {"measure": "latency", "aggregation": "avg"},
]


async def get_overview(window: str = "7d", model: Optional[str] = None) -> Dict[str, Any]:
    """主入口：返回模型总览整页数据。带缓存。"""
    mkey = model or ""
    cached = _CACHE.get((window, mkey))
    if cached and (time.time() - cached[0]) < CACHE_TTL:
        return cached[1]

    cfg = get_langfuse_config()
    from_ts, to_ts = _window_range(window)

    gen_filters = GEN_FILTER()
    if model:
        gen_filters = gen_filters + [_gen_filter("providedModelName", model)]

    async with httpx.AsyncClient(
        base_url=cfg["api_base"],
        auth=cfg["auth"],
        timeout=httpx.Timeout(30.0, connect=10.0),
    ) as client:
        # 1) KPI 主查询 + 错误数
        kpi_rows = await _metrics_query(client, from_ts, to_ts, KPI_METRICS, filters=gen_filters)
        err_rows = await _metrics_query(client, from_ts, to_ts, COUNT_ONLY, filters=gen_filters + [_gen_filter("level", "ERROR")])
        kpi_row = kpi_rows[0] if kpi_rows else {}
        total_calls = int(_row_num(kpi_row, "sum", "count"))
        err_count = int(_row_num(err_rows[0] if err_rows else {}, "sum", "count"))

        kpi = {
            "total_calls": total_calls,
            "session_count": int(_row_num(kpi_row, "uniq", "uniqueSessionIds")),
            "total_tokens": int(_row_num(kpi_row, "sum", "totalTokens")),
            "input_tokens": int(_row_num(kpi_row, "sum", "inputTokens")),
            "output_tokens": int(_row_num(kpi_row, "sum", "outputTokens")),
            "total_cost": round(_row_num(kpi_row, "sum", "totalCost"), 4),
            "p50_latency_ms": round(_row_num(kpi_row, "p50", "latency"), 1),
            "p95_latency_ms": round(_row_num(kpi_row, "p95", "latency"), 1),
            "avg_ttft_ms": round(_row_num(kpi_row, "avg", "timeToFirstToken"), 1),
            "error_rate": round(err_count / total_calls, 4) if total_calls else 0.0,
        }

        # 2) 模型维度（仅在「全部模型」时；单模型时跳过，前端隐藏模型对比区）
        by_model: List[Dict[str, Any]] = []
        if not model:
            m_rows = await _metrics_query(
                client, from_ts, to_ts, MODEL_METRICS,
                dimensions=[{"field": "providedModelName"}], filters=gen_filters,
            )
            m_err_rows = await _metrics_query(
                client, from_ts, to_ts, COUNT_ONLY,
                dimensions=[{"field": "providedModelName"}],
                filters=gen_filters + [_gen_filter("level", "ERROR")],
            )
            err_by_model: Dict[str, int] = {}
            for r in m_err_rows:
                err_by_model[str(r.get("providedModelName"))] = int(_row_num(r, "sum", "count"))
            for r in m_rows:
                name = str(r.get("providedModelName") or "未知模型")
                calls = int(_row_num(r, "sum", "count"))
                sum_lat_ms = _row_num(r, "sum", "latency")
                out_tok = int(_row_num(r, "sum", "outputTokens"))
                tps = (out_tok / (sum_lat_ms / 1000.0)) if sum_lat_ms > 0 else 0.0
                by_model.append({
                    "model": name,
                    "calls": calls,
                    "input_tokens": int(_row_num(r, "sum", "inputTokens")),
                    "output_tokens": out_tok,
                    "tokens": int(_row_num(r, "sum", "totalTokens")),
                    "cost": round(_row_num(r, "sum", "totalCost"), 4),
                    "p50_latency_ms": round(_row_num(r, "p50", "latency"), 1),
                    "p95_latency_ms": round(_row_num(r, "p95", "latency"), 1),
                    "avg_ttft_ms": round(_row_num(r, "avg", "timeToFirstToken"), 1),
                    "error_rate": round(err_by_model.get(name, 0) / calls, 4) if calls else 0.0,
                    "tokens_per_sec": round(tps, 1),
                })
            by_model.sort(key=lambda x: x["calls"], reverse=True)

        # 3) 按日趋势：每天一个主查询 + 一个错误数查询，并发拉取
        daily = await _fetch_daily(client, from_ts, to_ts, window, gen_filters)

    payload = {
        "enabled": True,
        "configured": True,
        "model": model,
        "window": {"days": window, "from": _iso(from_ts), "to": _iso(to_ts)},
        "kpi": kpi,
        "by_model": by_model,
        "daily": daily,
    }
    _CACHE[(window, mkey)] = (time.time(), payload)
    return payload


async def get_tools_overview(window: str = "7d", tool_name: Optional[str] = None) -> Dict[str, Any]:
    """工具调用总览：KPI（调用数/平均耗时/P95/错误率）+ by_tool（按工具名）+ daily 趋势。

    数据来自 Langfuse metrics observations view，按工具 observation 聚合。

    风险说明（见 task-B1）：工具调用 observation 的 type/分组字段名是据
    Langfuse LangChain CallbackHandler 默认行为假设的，未经运行时探查验证。
    本实现用 `TOOL_TYPE_FILTER_VALUE="CHAIN"` 与 `TOOL_DIMENSION_FIELD="name"` 作默认值；
    若探查发现实际 type/字段不同，修正模块顶部那两个常量即可，本函数无需改动。
    若探查发现工具调用无独立 observation（只嵌在 GENERATION 的 tool_calls 里），
    则应返回 `{"enabled": True, "configured": True, "supported": False, ...}` 空态。
    """
    mkey = f"tools::{tool_name or ''}"
    cached = _CACHE.get((window, mkey))
    if cached and (time.time() - cached[0]) < CACHE_TTL:
        return cached[1]

    cfg = get_langfuse_config()
    from_ts, to_ts = _window_range(window)

    tool_filters = [_gen_filter("type", TOOL_TYPE_FILTER_VALUE)]
    if tool_name:
        tool_filters = tool_filters + [_gen_filter(TOOL_DIMENSION_FIELD, tool_name)]

    async with httpx.AsyncClient(
        base_url=cfg["api_base"],
        auth=cfg["auth"],
        timeout=httpx.Timeout(30.0, connect=10.0),
    ) as client:
        # 1) KPI
        kpi_rows = await _metrics_query(client, from_ts, to_ts, TOOL_KPI_METRICS, filters=tool_filters)
        err_rows = await _metrics_query(client, from_ts, to_ts, COUNT_ONLY, filters=tool_filters + [_gen_filter("level", "ERROR")])
        kpi_row = kpi_rows[0] if kpi_rows else {}
        total_calls = int(_row_num(kpi_row, "sum", "count"))
        err_count = int(_row_num(err_rows[0] if err_rows else {}, "sum", "count"))
        kpi = {
            "tool_call_count": total_calls,
            "avg_latency_ms": round(_row_num(kpi_row, "avg", "latency"), 1),
            "p95_latency_ms": round(_row_num(kpi_row, "p95", "latency"), 1),
            "error_rate": round(err_count / total_calls, 4) if total_calls else 0.0,
        }

        # 2) by_tool 维度（仅「全部工具」时；单工具时跳过）
        by_tool: List[Dict[str, Any]] = []
        if not tool_name:
            t_rows = await _metrics_query(
                client, from_ts, to_ts, TOOL_BY_METRICS,
                dimensions=[{"field": TOOL_DIMENSION_FIELD}], filters=tool_filters,
            )
            t_err_rows = await _metrics_query(
                client, from_ts, to_ts, COUNT_ONLY,
                dimensions=[{"field": TOOL_DIMENSION_FIELD}],
                filters=tool_filters + [_gen_filter("level", "ERROR")],
            )
            err_by_tool: Dict[str, int] = {}
            for r in t_err_rows:
                err_by_tool[str(r.get(TOOL_DIMENSION_FIELD))] = int(_row_num(r, "sum", "count"))
            for r in t_rows:
                tn = str(r.get(TOOL_DIMENSION_FIELD) or "未知工具")
                calls = int(_row_num(r, "sum", "count"))
                by_tool.append({
                    "tool": tn,
                    "calls": calls,
                    "avg_latency_ms": round(_row_num(r, "avg", "latency"), 1),
                    "p95_latency_ms": round(_row_num(r, "p95", "latency"), 1),
                    "error_rate": round(err_by_tool.get(tn, 0) / calls, 4) if calls else 0.0,
                })
            by_tool.sort(key=lambda x: x["calls"], reverse=True)

        # 3) 按日趋势
        # NOTE: _fetch_daily 内部用 DAILY_METRICS（含 totalTokens/totalCost 等
        # GENERATION 专属字段），传 tool_filters 会让 daily 行多出无意义的 tokens/cost 列，
        # 且字段名（date/calls/tokens/cost/p50_latency_ms/error_rate）与本函数约定的
        # day/calls/avg_latency_ms/error_rate 不一致。故在此内联一份精简 daily 逻辑：
        # 仅 count + avg latency + error，字段名固定为 day/calls/avg_latency_ms/error_rate。
        daily = await _fetch_tool_daily(client, from_ts, to_ts, window, tool_filters)

    payload = {
        "enabled": True,
        "configured": True,
        "supported": True,
        "tool": tool_name,
        "window": {"days": window, "from": _iso(from_ts), "to": _iso(to_ts)},
        "kpi": kpi,
        "by_tool": by_tool,
        "daily": daily,
    }
    _CACHE[(window, mkey)] = (time.time(), payload)
    return payload


async def _fetch_tool_daily(
    client: httpx.AsyncClient,
    from_ts: datetime,
    to_ts: datetime,
    window: str,
    tool_filters: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """工具按日趋势：每天 count + avg latency + error 数，并发拉取。

    字段名固定 day/calls/avg_latency_ms/error_rate（与 _fetch_daily 的
    date/calls/tokens/cost/p50_latency_ms/error_rate 不同，故独立实现）。
    """
    days: List[Tuple[str, datetime, datetime]] = []
    cur = from_ts.astimezone(SHANGHAI).replace(hour=0, minute=0, second=0, microsecond=0)
    end_sh = to_ts.astimezone(SHANGHAI)
    while cur <= end_sh:
        d_start = cur
        d_end = cur + timedelta(days=1)
        days.append((cur.strftime("%Y-%m-%d"), d_start.astimezone(timezone.utc), d_end.astimezone(timezone.utc)))
        cur = cur + timedelta(days=1)
    if len(days) > 31:
        days = days[-31:]

    sem = asyncio.Semaphore(DAILY_CONCURRENCY)

    async def one_day(date_str: str, d_from: datetime, d_to: datetime) -> Dict[str, Any]:
        async with sem:
            rows = await _metrics_query(client, d_from, d_to, TOOL_DAILY_METRICS, filters=tool_filters)
            err_rows = await _metrics_query(
                client, d_from, d_to, COUNT_ONLY,
                filters=tool_filters + [_gen_filter("level", "ERROR")],
            )
        row = rows[0] if rows else {}
        calls = int(_row_num(row, "sum", "count"))
        err = int(_row_num(err_rows[0] if err_rows else {}, "sum", "count"))
        return {
            "day": date_str,
            "calls": calls,
            "avg_latency_ms": round(_row_num(row, "avg", "latency"), 1),
            "error_rate": round(err / calls, 4) if calls else 0.0,
        }

    results = await asyncio.gather(*[one_day(d, f, t) for d, f, t in days])
    return list(results)


async def _fetch_daily(
    client: httpx.AsyncClient,
    from_ts: datetime,
    to_ts: datetime,
    window: str,
    gen_filters: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """按 Asia/Shanghai 日期逐天查 count/tokens/cost/p50延迟 + 错误数。"""
    # 枚举从 from 到 to 的每一天（Asia/Shanghai 日期）
    days: List[Tuple[str, datetime, datetime]] = []
    cur = from_ts.astimezone(SHANGHAI).replace(hour=0, minute=0, second=0, microsecond=0)
    end_sh = to_ts.astimezone(SHANGHAI)
    while cur <= end_sh:
        d_start = cur
        d_end = cur + timedelta(days=1)
        days.append((cur.strftime("%Y-%m-%d"), d_start.astimezone(timezone.utc), d_end.astimezone(timezone.utc)))
        cur = cur + timedelta(days=1)
    # 30 天窗口最多 31 天，避免极端长窗
    if len(days) > 31:
        days = days[-31:]

    sem = asyncio.Semaphore(DAILY_CONCURRENCY)

    async def one_day(date_str: str, d_from: datetime, d_to: datetime) -> Dict[str, Any]:
        async with sem:
            rows = await _metrics_query(client, d_from, d_to, DAILY_METRICS, filters=gen_filters)
            err_rows = await _metrics_query(
                client, d_from, d_to, COUNT_ONLY,
                filters=gen_filters + [_gen_filter("level", "ERROR")],
            )
        row = rows[0] if rows else {}
        calls = int(_row_num(row, "sum", "count"))
        err = int(_row_num(err_rows[0] if err_rows else {}, "sum", "count"))
        return {
            "date": date_str,
            "calls": calls,
            "tokens": int(_row_num(row, "sum", "totalTokens")),
            "cost": round(_row_num(row, "sum", "totalCost"), 4),
            "p50_latency_ms": round(_row_num(row, "p50", "latency"), 1),
            "error_rate": round(err / calls, 4) if calls else 0.0,
        }

    results = await asyncio.gather(*[one_day(d, f, t) for d, f, t in days])
    return list(results)


def get_status() -> Dict[str, Any]:
    """给前端判断禁用态用（不发网络请求、不泄露 key）。"""
    return {
        "enabled": bool(settings.langfuse_enabled),
        "configured": is_configured(),
        "base_url": (settings.langfuse_base_url or ""),
    }


# ── 质量评分（scores-numeric 视图）──
# scores 合法 measure：count / value；维度 name(评分名) / observationModelName / timestampDay / value(分布)。
_SCORES_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}

_SCORES_AVG_METRICS = [
    {"measure": "count", "aggregation": "sum"},
    {"measure": "value", "aggregation": "avg"},
]
_SCORES_COUNT_METRICS = [{"measure": "count", "aggregation": "sum"}]


async def get_scores_overview(window: str = "7d", name: Optional[str] = None) -> Dict[str, Any]:
    """质量评分总览：5 条 scores-numeric 查询。带缓存。"""
    nkey = name or ""
    cached = _SCORES_CACHE.get((window, nkey))
    if cached and (time.time() - cached[0]) < CACHE_TTL:
        return cached[1]

    cfg = get_langfuse_config()
    from_ts, to_ts = _window_range(window)
    filters: List[Dict[str, Any]] = []
    if name:
        filters.append(_gen_filter("name", name))

    async with httpx.AsyncClient(
        base_url=cfg["api_base"],
        auth=cfg["auth"],
        timeout=httpx.Timeout(30.0, connect=10.0),
    ) as client:
        # 1) KPI 总览
        kpi_rows = await _metrics_query(
            client, from_ts, to_ts, _SCORES_AVG_METRICS, filters=filters, view="scores-numeric",
        )
        kpi_row = kpi_rows[0] if kpi_rows else {}
        score_count = int(_row_num(kpi_row, "sum", "count"))

        # 2) 各评分维度（选了具体 name 时跳过）
        by_name: List[Dict[str, Any]] = []
        if not name:
            n_rows = await _metrics_query(
                client, from_ts, to_ts, _SCORES_AVG_METRICS,
                dimensions=[{"field": "name"}], filters=filters, view="scores-numeric",
            )
            for r in n_rows:
                by_name.append({
                    "name": str(r.get("name") or "未知"),
                    "count": int(_row_num(r, "sum", "count")),
                    "avg_value": round(_row_num(r, "avg", "value"), 4),
                })
            by_name.sort(key=lambda x: x["count"], reverse=True)
            # 过滤已废弃的评分维度
            _DEPRECATED_SCORE_NAMES = frozenset({"helpfulness", "factuality", "chinese_quality"})
            by_name = [item for item in by_name if item["name"] not in _DEPRECATED_SCORE_NAMES]

        # 3) 按模型
        m_rows = await _metrics_query(
            client, from_ts, to_ts, _SCORES_AVG_METRICS,
            dimensions=[{"field": "observationModelName"}], filters=filters, view="scores-numeric",
        )
        by_model: List[Dict[str, Any]] = []
        for r in m_rows:
            by_model.append({
                "model": str(r.get("observationModelName") or "未知"),
                "count": int(_row_num(r, "sum", "count")),
                "avg_value": round(_row_num(r, "avg", "value"), 4),
            })
        by_model.sort(key=lambda x: x["count"], reverse=True)

        # 4) 日趋势（timestampDay 一条查询）
        d_rows = await _metrics_query(
            client, from_ts, to_ts, _SCORES_AVG_METRICS,
            dimensions=[{"field": "timestampDay"}], filters=filters, view="scores-numeric",
        )
        daily: List[Dict[str, Any]] = []
        for r in d_rows:
            daily.append({
                "date": str(r.get("timestampDay") or ""),
                "count": int(_row_num(r, "sum", "count")),
                "avg_value": round(_row_num(r, "avg", "value"), 4),
            })
        daily.sort(key=lambda x: x["date"])

        # 5) 评分分布（按 value）
        v_rows = await _metrics_query(
            client, from_ts, to_ts, _SCORES_COUNT_METRICS,
            dimensions=[{"field": "value"}], filters=filters, view="scores-numeric",
        )
        distribution: List[Dict[str, Any]] = []
        for r in v_rows:
            distribution.append({
                "value": float(r.get("value") or 0),
                "count": int(_row_num(r, "sum", "count")),
            })
        distribution.sort(key=lambda x: x["value"])

    payload = {
        "enabled": True,
        "configured": True,
        "name": name,
        "window": {"days": window, "from": _iso(from_ts), "to": _iso(to_ts)},
        "kpi": {
            "score_count": score_count,
            "avg_score": round(_row_num(kpi_row, "avg", "value"), 4),
            "score_name_count": len(by_name) if not name else 0,
            "score_model_count": len(by_model),
        },
        "by_name": by_name,
        "by_model": by_model,
        "daily": daily,
        "distribution": distribution,
    }
    _SCORES_CACHE[(window, nkey)] = (time.time(), payload)
    return payload


# ── 评分会话视图：把 trace + scores 串起来，给前端「按会话看评分 + 理由」──
# 数据来源：
#   1) /v2/observations?type=CHAIN&name=LangGraph —— root observation，拿 trace_id / session_id /
#     metadata(agent_version, mode, query) / input / output / started_at；
#   2) /v3/scores?fields=core,details,subject —— 拿 score 的 value / comment(理由) / subject.traceId。
# 两边按 traceId join 起来，前端按会话列出每个评分维度及理由。
_SCORE_TRACES_CACHE: Dict[Tuple[str, str, int], Tuple[float, Dict[str, Any]]] = {}


def _extract_query_from_input(input_val: Any) -> str:
    """从 root observation 的 input（messages 列表 JSON）里抽出第一条 human 消息作为用户查询。"""
    if not input_val:
        return ""
    # input 可能是 JSON 字符串或 dict
    try:
        data = input_val if isinstance(input_val, (dict, list)) else json.loads(input_val)
    except Exception:
        return ""
    msgs = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(msgs, list):
        return ""
    for m in msgs:
        if isinstance(m, dict) and m.get("type") == "human":
            c = m.get("content")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                # content 可能是 list of part dicts
                for p in c:
                    if isinstance(p, dict) and isinstance(p.get("text"), str):
                        return p["text"]
    return ""


def _extract_output_text(output_val: Any) -> str:
    """从 root observation 的 output（messages 列表 JSON）里抽出最后一条 AI 消息。"""
    if not output_val:
        return ""
    try:
        data = output_val if isinstance(output_val, (dict, list)) else json.loads(output_val)
    except Exception:
        return ""
    msgs = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(msgs, list):
        return ""
    last_ai = ""
    for m in msgs:
        if isinstance(m, dict) and m.get("type") == "ai":
            c = m.get("content")
            if isinstance(c, str) and c.strip():
                last_ai = c
            elif isinstance(c, list):
                for p in c:
                    if isinstance(p, dict) and isinstance(p.get("text"), str) and p["text"].strip():
                        last_ai = p["text"]
    return last_ai


def _safe_json_str(val: Any) -> str:
    """把 observation input/output 安全转成 JSON 字符串（已经是 str 就直接返回）。"""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    try:
        return json.dumps(val, ensure_ascii=False)
    except Exception:
        return str(val)


async def _fetch_root_observations(
    client: httpx.AsyncClient,
    from_ts: datetime,
    to_ts: datetime,
    version: Optional[str] = None,
    max_pages: int = 10,
) -> List[Dict[str, Any]]:
    """抓 type=CHAIN&name=LangGraph 的 root observation，cursor 翻页。"""
    observations: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    # 用 metadata.agent_version 做服务端过滤（v2 observations 支持 stringObject metadata 过滤）
    for _ in range(max_pages):
        params: Dict[str, Any] = {
            "fromStartTime": _iso(from_ts),
            "toStartTime": _iso(to_ts),
            "type": "CHAIN",
            "name": "LangGraph",
            "limit": 100,
            "fields": "core,details,io,metadata",
        }
        if cursor:
            params["cursor"] = cursor
        try:
            r = await client.get("/v2/observations", params=params)
            if r.status_code != 200:
                logger.warning(f"[Langfuse] observations -> {r.status_code}: {r.text[:300]}")
                break
            body = r.json() or {}
            items = body.get("data") or []
            observations.extend(items)
            cursor = (body.get("meta") or {}).get("cursor")
            if not cursor or not items:
                break
        except Exception as e:
            logger.warning(f"[Langfuse] observations 查询异常: {e}")
            break
    # 客户端再做一次 version 过滤（兜底；服务端 stringObject 过滤有些场景不准）
    if version:
        observations = [
            o for o in observations
            if str((o.get("metadata") or {}).get("agent_version", "")) == version
            or f"v{version}" in (str((o.get("metadata") or {}).get("agent_version", "")))
        ]
    return observations


async def _fetch_scores_with_subject(
    client: httpx.AsyncClient,
    from_ts: datetime,
    to_ts: datetime,
    trace_ids: Optional[List[str]] = None,
    max_pages: int = 10,
) -> List[Dict[str, Any]]:
    """抓 v3 scores 带 subject（traceId），cursor 翻页。"""
    scores: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    for _ in range(max_pages):
        params: Dict[str, Any] = {
            "fromTimestamp": _iso(from_ts),
            "toTimestamp": _iso(to_ts),
            "limit": 100,
            "fields": "core,details,subject",
        }
        if cursor:
            params["cursor"] = cursor
        try:
            r = await client.get("/v3/scores", params=params)
            if r.status_code != 200:
                logger.warning(f"[Langfuse] scores -> {r.status_code}: {r.text[:300]}")
                break
            body = r.json() or {}
            items = body.get("data") or []
            scores.extend(items)
            cursor = body.get("nextCursor") or body.get("cursor")
            if not cursor or not items:
                break
        except Exception as e:
            logger.warning(f"[Langfuse] scores 查询异常: {e}")
            break
    if trace_ids:
        tid_set = set(trace_ids)
        scores = [
            s for s in scores
            if ((s.get("subject") or {}).get("traceId") or "") in tid_set
        ]
    return scores


async def _fetch_trace_tool_steps(
    client: httpx.AsyncClient,
    trace_id: str,
) -> List[Dict[str, Any]]:
    """拉取一个 trace 内所有 TOOL 类型 observation（工具调用步骤）。

    排除 write_todos（TodoListMiddleware 自动记录，非用户关心的实际工具），
    按 startTime 升序排列。
    """
    steps: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    for _ in range(2):  # 最多 2 页，tool steps 通常不超过 50
        params: Dict[str, Any] = {
            "traceId": trace_id,
            "type": "TOOL",
            "limit": 100,
            "fields": "core,basic,io,metrics",
        }
        if cursor:
            params["cursor"] = cursor
        try:
            r = await client.get("/v2/observations", params=params)
            if r.status_code != 200:
                break
            body = r.json() or {}
            items = body.get("data") or []
            for o in items:
                name = o.get("name") or ""
                if name == "write_todos":
                    continue
                steps.append({
                    "name": name,
                    "input": _safe_json_str(o.get("input")),
                    "output": _safe_json_str(o.get("output")),
                    "start_time": o.get("startTime"),
                    "end_time": o.get("endTime"),
                    "latency": o.get("latency"),
                    "observation_id": o.get("id"),
                })
            cursor = body.get("meta", {}).get("cursor")
            if not cursor or not items:
                break
        except Exception as e:
            logger.warning(f"[Langfuse] tool steps for trace {trace_id[:20]}: {e}")
            break
    steps.sort(key=lambda s: s.get("start_time") or "")
    return steps


async def get_score_traces(
    window: str = "7d",
    version: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """按会话(session)聚合列出每个 trace 的评分 + 理由。

    返回:
      {
        "enabled": True, "configured": True,
        "window": {...},
        "version": "0.1" | null,
        "session_id": "xxx" | null,
        "available_versions": ["0.1", ...],
        "sessions": [
          {
            "session_id", "version", "mode", "query", "output",
            "started_at", "last_at", "trace_count", "score_count", "avg_score",
            "traces": [
              {trace_id, session_id, version, mode, query, output, started_at,
               score_count, avg_score, scores: [{name, value, comment, timestamp}]}
            ]
          }, ...
        ]
      }
    """
    cache_key = (window, version or "", session_id or "", limit)
    cached = _SCORE_TRACES_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < SCORE_TRACES_CACHE_TTL:
        return cached[1]

    cfg = get_langfuse_config()
    from_ts, to_ts = _window_range(window)

    async with httpx.AsyncClient(
        base_url=cfg["api_base"],
        auth=cfg["auth"],
        timeout=httpx.Timeout(30.0, connect=10.0),
    ) as client:
        root_obs = await _fetch_root_observations(client, from_ts, to_ts, version=version)
        trace_ids = [o.get("traceId") for o in root_obs if o.get("traceId")]
        scores = await _fetch_scores_with_subject(client, from_ts, to_ts, trace_ids=trace_ids)

        # 过滤已废弃的评分维度（helpfulness/factuality/chinese_quality 已替换为工具调用质量评估）
        _DEPRECATED_SCORE_NAMES = frozenset({"helpfulness", "factuality", "chinese_quality"})
        scores = [s for s in scores if s.get("name") not in _DEPRECATED_SCORE_NAMES]

        # 按 traceId 聚合 scores（保留 observation_id 用于后续匹配到 tool step）
        scores_by_trace: Dict[str, List[Dict[str, Any]]] = {}
        for s in scores:
            tid = (s.get("subject") or {}).get("traceId") or ""
            if not tid:
                continue
            scores_by_trace.setdefault(tid, []).append({
                "id": s.get("id"),
                "name": s.get("name"),
                "value": s.get("value"),
                "data_type": s.get("dataType"),
                "comment": s.get("comment") or "",
                "timestamp": s.get("timestamp"),
                "source": s.get("source"),
                "observation_id": (s.get("subject") or {}).get("id") or "",
            })

        # 把 trace 聚合到 session（thread_id 是 LangGraph 的 session 标识，跨多次 Agent 调用共享）
        traces: List[Dict[str, Any]] = []
        for o in root_obs:
            tid = o.get("traceId") or ""
            if not tid:
                continue
            md = o.get("metadata") or {}
            trace_scores = scores_by_trace.get(tid, [])
            nums = [float(s["value"]) for s in trace_scores
                    if s.get("data_type") == "NUMERIC" and isinstance(s.get("value"), (int, float))]
            avg = round(sum(nums) / len(nums), 4) if nums else None
            sid = md.get("thread_id") or (o.get("sessionId") or "")
            if session_id and sid != session_id:
                continue
            traces.append({
                "trace_id": tid,
                "observation_id": o.get("id"),
                "session_id": sid,
                "version": str(md.get("agent_version", "") or ""),
                "mode": str(md.get("mode", "") or ""),
                "query": _extract_query_from_input(o.get("input")) or str(md.get("query", "") or ""),
                "output": _extract_output_text(o.get("output")),
                "started_at": o.get("startTime"),
                "score_count": len(trace_scores),
                "avg_score": avg,
                "scores": trace_scores,
            })

        # 拉取每个 trace 的工具调用步骤 + 关联评分
        tool_steps_tasks = [
            _fetch_trace_tool_steps(client, t["trace_id"])
            for t in traces
        ]
        all_tool_steps_list = await asyncio.gather(*tool_steps_tasks)
        for t, tool_steps in zip(traces, all_tool_steps_list):
            # 把 scores 按 observation_id 匹配到具体 tool step
            trace_scores_by_obs: Dict[str, List[Dict[str, Any]]] = {}
            for sc in t.get("scores", []):
                obs_id = sc.get("observation_id", "")
                if obs_id:
                    trace_scores_by_obs.setdefault(obs_id, []).append(sc)
            for step in tool_steps:
                step["scores"] = trace_scores_by_obs.get(step["observation_id"], [])
            t["tool_steps"] = tool_steps

    # 挖出 available_versions：从已拉到的 root obs metadata 里取
    available_versions: List[str] = []
    vset: set[str] = set()
    for o in root_obs:
        v = str((o.get("metadata") or {}).get("agent_version", "")).strip()
        if v:
            vset.add(v)
    # 当前请求带了 version 过滤时，root_obs 已被过滤；重拉一次全量的补全版本下拉列表
    if version:
        try:
            async with httpx.AsyncClient(
                base_url=cfg["api_base"], auth=cfg["auth"],
                timeout=httpx.Timeout(20.0, connect=10.0),
            ) as client:
                all_root = await _fetch_root_observations(client, from_ts, to_ts, version=None, max_pages=3)
            for o in all_root:
                v = str((o.get("metadata") or {}).get("agent_version", "")).strip()
                if v:
                    vset.add(v)
        except Exception:
            pass
    available_versions = sorted(vset)

    # 按 session 聚合
    sessions_map: Dict[str, Dict[str, Any]] = {}
    session_order: List[str] = []  # 保留首次出现的顺序
    for t in traces:
        sid = t.get("session_id") or "_unknown"
        if sid not in sessions_map:
            sessions_map[sid] = {
                "session_id": sid,
                "version": t.get("version", ""),
                "mode": t.get("mode", ""),
                # session 级 query/output 用最早一条 trace 的（首轮 user query + 末轮 AI output）
                "query": t.get("query", ""),
                "traces": [],
                "started_at": t.get("started_at"),
                "last_at": t.get("started_at"),
                "score_count": 0,
                "avg_score": None,
            }
            session_order.append(sid)
        s = sessions_map[sid]
        s["traces"].append(t)
        s["score_count"] += t.get("score_count", 0)
        # 取末轮 output 作为 session 输出
        if t.get("output"):
            s["output"] = t.get("output")
        # 起止时间
        ts = t.get("started_at") or ""
        if ts:
            if (s.get("started_at") or "") > ts:
                s["started_at"] = ts
            if (s.get("last_at") or "") < ts:
                s["last_at"] = ts

    # session 平均分 = 所有 NUMERIC 评分的均值
    sessions: List[Dict[str, Any]] = []
    for sid in session_order:
        s = sessions_map[sid]
        all_nums: List[float] = []
        for t in s["traces"]:
            for sc in t.get("scores", []):
                if sc.get("data_type") == "NUMERIC" and isinstance(sc.get("value"), (int, float)):
                    all_nums.append(float(sc["value"]))
        s["avg_score"] = round(sum(all_nums) / len(all_nums), 4) if all_nums else None
        s["trace_count"] = len(s["traces"])
        # traces 内部按时间升序（同一 session 多轮 Agent 调用按先后看）
        s["traces"].sort(key=lambda t: t.get("started_at") or "")
        sessions.append(s)

    # session 倒序（最近一次对话在最上面）
    sessions.sort(key=lambda s: s.get("last_at") or s.get("started_at") or "", reverse=True)
    if limit > 0:
        sessions = sessions[:limit]

    payload = {
        "enabled": True,
        "configured": True,
        "version": version,
        "session_id": session_id,
        "window": {"days": window, "from": _iso(from_ts), "to": _iso(to_ts)},
        "available_versions": available_versions,
        "sessions": sessions,
    }
    _SCORE_TRACES_CACHE[cache_key] = (time.time(), payload)
    return payload


# ── Experiment 评估(离线 skill 评估闭环)──────────────────────────────

_EXPERIMENT_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_EXPERIMENT_CACHE_TTL = 60  # 60s


async def _experiment_items_request(
    client: httpx.AsyncClient,
    from_ts: datetime,
    to_ts: datetime,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    """拉 experiment-items(带 scores 字段),Langfuse v4 真正分数来源。

    契约(spike 钉死):
      GET /api/public/experiment-items?fromStartTime=<ISO_Z>&fields=scores&limit=N
      limit 必须 ≤100,超过会 400("Too big: expected number to be <=100")
    """
    # Langfuse REST 限制 limit ≤ 100,超了分页拉
    page_size = min(limit, 100)
    remaining = limit
    out: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while remaining > 0:
        n = min(page_size, remaining)
        query: Dict[str, Any] = {
            "fromStartTime": _iso(from_ts).replace("+00:00", "Z"),
            "limit": n,
            "fields": "scores",
        }
        if cursor:
            query["cursor"] = cursor
        try:
            r = await client.get("/experiment-items", params=query)
            if r.status_code != 200:
                logger.warning(f"[Langfuse] experiment-items -> {r.status_code}: {r.text[:300]}")
                return out
            body = r.json() or {}
            data = body.get("data") or []
            out.extend(data)
            if len(data) < n:
                # 没下一页
                break
            # 翻页游标:用最后一条的 id 或 nextCursor
            next_cursor = body.get("nextCursor")
            if not next_cursor and data:
                next_cursor = data[-1].get("id")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
            remaining -= len(data)
        except Exception as e:
            logger.warning(f"[Langfuse] experiment-items 查询异常: {e}")
            return out
    return out


async def list_datasets() -> List[Dict[str, Any]]:
    """列出所有 dataset(= skill 评估对象),用于前端下拉选择。

    走 SDK ``client.get_dataset_names()`` 不可靠(v4 有兼容性问题),故本函数走 REST。
    """
    cfg = get_langfuse_config()
    items: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # v4 dataset 列表端点
            r = await client.get(f"{cfg['api_base']}/datasets", params={"limit": 100}, auth=cfg["auth"])
            if r.status_code != 200:
                logger.warning(f"[Langfuse] datasets -> {r.status_code}: {r.text[:300]}")
                return []
            body = r.json() or {}
            for d in body.get("data") or []:
                items.append({
                    "id": d.get("id"),
                    "name": d.get("name"),
                    "items_count": (d.get("datasetItems") or {}).get("count") or 0,
                    "created_at": d.get("createdAt"),
                })
    except Exception as e:
        logger.warning(f"[Langfuse] list_datasets 异常: {e}")
    return items


async def list_prompt_versions(name: str, limit: int = 50) -> Dict[str, Any]:
    """拉取 Langfuse prompt 的所有版本(供「评估」页对照 experiment 用的提示词)。

    走 SDK 按版本号拉,REST v2/prompts 只列版本号不含内容。
    返回:
      {
        "name": "business_lead",
        "versions": [
          {"version": 1, "labels": [...], "prompt": "...", "config": {}}, ...
        ],
        "latest_version": N,
        "production_version": N | None,
      }
    """
    cfg = get_langfuse_config()
    out: Dict[str, Any] = {"name": name, "versions": [], "latest_version": None, "production_version": None}
    try:
        async with httpx.AsyncClient(base_url=cfg["api_base"], auth=cfg["auth"], timeout=10.0) as client:
            # 1. 先拉 v2 列表拿到版本号数组
            r = await client.get("/v2/prompts", params={"name": name, "limit": limit})
            if r.status_code != 200:
                logger.warning(f"[Langfuse] v2/prompts -> {r.status_code}: {r.text[:300]}")
                return out
            body = r.json() or {}
            data = body.get("data") or []
            if not data:
                return out
            meta = data[0]
            version_nums = meta.get("versions") or []
            labels = meta.get("labels") or []
            out["latest_version"] = max(version_nums) if version_nums else None
            if "production" in labels:
                # production 通常指向最新版本,SDK 取 production 时 fallback 逻辑会兜底
                out["production_version"] = max(version_nums) if version_nums else None
    except Exception as e:
        logger.warning(f"[Langfuse] list_prompt_versions 列版本异常: {e}")
        return out

    # 2. 用 SDK 按版本号拉每版的 prompt 内容
    try:
        from .sdk import get_langfuse_client
        client = get_langfuse_client()
        if client is None:
            return out
        for v in sorted(version_nums, reverse=True):
            try:
                pc = client.get_prompt(name, version=v, type="text", cache_ttl_seconds=0,
                                       max_retries=1, fetch_timeout_seconds=5)
                out["versions"].append({
                    "version": pc.version,
                    "labels": list(pc.labels or []),
                    "prompt": pc.prompt,
                    "config": dict(pc.config) if pc.config else {},
                })
            except Exception as e:
                logger.warning(f"[Langfuse] 拉 prompt {name} v{v} 失败: {e}")
                out["versions"].append({"version": v, "labels": [], "prompt": "", "config": {}, "error": str(e)})
    except Exception as e:
        logger.warning(f"[Langfuse] list_prompt_versions SDK 拉内容异常: {e}")
    return out


async def get_experiment_overview(dataset_name: Optional[str] = None) -> Dict[str, Any]:
    """按 dataset 聚合各 experiment(run)的分数通过率。

    数据源:
      1. GET /api/public/experiments?datasetName=<x> 列出该 dataset 下所有 run
      2. GET /api/public/experiment-items?fields=scores 拉所有 item(含 scores)
      3. 按 experimentId 聚合 scores:对每个 run 计算
         - 各 score name 的通过率(value==1.0 的占比)
         - 总 item 数 / 已评分 item 数

    缓存 60s。
    """
    cache_key = dataset_name or "_all"
    cached = _EXPERIMENT_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _EXPERIMENT_CACHE_TTL:
        return cached[1]

    cfg = get_langfuse_config()
    # 拉近 30 天的 experiment-items(评估跑得少,30 天够)
    to_ts = datetime.now(timezone.utc)
    from_ts = to_ts - timedelta(days=30)

    async with httpx.AsyncClient(
        base_url=cfg["api_base"],
        auth=cfg["auth"],
        timeout=15.0,
    ) as client:
        items = await _experiment_items_request(client, from_ts, to_ts, limit=1000)

    # dataset_name -> experimentName 前缀(约定:dataset=station-analysis-eval 对应 run 名
    # station-analysis-v1/v2/...;dataset 名去掉 "-eval" 后缀就是 skill 名 = run 名前缀)
    skill_prefix = dataset_name[:-5] if (dataset_name and dataset_name.endswith("-eval")) else dataset_name

    # 按 experimentId 聚合
    by_exp: Dict[str, Dict[str, Any]] = {}
    for it in items:
        exp_id = it.get("experimentId")
        if not exp_id:
            continue
        if skill_prefix:
            exp_name = it.get("experimentName") or ""
            if not exp_name.startswith(skill_prefix):
                continue

        slot = by_exp.setdefault(exp_id, {
            "experiment_id": exp_id,
            "experiment_name": it.get("experimentName") or "",
            "trace_id": it.get("traceId"),
            "started_at": it.get("startTime"),
            "ended_at": it.get("endTime"),
            "item_count": 0,
            "scored_count": 0,
            "scores_by_name": {},  # name -> [values]
        })
        slot["item_count"] += 1
        scores = it.get("scores") or []
        if scores:
            slot["scored_count"] += 1
        for s in scores:
            sname = s.get("name") or "<unknown>"
            sval = s.get("value")
            slot["scores_by_name"].setdefault(sname, []).append(sval)

    # 计算通过率
    runs: List[Dict[str, Any]] = []
    for exp_id, slot in by_exp.items():
        dimensions = []
        for sname, values in slot["scores_by_name"].items():
            n = len(values)
            passed = sum(1 for v in values if v == 1)
            dimensions.append({
                "name": sname,
                "total": n,
                "passed": passed,
                "pass_rate": (passed / n) if n > 0 else 0.0,
            })
        dimensions.sort(key=lambda d: d["name"])
        # 总通过率 = 各维度 pass_rate 的平均(简易聚合)
        overall = sum(d["pass_rate"] for d in dimensions) / len(dimensions) if dimensions else 0.0
        runs.append({
            "experiment_id": exp_id,
            "experiment_name": slot["experiment_name"],
            "started_at": slot["started_at"],
            "ended_at": slot["ended_at"],
            "item_count": slot["item_count"],
            "scored_count": slot["scored_count"],
            "dimensions": dimensions,
            "overall_pass_rate": overall,
        })
    # 按时间倒序
    runs.sort(key=lambda r: r.get("started_at") or "", reverse=True)

    payload = {
        "enabled": True,
        "configured": True,
        "dataset": dataset_name,
        "runs": runs,
    }
    _EXPERIMENT_CACHE[cache_key] = (time.time(), payload)
    return payload

