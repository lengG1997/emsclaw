"""B1: get_tools_overview 聚合结构正确。"""
import asyncio
from unittest.mock import patch, AsyncMock
from emsclaw_backend.observability import http_client as lc


def _stub_metrics(rows_by_call):
    """rows_by_call: list of row-lists，按 _metrics_query 调用顺序返回。"""
    it = iter(rows_by_call)

    async def _fake(client, from_ts, to_ts, metrics, dimensions=None, filters=None, view="observations"):
        try:
            return next(it)
        except StopIteration:
            return []
    return _fake


def test_get_tools_overview_kpi_and_by_tool():
    kpi_rows = [{"sum_count": 10, "avg_latency": 200.0, "p95_latency": 500.0}]
    err_rows = [{"sum_count": 1}]
    by_rows = [{"name": "get_device", "sum_count": 6, "avg_latency": 150.0, "p95_latency": 400.0},
               {"name": "list_devices", "sum_count": 4, "avg_latency": 250.0, "p95_latency": 600.0}]
    by_err_rows = [{"name": "get_device", "sum_count": 1}, {"name": "list_devices", "sum_count": 0}]
    daily_rows = []

    with patch.object(lc, "_metrics_query", _stub_metrics([kpi_rows, err_rows, by_rows, by_err_rows, daily_rows])), \
         patch.object(lc, "_fetch_tool_daily", new=AsyncMock(return_value=[])), \
         patch.object(lc, "get_langfuse_config", return_value={"api_base": "x", "auth": ("k", "s")}):
        lc._CACHE.clear()
        res = asyncio.run(lc.get_tools_overview(window="7d"))

    assert res["supported"] is True
    assert res["kpi"]["tool_call_count"] == 10
    assert res["kpi"]["error_rate"] == 0.1
    assert len(res["by_tool"]) == 2
    assert res["by_tool"][0]["tool"] == "get_device"
    assert res["by_tool"][0]["calls"] == 6
    assert res["by_tool"][0]["error_rate"] == round(1 / 6, 4)
