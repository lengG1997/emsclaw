"""run_skill_eval — 通用 skill 评估入口。

复用 Langfuse SDK ``run_experiment``:
  - dataset_name = skill 标识(如 ``station-analysis-eval``)
  - 一个 experiment run = 该 skill 的某个版本
  - SDK 自动把 task 输出写到 experiment item,evaluator 写 score 到 trace observation
  - 前端通过 ``GET /api/public/experiment-items?fields=scores`` 取分数按版本聚合

task 函数签名(SDK 注入 item):
    def skill_task_fn(*, item, **kwargs) -> Dict[str, Any]:
        query = item.input["query"]
        eval_result = asyncio.run(run_eval_task(session_id=..., query=query, ...))
        return {
            "answer": eval_result.response,
            "tool_trace": eval_result.tool_trace,
            "delegates": eval_result.delegates,
        }

evaluator 签名(SDK 注入 input/output/expected_output/metadata):
    def evaluator(*, input, output, expected_output, metadata, **kwargs) -> Dict[str, Any]:
        return {"name": "...", "value": 1.0, "comment": "...", "data_type": "NUMERIC"}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from ..sdk import get_langfuse_client, is_ready
from .evaluators import DEFAULT_EVALUATORS

# Langfuse SDK 的 EvaluatorFunction 类型(供类型注解;import 失败时降级为 Callable)
try:
    from langfuse.experiment import EvaluatorFunction  # type: ignore
except Exception:  # pragma: no cover
    EvaluatorFunction = Callable  # type: ignore


def run_skill_eval(
    dataset_name: str,
    skill_task_fn: Callable[..., Dict[str, Any]],
    evaluators: Optional[List[Callable[..., Dict[str, Any]]]] = None,
    *,
    run_name: Optional[str] = None,
    description: Optional[str] = None,
    max_concurrency: int = 4,
) -> Any:
    """通用 skill 评估入口。复用 Langfuse SDK ``run_experiment``。

    Args:
        dataset_name: dataset 名(= skill 标识,如 ``station-analysis-eval``)
        skill_task_fn: 处理单条 dataset item 的函数,签名 ``(*, item, **kwargs) -> dict``。
            返回 dict 至少含 ``answer`` / ``tool_trace`` / ``delegates`` 三个键。
        evaluators: evaluator 函数列表;为空则用 ``DEFAULT_EVALUATORS``(5 个 Code evaluator)
        run_name: experiment run 名(= skill 版本,如 ``station-analysis-v1``)。
            不传则用 ``dataset_name-<ISO timestamp>``
        description: experiment 描述(可选)
        max_concurrency: 并发上限(默认 4,Agent 调用比较重,不要太大)

    Returns:
        Langfuse ``ExperimentResult``(含 ``experiment_id`` / ``dataset_run_id`` /
        ``item_results`` / ``run_evaluations``)

    Raises:
        RuntimeError: Langfuse 未就绪(SDK 不可用或鉴权失败)
    """
    if not is_ready():
        raise RuntimeError(
            "Langfuse 未就绪(SDK 不可用或鉴权失败);无法跑 experiment。"
            "检查 LANGFUSE_ENABLED / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST。"
        )

    client = get_langfuse_client()
    if client is None:
        raise RuntimeError("Langfuse client 不可用")

    dataset = client.get_dataset(dataset_name)
    logger.info(
        f"[run_skill_eval] dataset={dataset_name} items={len(dataset.items)} "
        f"run_name={run_name or '(auto)'} evaluators={len(evaluators or DEFAULT_EVALUATORS)}"
    )

    if evaluators is None:
        evaluators = DEFAULT_EVALUATORS

    effective_run_name = run_name or f"{dataset_name}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    return client.run_experiment(
        name=dataset_name,
        run_name=effective_run_name,
        description=description or f"Skill eval: {dataset_name}",
        data=dataset.items,
        task=skill_task_fn,
        evaluators=evaluators,
        max_concurrency=max_concurrency,
    )
