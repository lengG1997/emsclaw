#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把上游网关的模型定价批量灌进 Langfuse（self-hosted v4）。

设计要点
- 幂等：先 GET 现有自定义模型，按 modelName 去重，已存在则跳过（不重复建）。
- 自动换算：网关给的是 ratio（倍率），约定 ratio=1 = $0.002/1K tokens
  （one-api 系标准基准，group_ratio 默认 1）。Langfuse 价格单位是 USD/token：
      inputPrice  = model_ratio * 2e-6
      outputPrice = model_ratio * completion_ratio * 2e-6
- 货币：Langfuse v4 货币单位写死 USD，无 CNY 选项，本脚本灌美元价。
- 图像/embedding 模型也一并灌（unit=TOKENS，价格按 token 算）；若不需要可改 filter。
- 排除 Langfuse 自带系统模型（isLangfuseManaged=true），只处理自建模型。
- 定价表 PRICING / TIER_PRICING 按自身网关的报价维护，换网关时整表替换即可。

用法
  # 需先设置 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY（见 .env.example）
  python scripts/langfuse_seed_models.py

  # 指定另一个环境的 Langfuse
  LANGFUSE_BASE_URL=http://other-host:3000 \
  LANGFUSE_PUBLIC_KEY=pk-lf-xxx \
  LANGFUSE_SECRET_KEY=sk-lf-xxx \
  python scripts/langfuse_seed_models.py

  # 干跑（只打印将建的，不实际 POST）
  DRY_RUN=1 python scripts/langfuse_seed_models.py

  # 只灌对话类模型，跳过 image/embedding
  ONLY_CHAT=1 python scripts/langfuse_seed_models.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import List, Tuple

# ── 配置（环境变量覆盖）──
BASE_URL = os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3000").rstrip("/")
PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
if not PUBLIC_KEY or not SECRET_KEY:
    print(
        "缺少必需的环境变量: LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY\n"
        "请参考 .env.example 填写后再运行。",
        file=sys.stderr,
    )
    sys.exit(2)
DRY_RUN = os.environ.get("DRY_RUN") == "1"
ONLY_CHAT = os.environ.get("ONLY_CHAT") == "1"
RATE_PER_1K = 2e-6  # ratio=1 => $0.002/1K tokens => $2e-6/token

# ── 定价数据（model_name, model_ratio, completion_ratio）──
# 来源：网关 /v1/models + 定价接口。ratio=1 = $0.002/1K tokens 基准。
# 网关调价后更新此表重跑即可（已存在的会跳过，需先删旧记录才更新价）。
PRICING: List[Tuple[str, float, float]] = [
    ("claude-haiku-4-5", 0.55, 5),
    ("claude-haiku-4-5-20251001", 0.55, 5),
    ("claude-opus-4-8", 2.5, 5),
    ("claude-sonnet-4-6", 1.5, 5),
    ("claude-sonnet-5", 1, 5),
    # DeepSeek 系按 Flash 一档计价（-pro / -vision-exp 均重定向至此）。
    # 新价（peak 档）输入 $0.2816/1M、输出 $1.1264/1M ⇒ ratio=0.2816/2=0.1408, completion=4。
    # 缓存价见下方 TIER_PRICING（扁平价表达不了，只能用 pricingTiers）。
    ("deepseek-v4-flash", 0.1408, 4),
    ("deepseek-v4-pro", 0.232, 2),
    ("doubao-seed-2-1-pro", 0.46475, 5),
    ("doubao-seed-2-1-turbo", 0.232375, 5),
    ("doubao-seed-evolving", 0.46475, 5),
    ("gemini-2.5-flash-image", 0.15, 100),
    ("gemini-3-pro-image", 1, 60),
    ("gemini-3.1-flash-image", 0.25, 120),
    ("gemini-3.1-flash-lite-image", 0.125, 120),
    ("gemini-3.1-pro-preview", 1, 6),
    ("gemini-3.5-flash", 0.75, 6),
    ("glm-5.1", 0.55, 3.6),
    ("glm-5.2", 0.5634, 3.5),
    ("gpt-5.3-codex", 0.875, 8),
    ("gpt-5.4", 1.25, 6),
    ("gpt-5.4-mini", 0.375, 6),
    ("gpt-5.4-nano", 0.1, 6.25),
    ("gpt-5.5", 2.5, 6),
    ("gpt-5.6-luna", 0.1, 6),
    ("gpt-5.6-sol", 2.5, 6),
    ("gpt-5.6-terra", 1, 6),
    ("gpt-image-2", 2.5, 6),
    ("grok-4.3", 0.625, 2),
    ("grok-4.5", 1, 3),
    ("kimi-k2.6", 0.475, 4.2105),
    ("kimi-k2.7-code", 0.475, 4.21),
    ("kimi-k2.7-code-highspeed", 0.95, 4.21),
    ("kimi-k3", 1.5, 5),
    ("MiniMax-M3", 0.144, 4),
    ("qwen3.7-max", 0.845, 3),
    ("qwen3.7-plus", 0.141, 4),
    ("text-embedding-3-large", 0.065, 1),
    ("text-embedding-3-small", 0.01, 1),
    ("text-embedding-v4", 0.04, 1),
]

