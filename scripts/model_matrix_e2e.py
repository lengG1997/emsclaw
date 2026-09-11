# -*- coding: utf-8 -*-
"""多模型 × 快捷卡片 端到端跑批（模型选型评测用）。

链路（与前端一致）：
    POST /api/v1/auth/login            -> 会话 cookie
    PUT  /api/v1/sessions              -> 每 (模型, 卡片) 新建独立会话，绑定 model_config_id
    POST /api/v1/sessions/{id}/chat    -> SSE 事件流（仅用于"点火"启动 worker）

⚠️ 测量为什么不读 SSE 结果
    后端 `route/sessions.py:741-742` 对 `_agent_queues[session_id]` 是**无条件覆盖**：
    任何第二个客户端（例如前端页面的自动重连）接入同一会话，就会顶替掉先来的队列，
    先来者的事件流从此静默、永远收不到 `done`——表现为"agent 卡死"。
    因此本脚本：
      1) POST /chat 后仅用一个 daemon 线程把 SSE 流**读到 EOF 并丢弃**（只为让连接健康、不回压）；
      2) 结果的唯一权威来源是**数据库**：worker 会把全部事件（含 thinking）落进
         `sessions.events` JSONB（实测 thinking 条数与 SSE 完全一致，无丢失）；
      3) 耗时用**事件时间戳**计算（首条 user message -> done），与队列归属无关。

产出：一条 run 一个 JSON（耗时/轮次/工具调用/token/错误/最终答复/事件计数），落 --out 目录。

用法：
    python scripts/model_matrix_e2e.py --list-models
    python scripts/model_matrix_e2e.py --smoke
    python scripts/model_matrix_e2e.py --models all --cards demand_cap,production_priority
    python scripts/model_matrix_e2e.py --skip-existing          # 断点续跑
    python scripts/model_matrix_e2e.py --recover                # 从 DB 重建已跑完的 run
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

BASE = os.environ.get("EMSCLAW_API_BASE", "http://127.0.0.1:12001/api/v1")
USERNAME = os.environ.get("EMSCLAW_USER", "admin")
PASSWORD = os.environ.get("EMSCLAW_PASS", "admin123")


def _detect_pg_container() -> str:
    """定位 compose 起的 postgres 容器。可用 EMSCLAW_PG 显式覆盖。"""
    override = os.environ.get("EMSCLAW_PG")
    if override:
        return override
    try:
        out = subprocess.run(
            ["docker", "ps", "--filter", "label=com.docker.compose.service=postgres",
             "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=15,
        ).stdout.split()
        if out:
            return out[0]
    except Exception:
        pass
    return "postgres"


PG_CONTAINER = _detect_pg_container()

# 卡片 prompt 与前端 QuickActionCards.vue 逐字一致（改了前端记得同步）
CARDS = {
    "demand_cap": (
        "压需量",
        "最近关口表需量快超标了,帮我生成充放电策略把需量压下来,别被罚款。",
    ),
    "production_priority": (
        "赶产保供",
        "明天产线订单多、负荷大,帮我生成充放电策略,优先保证生产用电不断,"
        "关口表需量别超过申报值。",
    ),
}

DEFAULT_MODELS = [
    "system-default",                            # deepseek-v4-flash
    "sys-dashscope-qwen3.6-max-preview",
    "sys-dashscope-qwen3.6-plus",
    "sys-dashscope-qwen3.6-plus-2026-04-02",
    "sys-dashscope-qwen3.6-flash",
    "sys-dashscope-qwen3.6-flash-2026-04-16",
    "sys-dashscope-qwen3.6-27b",
    "sys-dashscope-qwen3.6-35b-a3b",
    "sys-dashscope-qwen3.5-plus",
    "sys-dashscope-qwen3.5-plus-2026-04-20",
    "sys-dashscope-qwen3.5-plus-2026-02-15",
    "sys-dashscope-qwen3.5-flash",
    "sys-dashscope-qwen3.5-flash-2026-02-23",
    "sys-dashscope-qwen3.5-27b",
    "sys-dashscope-qwen3.5-35b-a3b",
    "sys-dashscope-qwen3.5-122b-a10b",
    "sys-dashscope-qwen3.5-397b-a17b",
]

NOISY = ("thinking", "message_chunk")

# assistant 消息里带 `<dispatch_*>` 前缀的是 dispatch_artifact 中间件产出的**机器可读**方案块
# （plan_label/日程 JSON），不是给人看的最终答复。混在一起会让"结论质量"评分失真：
# 同一会话里它总是**后于**正文输出，覆盖式取最后一条 assistant 会拿到 JSON 而不是结论。
DISPATCH_PREFIX = "<dispatch"

_OPENER = urllib.request.build_opener()
_COOKIE: dict[str, str] = {}


def _req(method: str, path: str, body: dict | None = None, stream: bool = False,
         timeout: int = 120):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if _COOKIE:
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in _COOKIE.items())
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    resp = _OPENER.open(req, timeout=timeout)
    for sc in resp.headers.get_all("Set-Cookie") or []:
        kv = sc.split(";", 1)[0]
        if "=" in kv:
            k, v = kv.split("=", 1)
            _COOKIE[k.strip()] = v.strip()
    if stream:
        return resp
    raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def api(method: str, path: str, body: dict | None = None, timeout: int = 120):
    payload = _req(method, path, body, timeout=timeout)
    if isinstance(payload, dict) and payload.get("code") not in (0, None):
        raise RuntimeError(f"{method} {path} -> code={payload.get('code')} msg={payload.get('msg')}")
    return payload.get("data") if isinstance(payload, dict) else payload


def login() -> None:
    data = api("POST", "/auth/login", {"username": USERNAME, "password": PASSWORD})
    if not data or not data.get("access_token"):
        raise RuntimeError(f"login failed: {data}")
    _COOKIE.setdefault("zdtc-agent-session", data["access_token"])


def create_session(model_id: str) -> str:
    data = api("PUT", "/sessions", {"mode": "business", "model_config_id": model_id})
    sid = (data or {}).get("session_id")
    if not sid:
        raise RuntimeError(f"create session failed: {data}")
    return sid


def _drain_stream(sid: str, prompt: str, model_id: str, holder: dict, timeout: int) -> None:
    """daemon 线程：把 SSE 流读到 EOF 并丢弃，只为让连接健康（不回压服务端）。

    结果不从这里取 —— 见模块 docstring。出错只记录，不抛出。
    """
    try:
        resp = _req("POST", f"/sessions/{sid}/chat",
                    {"message": prompt, "model_config_id": model_id, "language": "zh"},
                    stream=True, timeout=timeout)
        holder["resp"] = resp
        holder["opened"] = time.time()
        while True:
            if not resp.readline():
                holder["end"] = "eof"
                break
        holder.setdefault("end", "eof")
    except Exception as exc:  # noqa: BLE001
        holder["end"] = f"error:{type(exc).__name__}"


def fetch_session(sid: str) -> dict:
    return api("GET", f"/sessions/{sid}") or {}


def infer_card(prompt: str) -> str | None:
    for key, (_label, text) in CARDS.items():
        if prompt and prompt.strip()[:24] == text.strip()[:24]:
            return key
    return None


def extract(evts: list[dict], fallback_model: str, fallback_card: str | None,
            sid: str, session_model_id: str | None = None) -> dict:
    """从库里的 events 抽一条权威记录。"""
    rec: dict = {
        "session_id": sid,
        "model_id": session_model_id or fallback_model,
        "card_key": fallback_card or "",
        "card_label": CARDS.get(fallback_card or "", ("", ""))[0],
        "prompt": CARDS.get(fallback_card or "", ("", ""))[1],
        "events": [], "event_counts": {}, "tool_calls": [], "errors": [],
        "approvals": [], "final_text": "", "dispatch_text": "", "done": None, "ok": False,
        "t_user": None, "t_done": None, "n_assistant": 0,
    }
    counts: dict[str, int] = {}
    for e in evts:
        name = e.get("event") or ""
        d = e.get("data") or {}
        counts[name] = counts.get(name, 0) + 1
        if name not in NOISY:
            rec["events"].append({"event": name, "timestamp": d.get("timestamp")})
        if name == "message":
            role = d.get("role") or "assistant"
            if role == "user":
                if rec["t_user"] is None:
                    rec["t_user"] = d.get("timestamp")
                    if not fallback_card:
                        rec["card_key"] = infer_card(d.get("content") or "") or ""
                        rec["card_label"] = CARDS.get(rec["card_key"], ("", ""))[0]
                        rec["prompt"] = CARDS.get(rec["card_key"], ("", ""))[1]
            else:
                content = d.get("content") or ""
                rec["n_assistant"] += 1
                if content.lstrip().startswith(DISPATCH_PREFIX):
                    # 机器可读方案块：单独归档，供报告解析 plan_label
                    rec["dispatch_text"] = (rec["dispatch_text"] or "") + content + "\n"
                elif content:
                    rec["final_text"] = content
        elif name == "tool" and d.get("status") == "called":
            rec["tool_calls"].append({
                "name": d.get("name"), "function": d.get("function"),
                "args": d.get("args"), "duration_ms": d.get("duration_ms"),
                "depth": d.get("depth"), "agent_id": d.get("agent_id"),
                "ok": not bool(d.get("error")),
            })
        elif name == "error":
            rec["errors"].append(d.get("error") or d.get("message") or "unknown error")
        elif name == "approval":
            rec["approvals"].append(d.get("action_requests") or d)
        elif name == "done":
            rec["t_done"] = d.get("timestamp")
            stats = d.get("statistics") or {}
            rec["done"] = {"statistics": stats,
                           "round_files": [f.get("filename") for f in (d.get("round_files") or [])]}
            rec["trace_id"] = stats.get("trace_id")
            for k in ("total_duration_ms", "tool_call_count", "input_tokens",
                      "output_tokens", "token_count", "cached_tokens"):
                if k in stats:
                    rec[k] = stats[k]
    rec["event_counts"] = counts
    if rec["t_user"] and rec["t_done"]:
        rec["agent_seconds"] = round(float(rec["t_done"]) - float(rec["t_user"]), 2)
    rec["thinking_events"] = counts.get("thinking", 0)
    rec["ok"] = bool(rec["final_text"]) and not rec["errors"]
    return rec


def wait_for_done(sid: str, model_id: str, card: str, deadline: float,
                  poll: float = 3.0) -> tuple[dict, list[str]]:
    """轮询会话直到出现 done 事件 / 终止状态 / 超时。返回 (rec, 诊断信息)。"""
    notes: list[str] = []
    last_n = -1
    while True:
        try:
            sess = fetch_session(sid)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"poll_error:{type(exc).__name__}")
            time.sleep(poll)
            continue
        evts = sess.get("events") or []
        n = len(evts)
        if n != last_n:
            last_n = n
        rec = extract(evts, model_id, card, sid, sess.get("model_config_id"))
        status = sess.get("status")
        if rec["done"] is not None or status in ("completed", "awaiting_approval", "failed"):
            rec["session_status"] = status
            return rec, notes
        if time.time() > deadline:
            rec["session_status"] = status
            rec["timeout"] = True
            notes.append(f"timeout_at_events={n}")
            return rec, notes
        time.sleep(poll)


def run_card(model_id: str, card_key: str, timeout: int, hard_deadline: float) -> dict:
    label, prompt = CARDS[card_key]
    rec: dict = {"model_id": model_id, "card_key": card_key, "card_label": label,
                 "prompt": prompt, "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "errors": [], "notes": []}
    t0 = time.time()
    holder: dict = {}
    thread = None
    try:
        sid = create_session(model_id)
        rec["session_id"] = sid
        thread = threading.Thread(target=_drain_stream,
                                  args=(sid, prompt, model_id, holder, timeout),
                                  daemon=True)
        thread.start()
        # 等 SSE 连接建立（worker 已被点火）
        for _ in range(60):
            if holder.get("resp") or holder.get("end"):
                break
            time.sleep(0.1)
        rec["sse_open_seconds"] = round(time.time() - t0, 2)
        db_rec, notes = wait_for_done(sid, model_id, card_key, hard_deadline)
        rec.update(db_rec)
        rec["notes"] = notes + [f"sse_end={holder.get('end')}"]
        if holder.get("end") != "eof" and db_rec.get("done") is not None:
            rec["notes"].append("stream_not_eof_but_db_has_done")
    except Exception as exc:  # noqa: BLE001
        rec["errors"].append(f"{type(exc).__name__}: {exc}")
        rec.setdefault("session_id", "")
    finally:
        rec["wall_seconds"] = round(time.time() - t0, 2)
        rec["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        resp = holder.get("resp")
        if resp is not None:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
        if thread is not None:
            thread.join(timeout=2)
    rec["ok"] = bool(rec.get("final_text")) and not rec["errors"]
    return rec


def list_db_sessions(since_ts: int) -> list[tuple[str, str]]:
    """(session_id, model_config_id) —— 直接问库，避开 /sessions 列表缺字段。"""
    sql = ("SELECT id, coalesce(model_config->>'id','') FROM sessions "
           f"WHERE created_at >= {since_ts} ORDER BY created_at;")
    r = subprocess.run(["docker", "exec", "-i", PG_CONTAINER, "psql", "-U", "agentone",
                        "-d", "ai_agent", "-t", "-A", "-F", "|", "-c", sql],
                       capture_output=True, text=True, encoding="utf-8")
    out = (r.stdout or "").strip()
    if not out:
        sys.stderr.write(f"[pg] empty; stderr={r.stderr[:300]}\n")
        return []
    rows = []
    for line in out.splitlines():
        if "|" in line:
            a, b = line.split("|", 1)
            rows.append((a.strip(), b.strip()))
    return rows


def cmd_recover(since_ts: int, out_dir: str, models: list[str]) -> int:
    rows = list_db_sessions(since_ts)
    print(f"[recover] {len(rows)} sessions since {since_ts}", flush=True)
    n = 0
    for sid, mid in rows:
        if mid not in models:
            continue
        try:
            sess = fetch_session(sid)
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {sid}: {type(exc).__name__}", flush=True)
            continue
        rec = extract(sess.get("events") or [], mid, None, sid, sess.get("model_config_id"))
        if not rec.get("card_key"):
            continue
        rec["session_status"] = sess.get("status")
        rec["recovered"] = True
        rec["wall_seconds"] = rec.get("agent_seconds")
        rec["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        tag = f"{rec['model_id']}__{rec['card_key']}"
        with open(os.path.join(out_dir, tag + ".json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        n += 1
        print(f"  {tag:<58} agent={rec.get('agent_seconds')}s tools={len(rec['tool_calls'])} "
              f"ok={rec['ok']} status={rec.get('session_status')}", flush=True)
    print(f"[recover] wrote {n}", flush=True)
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="all")
    ap.add_argument("--cards", default="demand_cap,production_priority")
    ap.add_argument("--out", default=os.path.join("tmp", "model_matrix"))
    ap.add_argument("--timeout", type=int, default=300, help="单次 socket 超时")
    ap.add_argument("--hard-deadline", type=int, default=420, help="单次墙钟硬上限")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--recover", action="store_true")
    ap.add_argument("--since", type=int, default=0, help="recover 的起始 epoch")
    ap.add_argument("--list-models", action="store_true")
    args = ap.parse_args()

    login()
    if args.list_models:
        for m in api("GET", "/models") or []:
            print(m.get("id"), "|", m.get("model_name"), "|", m.get("is_active"))
        return 0

    models = DEFAULT_MODELS if args.models == "all" else \
        [m.strip() for m in args.models.split(",") if m.strip()]
    os.makedirs(args.out, exist_ok=True)

    if args.recover:
        return 0 if cmd_recover(args.since, args.out, models) else 1

    if args.smoke:
        models, cards = ["system-default"], ["demand_cap"]
    else:
        cards = [c.strip() for c in args.cards.split(",") if c.strip()]

    total = len(models) * len(cards)
    print(f"[plan] {len(models)} models x {len(cards)} cards = {total} runs -> {args.out}", flush=True)
    done = idx = 0
    for model in models:
        for card in cards:
            idx += 1
            tag = f"{model}__{card}"
            path = os.path.join(args.out, tag + ".json")
            if args.skip_existing and os.path.exists(path):
                print(f"[{idx}/{total}] {tag} ... skip (exists)", flush=True)
                continue
            print(f"[{idx}/{total}] {tag} ...", flush=True)
            rec = run_card(model, card, args.timeout, time.time() + args.hard_deadline)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=1)
            done += 1
            print(f"    ok={rec['ok']} agent={rec.get('agent_seconds')}s wall={rec.get('wall_seconds')}s "
                  f"tools={len(rec['tool_calls'])} tokens={rec.get('token_count')} "
                  f"errors={len(rec['errors'])} status={rec.get('session_status')} "
                  f"{'TIMEOUT' if rec.get('timeout') else ''}", flush=True)
    print(f"[done] {done} runs this pass", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
