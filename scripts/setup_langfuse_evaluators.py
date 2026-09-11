#!/usr/bin/env python3
"""
一键配置 Langfuse LLM-as-judge 在线评测系统。

幂等：同名 evaluator 自动 version-bump，同名 rule 会报 409 但可手动清理后重跑。
需先启动 Langfuse 栈：
  docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up -d

用法：
  python scripts/setup_langfuse_evaluators.py

环境变量：
  LANGFUSE_HOST        - Langfuse 地址，默认 http://localhost:3001
  LANGFUSE_PUBLIC_KEY  - 必填。与 docker-compose.langfuse.yml 中 LANGFUSE_PUBLIC_KEY 一致
  LANGFUSE_SECRET_KEY  - 必填。与 docker-compose.langfuse.yml 中 LANGFUSE_SECRET_KEY 一致
  JUDGE_API_KEY        - 必填。Judge 模型所在网关的 API Key
  JUDGE_BASE_URL       - 必填。Judge 模型网关的 OpenAI 兼容地址，如 https://your-gateway/v1
  JUDGE_MODEL          - Judge 模型名，默认 qwen3.7-plus
"""
import json
import os
import sys
import urllib.request
import base64

# ── 配置 ──
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "http://localhost:3001")
PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
JUDGE_KEY = os.environ.get("JUDGE_API_KEY", "")
JUDGE_BASE = os.environ.get("JUDGE_BASE_URL", "")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "qwen3.7-plus")

_missing = [
    name
    for name, value in (
        ("LANGFUSE_PUBLIC_KEY", PUBLIC_KEY),
        ("LANGFUSE_SECRET_KEY", SECRET_KEY),
        ("JUDGE_API_KEY", JUDGE_KEY),
        ("JUDGE_BASE_URL", JUDGE_BASE),
    )
    if not value
]
if _missing:
    print(f"缺少必需的环境变量: {', '.join(_missing)}", file=sys.stderr)
    print("请参考 .env.example 填写后再运行。", file=sys.stderr)
    sys.exit(2)

AUTH = base64.b64encode(f"{PUBLIC_KEY}:{SECRET_KEY}".encode()).decode()
AUTH_HEADER = {"Authorization": f"Basic {AUTH}", "Content-Type": "application/json"}


