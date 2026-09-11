"""8 个通用 Code evaluator 的单元测试。

每个 evaluator 覆盖：通过、失败、边界（无 expected 字段时 skip=1.0）。
所有 evaluator 签名一致：``(*, input, output, expected_output, metadata, **kwargs) -> dict``
返回 dict 必含 name / value(0.0|1.0) / comment / data_type。
"""
from __future__ import annotations

from emsclaw_backend.observability.eval.evaluators import (
    _actual_delegates,
    _actual_tool_names,
    _args_structural_hash,
    _repeat_pairs,
    eval_subagent,
    eval_tool_count,
    eval_tool_order,
    eval_tool_set,
    eval_repeat_rate,
    eval_tool_result_quality,
    eval_tool_args_validity,
    eval_tool_efficiency,
)


# ── helpers 测试 ──────────────────────────────────────────────────────

def test_actual_tool_names_skips_empty_names():
    out = {
        "tool_trace": [
            {"name": "read_file"},
            {"name": ""},          # 空 name 跳过
            {"name": "execute"},
            {"no_name": 1},        # 没 name 字段跳过
        ]
    }
    assert _actual_tool_names(out) == ["read_file", "execute"]
    assert _actual_tool_names(None) == []
    assert _actual_tool_names({}) == []


def test_actual_delegates_skips_empty():
    out = {
        "delegates": [
            {"subagent_type": "device_management"},
            {"no_type": 1},
            {"subagent_type": ""},
        ]
    }
    assert _actual_delegates(out) == ["device_management"]


def test_args_structural_hash_key_order_invariant():
    a = _args_structural_hash({"a": 1, "b": 2})
    b = _args_structural_hash({"b": 2, "a": 1})
    assert a == b and len(a) == 8


def test_args_structural_hash_different_inputs_differ():
    a = _args_structural_hash({"a": 1})
    b = _args_structural_hash({"a": 2})
    assert a != b


def test_args_structural_hash_none_empty():
    assert _args_structural_hash(None) == ""


# ── eval_tool_set ──────────────────────────────────────────────────────

def test_tool_set_pass_when_expected_subset_of_actual():
    out = {"tool_trace": [
        {"name": "read_file"}, {"name": "execute"}, {"name": "write_todos"}]}
    res = eval_tool_set(
        input={"query": "..."},
        output=out,
        expected_output={"expected_tools": ["read_file", "execute"]},
    )
    assert res["name"] == "tool_set"
    assert res["value"] == 1.0
    assert res["data_type"] == "NUMERIC"


def test_tool_set_fail_when_missing_tool():
    out = {"tool_trace": [{"name": "read_file"}]}
    res = eval_tool_set(
        output=out,
        expected_output={"expected_tools": ["read_file", "execute"]},
        input={}, metadata=None,
    )
    assert res["value"] == 0.0
    assert "missing" in res["comment"]


def test_tool_set_fail_when_forbidden_hit():
    out = {"tool_trace": [{"name": "read_file"}, {"name": "delete_device"}]}
    res = eval_tool_set(
        output=out,
        expected_output={
            "expected_tools": ["read_file"],
            "forbidden_tools": ["delete_device"],
        },
        input={}, metadata=None,
    )
    assert res["value"] == 0.0
    assert "forbidden hit" in res["comment"]


