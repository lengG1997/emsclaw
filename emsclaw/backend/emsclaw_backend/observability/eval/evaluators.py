"""8 个通用 Code evaluator + 重复率算法定义。

所有 evaluator 签名一致(与 Langfuse SDK ``run_experiment`` 的 evaluator 约定一致):
    (*, input, output, expected_output, metadata, **kwargs) -> Dict[str, Any]

返回 dict 必含字段:
    name   : 评分维度名(唯一)
    value  : NUMERIC 数值(0.0 ~ 1.0,通过率/均值,前端按版本聚合)
    comment: 评语(展示用,会进 trace score 的 comment)

可选字段:
    data_type : "NUMERIC"(默认)

评估维度(通用,任何 skill 都适用):

| 维度                   | 算法                                              |
|-----------------------|---------------------------------------------------|
| tool_set              | expected_tools ⊆ actual 且 forbidden ∩ actual = ∅  |
| tool_order            | expected_order 是 actual 的子序列(允许中间插别的) |
| subagent              | expected_subagent ∈ delegates.subagent_type      |
| tool_count            | len(actual) <= max_tool_calls                     |
| repeat_rate           | 相邻重复对数 / max(len-1, 1) <= max_repeat_ratio  |
| tool_result_quality   | 工具返回值:非空、无错误标记、未被截断              |
| tool_args_validity    | 工具参数:必需字段存在、类型正确、值域合理          |
| tool_efficiency       | 检测浪费模式:读后覆写、冗余搜索                    |

dataset item 的 expectedOutput schema(通用):
    {
      "expected_tools": ["read_file", "execute"],
      "expected_order": ["read_file", "execute"],
      "forbidden_tools": ["delete_device"],
      "expected_subagent": null,
      "max_tool_calls": 8,
      "max_repeat_ratio": 0.2,
      "tool_result_checks": [
        {"tool_name": "get_*", "non_empty": true, "no_error": true, "not_truncated": true}
      ],
      "tool_args_checks": [
        {"tool_name": "get_*", "required_fields": ["station_id"],
         "field_types": {"station_id": "str"},
         "reasonable": {"station_id": {"min_len": 1, "max_len": 64}}}
      ],
      "tool_efficiency_checks": {"no_read_write_pair": true, "no_redundant_search": true},
      "quality_rubric": "回答必须覆盖:发电量、储能配置、具体建议"
    }
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
from typing import Any, Dict, List, Optional


def _actual_tool_names(output: Optional[Dict[str, Any]]) -> List[str]:
    """从 task 返回的 output.tool_trace 抽有序工具名列表。"""
    if not output:
        return []
    tool_trace = output.get("tool_trace") or []
    return [t.get("name", "") for t in tool_trace if t.get("name")]


def _actual_delegates(output: Optional[Dict[str, Any]]) -> List[str]:
    """从 output.delegates 抽 subagent_type 列表。"""
    if not output:
        return []
    delegates = output.get("delegates") or []
    return [d.get("subagent_type", "") for d in delegates if d.get("subagent_type")]


def _args_structural_hash(args: Any) -> str:
    """args 结构化 hash:dict 排序键后 json.dumps + md5 前 8 位。

    用于重复率判定:同 name + 同 args 结构 = 视为重复调用。
    """
    if args is None:
        return ""
    try:
        normalized = json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)
    except Exception:
        normalized = str(args)
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:8]


# ───────────────────────────────────────────────────────────────────
# Evaluator 1:工具正确性(集合)
# ───────────────────────────────────────────────────────────────────

def eval_tool_set(
    *,
    input: Any = None,
    output: Optional[Dict[str, Any]] = None,
    expected_output: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """expected_tools ⊆ actual 且 forbidden_tools ∩ actual = ∅。"""
    actual = _actual_tool_names(output)
    expected = (expected_output or {}).get("expected_tools", []) or []
    forbidden = (expected_output or {}).get("forbidden_tools", []) or []

    actual_set = set(actual)
    expected_set = set(expected)
    forbidden_set = set(forbidden)

    missing = expected_set - actual_set
    forbidden_hit = forbidden_set & actual_set
    ok = not missing and not forbidden_hit

    comment_parts = []
    if missing:
        comment_parts.append(f"missing: {sorted(missing)}")
    if forbidden_hit:
        comment_parts.append(f"forbidden hit: {sorted(forbidden_hit)}")
    if not comment_parts:
        comment_parts.append("ok")
    comment = f"expected={expected} actual={actual}; " + "; ".join(comment_parts)

    return {
        "name": "tool_set",
        "value": 1.0 if ok else 0.0,
        "comment": comment,
        "data_type": "NUMERIC",
    }


# ───────────────────────────────────────────────────────────────────
# Evaluator 2:工具顺序(子序列)
# ───────────────────────────────────────────────────────────────────

def eval_tool_order(
    *,
    input: Any = None,
    output: Optional[Dict[str, Any]] = None,
    expected_output: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """expected_order 是否为 actual 的子序列(允许中间插别的工具)。

    例:expected=["read_file","execute"], actual=["read_file","write_todos","execute"]
        → 通过(read_file 在 execute 前,中间允许有别的)
    """
    actual = _actual_tool_names(output)
    expected = (expected_output or {}).get("expected_order", []) or []

    if not expected:
        return {
            "name": "tool_order",
            "value": 1.0,
            "comment": "no expected_order specified; skip",
            "data_type": "NUMERIC",
        }

    # 子序列匹配:在 actual 里按顺序找 expected 的每个元素
    i = 0
    for name in expected:
        # 在 actual[i:] 里找下一个等于 name 的位置
        try:
            i = actual.index(name, i) + 1
        except ValueError:
            ok = False
            break
    else:
        ok = True

    return {
        "name": "tool_order",
        "value": 1.0 if ok else 0.0,
        "comment": f"expected_order={expected} actual={actual}; " + ("ok" if ok else "order mismatch"),
        "data_type": "NUMERIC",
    }


# ───────────────────────────────────────────────────────────────────
# Evaluator 3:子 agent 路由
# ───────────────────────────────────────────────────────────────────

def eval_subagent(
    *,
    input: Any = None,
    output: Optional[Dict[str, Any]] = None,
    expected_output: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """expected_subagent ∈ delegates 的 subagent_type。

    expected_subagent=null/空 → 跳过(默认 1.0,因为没要求路由)。
    """
    expected_subagent = (expected_output or {}).get("expected_subagent")
    if not expected_subagent:
        return {
            "name": "subagent",
            "value": 1.0,
            "comment": "no expected_subagent specified; skip",
            "data_type": "NUMERIC",
        }

    actual_delegates = _actual_delegates(output)
    ok = expected_subagent in actual_delegates
    return {
        "name": "subagent",
        "value": 1.0 if ok else 0.0,
        "comment": f"expected_subagent={expected_subagent} actual={actual_delegates}; "
                   + ("ok" if ok else "not routed"),
        "data_type": "NUMERIC",
    }


# ───────────────────────────────────────────────────────────────────
# Evaluator 4:工具用量(阈值)
# ───────────────────────────────────────────────────────────────────

def eval_tool_count(
    *,
    input: Any = None,
    output: Optional[Dict[str, Any]] = None,
    expected_output: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """len(actual) <= max_tool_calls。"""
    actual = _actual_tool_names(output)
    max_calls = (expected_output or {}).get("max_tool_calls")
    if max_calls is None:
        return {
            "name": "tool_count",
            "value": 1.0,
            "comment": "no max_tool_calls specified; skip",
            "data_type": "NUMERIC",
        }
    count = len(actual)
    ok = count <= max_calls
    return {
        "name": "tool_count",
        "value": 1.0 if ok else 0.0,
        "comment": f"count={count} max={max_calls}; " + ("ok" if ok else "exceeded"),
        "data_type": "NUMERIC",
    }


# ───────────────────────────────────────────────────────────────────
# Evaluator 5:重复率(阈值)
# ───────────────────────────────────────────────────────────────────

def _repeat_pairs(tool_trace: List[Dict[str, Any]]) -> int:
    """计算相邻重复对数。

    重复定义:相邻位置 i 和 i+1 的 (name, args_structural_hash) 相等。
    分母用 max(len-1, 1),所以 0 个或 1 个工具时分子分母都是 1,返回 0/1=0。
    """
    if not tool_trace:
        return 0
    # 抽 (name, args_hash) 序列;只看 start 或 complete 阶段(避免重复算)
    seq = []
    seen_ids = set()
    for t in tool_trace:
        # 取每个工具调用的代表条目(phase=start),避免 start+complete 双算
        if t.get("phase") == "start":
            tid = t.get("tool_call_id")
            if tid and tid in seen_ids:
                continue
            seen_ids.add(tid)
            seq.append((t.get("name", ""), _args_structural_hash(t.get("args"))))
    pairs = 0
    for i in range(len(seq) - 1):
        if seq[i] == seq[i + 1]:
            pairs += 1
    return pairs


def eval_repeat_rate(
    *,
    input: Any = None,
    output: Optional[Dict[str, Any]] = None,
    expected_output: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """相邻重复对数 / max(len-1, 1) <= max_repeat_ratio。

    重复定义:(name, args_structural_hash) 相邻才算重复。
    分子:相邻位置 i 和 i+1 满足上述相等的对数。
    分母:max(len(actual) - 1, 1)。
    """
    if not output:
        return {
            "name": "repeat_rate",
            "value": 1.0,
            "comment": "no output; skip",
            "data_type": "NUMERIC",
        }
    tool_trace = output.get("tool_trace") or []
    max_ratio = (expected_output or {}).get("max_repeat_ratio")
    if max_ratio is None:
        return {
            "name": "repeat_rate",
            "value": 1.0,
            "comment": "no max_repeat_ratio specified; skip",
            "data_type": "NUMERIC",
        }

    pairs = _repeat_pairs(tool_trace)
    # 抽唯一工具调用数(去 start+complete 双算)
    unique_ids = {t.get("tool_call_id") for t in tool_trace if t.get("phase") == "start"}
    n = len(unique_ids)
    denom = max(n - 1, 1)
    ratio = pairs / denom
    ok = ratio <= max_ratio

    return {
        "name": "repeat_rate",
        "value": 1.0 if ok else 0.0,
        "comment": f"repeat_pairs={pairs} denom={denom} ratio={ratio:.3f} max={max_ratio}; "
                   + ("ok" if ok else "too many repeats"),
        "data_type": "NUMERIC",
    }


# ───────────────────────────────────────────────────────────────────
# Evaluator 6: 工具结果质量（非空 / 无错误 / 无截断）
# ───────────────────────────────────────────────────────────────────

def eval_tool_result_quality(
    *,
    input: Any = None,
    output: Optional[Dict[str, Any]] = None,
    expected_output: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """检查工具返回值：非空、不含错误标记、未被截断。

    expectedOutput.tool_result_checks 是检查项列表：
    [
      {"tool_name": "get_station_snapshot", "non_empty": true, "no_error": true},
      {"tool_name": "analyze_*", "non_empty": true, "not_truncated": true},
    ]

    每个匹配 tool_name pattern（支持 ``*`` 通配符）的调用的 result 都要通过所有检查。
    通过率 = 通过 check 的调用数 / 总匹配调用数（0 匹配 → skip=1.0）。
    """
    if not output:
        return {
            "name": "tool_result_quality",
            "value": 1.0,
            "comment": "no output; skip",
            "data_type": "NUMERIC",
        }
    checks = (expected_output or {}).get("tool_result_checks", []) or []
    if not checks:
        return {
            "name": "tool_result_quality",
            "value": 1.0,
            "comment": "no tool_result_checks specified; skip",
            "data_type": "NUMERIC",
        }

    tool_trace = output.get("tool_trace") or []
    # 只取 complete 阶段（有 result）
    completed = [t for t in tool_trace if t.get("phase") == "complete"]
    total_matched = 0
    passed = 0
    details: List[str] = []

    for chk in checks:
        pattern = chk.get("tool_name", "*")
        matched = [t for t in completed if fnmatch.fnmatch(t.get("name", ""), pattern)]
        for t in matched:
            total_matched += 1
            result = t.get("result", "")
            call_pass = True
            call_issues: List[str] = []
            if chk.get("non_empty") and (result is None or str(result).strip() == ""):
                call_pass = False
                call_issues.append("empty")
            if chk.get("no_error"):
                result_str = str(result).lower()
                error_markers = ["error:", "exception:", "traceback", "failed:", "失败", "错误"]
                if any(m in result_str for m in error_markers):
                    call_pass = False
                    call_issues.append("error")
            if chk.get("not_truncated"):
                result_str = str(result)
                if result_str.endswith("...") or "[truncated]" in result_str.lower():
                    call_pass = False
                    call_issues.append("truncated")
            if call_pass:
                passed += 1
            else:
                details.append(f"{t['name']}({t.get('tool_call_id','')[:8]}): {','.join(call_issues)}")

    if total_matched == 0:
        return {
            "name": "tool_result_quality",
            "value": 1.0,
            "comment": "no tool results matched checks; skip",
            "data_type": "NUMERIC",
        }
    value = passed / total_matched
    comment = f"passed={passed}/{total_matched}"
    if details:
        comment += "; issues: " + "; ".join(details[:5])
    return {"name": "tool_result_quality", "value": value, "comment": comment, "data_type": "NUMERIC"}


# ───────────────────────────────────────────────────────────────────
# Evaluator 7: 工具参数有效性（必需字段 / 类型 / 合理值域）
# ───────────────────────────────────────────────────────────────────

def eval_tool_args_validity(
    *,
    input: Any = None,
    output: Optional[Dict[str, Any]] = None,
    expected_output: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """检查工具参数：必需字段存在、类型正确、值域合理。

    expectedOutput.tool_args_checks 格式：
    [
      {"tool_name": "get_station_snapshot", "required_fields": ["station_id"],
       "field_types": {"station_id": "str"},
       "reasonable": {"station_id": {"min_len": 1, "max_len": 64}}},
    ]

    每个匹配的调用的 args 要满足所有 check。通过率计算同 tool_result_quality。
    """
    if not output:
        return {
            "name": "tool_args_validity",
            "value": 1.0,
            "comment": "no output; skip",
            "data_type": "NUMERIC",
        }
    checks = (expected_output or {}).get("tool_args_checks", []) or []
    if not checks:
        return {
            "name": "tool_args_validity",
            "value": 1.0,
            "comment": "no tool_args_checks specified; skip",
            "data_type": "NUMERIC",
        }

    tool_trace = output.get("tool_trace") or []
    total_matched = 0
    passed = 0
    details: List[str] = []

    for chk in checks:
        pattern = chk.get("tool_name", "*")
        required_fields = chk.get("required_fields", []) or []
        field_types = chk.get("field_types", {}) or {}
        reasonable = chk.get("reasonable", {}) or {}

        matched = [t for t in tool_trace if fnmatch.fnmatch(t.get("name", ""), pattern)]
        for t in matched:
            total_matched += 1
            args = t.get("args") or {}
            if not isinstance(args, dict):
                details.append(f"{t['name']}: args not dict")
                continue
            call_pass = True
            call_issues: List[str] = []

            # 检查必需字段
            for f in required_fields:
                if f not in args or args[f] is None:
                    call_pass = False
                    call_issues.append(f"missing:{f}")

            # 检查字段类型（简单类型名称比较）
            for f, expected_type in field_types.items():
                if f in args and args[f] is not None:
                    actual_type = type(args[f]).__name__
                    if actual_type != expected_type:
                        call_pass = False
                        call_issues.append(f"type:{f}={actual_type}!={expected_type}")

            # 检查值域合理性（min_len/max_len for str, min/max for int/float）
            for f, constraints in reasonable.items():
                if f not in args or args[f] is None:
                    continue
                val = args[f]
                if isinstance(val, str):
                    if "min_len" in constraints and len(val) < constraints["min_len"]:
                        call_pass = False
                        call_issues.append(f"len:{f}={len(val)}<{constraints['min_len']}")
                    if "max_len" in constraints and len(val) > constraints["max_len"]:
                        call_pass = False
                        call_issues.append(f"len:{f}={len(val)}>{constraints['max_len']}")
                elif isinstance(val, (int, float)):
                    if "min" in constraints and val < constraints["min"]:
                        call_pass = False
                        call_issues.append(f"range:{f}={val}<{constraints['min']}")
                    if "max" in constraints and val > constraints["max"]:
                        call_pass = False
                        call_issues.append(f"range:{f}={val}>{constraints['max']}")

            if call_pass:
                passed += 1
            else:
                details.append(f"{t['name']}: {','.join(call_issues)}")

    if total_matched == 0:
        return {
            "name": "tool_args_validity",
            "value": 1.0,
            "comment": "no args matched checks; skip",
            "data_type": "NUMERIC",
        }
    value = passed / total_matched
    comment = f"passed={passed}/{total_matched}"
    if details:
        comment += "; issues: " + "; ".join(details[:5])
    return {"name": "tool_args_validity", "value": value, "comment": comment, "data_type": "NUMERIC"}


# ───────────────────────────────────────────────────────────────────
# Evaluator 8: 工具效率（冗余模式检测）
# ───────────────────────────────────────────────────────────────────

def eval_tool_efficiency(
    *,
    input: Any = None,
    output: Optional[Dict[str, Any]] = None,
    expected_output: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """检测浪费模式：读后立即覆写、不必要的搜索等。

    expectedOutput.tool_efficiency_checks 可选配置：
    {"no_read_write_pair": true, "no_redundant_search": true}

    当前检测的浪费模式：
    1. read_file path P → write_file path P（读完立刻覆写，说明读不需要）
    2. 连续 n>=3 次 search/grep 模式（无中间 execute），视为过度搜索

    效率分 = 1.0 - (浪费权重 / 总调用)，0 浪费 → 1.0。
    """
    if not output:
        return {
            "name": "tool_efficiency",
            "value": 1.0,
            "comment": "no output; skip",
            "data_type": "NUMERIC",
        }
    checks = (expected_output or {}).get("tool_efficiency_checks", {}) or {}
    if not checks:
        return {
            "name": "tool_efficiency",
            "value": 1.0,
            "comment": "no tool_efficiency_checks specified; skip",
            "data_type": "NUMERIC",
        }

    tool_trace = output.get("tool_trace") or []
    n = len(tool_trace)
    if n <= 1:
        return {"name": "tool_efficiency", "value": 1.0, "comment": "<=1 call; no waste possible", "data_type": "NUMERIC"}

    waste_weight = 0
    details: List[str] = []

    # 模式 1：read_file → write_file 同 path（读后立刻覆写）
    if checks.get("no_read_write_pair", True):
        for i in range(n - 1):
            cur = tool_trace[i]
            nxt = tool_trace[i + 1]
            if cur.get("name") == "read_file" and nxt.get("name") == "write_file":
                read_args = cur.get("args") or {}
                write_args = nxt.get("args") or {}
                read_path = read_args.get("file_path") or read_args.get("path", "")
                write_path = write_args.get("file_path") or write_args.get("path", "")
                if read_path and read_path == write_path:
                    waste_weight += 1
                    details.append(f"read-write pair on {read_path}")

    # 模式 2：连续 >=3 次 search/grep（无中间 execute/write）
    if checks.get("no_redundant_search", True):
        search_names = {"search_file", "search_content", "grep", "rg", "search"}
        consecutive_search = 0
        for t in tool_trace:
            if t.get("name", "") in search_names:
                consecutive_search += 1
            else:
                if consecutive_search >= 3:
                    waste_weight += consecutive_search - 2
                    details.append(f"consecutive searches x{consecutive_search}")
                consecutive_search = 0
        if consecutive_search >= 3:
            waste_weight += consecutive_search - 2
            details.append(f"consecutive searches x{consecutive_search}")

    # 效率分 = 1.0 - (浪费权重 / 总调用)
    max_penalty = min(waste_weight / n, 1.0)
    value = 1.0 - max_penalty
    comment = f"waste_weight={waste_weight} calls={n} efficiency={value:.3f}"
    if details:
        comment += "; patterns: " + "; ".join(details[:3])
    return {"name": "tool_efficiency", "value": value, "comment": comment, "data_type": "NUMERIC"}


# ───────────────────────────────────────────────────────────────────
# 默认 evaluator 列表(供 run_skill_eval 直接用)
# ───────────────────────────────────────────────────────────────────

DEFAULT_EVALUATORS = [
    eval_tool_set,
    eval_tool_order,
    eval_subagent,
    eval_tool_count,
    eval_repeat_rate,
    eval_tool_result_quality,
    eval_tool_args_validity,
    eval_tool_efficiency,
]
