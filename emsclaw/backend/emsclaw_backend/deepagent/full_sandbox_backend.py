"""
FullSandboxBackend — 全沙盒后端实现。

所有操作（文件管理、命令执行、搜索等）均通过远程 Sandbox API 完成。
实现了会话级隔离，每个会话在沙盒中拥有独立的执行目录和 Shell 状态。

改进：
  - 使用共享 httpx.AsyncClient 连接池，避免每次请求新建 TCP 连接
  - 同步包装方法兼容已有事件循环（通过线程池 fallback）
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import time
from typing import Any, List, Optional, cast

import httpx
from deepagents.backends.protocol import (
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GlobResult,
    GrepMatch,
    SandboxBackendProtocol,
    WriteResult,
)

logger = logging.getLogger(__name__)

_SANDBOX_URL = os.environ.get("SANDBOX_REST_URL", "http://localhost:18080").rstrip("/")
_BASE_WORKSPACE = os.environ.get("WORKSPACE_DIR", "/home/emsclaw")
_EXECUTE_TIMEOUT = 600
_MAX_OUTPUT_CHARS = 50000
_CIRCUIT_BREAKER_THRESHOLD = 3
_CIRCUIT_BREAKER_COOLDOWN = 30

_sync_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

def _run_sync(coro):
    """Run coroutine from sync context, safe even when an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return _sync_executor.submit(asyncio.run, coro).result()

def _extract_list_from_data(data: Any, *keys: str) -> list:
    """从 sandbox API 的 data 字段中按候选 key 顺序提取列表，
    兼容不同版本 API 返回 files / items / matches 等不同字段名。"""
    if not isinstance(data, dict):
        return list(data) if isinstance(data, list) else []
    for k in keys:
        val = data.get(k)
        if isinstance(val, list):
            return val
    return []

def _normalize_file_item(raw: Any) -> dict | None:
    """将 sandbox API 返回的单个文件条目统一为 {path, name, is_dir, size, modified_at}。
    兼容字符串路径、不同字段名 (is_directory/is_dir, modified_time/modified_at) 等格式。"""
    if isinstance(raw, str):
        name = raw.rsplit("/", 1)[-1] if "/" in raw else raw
        return {"path": raw, "name": name, "is_dir": False, "size": 0, "modified_at": ""}
    if not isinstance(raw, dict):
        return None
    path = raw.get("path", "")
    name = raw.get("name", "")
    if not name and path:
        name = path.rsplit("/", 1)[-1] if "/" in path else path
    return {
        "path": path,
        "name": name,
        "is_dir": raw.get("is_dir", raw.get("is_directory", False)),
        "size": raw.get("size", 0) or 0,
        "modified_at": raw.get("modified_at", raw.get("modified_time", "")),
    }

def _truncate_for_log(value: Any, limit: int = 500) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "...(truncated)"

