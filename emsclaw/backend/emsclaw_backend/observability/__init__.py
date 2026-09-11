"""observability — Langfuse 可观测性集成 + 工具调用质量评估（在线 + 离线）。

在线 LLM-as-Judge: 4 维度(tool_selection/tool_order_reasoning/argument_quality/result_utilization),
  配置见 docs/langfuse-judge-setup.md, Langfuse evaluation rule 自动触发。
离线 Code evaluator: 8 维度(tool_set/tool_order/subagent/tool_count/repeat_rate/
  tool_result_quality/tool_args_validity/tool_efficiency), 通过 run_experiment 对 golden dataset 跑。

子模块:
  sdk             — SDK 单例 + CallbackHandler + trace_attributes + warmup
  prompts         — 提示词版本化(运行时拉取 + sync CLI)
  http_client     — Langfuse REST 取数(运营指标:模型/质量/工具)
  route           — 运营指标路由(挂 /api/v1/langfuse/*)
  sse_middleware  — SSEMonitoringMiddleware(主对话流 + eval 流共用)
  eval/           — 离线评估闭环:
      runner.py        — EvalResult + run_eval_task(独立 eval Agent 执行器)
      tool_trace.py    — ToolTraceCollector(astream_events v2 收集 + 子 agent mapping)
      evaluators.py    — 8 个通用 Code evaluator
      experiment.py    — run_skill_eval() 包装 SDK run_experiment
      dataset_api.py   — dataset/dataset_item REST 客户端(批量导入样本)
      cli.py           — python -m emsclaw_backend.observability.eval.cli run ...
"""
