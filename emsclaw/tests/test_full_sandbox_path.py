"""FullSandboxBackend 路径 containment 测试（沙箱收纳模型）。

Agent 的整个文件世界就是它的 session workspace：
- workspace 内的路径（相对或绝对）→ 解析为 workspace 内的绝对路径。
- workspace 外的绝对路径（含框架 ``validate_path`` 把相对路径规范成的 ``/reports/x``）
  → 收纳进 workspace（剥前导 / 后拼 workspace），无法逃逸到真实文件系统。
- ``..`` 经 normpath 折叠后越界 workspace 的 → 返回 None（rescue 的安全兜底），
  文件操作优雅降级、且不触发任何网络请求。
"""
import os

import pytest

from emsclaw_backend.deepagent.full_sandbox_backend import FullSandboxBackend


@pytest.fixture
def sandbox() -> FullSandboxBackend:
    # 用固定 POSIX 根构造；Windows 下 os.path 内部统一用平台分隔符，断言用同一 os.path 计算期望值
    return FullSandboxBackend(session_id="s1", user_id="u", base_dir="/home/emsclaw")


class _NoNetClient:
    """任何方法调用都抛错：证明被拒绝的路径没有真正发请求。"""

    def __getattr__(self, name):
        def _raise(*_a, **_k):
            raise AssertionError(f"network call attempted: {name}")

        return _raise


def _norm(p: str) -> str:
    return os.path.normpath(p)


def _rescued(sandbox: FullSandboxBackend, p: str) -> str:
    """镜像 ``_resolve_path`` 对外部绝对路径的 rescue 计算：
    剥前导 ``/`` 后拼到 workspace、再 normpath。用于断言「收纳进 workspace」的期望值。"""
    return _norm(os.path.join(sandbox.workspace, p.lstrip("/")))


# ── _resolve_path：放行 ──────────────────────────────────────────

def test_resolve_path_allows_workspace_and_children(sandbox):
    ws = sandbox.workspace
    assert sandbox._resolve_path(ws) == _norm(ws)
    assert sandbox._resolve_path(f"{ws}/reports/a.md") == _norm(f"{ws}/reports/a.md")
    # 相对路径 → 拼到 workspace 下
    assert sandbox._resolve_path("reports/a.md") == _norm(os.path.join(ws, "reports", "a.md"))
    assert sandbox._resolve_path("x") == _norm(os.path.join(ws, "x"))
    # ./ 归一化
    assert sandbox._resolve_path("./x") == _norm(os.path.join(ws, "x"))
    # 框架 validate_path 把相对路径规范成的根绝对路径 /reports/a.md → 收纳进 workspace。
    # 这是真实生产链路：write_file("reports/x") 先经 validate_path → "/reports/x" 再到 _resolve_path。
    assert sandbox._resolve_path("/reports/a.md") == _rescued(sandbox, "/reports/a.md")


# ── _resolve_path：外部绝对路径收纳进 workspace ─────────────────

def test_resolve_path_rescues_foreign_into_workspace(sandbox):
    """越界的绝对路径一律收纳进 session workspace（沙箱收纳模型），不再返回 None。

    Agent 无法触及 workspace 以外的真实文件——越界路径被重定向进沙箱后仍在其内，
    无法逃逸。只有 ``..`` 经 normpath 折叠后越界的才返回 None（见 test_resolve_path_denies_traversal）。
    """
    ws = _norm(sandbox.workspace)
    # /etc/passwd → 收纳进 workspace（容器内、不可逃逸到真实 /etc/passwd）
    assert sandbox._resolve_path("/etc/passwd") == _rescued(sandbox, "/etc/passwd")
    assert sandbox._resolve_path("/etc/passwd") == _norm(os.path.join(ws, "etc", "passwd"))
    # / → 收纳为 workspace 根本身
    assert sandbox._resolve_path("/") == ws
    # 其它会话的路径 → 收纳进本会话（跨会话隔离更强）
    assert sandbox._resolve_path("/home/emsclaw/other_session/x") == _rescued(
        sandbox, "/home/emsclaw/other_session/x"
    )
    # 父目录（会看到其它会话）也收纳进 workspace，而非拒绝
    assert sandbox._resolve_path("/home/emsclaw") == _rescued(sandbox, "/home/emsclaw")
    # 前缀陷阱：s1 不是 s1x 的目录前缀 → 被视作越界、收纳进 workspace（而非 None）
    assert sandbox._resolve_path(sandbox.workspace + "x/f") == _rescued(
        sandbox, sandbox.workspace + "x/f"
    )