class FullSandboxBackend(SandboxBackendProtocol):
    """全沙盒后端：完全依赖远程 API 进行计算和存储。"""

    def __init__(
        self,
        session_id: str,
        user_id: str,
        sandbox_url: str = _SANDBOX_URL,
        base_dir: str = _BASE_WORKSPACE,
        execute_timeout: int = _EXECUTE_TIMEOUT,
        max_output_chars: int = _MAX_OUTPUT_CHARS,
    ) -> None:
        self._session_id = session_id
        self._user_id = user_id
        self._sandbox_url = sandbox_url
        self._base_dir = base_dir
        self._remote_workspace = os.path.join(base_dir, session_id)
        self._execute_timeout = execute_timeout
        self._max_output_chars = max_output_chars
        self._shell_session_id: Optional[str] = None
        self._env_context: Optional[dict] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._client_loop_id: Optional[int] = None
        self._consecutive_sandbox_errors = 0
        self._circuit_open_until = 0.0

        logger.info(
            f"[FullSandbox] Initialized: user={user_id}, session={session_id}, "
            f"remote_path={self._remote_workspace}"
        )

    def _get_client(self) -> httpx.AsyncClient:
        """获取绑定当前事件循环的 httpx 异步客户端（不设客户端级别超时，由各请求自行控制）。

        sync 方法（glob_info/ls_info/grep_raw 等）经 ``_run_sync`` 在线程池
        ``asyncio.run`` 的新 loop 里跑，每个新 loop 不能复用上一个（已关闭）loop 的
        client——否则 httpx 内部连接池的 asyncio 原语会抛 'Event loop is closed' /
        'bound to a different event loop'，导致 glob/ls/grep 全失败、子 agent 反复重试。
        故按 loop 缓存：当前 loop 与 client 绑定 loop 不一致则丢弃重建（旧 loop 已死
        无法 aclose，交由 GC；同一 loop 内复用连接池）。
        """
        try:
            lid = id(asyncio.get_running_loop())
        except RuntimeError:
            lid = None
        if (self._client is not None and not self._client.is_closed
                and self._client_loop_id == lid):
            return self._client
        self._client = httpx.AsyncClient(
            base_url=self._sandbox_url,
            timeout=httpx.Timeout(30),
        )
        self._client_loop_id = lid
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @property
    def id(self) -> str:
        return f"full-sandbox-{self._session_id}"

    @property
    def workspace(self) -> str:
        return self._remote_workspace

    def _resolve_path(self, file_path: str) -> Optional[str]:
        """把 Agent 提供的路径解析为 session workspace 内的绝对路径（沙箱收纳模型）。

        框架的 ``write_file``/``read_file`` 等工具会先调 ``validate_path``，把相对路径
        ``reports/x`` 规范成根绝对路径 ``/reports/x``（见 deepagents/backends/utils.py
        ``validate_path``，示例 ``validate_path("foo/bar") -> "/foo/bar"``）。按旧的
        「拒绝越界」语义，这类路径会被当作「不在 workspace 内的绝对路径」直接拒绝，
        导致 Agent 用相对路径写文件时首次必失败、再重试一轮——见 trace
        eea37da7c5de44c31f1792ef7d62278e：write_file permission_denied + 整份报告二次重生成。

        沙箱收纳模型：Agent 的整个文件世界就是它的 session workspace，任何「非
        workspace 内」的路径都视作「相对 workspace 的路径」重定向进 workspace——既让
        相对路径机械生效（不再依赖提示词约束 Agent 用绝对路径），又保证 Agent 无法
        触及 workspace 以外的真实文件（越界一律收纳进沙箱，无法逃逸）：
          - 相对路径 ``reports/x``            → ``{ws}/reports/x``
          - 框架规范后的 ``/reports/x``        → ``{ws}/reports/x``
          - ``/etc/passwd``                    → ``{ws}/etc/passwd``（容器内、不可逃逸）
          - ``/home/emsclaw/other_session/x``  → ``{ws}/home/emsclaw/other_session/x``
        ``..`` 经 normpath 折叠后仍越界 workspace 的返回 None（``..`` 在工具层已被
        ``validate_path`` 拦截，此处兜底；该校验是 rescue 安全的关键，不可删）。
        """
        workspace = os.path.normpath(self._remote_workspace)
        if not file_path.startswith("/"):
            # 真正的相对路径：直接拼到 workspace 下
            candidate = os.path.join(self._remote_workspace, file_path)
        else:
            normalized = os.path.normpath(file_path)
            if normalized == workspace or normalized.startswith(workspace + os.sep):
                # 已在 workspace 内的绝对路径：原样放行
                candidate = normalized
            else:
                # 非 workspace 内的绝对路径（含框架把相对路径规范化成的 /reports/x）：
                # 剥前导 /，当作相对 workspace 处理，重定向进沙箱。
                candidate = os.path.join(self._remote_workspace, file_path.lstrip("/"))
        normalized = os.path.normpath(candidate)
        # normpath 后再校验一次：防 .. 等被 normpath 折叠后越界（rescue 的安全兜底）
        if normalized == workspace or normalized.startswith(workspace + os.sep):
            return normalized
        logger.warning(
            f"[FullSandbox] Path could not be contained in session workspace: {file_path}"
        )
        return None

    # ── 内部辅助：环境上下文与会话管理 ──────────────────────────

    async def get_context(self) -> dict:
        if self._env_context:
            return self._env_context

        try:
            client = self._get_client()
            resp = await client.get("/v1/sandbox", timeout=10)
            resp.raise_for_status()
            self._env_context = resp.json()
            return self._env_context
        except Exception as exc:
            logger.error(f"[FullSandbox] Failed to fetch sandbox context: {exc}")
            return {"success": False, "message": str(exc)}

    async def _aensure_session(self, force_new: bool = False) -> str:
        if self._shell_session_id and not force_new:
            return self._shell_session_id

        if force_new:
            logger.info("[FullSandbox] Force recreating shell session (previous session may have expired)")
            self._shell_session_id = None

        await self.get_context()

        try:
            client = self._get_client()
            resp = await client.post(
                "/v1/shell/sessions/create",
                json={"id": self._session_id, "exec_dir": self._remote_workspace},
            )
            resp.raise_for_status()
            data = resp.json()
            self._shell_session_id = data["data"]["session_id"]
            logger.info(f"[FullSandbox] Shell session created: {self._shell_session_id}")
            return self._shell_session_id
        except Exception as exc:
            logger.error(f"[FullSandbox] Failed to create shell session: {exc}")
            raise

    def _ensure_session(self) -> str:
        if self._shell_session_id:
            return self._shell_session_id
        return _run_sync(self._aensure_session())

    # ── 命令执行 (Execute) ────────────────────────────────────

    def _parse_exec_response(self, result: dict) -> tuple[ExecuteResponse, bool]:
        raw_data = result.get("data")
        data = raw_data or {}
        if raw_data is not None and not isinstance(raw_data, dict):
            logger.warning(
                "[FullSandbox] Unexpected exec response format: "
                f"data_type={type(raw_data).__name__}, "
                f"data={_truncate_for_log(raw_data)}, "
                f"result={_truncate_for_log(result)}"
            )
            error_msg = str(raw_data).strip() if raw_data else ""
            if not error_msg:
                error_msg = "Sandbox returned an unexpected response format."
            return ExecuteResponse(output=f"[error] {error_msg}", exit_code=-1, truncated=False), True

        output = data.get("output", "")
        exit_code = data.get("exit_code", 0)
        truncated = False
        if len(output) > self._max_output_chars:
            output = output[:self._max_output_chars] + "\n...(truncated)...\n"
            truncated = True
        return ExecuteResponse(output=output, exit_code=exit_code, truncated=truncated), False

    def _reset_sandbox_error_state(self) -> None:
        if self._consecutive_sandbox_errors > 0 or self._circuit_open_until > 0:
            logger.info("[FullSandbox] Sandbox exec error state reset after successful response")
        self._consecutive_sandbox_errors = 0
        self._circuit_open_until = 0.0

    def _check_circuit_breaker(self) -> ExecuteResponse | None:
        if self._circuit_open_until <= 0:
            return None

        remaining = self._circuit_open_until - time.monotonic()
        if remaining <= 0:
            logger.info("[FullSandbox] Sandbox exec circuit breaker cooldown expired")
            self._reset_sandbox_error_state()
            return None

        remaining_seconds = max(1, int(remaining + 0.999))
        return ExecuteResponse(
            output=(
                "[error] Sandbox execution is temporarily disabled for this session after "
                f"{self._consecutive_sandbox_errors} consecutive malformed responses. "
                f"Retry after {remaining_seconds}s, and stop issuing further shell commands "
                "until the sandbox health/logs have been checked."
            ),
            exit_code=-1,
            truncated=False,
        )

    def _record_malformed_exec_response(
        self, command: str, response: ExecuteResponse, effective_timeout: int
    ) -> ExecuteResponse:
        self._consecutive_sandbox_errors += 1
        logger.warning(
            "[FullSandbox] Malformed exec response detected: "
            f"count={self._consecutive_sandbox_errors}/{_CIRCUIT_BREAKER_THRESHOLD}, "
            f"timeout={effective_timeout}s, "
            f"command={_truncate_for_log(command, limit=200)}"
        )

        guidance = (
            f"Sandbox returned malformed execution data "
            f"({self._consecutive_sandbox_errors}/{_CIRCUIT_BREAKER_THRESHOLD} consecutive failures). "
            "If this continues, stop retrying commands and inspect sandbox health/logs."
        )

        if self._consecutive_sandbox_errors >= _CIRCUIT_BREAKER_THRESHOLD:
            self._circuit_open_until = time.monotonic() + _CIRCUIT_BREAKER_COOLDOWN
            logger.error(
                "[FullSandbox] Opening sandbox exec circuit breaker: "
                f"cooldown={_CIRCUIT_BREAKER_COOLDOWN}s, "
                f"timeout={effective_timeout}s, "
                f"command={_truncate_for_log(command, limit=200)}"
            )
            guidance = (
                f"Sandbox returned malformed execution data "
                f"{self._consecutive_sandbox_errors} times in a row. "
                f"Circuit breaker opened for {_CIRCUIT_BREAKER_COOLDOWN}s. "
                "Stop retrying commands and inspect sandbox health/logs."
            )

        output_parts = [response.output.strip(), f"[error] {guidance}"]
        return ExecuteResponse(
            output="\n".join(part for part in output_parts if part),
            exit_code=-1,
            truncated=response.truncated,
        )

    def _is_session_expired(self, resp_json: dict) -> bool:
        """Check if the sandbox API response indicates the shell session no longer exists."""
        if not resp_json.get("success", True):
            msg = (resp_json.get("message") or "").lower()
            if "session not found" in msg or "session expired" in msg:
                return True
        return False

    async def aexecute(
        self, command: str, *, timeout: int | None = None
    ) -> ExecuteResponse:
        effective_timeout = timeout or self._execute_timeout
        debug_run_id = f"{self._session_id}-{int(time.time() * 1000)}"
        circuit_response = self._check_circuit_breaker()
        if circuit_response is not None:
            return circuit_response

        for attempt in range(2):
            try:
                sid = await self._aensure_session(force_new=(attempt > 0))
                client = self._get_client()
                logger.info(
                    "[FullSandbox] Executing command: "
                    f"timeout={effective_timeout}s, "
                    f"attempt={attempt + 1}/2, "
                    f"command={_truncate_for_log(command, limit=200)}"
                )
                resp = await client.post(
                    "/v1/shell/exec",
                    json={
                        "id": sid,
                        "command": command,
                        "async_mode": False,
                        "exec_dir": self._remote_workspace,
                    },
                    timeout=httpx.Timeout(effective_timeout + 10, connect=10),
                )
                resp.raise_for_status()
                result = resp.json()
                raw_data = result.get("data") if isinstance(result, dict) else None

                if self._is_session_expired(result):
                    if attempt == 0:
                        logger.warning(f"[FullSandbox] Session expired, recreating (attempt {attempt + 1})")
                        continue
                    return ExecuteResponse(
                        output="[error] Shell session expired and recreation failed", exit_code=1
                    )

                exec_response, is_malformed = self._parse_exec_response(result)
                if is_malformed:
                    return self._record_malformed_exec_response(command, exec_response, effective_timeout)
                self._reset_sandbox_error_state()
                return exec_response
            except httpx.TimeoutException as exc:
                logger.error(f"[FullSandbox] Execute timed out after {effective_timeout}s: {exc!r}")
                return ExecuteResponse(output=f"[error] Command timed out after {effective_timeout}s", exit_code=1)
            except Exception as exc:
                if attempt == 0 and ("connection" in str(exc).lower() or "connect" in str(exc).lower()):
                    logger.warning(f"[FullSandbox] Connection error, retrying with new session: {exc!r}")
                    self._shell_session_id = None
                    continue
                logger.error(f"[FullSandbox] Execute failed: {exc!r}")
                return ExecuteResponse(output=f"[error] {exc}", exit_code=1)

        return ExecuteResponse(output="[error] Execute failed after retries", exit_code=1)

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return _run_sync(self.aexecute(command, timeout=timeout))

    # ── 文件操作 (File Operations) ─────────────────────────────

    async def als_info(self, path: str) -> list[FileInfo]:
        resolved = self._resolve_path(path)
        if resolved is None:
            return []
        try:
            client = self._get_client()
            resp = await client.post("/v1/file/list", json={"path": resolved, "recursive": False})
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data", body)
            raw_items = _extract_list_from_data(data, "files", "items")
            if not raw_items:
                logger.debug(f"[FullSandbox] ls_info({resolved}): empty result, data keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
            results: list[FileInfo] = []
            for raw in raw_items:
                normed = _normalize_file_item(raw)
                if normed and normed["path"]:
                    results.append(cast("FileInfo", normed))
            return results
        except Exception as exc:
            logger.warning(f"[FullSandbox] ls_info({resolved}) failed: {exc}")
            return []

    def ls_info(self, path: str) -> list[FileInfo]:
        return _run_sync(self.als_info(path))

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        resolved = self._resolve_path(file_path)
        if resolved is None:
            return f"Error: path '{file_path}' outside session workspace"
        try:
            client = self._get_client()
            resp = await client.post(
                "/v1/file/read",
                json={"file": resolved, "start_line": offset, "end_line": offset + limit},
            )
            if resp.status_code == 404:
                return f"Error: File '{resolved}' not found"
            resp.raise_for_status()
            return resp.json().get("data", {}).get("content", "")
        except Exception as exc:
            return f"Error reading file '{resolved}': {exc}"

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        return _run_sync(self.aread(file_path, offset, limit))

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        resolved = self._resolve_path(file_path)
        if resolved is None:
            return WriteResult(
                error=f"permission_denied: path '{file_path}' outside session workspace"
            )
        try:
            client = self._get_client()
            resp = await client.post(
                "/v1/file/write", json={"file": resolved, "content": content}
            )
            resp.raise_for_status()
            return WriteResult(path=resolved)
        except Exception as exc:
            return WriteResult(error=f"Error writing file '{resolved}': {exc}")

    def write(self, file_path: str, content: str) -> WriteResult:
        return _run_sync(self.awrite(file_path, content))

    async def aedit(
        self, file_path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> EditResult:
        resolved = self._resolve_path(file_path)
        if resolved is None:
            return EditResult(
                error=f"permission_denied: path '{file_path}' outside session workspace"
            )
        try:
            client = self._get_client()
            resp = await client.post(
                "/v1/file/str_replace_editor",
                json={
                    "command": "str_replace",
                    "path": resolved,
                    "old_str": old_string,
                    "new_str": new_string,
                },
            )
            resp.raise_for_status()
            return EditResult(path=resolved, occurrences=1)
        except Exception as exc:
            return EditResult(error=f"Error editing file '{resolved}': {exc}")

    def edit(
        self, file_path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> EditResult:
        return _run_sync(self.aedit(file_path, old_string, new_string, replace_all))

    async def agrep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        target = path or self._remote_workspace
        resolved = self._resolve_path(target)
        if resolved is None:
            logger.warning(f"[FullSandbox] grep denied (outside session workspace): {target}")
            return []
        target = resolved
        try:
            client = self._get_client()
            resp = await client.post(
                "/v1/file/search",
                json={"file": target, "regex": pattern},
            )
            body = resp.json()
            if not body.get("success", True):
                # /v1/file/search 不支持目录，回退到 shell grep
                return await self._grep_via_shell(pattern, target, glob)
            resp.raise_for_status()
            data = body.get("data", {}) if isinstance(body.get("data"), dict) else {}
            raw_matches = _extract_list_from_data(data, "matches", "results")
            line_numbers = data.get("line_numbers", [])
            file_path = data.get("file", target)
            results: list[GrepMatch] = []
            for i, m in enumerate(raw_matches):
                if isinstance(m, dict):
                    results.append(cast("GrepMatch", {
                        "path": m.get("path", file_path),
                        "line": m.get("line", m.get("line_number", 0)),
                        "text": m.get("text", m.get("content", "")),
                    }))
                elif isinstance(m, str):
                    line_num = line_numbers[i] if i < len(line_numbers) else 0
                    results.append(cast("GrepMatch", {
                        "path": file_path,
                        "line": line_num,
                        "text": m,
                    }))
            return results
        except Exception as exc:
            logger.warning(f"[FullSandbox] grep_raw({target}, {pattern!r}) API failed, trying shell fallback: {exc}")
            try:
                return await self._grep_via_shell(pattern, target, glob)
            except Exception:
                return f"Error searching pattern '{pattern}': {exc}"

    async def _grep_via_shell(
        self, pattern: str, path: str, glob: str | None = None
    ) -> list[GrepMatch] | str:
        """通过 shell grep 命令实现搜索，作为 /v1/file/search 不支持目录时的回退方案。"""
        import shlex
        glob_flag = f"--include={shlex.quote(glob)} " if glob else ""
        cmd = f"grep -rn {glob_flag}{shlex.quote(pattern)} {shlex.quote(path)} 2>/dev/null || true"
        exec_result = await self.aexecute(cmd, timeout=30)
        results: list[GrepMatch] = []
        for line in exec_result.output.splitlines():
            # grep -rn output: file:line_num:text
            parts = line.split(":", 2)
            if len(parts) >= 3:
                try:
                    results.append(cast("GrepMatch", {
                        "path": parts[0],
                        "line": int(parts[1]),
                        "text": parts[2],
                    }))
                except (ValueError, IndexError):
                    continue
        return results

    def grep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        return _run_sync(self.agrep_raw(pattern, path, glob))

    # ── glob (新 API，覆盖 BackendProtocol 默认 "/" 的 fallback) ────

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        """Find files matching a glob pattern.

        Default search root is the session workspace (not ``"/"``),
        avoiding full-filesystem scans that hit the framework's GLOB_TIMEOUT.
        """
        return GlobResult(matches=self.glob_info(pattern, path or self._remote_workspace))

    async def aglob(self, pattern: str, path: str | None = None) -> GlobResult:
        """Async version of ``glob``."""
        return GlobResult(matches=await self.aglob_info(pattern, path or self._remote_workspace))

    async def aglob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        resolved = self._resolve_path(path)
        if resolved is None:
            return []
        try:
            client = self._get_client()
            resp = await client.post(
                "/v1/file/find", json={"path": resolved, "glob": pattern}
            )
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data", body)
            raw_items = _extract_list_from_data(data, "files", "items")
            results: list[FileInfo] = []
            for raw in raw_items:
                normed = _normalize_file_item(raw)
                if normed and normed["path"]:
                    results.append(cast("FileInfo", normed))
            return results
        except Exception as exc:
            logger.warning(f"[FullSandbox] glob_info({resolved}, {pattern!r}) failed: {exc}")
            return []

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        return _run_sync(self.aglob_info(pattern, path))

    # ── 批量文件传输 ──────────────────────────────────────────

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        async def _upload_all():
            client = self._get_client()
            tasks = []
            for file_path, content in files:
                tasks.append(self._upload_one(client, file_path, content))
            return await asyncio.gather(*tasks)

        return list(_run_sync(_upload_all()))

    async def _upload_one(
        self, client: httpx.AsyncClient, file_path: str, content: bytes
    ) -> FileUploadResponse:
        resolved = self._resolve_path(file_path)
        if resolved is None:
            return FileUploadResponse(path=file_path, error="permission_denied")
        try:
            files_payload = {"file": (os.path.basename(resolved), content)}
            data_payload = {"path": resolved}
            resp = await client.post("/v1/file/upload", files=files_payload, data=data_payload, timeout=60)
            resp.raise_for_status()
            return FileUploadResponse(path=resolved)
        except Exception as exc:
            logger.error(f"[FullSandbox] Upload failed for {resolved}: {exc}")
            return FileUploadResponse(path=resolved, error="permission_denied")

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        async def _download_all():
            client = self._get_client()
            tasks = [self._download_one(client, p) for p in paths]
            return await asyncio.gather(*tasks)

        return list(_run_sync(_download_all()))

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        client = self._get_client()
        tasks = [self._download_one(client, p) for p in paths]
        return list(await asyncio.gather(*tasks))

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        client = self._get_client()
        tasks = [self._upload_one(client, fp, content) for fp, content in files]
        return list(await asyncio.gather(*tasks))

    async def _download_one(
        self, client: httpx.AsyncClient, file_path: str
    ) -> FileDownloadResponse:
        resolved = self._resolve_path(file_path)
        if resolved is None:
            return FileDownloadResponse(path=file_path, error="permission_denied")
        try:
            resp = await client.get("/v1/file/download", params={"path": resolved}, timeout=60)
            if resp.status_code == 404:
                return FileDownloadResponse(path=resolved, error="file_not_found")
            resp.raise_for_status()
            return FileDownloadResponse(path=resolved, content=resp.content)
        except Exception as exc:
            logger.error(f"[FullSandbox] Download failed for {resolved}: {exc}")
            return FileDownloadResponse(path=resolved, error="permission_denied")
