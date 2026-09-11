"""dataset REST 客户端 — 批量导入 golden sample 到 Langfuse dataset。

Langfuse v4 自托管实测契约（2026-08-06 spike 钉死）：
  - 端点：``POST /api/public/dataset-items``（**无** v2/v3 前缀）
  - 鉴权：HTTP Basic，username=public_key，password=secret_key
  - 请求体（单条）：
        {
          "datasetName": "station-analysis-eval",
          "input":         {"query": "..."},
          "expectedOutput": {"expected_tools": [...], ...},
          "metadata":       {...}     # 可选
        }
  - 返回：单条 {"id": "...", "datasetId": "...", ...}
  - 批量：循环单条 POST（无批量端点）；并发上限 4

SDK 也提供 ``client.create_dataset_item(...)``,但 spike 时用 SDK 创建的 item
偶尔在 ``get_dataset`` 拉回时 expectedOutput 字段拿不到（疑似 SDK 序列化问题）。
因此本模块直接走 REST,绕开 SDK 序列化层,保证 expectedOutput 原样落库。

用法：
    from emsclaw_backend.observability.eval.dataset_api import create_dataset_items
    items = [
        {"input": {"query": "..."}, "expectedOutput": {...}, "metadata": {...}},
        ...
    ]
    created = await create_dataset_items("station-analysis-eval", items)
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from ..http_client import get_langfuse_config


async def create_dataset_item(
    dataset_name: str,
    input: Dict[str, Any],
    expected_output: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """单条创建 dataset item。返回 Langfuse 响应（含 id/datasetId），失败返回 None。"""
    cfg = get_langfuse_config()
    url = f"{cfg['api_base']}/dataset-items"
    body = {
        "datasetName": dataset_name,
        "input": input,
        "expectedOutput": expected_output,
    }
    if metadata:
        body["metadata"] = metadata
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=body, auth=cfg["auth"])
        if r.status_code not in (200, 201):
            logger.warning(
                f"[dataset_api] POST dataset-items -> {r.status_code}: {r.text[:300]}"
            )
            return None
        return r.json()
    except Exception as e:
        logger.warning(f"[dataset_api] create item 异常: {e}")
        return None


async def create_dataset_items(
    dataset_name: str,
    items: List[Dict[str, Any]],
    *,
    max_concurrency: int = 4,
) -> List[Optional[Dict[str, Any]]]:
    """批量创建 dataset items。并发上限 max_concurrency（默认 4）。

    每个 item 形如：
        {"input": {"query": "..."}, "expectedOutput": {...}, "metadata": {...}}

    返回与 items 等长的列表：成功位置为 Langfuse 响应 dict,失败位置为 None。
    """
    sem = asyncio.Semaphore(max_concurrency)

    async def _one(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        async with sem:
            return await create_dataset_item(
                dataset_name=dataset_name,
                input=item.get("input") or {},
                expected_output=item.get("expectedOutput") or item.get("expected_output") or {},
                metadata=item.get("metadata"),
            )

    logger.info(
        f"[dataset_api] creating {len(items)} items into dataset={dataset_name} "
        f"(concurrency={max_concurrency})"
    )
    return await asyncio.gather(*[_one(it) for it in items])


def load_items_from_json(path: str) -> List[Dict[str, Any]]:
    """从 JSON 文件加载 items。文件内容可以是 list,或 {"items": [...]}。"""
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("items") or []
    if not isinstance(data, list):
        raise ValueError(f"invalid items file: expected list, got {type(data).__name__}")
    return data