def _post(path: str, body: dict) -> dict:
    """POST JSON 到 Langfuse API，返回解析后的响应。"""
    req = urllib.request.Request(
        f"{LANGFUSE_HOST}{path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=AUTH_HEADER,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def step1_llm_connection():
    """创建/更新 Judge 模型连接（upsert on provider）。"""
    print("\n[1/4] 配置 LLM 连接 (judge-gateway)...")
    body = {
        "provider": "judge-gateway",
        "adapter": "openai",
        "secretKey": JUDGE_KEY,
        "baseURL": JUDGE_BASE,
        "withDefaultModels": False,
        "customModels": [
            JUDGE_MODEL,
        ],
    }
    req = urllib.request.Request(
        f"{LANGFUSE_HOST}/api/public/llm-connections",
        data=json.dumps(body).encode(),
        headers=AUTH_HEADER,
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        r = json.loads(resp.read())
    print(f"  完成: provider={r.get('provider')}")


def step2_evaluators():
    """创建 4 个 LLM-as-judge evaluator。"""
    print("\n[2/4] 创建 4 个 Evaluator...")

    prompt_template = (
        "你是一个工具调用质量评判员。请用中文评估这次 Agent 对话中每一步的「{dim}」质量。\n"
        "\n"
        "【用户问题】\n"
        "{{{{input}}}}\n"
        "\n"
        "【Agent 的工具调用序列与最终回复】\n"
        "{{{{output}}}}\n"
        "\n"
        "步骤编号 N 对应对话过程中 `[工具返回 #N]` 标记的工具调用。如某步骤无问题，不要提及。\n"
        "\n"
        "打分标准（1-5 整数）：\n"
        "{criteria}\n"
        "\n"
        "请严格按以下 markdown 结构输出评分理由：\n"
        "\n"
        "**优点**\n"
        "- 分点列出做得好的方面（至少 1 条，如无明显优点写「无明显优点」）\n"
        "\n"
        "**问题工具**（必须引用步骤编号，无则写「无」）\n"
        "- 步骤 #N: 一句话说明该步骤的问题\n"
        "\n"
        "**综合建议**\n"
        "- 一句话给出改进方向\n"
        "\n"
        "**评分：X**\n"
        "\n"
        "注意：必须全中文输出。步骤编号必须用 `#N` 格式引用。"
    )

    dimensions = {
        "tool_selection": {
            "dim": "工具选型",
            "criteria": "\n".join([
                "- 5：每一步都选了最合适的工具，无遗漏、无多余调用",
                "- 4：绝大部分步骤工具选型正确，仅个别次优选择",
                "- 3：大部分步骤工具正确，但有明显选型不当",
                "- 2：多个关键步骤选错工具，影响任务完成",
                "- 1：大量工具选型错误，任务基本未完成",
            ]),
        },
        "tool_order_reasoning": {
            "dim": "调用顺序",
            "criteria": "\n".join([
                "- 5：调用顺序完全合理，先获取数据再分析再行动，逻辑链条清晰",
                "- 4：整体顺序合理，个别步骤可以优化",
                "- 3：部分步骤顺序存在问题，但不影响核心结果",
                "- 2：明显有步骤颠倒或跳跃，影响了执行效率",
                "- 1：调用顺序混乱，完全不符合分析逻辑",
            ]),
        },
        "argument_quality": {
            "dim": "参数质量",
            "criteria": "\n".join([
                "- 5：所有参数准确完整，必需字段不缺，值域合理",
                "- 4：绝大多数参数正确，仅个别参数有轻微偏差",
                "- 3：参数基本可用，但存在缺失或不当参数",
                "- 2：关键参数缺失或明显错误，影响工具执行结果",
                "- 1：参数大面积错误，工具基本无法正确执行",
            ]),
        },
        "result_utilization": {
            "dim": "结果利用",
            "criteria": "\n".join([
                "- 5：工具返回的关键数据和结论全部被正确整合到最终回复中",
                "- 4：绝大部分工具结果被有效利用，仅个别遗漏",
                "- 3：部分工具结果未被利用，或利用方式不够准确",
                "- 2：多个工具调用结果被忽视或误用",
                "- 1：工具调用与最终回复严重脱节，结果基本白费",
            ]),
        },
    }

    for name, cfg in dimensions.items():
        prompt = prompt_template.format(dim=cfg["dim"], criteria=cfg["criteria"])
        # tool_selection 维度 qwen3.7-plus 有英文输出偏好，强制中文
        if name == "tool_selection":
            prompt = "【语言要求：你必须用中文回复，全文禁止出现英文单词或英文句子。】\n\n" + prompt
        body = {
            "type": "llm_as_judge",
            "name": name,
            "prompt": prompt,
            "outputDefinition": {
                "dataType": "NUMERIC",
                "reasoning": {
                    "description": (
                        "按「优点/问题工具/综合建议」三段 markdown 格式输出，"
                        "问题工具段引用 `[工具返回 #N]` 步骤编号"
                    ),
                },
                "score": {"description": "1 到 5 之间的整数"},
            },
            "modelConfig": {"provider": "judge-gateway", "model": JUDGE_MODEL},
        }
        r = _post("/api/public/unstable/evaluators", body)
        print(f"  {r['name']} v{r['version']} ✓")


def step3_evaluation_rules():
    """创建 4 条评分规则（自动触发 LLM-as-judge 评分）。"""
    print("\n[3/4] 创建 4 条评分规则...")

    for name in [
        "tool_selection",
        "tool_order_reasoning",
        "argument_quality",
        "result_utilization",
    ]:
        body = {
            "name": name,
            "evaluator": {"name": name, "scope": "project", "type": "llm_as_judge"},
            "target": "observation",
            "enabled": True,
            "mapping": [
                {"variable": "input", "source": "input"},
                {"variable": "output", "source": "output"},
            ],
            "filter": [
                {
                    "type": "stringOptions",
                    "column": "name",
                    "operator": "any of",
                    "value": ["eval-data"],
                }
            ],
        }
        try:
            r = _post("/api/public/unstable/evaluation-rules", body)
            print(f"  {r['name']} enabled={r['enabled']} ✓")
        except urllib.error.HTTPError as e:
            if e.code == 409:
                print(f"  {name} 已存在，跳过 (409 Conflict)")
            else:
                raise


def step4_seed_models():
    """灌入模型定价数据。"""
    import subprocess
    print("\n[4/4] 灌入模型定价...")
    seed_script = os.path.join(os.path.dirname(__file__), "langfuse_seed_models.py")
    env = os.environ.copy()
    env["LANGFUSE_BASE_URL"] = LANGFUSE_HOST
    result = subprocess.run(
        [sys.executable, seed_script],
        env=env,
        capture_output=True,
        text=True,
    )
    # 只打印关键行
    for line in result.stdout.strip().split("\n"):
        if "完成" in line or "建成" in line or "base_url" in line:
            print(f"  {line.strip()}")
    if result.returncode != 0:
        print(f"  警告: seed_models 退出码 {result.returncode}")
        print(f"  stderr: {result.stderr[:500]}")


def print_summary():
    print(f"""
{'=' * 60}
✅ Langfuse 在线评测系统配置完成！

Judge 模型: {JUDGE_MODEL}
Langfuse:   {LANGFUSE_HOST}
登录:       admin@emsclaw.local / admin123

4 个评分维度（对每轮 Agent 对话自动评分）：
  1. tool_selection       — 工具选型 (1-5)
  2. tool_order_reasoning — 调用顺序 (1-5)
  3. argument_quality     — 参数质量 (1-5)
  4. result_utilization   — 结果利用 (1-5)

验证：
  跟 Agent 聊几句 → 等待 10-30s → 打开 http://localhost:5173/chat/score-overview
{"=" * 60}
""")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"Langfuse: {LANGFUSE_HOST}")
    print(f"Judge:     {JUDGE_MODEL}")

    try:
        step1_llm_connection()
    except Exception as e:
        print(f"  ❌ LLM 连接失败: {e}")
        print("  请确认 Langfuse 已启动，且 JUDGE_API_KEY / JUDGE_BASE_URL 正确")
        sys.exit(1)

    try:
        step2_evaluators()
    except Exception as e:
        print(f"  ❌ Evaluator 创建失败: {e}")
        print("  请确认 judge 模型支持 json_schema structured output")
        sys.exit(1)

    try:
        step3_evaluation_rules()
    except Exception as e:
        print(f"  ⚠️  Rule 创建部分失败（可能已存在）: {e}")

    try:
        step4_seed_models()
    except Exception as e:
        print(f"  ⚠️ 模型定价灌入失败（不影响核心功能）: {e}")

    print_summary()
