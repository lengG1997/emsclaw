"""Langfuse 提示词版本化管理：运行时拉取 + 本地兜底 + 同步 CLI。

父子 Agent 的系统提示词以 Langfuse 为运行时真相源（production 标签版本），
本地 ``prompts.py`` 常量作兜底/种子。Langfuse 关闭或不可用时，全量回落本地，
行为与未接入前完全一致。

- :func:`load_text_prompt` —— 子 agent 提示词拉取（原文 + 日期追加）。
- :func:`load_lead_prompt` —— 父（Lead）提示词拉取 + sandbox 追加 + 日期追加。
- :func:`sync_prompts_to_langfuse` —— 把本地提示词 upsert 到 Langfuse，内容变化时新建版本
  （旧版保留为历史），实现版本化管理。
- CLI: ``python -m emsclaw_backend.observability.prompts sync [--create-only]``
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional, Tuple

from loguru import logger

from .sdk import get_langfuse_client, is_ready

# Lead 提示词在 Langfuse 中的名字
LEAD_PROMPT_NAME = "business_lead"

# 提示词拉取后的缓存 TTL（秒）。提示词变更不频繁，缓存 5 分钟。
_PROMPT_CACHE_TTL = 300


def _now_date() -> str:
    """返回当前日期字符串（北京时间 YYYY-MM-DD）。

    只到年月日，注入提示词末尾不破坏前缀缓存（静态内容仍可缓存）。
    """
    tz_utc8 = timezone(timedelta(hours=8))
    return datetime.now(tz_utc8).strftime("%Y-%m-%d")


# 语言映射: lang_code → (语言名, 提示词中的强制语言指令)
_LANGUAGE_MAP: dict[str, tuple[str, str]] = {
    "zh": ("简体中文", "你必须使用简体中文回复所有内容。所有生成的报告、文档标题和正文也必须使用简体中文。专业术语可保留英文缩写。"),
    "en": ("English", "You must respond in English. All generated reports, document titles and body text must also be in English. Technical acronyms may remain in their original form."),
}


def _language_instruction(language: Optional[str]) -> str:
    """根据语言码返回提示词中的语言约束行。未匹配时返回跟随用户语言的指令。"""
    if not language:
        return ""
    lc = language.strip().lower()
    if lc in _LANGUAGE_MAP:
        lang_name, lang_detail = _LANGUAGE_MAP[lc]
        return (
            f"## 语言要求（语言/Language）\n"
            f"用户界面语言已设为 **{lang_name}**（`{lc}`）。{lang_detail}"
        )
    return ""


def _append_date(prompt: str) -> str:
    """在提示词末尾追加当前日期行。

    放在提示词最末尾，确保静态前缀不受影响（prompt caching 按前缀匹配）。
    """
    return f"{prompt}\n\n当前日期：{_now_date()}"


def _date_label(language: Optional[str]) -> str:
    """根据语言返回日期标签文本。"""
    if language and language.strip().lower() == "en":
        return "Current date"
    return "当前日期"


def _append_date_and_language(prompt: str, language: Optional[str] = None) -> str:
    """在提示词末尾追加语言约束（如有）和当前日期行。

    语言行在前、日期行在末尾，均不破坏静态前缀缓存。
    语言参数仅从 UI 传入时注入；不传则只追加日期。
    """
    result = prompt
    lang_instr = _language_instruction(language)
    if lang_instr:
        result = f"{result}\n\n{lang_instr}"
    return f"{result}\n\n{_date_label(language)}：{_now_date()}"


def workspace_section(workspace: Optional[str]) -> str:
    """返回「工作目录」说明段。

    Agent（Lead 与子 agent 共用）若不被告知会话工作目录，会在被拒绝写入后
    反复 ``ls`` 错误路径（``/``、``/app``、容器系统路径）去猜测根目录——``ls /`` 又只返回
    CompositeBackend 拼接的 skills 只读挂载，越看越偏。把真实工作目录告知 agent 后，它要查看
    文件就 ``ls`` 正确的目录、要写入就直接写对路径，无需探路。

    放在提示词末尾（日期行之前），不破坏静态前缀缓存。
    """
    if not workspace:
        return ""
    ws = workspace.rstrip("/")
    return (
        "## 工作目录\n"
        f"你的会话工作目录是 `{ws}/`。文件读写都在此目录下进行：写入用相对路径"
        f"（如 `reports/x.md`，`write_file` 会自动创建父目录）或此目录下的绝对路径；"
        f"查看已有文件直接 `ls` 此目录或其子目录（如 `reports/`），"
        f"不要 `ls` `/`、`/app`、`/home/gem` 等容器系统路径。回传给上游的文件路径用相对路径。"
    )


def load_text_prompt(
    name: str,
    fallback: str,
    *,
    label: str = "production",
    cache_ttl_seconds: int = _PROMPT_CACHE_TTL,
    language: Optional[str] = None,
) -> str:
    """从 Langfuse 拉取文本提示词原文；不可用/失败时返回 ``fallback``。
    末尾自动追加语言约束（如有）和当前日期行（不破坏前缀缓存）。

    - Langfuse 未就绪（关闭或鉴权失败冷却期内）-> 直接返回 fallback + 语言 + 日期，零网络。
    - Langfuse 就绪 -> ``get_prompt(label=production, fallback=fallback)``，取 ``.prompt``；
      任何异常回落 fallback。末尾追加语言约束和当前日期。

    ``fallback`` 既是网络失败时的兜底，也是同步 CLI 的本地种子来源。
    """
    if not is_ready():
        return _append_date_and_language(fallback, language)
    client = get_langfuse_client()
    if client is None:
        return _append_date_and_language(fallback, language)
    try:
        pc = client.get_prompt(
            name,
            label=label,
            type="text",
            fallback=fallback,
            cache_ttl_seconds=cache_ttl_seconds,
            max_retries=1,
            fetch_timeout_seconds=3,
        )
        return _append_date_and_language(pc.prompt, language)
    except Exception as e:
        logger.warning(f"[Langfuse] 拉取提示词 {name!r} 失败，用本地兜底: {e}")
        return _append_date_and_language(fallback, language)


def load_lead_prompt(
    fallback_template: str,
    sandbox_info: Optional[str] = None,
    language: Optional[str] = None,
    workspace: Optional[str] = None,
) -> str:
    """父（Lead）提示词：Langfuse 拉取模板 -> 追加 sandbox -> 追加工作目录。

    ``fallback_template`` 是本地模板（与 Langfuse 中存储的模板同构）。
    子 agent 能力清单不再注入——``create_deep_agent(subagents=...)`` 已把每个子 agent
    作为 ``task`` 工具注入（描述=子 agent 的 ② description），Lead 路由直接依据该工具描述。
    ``load_text_prompt`` 内部已追加语言约束和当前日期行，此处只额外追加 sandbox 信息与
    工作目录说明。工作目录告知 Lead 用 ``read_file`` 回收子 agent 落盘报告时应以哪个目录为根，
    避免 Lead 也去 ``ls`` 探路。
    """
    prompt = load_text_prompt(LEAD_PROMPT_NAME, fallback=fallback_template, language=language)
    if sandbox_info:
        prompt += f"\n\n## Sandbox Environment\n{sandbox_info}"
    ws = workspace_section(workspace)
    if ws:
        prompt += f"\n\n{ws}"
    return prompt


def collect_local_prompts() -> List[Tuple[str, str]]:
    """收集所有本地提示词 ``(name, text)``，供同步到 Langfuse。

    = Lead 模板 + 全部已注册子 agent 的本地提示词。
    lazy import 防止与 domain_agent/factory 的循环导入。
    """
    prompts: List[Tuple[str, str]] = []
    # Lead
    from emsclaw_backend.deepagent.agents.business.factory import BUSINESS_LEAD_PROMPT
    prompts.append((LEAD_PROMPT_NAME, BUSINESS_LEAD_PROMPT))
    # 子 agent：import domains 触发自注册
    from emsclaw_backend.deepagent.agents.business.registry import AgentRegistry
    from emsclaw_backend.deepagent.agents.business import domains as _  # noqa: F401 触发自注册
    for agent in AgentRegistry.get_all():
        prompts.append((agent.get_prompt_name(), agent.get_system_prompt()))
    return prompts


def _is_not_found(exc: Exception) -> bool:
    """判断异常是否为「提示词不存在」（NotFoundError / 404）。"""
    if type(exc).__name__ == "NotFoundError":
        return True
    msg = str(exc).lower()
    return "404" in msg or "not found" in msg or "notfound" in msg


def sync_prompts_to_langfuse(create_only: bool = False) -> List[dict]:
    """把本地提示词同步到 Langfuse，实现版本化管理。

    - 不存在（NotFoundError）-> ``create_prompt(labels=["production"])``（seed）。
    - 存在且内容相同 -> skip。
    - 存在但不同 -> ``create_prompt(labels=["production"])`` 新建版本（旧版保留为历史，
      production 标签自动迁移到新版）；``create_only=True`` 时仅 seed 缺失项，不改已有。

    返回每个提示词的同步结果列表（``created/updated/unchanged/skipped/error``）。
    """
    if not is_ready():
        raise RuntimeError(
            "Langfuse 未就绪（未启用或鉴权失败），无法同步。"
            "请检查 LANGFUSE_ENABLED / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL。"
        )
    client = get_langfuse_client()
    if client is None:
        raise RuntimeError("Langfuse client 不可用")

    results: List[dict] = []
    for name, local_text in collect_local_prompts():
        try:
            # cache_ttl_seconds=0 强制拉最新，避免读到旧缓存导致漏新建版本
            existing = client.get_prompt(name, type="text", cache_ttl_seconds=0)
        except Exception as e:
            if _is_not_found(e):
                try:
                    client.create_prompt(
                        name=name,
                        prompt=local_text,
                        labels=["production"],
                        type="text",
                        commit_message="seed from local prompts",
                    )
                    results.append({"name": name, "action": "created", "version": None})
                    logger.info(f"[Langfuse] 提示词 {name!r} 已 seed")
                except Exception as ce:
                    results.append({"name": name, "action": "error", "detail": f"create failed: {ce}"})
                    logger.error(f"[Langfuse] seed {name!r} 失败: {ce}")
                continue
            results.append({"name": name, "action": "error", "detail": f"get failed: {e}"})
            logger.error(f"[Langfuse] 拉取 {name!r} 失败: {e}")
            continue

        # 已存在
        if existing.prompt == local_text:
            results.append({"name": name, "action": "unchanged", "version": existing.version})
            logger.info(f"[Langfuse] 提示词 {name!r} 无变化 (v{existing.version})")
            continue
        if create_only:
            results.append({
                "name": name, "action": "skipped", "version": existing.version,
                "detail": "create_only=True，已存在且不同",
            })
            logger.info(f"[Langfuse] 提示词 {name!r} 已存在且不同，create_only 跳过 (v{existing.version})")
            continue
        try:
            client.create_prompt(
                name=name,
                prompt=local_text,
                labels=["production"],
                type="text",
                commit_message="sync from local prompts",
            )
            results.append({"name": name, "action": "updated", "version": None})
            logger.info(f"[Langfuse] 提示词 {name!r} 已新建版本（production 已迁移）")
        except Exception as ce:
            results.append({"name": name, "action": "error", "detail": f"update failed: {ce}"})
            logger.error(f"[Langfuse] 更新 {name!r} 失败: {ce}")
    return results


def _main() -> int:
    parser = argparse.ArgumentParser(description="Langfuse 提示词版本化同步")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_sync = sub.add_parser("sync", help="把本地提示词同步到 Langfuse")
    p_sync.add_argument(
        "--create-only", action="store_true",
        help="仅 seed 缺失的提示词，不更新已有版本",
    )
    args = parser.parse_args()

    if args.cmd == "sync":
        try:
            results = sync_prompts_to_langfuse(create_only=args.create_only)
        except RuntimeError as e:
            print(f"[error] {e}")
            return 1
        print(f"\n同步完成（create_only={args.create_only}）：")
        for r in results:
            extra = f" v{r['version']}" if r.get("version") else ""
            detail = f"  ({r['detail']})" if r.get("detail") else ""
            print(f"  - {r['name']}: {r['action']}{extra}{detail}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
