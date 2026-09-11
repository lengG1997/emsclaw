"""域技能虚拟挂载 `/domain-skills/` 根目录可枚举性回归测试。

背景:per-pkg 路由只注册了
`/domain-skills/<pkg>/`,裸根 `/domain-skills/` 落到 sandbox 默认后端(沙箱里不存在该
路径)→ ls 返回空,agent 看不到技能结构,只能逐包 ls + glob 探路。裸根应返回
各域包目录;`ls /`(根聚合)只出现一个 `/domain-skills/` 入口;glob 不重复。
"""
from deepagents.backends.protocol import GlobResult, GrepResult, LsResult, ReadResult

from emsclaw_backend.deepagent.agents.business.factory import _build_business_backend

EXPECTED_PACKAGES = {
    "/domain-skills/dispatch_planning/",
    "/domain-skills/device_operation/",
    "/domain-skills/station_data/",
}


class _EmptySandbox:
    """模拟 sandbox 默认后端:未知路径一律返回空(对齐 FullSandboxBackend 对缺失目录返回 [])。"""

    def ls(self, path: str) -> LsResult:
        return LsResult(entries=[])

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        return ReadResult(error=f"not found: {file_path}")

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        return GlobResult(matches=[])

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None) -> GrepResult:
        return GrepResult(matches=[])


def _backend():
    return _build_business_backend(_EmptySandbox())


def test_domain_skills_root_lists_all_packages():
    res = _backend().ls("/domain-skills/")
    assert res.error is None, res.error
    assert {e["path"] for e in res.entries} == EXPECTED_PACKAGES


def test_domain_skills_root_no_trailing_slash():
    # validate_path 会把尾部斜杠剥掉,再走同一路由
    res = _backend().ls("/domain-skills")
    assert res.error is None, res.error
    assert {e["path"] for e in res.entries} == EXPECTED_PACKAGES


def test_domain_skills_pkg_ls_still_works():
    res = _backend().ls("/domain-skills/dispatch_planning/")
    assert res.error is None, res.error
    assert any("dispatch-strategy" in e["path"] for e in res.entries)


def test_domain_skills_read_skill_md():
    res = _backend().read("/domain-skills/dispatch_planning/dispatch-strategy/SKILL.md")
    assert res.error is None, res.error
    content = (res.file_data or {}).get("content") or ""
    assert content.strip(), "SKILL.md content empty"


def test_root_ls_shows_single_domain_skills_entry():
    res = _backend().ls("/")
    assert res.error is None, res.error
    ds = [e["path"] for e in res.entries if e["path"].startswith("/domain-skills")]
    assert ds == ["/domain-skills/"], ds


def test_glob_workspace_no_duplicate_skill_md():
    res = _backend().glob("**/*", path="/home/emsclaw/ws/")
    skill_mds = [m["path"] for m in res.matches if m["path"].endswith("SKILL.md")]
    assert len(skill_mds) == len(set(skill_mds)), f"duplicated SKILL.md: {skill_mds}"
    assert len(skill_mds) == 3, skill_mds


def test_glob_domain_skills_root():
    res = _backend().glob("**/*", path="/domain-skills/")
    skill_mds = [m["path"] for m in res.matches if m["path"].endswith("SKILL.md")]
    assert len(skill_mds) == 3, skill_mds


def test_async_als_root_lists_all_packages():
    """回归:DomainSkillsBackend 必须继承 BackendProtocol,否则子 agent 走 async
    文件工具(als/aread/aglob/agrep)时抛 'no attribute als'。

    单测若只调 sync 方法会漏掉这条路径(实测踩坑后补上)。
    """
    import asyncio

    be = _backend()

    async def _run():
        res = await be.als("/domain-skills/")
        assert res.error is None, res.error
        return {e["path"] for e in res.entries}

    assert asyncio.run(_run()) == EXPECTED_PACKAGES


def test_async_aread_skill_md():
    """子 agent SkillsMiddleware 用 aread 读 SKILL.md,验证 async 委托可用。"""
    import asyncio

    be = _backend()

    async def _run():
        res = await be.aread(
            "/domain-skills/dispatch_planning/dispatch-strategy/SKILL.md"
        )
        return (res.file_data or {}).get("content") or ""

    content = asyncio.run(_run())
    assert content.strip(), "SKILL.md content empty"


def test_download_files_skill_md():
    """回归:SkillsMiddleware 用 backend.download_files 拉 SKILL.md 全文。

    DomainSkillsBackend 若缺 download_files,会命中 BackendProtocol 基类默认的
    NotImplementedError(生产实测踩坑:子 agent 加载技能时崩溃)。CompositeBackend
    会先剥 `/domain-skills/` 前缀再传进来,并在返回前把响应 path 还原为完整路径。
    """
    be = _backend()
    res = be.download_files([
        "/domain-skills/dispatch_planning/dispatch-strategy/SKILL.md",
        "/domain-skills/station_data/station-analysis/SKILL.md",
    ])
    assert len(res) == 2
    for r in res:
        assert r.error is None, r.error
        assert r.content and r.content.strip(), f"empty content for {r.path}"


def test_download_files_unknown_pkg_errors():
    """未知包/目录路径返回错误响应而非崩溃。"""
    be = _backend()
    res = be.download_files([
        "/domain-skills/not-a-pkg/foo.md",  # 未知包
        "/domain-skills/station_data",       # 已知包但指向目录本身
    ])
    assert len(res) == 2
    assert all(r.error for r in res), res
