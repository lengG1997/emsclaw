"""eval CLI — 命令行入口,跑一次 experiment 或批量导入 dataset items。

用法：

  # 批量导入 golden sample 到 dataset
  python -m emsclaw_backend.observability.eval.cli import-items \\
      --dataset station-analysis-eval \\
      --file ./samples.json

  # 跑一次 experiment（run_name 不传则用 dataset-<ISO ts>）
  python -m emsclaw_backend.observability.eval.cli run \\
      --dataset station-analysis-eval \\
      --run-name station-analysis-v1

注：CLI 仅做参数解析与调度。task 函数（如何把 dataset item 的 input.query
跑成 Agent 输出）由调用方提供 —— 默认用 ``default_skill_task`` 走通用 eval Agent,
不绑定任何 skill 专有逻辑。

Langfuse 必须已就绪（LANGFUSE_ENABLED=true 且鉴权通过）,否则会 RuntimeError。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from typing import Any, Dict, List

from loguru import logger

from .dataset_api import create_dataset_items, load_items_from_json
from .experiment import run_skill_eval
from .runner import run_eval_task
from ..sdk import is_ready


# ── 默认 task 函数（通用,不绑定 skill） ────────────────────────────────

async def default_skill_task(*, item: Any, **kwargs: Any) -> Dict[str, Any]:
    """默认 task：拿 item.input["query"] 跑生产 Lead,返回 SDK 约定的 dict。

    Langfuse SDK ``run_experiment`` 的 task 函数可同步可异步;SDK 内部用
    ``run_async_safely`` 包了一层事件循环,task 同步签名会在已运行的 loop 里调
    ``asyncio.run`` 报错,所以这里**必须 async**。

    item 可能是 dict(本地)或 langfuse DatasetItem 对象(从 Langfuse dataset 拉的),
    都要兼容 —— SDK 实测默认走 DatasetItem 对象路径。

    返回 dict 至少含 ``answer`` / ``tool_trace`` / ``delegates`` 三个键,
    供 5 个通用 Code evaluator 判定。
    """
    # 兼容 dict / DatasetItem 对象
    if isinstance(item, dict):
        input_data = item.get("input") or {}
        metadata = item.get("metadata") or {}
    else:
        input_data = getattr(item, "input", None) or {}
        metadata = getattr(item, "metadata", None) or {}
    query = (input_data or {}).get("query") if isinstance(input_data, dict) else ""
    if not query:
        return {"answer": "", "tool_trace": [], "delegates": []}

    session_id = metadata.get("session_id") or f"eval-{uuid.uuid4().hex[:12]}"
    model_config = metadata.get("model_config")

    result = await run_eval_task(
        session_id=session_id,
        query=query,
        model_config=model_config,
    )
    return {
        "answer": result.response,
        "tool_trace": result.tool_trace,
        "delegates": result.delegates,
    }


# ── 子命令：run ───────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> int:
    if not is_ready():
        logger.error(
            "Langfuse 未就绪;检查 LANGFUSE_ENABLED / LANGFUSE_PUBLIC_KEY / "
            "LANGFUSE_SECRET_KEY / LANGFUSE_HOST"
        )
        return 2

    logger.info(f"[cli] run experiment: dataset={args.dataset} run_name={args.run_name or '(auto)'}")
    result = run_skill_eval(
        dataset_name=args.dataset,
        skill_task_fn=default_skill_task,
        run_name=args.run_name,
        max_concurrency=args.concurrency,
    )
    # ExperimentResult 至少含 experiment_id / dataset_run_id / item_results
    exp_id = getattr(result, "experiment_id", None) or "(unknown)"
    ds_run_id = getattr(result, "dataset_run_id", None) or "(unknown)"
    items = getattr(result, "item_results", None) or []
    logger.info(
        f"[cli] experiment done: experiment_id={exp_id} "
        f"dataset_run_id={ds_run_id} items={len(items)}"
    )
    # 简要打印每条 item 的各 evaluator pass/fail
    for i, it in enumerate(items):
        scores = getattr(it, "evaluations", None) or []
        if not scores:
            continue
        parts = []
        for s in scores:
            name = getattr(s, "name", "") or (s.get("name") if isinstance(s, dict) else "")
            val = getattr(s, "value", None)
            if val is None and isinstance(s, dict):
                val = s.get("value")
            parts.append(f"{name}={val}")
        logger.info(f"  item[{i}]: {' '.join(parts)}")
    return 0


# ── 子命令：import-items ───────────────────────────────────────────────

async def _import_items(args: argparse.Namespace) -> int:
    items = load_items_from_json(args.file)
    if not items:
        logger.error(f"items file is empty: {args.file}")
        return 2
    created = await create_dataset_items(args.dataset, items, max_concurrency=args.concurrency)
    ok = sum(1 for c in created if c is not None)
    fail = len(created) - ok
    logger.info(f"[cli] import-items done: ok={ok} fail={fail} total={len(created)}")
    return 0 if fail == 0 else 1


def cmd_import_items(args: argparse.Namespace) -> int:
    return asyncio.run(_import_items(args))


# ── 入口 ────────────────────────────────────────────────────────────────

def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m emsclaw_backend.observability.eval.cli",
        description="Skill eval CLI: run experiment / import dataset items",
    )
    sp = p.add_subparsers(dest="cmd", required=True)

    # run
    p_run = sp.add_parser("run", help="跑一次 experiment (= skill 某个版本)")
    p_run.add_argument("--dataset", required=True, help="dataset 名(= skill 标识)")
    p_run.add_argument("--run-name", default=None, help="experiment run 名(= skill 版本)")
    p_run.add_argument("--concurrency", type=int, default=2,
                       help="并发上限(Agent 调用比较重,默认 2)")
    p_run.set_defaults(func=cmd_run)

    # import-items
    p_imp = sp.add_parser("import-items", help="批量导入 golden sample 到 dataset")
    p_imp.add_argument("--dataset", required=True, help="dataset 名")
    p_imp.add_argument("--file", required=True, help="JSON 文件路径(list 或 {items:[...]})")
    p_imp.add_argument("--concurrency", type=int, default=4, help="并发上限")
    p_imp.set_defaults(func=cmd_import_items)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