def test_tool_set_pass_when_no_expected_specified():
    """无 expected_tools 时直接通过(没要求集合)。"""
    res = eval_tool_set(
        output={"tool_trace": [{"name": "read_file"}]},
        expected_output={},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0


# ── eval_tool_order ────────────────────────────────────────────────────

def test_tool_order_pass_subsequence_with_insertions():
    """expected_order 是 actual 的子序列(允许中间插别的工具)。"""
    out = {"tool_trace": [
        {"name": "read_file"}, {"name": "write_todos"}, {"name": "execute"}]}
    res = eval_tool_order(
        output=out,
        expected_output={"expected_order": ["read_file", "execute"]},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0


def test_tool_order_fail_when_order_violated():
    out = {"tool_trace": [{"name": "execute"}, {"name": "read_file"}]}
    res = eval_tool_order(
        output=out,
        expected_output={"expected_order": ["read_file", "execute"]},
        input={}, metadata=None,
    )
    assert res["value"] == 0.0


def test_tool_order_pass_exact_match():
    out = {"tool_trace": [{"name": "read_file"}, {"name": "execute"}]}
    res = eval_tool_order(
        output=out,
        expected_output={"expected_order": ["read_file", "execute"]},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0


def test_tool_order_skip_when_empty_expected():
    res = eval_tool_order(
        output={"tool_trace": [{"name": "read_file"}]},
        expected_output={},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0
    assert "skip" in res["comment"]


def test_tool_order_fail_when_expected_missing_in_actual():
    out = {"tool_trace": [{"name": "read_file"}]}
    res = eval_tool_order(
        output=out,
        expected_output={"expected_order": ["read_file", "execute"]},
        input={}, metadata=None,
    )
    assert res["value"] == 0.0


# ── eval_subagent ──────────────────────────────────────────────────────

def test_subagent_pass_when_expected_in_delegates():
    out = {"delegates": [{"subagent_type": "device_management"}]}
    res = eval_subagent(
        output=out,
        expected_output={"expected_subagent": "device_management"},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0


def test_subagent_fail_when_not_routed():
    out = {"delegates": [{"subagent_type": "search"}]}
    res = eval_subagent(
        output=out,
        expected_output={"expected_subagent": "device_management"},
        input={}, metadata=None,
    )
    assert res["value"] == 0.0
    assert "not routed" in res["comment"]


def test_subagent_skip_when_expected_null():
    res = eval_subagent(
        output={"delegates": []},
        expected_output={"expected_subagent": None},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0


def test_subagent_skip_when_no_delegates_no_expected():
    """没要求路由 + 实际也没路由 → 通过(没要求就不算失败)。"""
    res = eval_subagent(
        output={"delegates": []},
        expected_output={},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0


# ── eval_tool_count ────────────────────────────────────────────────────

def test_tool_count_pass_under_threshold():
    out = {"tool_trace": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}
    res = eval_tool_count(
        output=out,
        expected_output={"max_tool_calls": 5},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0


def test_tool_count_pass_at_threshold():
    out = {"tool_trace": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}
    res = eval_tool_count(
        output=out,
        expected_output={"max_tool_calls": 3},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0


def test_tool_count_fail_over_threshold():
    out = {"tool_trace": [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}]}
    res = eval_tool_count(
        output=out,
        expected_output={"max_tool_calls": 3},
        input={}, metadata=None,
    )
    assert res["value"] == 0.0
    assert "exceeded" in res["comment"]


def test_tool_count_skip_when_no_threshold():
    res = eval_tool_count(
        output={"tool_trace": [{"name": "a"}]},
        expected_output={},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0
    assert "skip" in res["comment"]


# ── _repeat_pairs + eval_repeat_rate ───────────────────────────────────

def _trace(names_and_args, phase="start"):
    """构造 tool_trace,每条都是 phase=start(去重逻辑只算 start)。

    names_and_args: [(name, args), ...]
    """
    return [
        {"name": n, "args": a, "phase": phase, "tool_call_id": f"call_{i}"}
        for i, (n, a) in enumerate(names_and_args)
    ]


def test_repeat_pairs_zero_when_all_distinct():
    trace = _trace([("read_file", {"p": "/a"}),
                    ("read_file", {"p": "/b"})])
    assert _repeat_pairs(trace) == 0


def test_repeat_pairs_counts_adjacent_same_name_and_args():
    trace = _trace([("execute", {"code": "x"}),
                    ("execute", {"code": "x"}),  # 相邻同 name+args → 1 pair
                    ("execute", {"code": "y"})])
    assert _repeat_pairs(trace) == 1


def test_repeat_pairs_skips_non_adjacent_repeat():
    """不相邻的相同调用不算重复对。"""
    trace = _trace([("execute", {"code": "x"}),
                    ("read_file", {"p": "/a"}),
                    ("execute", {"code": "x"})])
    assert _repeat_pairs(trace) == 0


def test_repeat_pairs_only_counts_start_phase():
    """start + complete 双条只算 start 一条。"""
    base = [("execute", {"code": "x"}), ("execute", {"code": "x"})]
    trace = _trace(base, phase="start")
    # 给每条加一个 phase=complete 兜底（_repeat_pairs 应过滤掉）
    trace += [
        {"name": n, "args": a, "phase": "complete",
         "tool_call_id": f"call_{i}"}
        for i, (n, a) in enumerate(base)
    ]
    # 去重后只剩 2 个 start,1 对重复
    assert _repeat_pairs(trace) == 1


def test_repeat_rate_pass_under_ratio():
    """1 pair / 2 unique items = 0.5 ≤ 0.5 → 通过(等号算通过)。"""
    trace = _trace([("execute", {"c": "x"}),
                    ("execute", {"c": "x"}),
                    ("read_file", {"p": "/a"})])
    res = eval_repeat_rate(
        output={"tool_trace": trace},
        expected_output={"max_repeat_ratio": 0.5},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0


def test_repeat_rate_fail_over_ratio():
    """2 pair / 3 unique = 0.667 > 0.5 → 失败。"""
    trace = _trace([("execute", {"c": "x"}),
                    ("execute", {"c": "x"}),     # pair 1
                    ("execute", {"c": "x"}),     # pair 2
                    ("read_file", {"p": "/a"})])
    res = eval_repeat_rate(
        output={"tool_trace": trace},
        expected_output={"max_repeat_ratio": 0.5},
        input={}, metadata=None,
    )
    assert res["value"] == 0.0
    assert "too many repeats" in res["comment"]


def test_repeat_rate_skip_when_no_threshold():
    res = eval_repeat_rate(
        output={"tool_trace": []},
        expected_output={},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0
    assert "skip" in res["comment"]


def test_repeat_rate_pass_when_zero_repeats():
    """无任何相邻重复 → ratio=0,任何阈值都通过。"""
    trace = _trace([("read_file", {"p": "/a"}),
                    ("execute", {"c": "x"}),
                    ("write_file", {"p": "/b"})])
    res = eval_repeat_rate(
        output={"tool_trace": trace},
        expected_output={"max_repeat_ratio": 0.2},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0


def test_repeat_rate_empty_trace():
    """空 tool_trace → denom=1, pairs=0, ratio=0 → 通过。"""
    res = eval_repeat_rate(
        output={"tool_trace": []},
        expected_output={"max_repeat_ratio": 0.2},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0


def test_repeat_rate_single_call():
    """只 1 次调用 → denom=1, pairs=0 → 通过。"""
    trace = _trace([("execute", {"c": "x"})])
    res = eval_repeat_rate(
        output={"tool_trace": trace},
        expected_output={"max_repeat_ratio": 0.2},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0


# ── eval_tool_result_quality ───────────────────────────────────────

def _trace_complete(names_results: list):
    """构造 tool_trace，每条都是 phase=complete（有 result）。"""
    return [
        {"name": n, "phase": "complete", "result": r, "tool_call_id": f"c{i}"}
        for i, (n, r) in enumerate(names_results)
    ]


def test_tool_result_quality_pass_all_non_empty():
    trace = _trace_complete([("get_snapshot", "data"), ("analyze", "ok")])
    res = eval_tool_result_quality(
        output={"tool_trace": trace},
        expected_output={"tool_result_checks": [{"tool_name": "get_snapshot", "non_empty": True}]},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0


def test_tool_result_quality_fail_empty_result():
    trace = _trace_complete([("get_snapshot", "")])
    res = eval_tool_result_quality(
        output={"tool_trace": trace},
        expected_output={"tool_result_checks": [{"tool_name": "get_snapshot", "non_empty": True}]},
        input={}, metadata=None,
    )
    assert res["value"] == 0.0
    assert "empty" in res["comment"]


def test_tool_result_quality_fail_error_marker():
    trace = _trace_complete([("execute", "Error: Traceback ...")])
    res = eval_tool_result_quality(
        output={"tool_trace": trace},
        expected_output={"tool_result_checks": [{"tool_name": "execute", "no_error": True}]},
        input={}, metadata=None,
    )
    assert res["value"] == 0.0


def test_tool_result_quality_fail_truncated():
    trace = _trace_complete([("read_file", "very long content...[truncated]")])
    res = eval_tool_result_quality(
        output={"tool_trace": trace},
        expected_output={"tool_result_checks": [{"tool_name": "read_file", "not_truncated": True}]},
        input={}, metadata=None,
    )
    assert res["value"] == 0.0


def test_tool_result_quality_wildcard_match():
    trace = _trace_complete([
        ("get_station_snapshot", "data"),
        ("get_device_snapshot", ""),
    ])
    res = eval_tool_result_quality(
        output={"tool_trace": trace},
        expected_output={"tool_result_checks": [{"tool_name": "get_*", "non_empty": True}]},
        input={}, metadata=None,
    )
    assert res["value"] == 0.5  # 1 pass / 2 matched


def test_tool_result_quality_skip_when_no_checks():
    res = eval_tool_result_quality(
        output={"tool_trace": []},
        expected_output={},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0
    assert "skip" in res["comment"]


def test_tool_result_quality_no_output():
    res = eval_tool_result_quality(
        output=None,
        expected_output={"tool_result_checks": [{"tool_name": "*", "non_empty": True}]},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0
    assert "skip" in res["comment"]


# ── eval_tool_args_validity ────────────────────────────────────────

def _trace_args(names_and_args: list):
    """构造 tool_trace，每条带 args。"""
    return [
        {"name": n, "args": a, "tool_call_id": f"c{i}"}
        for i, (n, a) in enumerate(names_and_args)
    ]


def test_tool_args_validity_pass_all_fields():
    trace = _trace_args([("get_snapshot", {"station_id": "S001", "fields": ["soc"]})])
    res = eval_tool_args_validity(
        output={"tool_trace": trace},
        expected_output={"tool_args_checks": [{"tool_name": "get_snapshot", "required_fields": ["station_id"]}]},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0


def test_tool_args_validity_fail_missing_field():
    trace = _trace_args([("get_snapshot", {"fields": ["soc"]})])
    res = eval_tool_args_validity(
        output={"tool_trace": trace},
        expected_output={"tool_args_checks": [{"tool_name": "get_snapshot", "required_fields": ["station_id"]}]},
        input={}, metadata=None,
    )
    assert res["value"] == 0.0
    assert "missing" in res["comment"]


def test_tool_args_validity_fail_type_mismatch():
    trace = _trace_args([("get_snapshot", {"station_id": 123})])
    res = eval_tool_args_validity(
        output={"tool_trace": trace},
        expected_output={"tool_args_checks": [{"tool_name": "get_snapshot", "field_types": {"station_id": "str"}}]},
        input={}, metadata=None,
    )
    assert res["value"] == 0.0
    assert "type" in res["comment"]


def test_tool_args_validity_fail_range_check():
    trace = _trace_args([("charge", {"power": 9999})])
    res = eval_tool_args_validity(
        output={"tool_trace": trace},
        expected_output={"tool_args_checks": [{"tool_name": "charge", "reasonable": {"power": {"max": 1000}}}]},
        input={}, metadata=None,
    )
    assert res["value"] == 0.0
    assert "range" in res["comment"]


def test_tool_args_validity_skip_no_checks():
    res = eval_tool_args_validity(
        output={"tool_trace": []},
        expected_output={},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0
    assert "skip" in res["comment"]


# ── eval_tool_efficiency ───────────────────────────────────────────

def _trace_names(names: list):
    """构造 tool_trace，每条带 name 和空 args。"""
    return [
        {"name": n, "args": {}, "tool_call_id": f"c{i}"}
        for i, n in enumerate(names)
    ]


def test_tool_efficiency_pass_no_waste():
    trace = _trace_names(["read_file", "execute", "write_file"])
    res = eval_tool_efficiency(
        output={"tool_trace": trace},
        expected_output={"tool_efficiency_checks": {"no_read_write_pair": True}},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0


def test_tool_efficiency_detect_read_write_pair():
    trace = [
        {"name": "read_file", "args": {"file_path": "/x.txt"}, "tool_call_id": "c1"},
        {"name": "write_file", "args": {"file_path": "/x.txt"}, "tool_call_id": "c2"},
    ]
    res = eval_tool_efficiency(
        output={"tool_trace": trace},
        expected_output={"tool_efficiency_checks": {"no_read_write_pair": True}},
        input={}, metadata=None,
    )
    assert res["value"] < 1.0
    assert "read-write pair" in res["comment"]


def test_tool_efficiency_detect_redundant_search():
    trace = _trace_names(["search_content", "grep", "search_content", "search_content"])
    res = eval_tool_efficiency(
        output={"tool_trace": trace},
        expected_output={"tool_efficiency_checks": {"no_redundant_search": True}},
        input={}, metadata=None,
    )
    assert res["value"] < 1.0
    assert "searches" in res["comment"]


def test_tool_efficiency_skip_no_checks():
    res = eval_tool_efficiency(
        output={"tool_trace": [{"name": "a", "args": {}, "tool_call_id": "c1"}]},
        expected_output={},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0
    assert "skip" in res["comment"]


def test_tool_efficiency_single_call_no_waste():
    res = eval_tool_efficiency(
        output={"tool_trace": [{"name": "read_file", "args": {}, "tool_call_id": "c1"}]},
        expected_output={"tool_efficiency_checks": {"no_read_write_pair": True}},
        input={}, metadata=None,
    )
    assert res["value"] == 1.0