# 图像生成 / embedding 类（ONLY_CHAT 时排除）
IMAGE_EMBEDDING = {
    "gemini-2.5-flash-image", "gemini-3-pro-image", "gemini-3.1-flash-image",
    "gemini-3.1-flash-lite-image", "gpt-image-2",
    "text-embedding-3-large", "text-embedding-3-small", "text-embedding-v4",
}

# 需要「缓存价」的模型 —— 扁平 inputPrice/outputPrice 表达不了，必须用 pricingTiers
# （API 约束：两套价格二选一，同时给会 400）。
# 数值单位 USD / 1M tokens，取自网关模型页「基础价格」（= peak 档）。
# 网关实际计费按时段浮动（peak 为工作日 09:00-12:00 / 14:00-18:00，其余时段 off，off = peak 的 50%），
# Langfuse 不支持按时段计价，这里统一按 peak（保守、不低估成本）。
TIER_PRICING = {
    "deepseek-v4-flash": {
        "input": 0.2816,
        "input_tokens": 0.2816,
        "output": 1.1264,
        "output_tokens": 1.1264,
        "input_cache_read": 0.005632,
        "cache_read_input_tokens": 0.005632,
        "input_cached_tokens": 0.005632,
        "input_cache_creation": 0.2816,
        "cache_creation_input_tokens": 0.2816,
        "input_cache_creation_1h": 0.2816,
    },
}


def _auth_header() -> str:
    return "Basic " + base64.b64encode(f"{PUBLIC_KEY}:{SECRET_KEY}".encode()).decode()


def _get(path: str) -> dict:
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        headers={"Authorization": _auth_header()},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _post(path: str, body: dict) -> Tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, method="POST",
        headers={"Authorization": _auth_header(), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def list_existing_custom_models() -> set:
    """返回已存在的自定义模型名（排除 Langfuse 自带的）。"""
    names: set = set()
    page = 1
    while True:
        d = _get(f"/api/public/models?limit=100&page={page}")
        rows = d.get("data", [])
        for m in rows:
            if not m.get("isLangfuseManaged"):
                names.add(m["modelName"])
        if len(rows) < 100:
            break
        page += 1
        if page > 20:
            break
    return names


def main() -> int:
    print(f"[Langfuse] base_url={BASE_URL}  dry_run={DRY_RUN}  only_chat={ONLY_CHAT}")
    print(f"[Langfuse] 待处理模型数: {len(PRICING)}")

    existing = list_existing_custom_models()
    print(f"[Langfuse] 已存在自定义模型: {len(existing)} 个")

    created, skipped, failed = 0, 0, 0
    for name, ratio, comp_ratio in PRICING:
        if ONLY_CHAT and name in IMAGE_EMBEDDING:
            continue
        tier = TIER_PRICING.get(name)
        if tier:
            # 用 pricingTiers 走（含缓存价）
            in_1m = tier["input"]
            out_1m = tier["output"]
        else:
            input_price = round(ratio * RATE_PER_1K, 9)
            output_price = round(ratio * comp_ratio * RATE_PER_1K, 9)
            # 1M token 价（仅打印用）
            in_1m = input_price * 1_000_000
            out_1m = output_price * 1_000_000

        if name in existing:
            print(f"  跳过(已存在) {name:<26} ${in_1m:.4f}/${out_1m:.4f} per 1M")
            skipped += 1
            continue

        if tier:
            # 注意：pricingTiers 与扁平 inputPrice/outputPrice 只能二选一，同时给会 400
            body = {
                "modelName": name,
                "matchPattern": f"(?i)^({name})$",
                "unit": "TOKENS",
                "pricingTiers": [
                    {
                        "name": "Standard",
                        "isDefault": True,
                        "priority": 0,
                        "conditions": [],
                        "prices": {k: v / 1_000_000 for k, v in tier.items()},
                    }
                ],
            }
        else:
            body = {
                "modelName": name,
                "matchPattern": f"(?i)^({name})$",
                "unit": "TOKENS",
                "inputPrice": input_price,
                "outputPrice": output_price,
            }
        if DRY_RUN:
            print(f"  [DRY] 将建 {name:<26} ${in_1m:.4f}/${out_1m:.4f} per 1M")
            created += 1
            continue

        code, resp = _post("/api/public/models", body)
        if code == 200:
            print(f"  建成   {name:<26} ${in_1m:.4f}/${out_1m:.4f} per 1M")
            created += 1
        else:
            print(f"  失败   {name:<26} HTTP {code}: {str(resp)[:120]}")
            failed += 1
        time.sleep(0.05)

    print(f"\n完成: 新建 {created}, 跳过 {skipped}, 失败 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
