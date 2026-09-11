# -*- coding: utf-8 -*-
"""汇总 model_matrix_e2e.py 的跑批结果，输出可复核的评分表。

用法：
    python scripts/model_matrix_report.py --dir tmp/model_matrix --out-dir docs

评分口径（总分 100，规则化、可逐项复核）：
    A 链路可用性 30   有最终答复且无 error=30；有答复但有 error=12；无答复=0
    B 规划链路完整性 25  调用 optimize_dispatch ≥1=12；有 task 委派=5；
                         工具调用次数在 3..30=4；产出结构化方案块（dispatch plan_label
                         或 write_file）=4
    C 结论质量 30     结构化方案表=8；给出需量达标/不可达的明确判定=8；
                         量化指标 ≥4 个=8；不可达时未谎称可达=6
    D 效率 15        15 × min(ok 集的 wall_seconds) / 本次 wall_seconds（仅 ok 记分）
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict

UNIT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:kW|kWh|kW·h|元|%|度)")
PLAN_LABEL_RE = re.compile(r'"plan_label"\s*:\s*"([^"]+)"')
DISP_FIELD_RE = r'"{k}"\s*:\s*(-?\d+(?:\.\d+)?)'


def disp_field(dispatch: str, key: str) -> float | None:
    """从 dispatch JSON 里取字段（同名多值取最后一个 = 最终采纳方案）。"""
    vals = re.findall(DISP_FIELD_RE.format(k=key), dispatch or "")
    try:
        return float(vals[-1]) if vals else None
    except ValueError:
        return None
# 物理共识交叉校验（正确性代理）：
# 同一张卡片 + 同一份冻结基线，"申报需量"和"储能极限可达的最小需量"是**确定的物理常量**，
# 因此各模型应当收敛到同一组数字。做法：统计每个 kW 数值在全部 run 中的出现率，
# 出现率 ≥ 阈值的即为"共识常量"，再看每个 run 复现了几个。
# 这比"关键词→数值"的角色归因稳健 —— 实测角色归因 0/13 命中（模型表述方式各异），
# 而共识法只看数字集合，不依赖措辞。
KW_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*kW")
CONSENSUS_MIN_RATE = 0.4

# 官方口径单价（美元/百万 token，中国区，2026-09 查证）。
# 仅按量计费型号有价；开源权重型号（27b/35b-a3b/122b-a10b/397b-a17b）在百炼按
# 部署（MU 小时）计费，**无按量单价**，故不估成本。
# 来源：阿里云百炼「模型调用(按量付费)」文档 + 公开价目核对。
PRICE_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "sys-dashscope-qwen3.6-plus": (0.33, 1.98),
    "sys-dashscope-qwen3.6-plus-2026-04-02": (0.33, 1.98),
    "sys-dashscope-qwen3.6-flash": (0.20, 1.19),
    "sys-dashscope-qwen3.6-flash-2026-04-16": (0.20, 1.19),
    "sys-dashscope-qwen3.6-max-preview": (1.04, 6.24),
    "sys-dashscope-qwen3.5-plus": (0.138, 0.826),
    "sys-dashscope-qwen3.5-plus-2026-04-20": (0.138, 0.826),
    "sys-dashscope-qwen3.5-plus-2026-02-15": (0.138, 0.826),
    "system-default": (0.17, 0.33),
}
USD_TO_CNY = 7.1


def est_cost_cny(mid: str, in_tok: int, out_tok: int) -> float | None:
    p = PRICE_USD_PER_MTOK.get(mid)
    if not p or not in_tok:
        return None
    usd = in_tok / 1e6 * p[0] + out_tok / 1e6 * p[1]
    return round(usd * USD_TO_CNY, 3)
VERDICT_RE = re.compile(
    r"(不超|超(?:出|过|申报)?|低于|高于|达到|达标|达不到|不可达|不可行|满足|违反|突破)"
    r"[^。；\n]{0,16}?(申报|需量|上限|阈值)"
    r"|(申报|需量)[^。；\n]{0,16}?(达标|不可达|超出|超标|超了|满足|未超)"
)
INFEASIBLE_RE = re.compile(r"物理(?:极限|下限)|不可达|做不到|无法(?:压|降|满足)|不可行|达不到|结构性缺口")
CONTINUITY_RE = re.compile(r"生产|不断电|优先保障|供电可靠|保供|断电风险")


def kw_values(text: str, dispatch: str = "") -> set[float]:
    """答案**正文**中出现的全部 kW 数值，保留 1 位小数。

    ⚠️ 默认**不**把 dispatch JSON 计入：里面含完整的 96 点功率日程与总量，
    会把"搬运工具输出"误当成质量信号（实测能把一个报错失败的 run 抬到满分）。
    dispatch 内的字段请用 disp_field() 单独取。
    """
    out: set[float] = set()
    for m in KW_RE.finditer(text):
        try:
            out.add(round(float(m.group(1).replace(",", "")), 1))
        except ValueError:
            pass
    for m in re.finditer(DISP_FIELD_RE.format(k=r"[a-z_]*kw[a-z_]*"), dispatch or ""):
        try:
            out.add(round(float(m.group(1)), 1))
        except ValueError:
            pass
    return out


def kw_values_prose(text: str) -> set[float]:
    """仅正文（用于真值对账 / 共识校验，口径最干净）。"""
    return kw_values(text, "")


def consensus_constants(runs: list[tuple[str, set[float]]]) -> list[float]:
    """跨 run 出现率 ≥ CONSENSUS_MIN_RATE 的 kW 数值 = 物理常量。"""
    if not runs:
        return []
    hit: dict[float, int] = {}
    for _tag, vals in runs:
        for v in vals:
            hit[v] = hit.get(v, 0) + 1
    need = max(2, int(len(runs) * CONSENSUS_MIN_RATE + 0.5))
    return sorted(v for v, c in hit.items() if c >= need)


def truth_verify(kw_vals: set[float], truth: dict) -> dict:
    """核查答复是否引用了 DB 里可独立读到的实测真值（±1 kW 容差吸收取整）。"""
    if not truth:
        return {}
    cands = {
        "contract_demand_kw": truth.get("contract_demand_kw"),
        "max_rolling_demand_kw": truth.get("max_rolling_demand_kw"),
        "max_load_kw": truth.get("max_load_kw"),
    }
    hits = {}
    for k, v in cands.items():
        if v is None:
            continue
        hits[k] = {
            "truth": v,
            "cited": any(abs(x - float(v)) <= 1.0 for x in kw_vals),
        }
    return hits


def load_runs(d: str) -> list[dict]:
    runs = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json") or "__" not in fn:
            continue
        with open(os.path.join(d, fn), encoding="utf-8") as f:
            rec = json.load(f)
        if not rec.get("session_id"):
            continue
        runs.append(rec)
    return runs


def features(rec: dict) -> dict:
    text = rec.get("final_text") or ""
    dtext = rec.get("dispatch_text") or ""
    plan_labels = PLAN_LABEL_RE.findall(dtext)
    tools = rec.get("tool_calls") or []
    names = [t.get("name") for t in tools]
    agents = sorted({(t.get("agent_id") or "").split("_0")[0] for t in tools if t.get("agent_id")})
    ev = rec.get("event_counts") or {}
    n_metrics = len(set(UNIT_RE.findall(text)))
    return {
        "model_id": rec["model_id"],
        "card": rec["card_key"],
        "ok": bool(rec.get("ok")),
        "wall_s": rec.get("agent_seconds") or rec.get("wall_seconds"),
        "session_status": rec.get("session_status"),
        "recovered": rec.get("recovered", False),
        "tokens": rec.get("token_count"),
        "in_tokens": rec.get("input_tokens"),
        "out_tokens": rec.get("output_tokens"),
        "thinking_events": rec.get("thinking_events"),
        "trace_id": rec.get("trace_id"),
        "n_tools": len(tools),
        "n_optimize": names.count("optimize_dispatch"),
        "n_task": names.count("task"),
        "n_write": names.count("write_file"),
        "subagents": agents,
        "n_errors": len(rec.get("errors") or []),
        "errors": (rec.get("errors") or [])[:2],
        "n_approvals": len(rec.get("approvals") or []),
        "n_assistant": rec.get("n_assistant"),
        "final_len": len(text),
        "n_plans": len(plan_labels),
        "plan_labels": plan_labels[:4],
        "has_plan": (("方案" in text) and ("|" in text)) or bool(plan_labels),
        "has_verdict": bool(VERDICT_RE.search(text)),
        "has_infeasible": bool(INFEASIBLE_RE.search(text)),
        "continuity": bool(CONTINUITY_RE.search(text)),
        "n_metrics": n_metrics,
        "kw_vals": kw_values_prose(text),
        "baseline_peak_kw": disp_field(dtext, "baseline_peak_kw"),
        "peak_demand_kw": disp_field(dtext, "peak_demand_kw"),
        "charge_kwh": disp_field(dtext, "charge_kwh"),
        "discharge_kwh": disp_field(dtext, "discharge_kwh"),
        "has_dispatch_preview": bool(ev.get("dispatch_preview")),
        "final_text": text,
    }


def score_parts(f: dict, ok_walls: list[float], contract_kw: float | None = None,
                best_peak: float | None = None, ref_wall: float | None = None) -> dict:
    """返回 A/B/C/E/D 分项，便于逐项复核。"""
    # A 链路可用性 25
    if f["ok"]:
        a = 25.0
    elif f["final_len"] > 0:
        a = 10.0
    else:
        a = 0.0
    # B 规划链路完整性 20
    b = 0.0
    if f["n_optimize"] >= 1:
        b += 10.0
    if f["n_task"] >= 1:
        b += 4.0
    if 3 <= f["n_tools"] <= 30:
        b += 3.0
    if f["n_plans"] >= 1 or f["n_write"] >= 1:
        b += 3.0
    # C 结论质量 20（启发式：只测"是否可交付"，不测正确性）
    c = 0.0
    if f["has_plan"]:
        c += 6.0
    if f["has_verdict"]:
        c += 6.0
    if f["n_metrics"] >= 4:
        c += 4.0
    if not (f["has_infeasible"] and not f["has_verdict"]):
        c += 4.0
    # E 方案有效性 20（客观：用 dispatch JSON 的达成峰值对账）
    # 归一化基准用**本卡可达前沿**（= 本批所有 run 达成的最低峰值），而不是申报需量：
    # 申报需量低于物理下限时根本不可达（本批 contract=1250 而物理下限≈1303），
    # 拿它当分母会把所有模型系统性低估。
    e = 0.0
    base, peak = f.get("baseline_peak_kw"), f.get("peak_demand_kw")
    if base and peak and best_peak and base > best_peak:
        got = max(0.0, base - peak)                 # 本模型削峰量
        span = base - best_peak                     # 前沿削峰量
        e += round(12.0 * min(1.0, got / span), 2)
    if f["n_plans"] >= 2:
        e += 8.0                                   # 产品约定：给用户 ≥2 套方案比对
    # D 效率 15（仅 ok 记分）
    # 基准取 ok 集耗时的**中位数**，不用最小值：本批最快的一次（25 s）只调了 2 次工具、
    # 没走完整链路，拿它当分母会把所有正常 run 压到 2~4 分（失真）。
    d = 0.0
    if f["ok"] and ref_wall and f["wall_s"]:
        d = round(min(15.0, 15.0 * ref_wall / f["wall_s"]), 2)
    return {"A": round(a, 2), "B": round(b, 2), "C": round(c, 2),
            "E": round(e, 2), "D": d}


def score(f: dict, ok_walls: list[float], contract_kw: float | None = None,
          best_peak: float | None = None, ref_wall: float | None = None) -> float:
    return round(sum(score_parts(f, ok_walls, contract_kw, best_peak, ref_wall).values()), 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join("tmp", "model_matrix"))
    ap.add_argument("--out-dir", default="docs")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--md", default="", help="额外输出可再生的 Markdown 数据表到该路径")
    ap.add_argument("--truth", default="", help="station_floor_oracle.py --json 产出的真值文件")
    args = ap.parse_args()

    truth_ctx = {}
    if args.truth and os.path.exists(args.truth):
        with open(args.truth, encoding="utf-8") as fh:
            truth_ctx = (json.load(fh) or {}).get("truth") or {}

    runs = load_runs(args.dir)
    if not runs:
        print("no runs found")
        return 1
    feats = [features(r) for r in runs]
    ok_walls = [f["wall_s"] for f in feats if f["ok"] and f["wall_s"]]
    contract_kw = truth_ctx.get("contract_demand_kw")
    # 每张卡片的"可达前沿" = 本批 ok run 中达成的最低需量峰值
    def median(xs: list[float]) -> float | None:
        if not xs:
            return None
        s = sorted(xs)
        n = len(s)
        return s[n // 2] if n % 2 else round((s[n // 2 - 1] + s[n // 2]) / 2, 2)

    ref_wall = median(ok_walls)
    frontier: dict[str, float] = {}
    for f in feats:
        if f["ok"] and f.get("peak_demand_kw"):
            cur = frontier.get(f["card"])
            frontier[f["card"]] = min(cur, f["peak_demand_kw"]) if cur else f["peak_demand_kw"]
    for f in feats:
        f["best_peak_kw"] = frontier.get(f["card"])
        f["parts"] = score_parts(f, ok_walls, contract_kw, frontier.get(f["card"]), ref_wall)
        f["score"] = round(sum(f["parts"].values()), 2)
    print(f"[frontier] 各卡片可达前沿（本批最优达成峰值）: "
          + ", ".join(f"{k}={v:g} kW" for k, v in sorted(frontier.items()))
          + f"　|　效率基准(ok 耗时中位数) = {ref_wall}s")

    by_model: dict[str, list[dict]] = defaultdict(list)
    for f in feats:
        by_model[f["model_id"]].append(f)

    rows = []
    for mid, fs in by_model.items():
        rows.append({
            "model_id": mid,
            "card": fs[0]["card"],
            "ok": all(x["ok"] for x in fs),
            "wall_s": round(sum(x["wall_s"] or 0 for x in fs), 1),
            "tokens": sum(x["tokens"] or 0 for x in fs),
            "in_tokens": sum(x["in_tokens"] or 0 for x in fs),
            "out_tokens": sum(x["out_tokens"] or 0 for x in fs),
            "thinking": sum(x["thinking_events"] or 0 for x in fs),
            "n_optimize": sum(x["n_optimize"] for x in fs),
            "n_task": sum(x["n_task"] for x in fs),
            "n_tools": sum(x["n_tools"] for x in fs),
            "n_plans": sum(x["n_plans"] for x in fs),
            "final_len": sum(x["final_len"] for x in fs),
            "score": round(sum(x["score"] for x in fs) / len(fs), 1),
            "parts": {k: round(sum(x["parts"][k] for x in fs) / len(fs), 1)
                      for k in ("A", "B", "C", "E", "D")},
            "peak_demand_kw": [x.get("peak_demand_kw") for x in fs],
            "baseline_peak_kw": [x.get("baseline_peak_kw") for x in fs],
            "consensus": round(sum(x.get("consensus_hit") or 0 for x in fs) / len(fs), 2),
            "consensus_total": fs[0].get("consensus_total") or 0,
            "errors": [e for x in fs for e in x["errors"]],
            "metrics": sum(x["n_metrics"] for x in fs),
        })
        rows[-1]["cost_cny"] = est_cost_cny(
            mid, rows[-1]["in_tokens"], rows[-1]["out_tokens"])
    rows.sort(key=lambda r: (-r["ok"], -r["score"], r["wall_s"]))

    print(f"{'model':<42}{'ok':<6}{'agent_s':>9}{'tokens':>10}{'cost':>8}{'think':>7}"
          f"{'tools':>7}{'plans':>7}{'con':>6}{'score':>7}")
    for r in rows:
        con = f"{r['consensus']:g}/{r['consensus_total']}"
        c = r.get("cost_cny")
        print(f"{r['model_id']:<42}{str(r['ok']):<6}{r['wall_s']:>9}{r['tokens']:>10}"
              f"{(f'{c:.2f}' if c is not None else '-'):>8}"
              f"{r['thinking']:>7}{r['n_tools']:>7}{r['n_plans']:>7}{con:>6}{r['score']:>7}")

    # ---- 物理共识交叉校验（正确性代理）----
    consensus: dict[str, dict] = {}
    for card in sorted({f["card"] for f in feats}):
        sub = [f for f in feats if f["card"] == card]
        consts = consensus_constants([(f["model_id"], f["kw_vals"]) for f in sub])
        votes = {v: sum(1 for f in sub if v in f["kw_vals"]) for v in consts}
        for f in feats:
            if f["card"] != card:
                continue
            f["consensus_hit"] = len([v for v in consts if v in f["kw_vals"]])
            f["consensus_total"] = len(consts)
        consensus[card] = {
            "n_runs": len(sub),
            "constants": consts,
            "votes": votes,
            "threshold": max(2, int(len(sub) * CONSENSUS_MIN_RATE + 0.5)),
        }
        print(f"\n[cross-check] card={card} runs={len(sub)} "
              f"入榜阈值={consensus[card]['threshold']} 次")
        print(f"  物理共识常量(kW) = {consts}")
        print(f"  各值出现次数 = {votes}")
        for f in sorted([x for x in sub], key=lambda x: -x["consensus_hit"]):
            print(f"    {f['model_id']:<42} 复现 {f['consensus_hit']}/{len(consts)}  "
                  f"命中值={sorted(v for v in consts if v in f['kw_vals'])}")

    # ---- 实测真值对账（比模型共识更强的正确性证据）----
    truth_rows = []
    if truth_ctx:
        for f in feats:
            f["truth_hits"] = truth_verify(f["kw_vals"], truth_ctx)
        tkeys = [k for k in ("contract_demand_kw", "max_rolling_demand_kw", "max_load_kw")
                 if truth_ctx.get(k) is not None]
        print("\n[cross-check] 实测真值对账（DB 可独立读取，±1 kW 容差）")
        for k in tkeys:
            print(f"  {k:<24} = {truth_ctx[k]} kW")
        print(f"  {'model':<42}{'card':<22}{'对账'}")
        for f in sorted(feats, key=lambda x: (x["model_id"], x["card"])):
            h = f.get("truth_hits") or {}
            n = sum(1 for k in tkeys if (h.get(k) or {}).get("cited"))
            f["truth_score"] = n
            f["truth_total"] = len(tkeys)
            mark = "".join("O" if (h.get(k) or {}).get("cited") else "."
                           for k in tkeys)
            print(f"  {f['model_id']:<42}{f['card']:<22}{mark}  {n}/{len(tkeys)}")
            truth_rows.append({"model_id": f["model_id"], "card": f["card"],
                               "score": n, "total": len(tkeys),
                               "detail": {k: (h.get(k) or {}).get("cited") for k in tkeys}})
    else:
        for f in feats:
            f["truth_score"] = None
            f["truth_total"] = None

    out = {
        "generated_at": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        "ok_wall_min_s": round(min(ok_walls), 1) if ok_walls else None,
        "truth_source": truth_ctx or None,
        "truth_verify": truth_rows,
        "cross_check": consensus,
        "per_run": [{k: sorted(v) if isinstance(v, set) else v
                     for k, v in f.items() if k != "final_text"} for f in feats],
        "per_model": rows,
    }
    if not args.no_write:
        os.makedirs(args.out_dir, exist_ok=True)
        p = os.path.join(args.out_dir, "model-matrix-results.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
        print(f"\n[written] {p}")

    if args.md:
        lines = [
            "<!-- 本文件由 scripts/model_matrix_report.py --md 自动生成，请勿手工编辑 -->",
            "",
            f"生成时间：{__import__('time').strftime('%Y-%m-%d %H:%M:%S')}　"
            f"样本：{len(feats)} 次 run（{len(rows)} 模型 × 2 卡片）　"
            f"最快 ok 耗时：{out['ok_wall_min_s']}s",
            "",
            "| 模型 | 链路 ok | A 链路 | B 规划 | C 结论 | E 方案有效 | D 效率 | 总均分 | 耗时合计(s) | token 合计 | 成本(元) | 达成峰值(dem/prod) | 真值对账 | 共识复现 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            p = r["parts"]
            pk = r.get("peak_demand_kw") or [None, None]
            pk_s = " / ".join(f"{v:g}" if v else "—" for v in pk[:2])
            cost = r.get("cost_cny")
            cost_s = f"{cost:.2f}" if cost is not None else "—"
            tv = [x for x in truth_rows if x["model_id"] == r["model_id"]]
            tv_s = f"{sum(x['score'] for x in tv)}/{sum(x['total'] for x in tv)}" if tv else "—"
            lines.append(
                f"| `{r['model_id']}` | {'✅' if r['ok'] else '❌'} | {p['A']} | {p['B']} | "
                f"{p['C']} | {p['E']} | {p['D']} | **{r['score']}** | {r['wall_s']} | "
                f"{r['tokens']} | {cost_s} | {pk_s} | {tv_s} | "
                f"{r['consensus']:g}/{r['consensus_total']} |")
        lines += ["", "### 物理共识交叉校验（正确性代理，不计分）", ""]
        for card, c in consensus.items():
            consts = c["constants"]
            lines.append(
                f"**{card}**：{c['n_runs']} 次运行，入榜阈值 {c['threshold']} 次；"
                f"共识物理常量 = {', '.join(f'{v:g} kW' for v in consts) if consts else '（无）'}")
            lines.append("")
            lines.append("| 模型 | 复现共识常量 |")
            lines.append("|---|---|")
            for f in sorted([x for x in feats if x["card"] == card],
                            key=lambda x: (-(x.get("consensus_hit") or 0), x["model_id"])):
                hit = f.get("consensus_hit") or 0
                tot = f.get("consensus_total") or len(consts)
                lines.append(f"| `{f['model_id']}` | {hit}/{tot} |")
            lines.append("")
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        print(f"[written] {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