# ── _resolve_path：.. 仍拒绝（rescue 的安全兜底） ────────────────

def test_resolve_path_denies_traversal(sandbox):
    """.. 经 normpath 折叠后越界 workspace 的，返回 None。

    ``..`` 在工具层已被框架 ``validate_path`` 拒绝，此处为兜底；该 containment 校验是
    rescue 安全的关键——没有它 ``..`` 可在 rescue 后逃逸，不可删。
    """
    assert sandbox._resolve_path("../x") is None
    assert sandbox._resolve_path("../../x") is None
    # 剥前导 / 后仍含 ..，normpath 折叠后越界 → None
    assert sandbox._resolve_path("/../x") is None
    assert sandbox._resolve_path("/..") is None


# ── 各文件操作：.. 越界优雅降级、零网络 ─────────────────────────

@pytest.mark.asyncio
async def test_file_ops_deny_traversal_without_network(sandbox, monkeypatch):
    """.. 越界路径被 _resolve_path 拒绝（None），文件操作优雅降级、且不触发任何网络请求。

    外部绝对路径（/etc/passwd 等）现已收纳进 workspace（见 test_file_ops_rescue_foreign_paths），
    会真正发请求；故零网络拒绝改用 ..-traversal 路径验证。
    """
    monkeypatch.setattr(sandbox, "_get_client", lambda: _NoNetClient())

    # .. 越界 → None → 各操作返回拒绝态、零网络
    assert await sandbox.als_info("../x") == []
    assert await sandbox.aglob_info("*.py", "../x") == []
    assert await sandbox.agrep_raw("foo", path="../x") == []

    r = await sandbox.aread("../x")
    assert "outside session workspace" in r

    wr = await sandbox.awrite("../x", "data")
    assert wr.error and "permission_denied" in wr.error

    er = await sandbox.aedit("../x", "a", "b")
    assert er.error and "permission_denied" in er.error

    dl = await sandbox.adownload_files(["../x"])
    assert dl and dl[0].error == "permission_denied"

    ul = await sandbox.aupload_files([("../x", b"data")])
    assert ul and ul[0].error == "permission_denied"


@pytest.mark.asyncio
async def test_file_ops_rescue_foreign_paths(sandbox, monkeypatch):
    """外部绝对路径被收纳进 workspace：文件操作不再返回 permission_denied，
    而是尝试在 workspace 内发请求（这里打 NoNet → 网络/写入错误）。

    这锁定 rescue 行为变化：../x 仍拒绝（上一测试），但 /etc/passwd 收纳（不拒绝）。
    """
    monkeypatch.setattr(sandbox, "_get_client", lambda: _NoNetClient())

    wr = await sandbox.awrite("/etc/passwd", "data")
    assert wr.error and "permission_denied" not in wr.error

    r = await sandbox.aread("/etc/passwd")
    assert "outside session workspace" not in r  # 不再是拒绝态字符串


@pytest.mark.asyncio
async def test_grep_denies_traversal_without_shell(sandbox, monkeypatch):
    """grep 的 .. 越界 path 直接拒绝并返回 []，不落到 shell 回退（无网络）。

    /etc 等外部绝对路径现已收纳进 workspace（会发请求）；零网络拒绝改用 ..-traversal。
    """
    monkeypatch.setattr(sandbox, "_get_client", lambda: _NoNetClient())
    assert await sandbox.agrep_raw("x", path="../etc") == []
