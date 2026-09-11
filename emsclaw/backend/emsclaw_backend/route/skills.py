"""外置 Skills 管理路由。

从 route/sessions.py 拆出。路由路径保持 /sessions 前缀不变（前端无需改）。
内置能力（领域 Agent 内置 skills）只读枚举，外置 skills 可屏蔽/删除/保存。
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path as _Path
from typing import Any, Dict, List, Optional

import httpx
import yaml as _yaml

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select, delete

from emsclaw_backend.db.session import AsyncSessionLocal
from emsclaw_backend.db.models import BlockedSkill
from emsclaw_backend.user.dependencies import require_user, User

from ._common import (
    ApiResponse,
    _EXTERNAL_SKILLS_DIR,
    _BUILTIN_SKILLS_DIR,
    _WORKSPACE_DIR,
    _set_blocked,
    _delete_blocked,
)

router = APIRouter(prefix="/sessions", tags=["skills"])


# ── 内置能力（领域 Agent 内置的 skills）──────────────────────
# 这些不居住在 /app/Skills，而是随 backend 包内各 domain 一起
# 打包，由 AgentRegistry 在 import 时注册。此处把它们也枚举出来，供前端
# 「内置能力一览」只读展示。不可屏蔽/删除。

def _ensure_business_domains_loaded() -> None:
    """确保 business 领域 Agent 已自注册。

    runner 只在首次 chat 时才 import factory，故在此之前 AgentRegistry 可能为空。
    import factory 会触发其顶部的 ``from . import domains`` -> 各 domain 自注册。
    幂等（Python import 缓存）。
    """
    try:
        from emsclaw_backend.deepagent.agents.business import factory  # noqa: F401
    except Exception as e:  # pragma: no cover - 容错：不阻塞外置 skills/tools
        logger.warning("internal capabilities: 无法加载 business factory: %r", e)


def _parse_skill_frontmatter_file(md_file: _Path) -> Dict[str, Any]:
    """从单个 .md 文件（文件型内置 skill）解析 YAML front-matter。

    与 _parse_skill_frontmatter（读 dir/SKILL.md）的区别：这里 .md 文件本身就是 skill。
    name 缺省取文件 stem；若文件名就是 SKILL.md（无业务含义）则回退到域目录名。
    """
    result: Dict[str, Any] = {"name": md_file.stem, "description": ""}
    try:
        text = md_file.read_text(encoding="utf-8", errors="replace")
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if match:
            fm = _yaml.safe_load(match.group(1))
            if isinstance(fm, dict):
                name = fm.get("name")
                if not name and md_file.stem.lower() == "skill":
                    # SKILL.md 无 name -> 用域目录名（grandparent）
                    name = md_file.parent.parent.name
                result["name"] = name or md_file.stem
                result["description"] = fm.get("description", "")
    except Exception:
        pass
    return result


def _collect_internal_skills() -> List[Dict[str, Any]]:
    """收集所有已注册领域 Agent 的内置 skills。

    支持两种 get_skills() 约定：
      - 目录型：返回 [dir]，dir 下每个含 SKILL.md 的子目录是一个 skill（root=子目录）。
      - 文件型：返回 [file.md, ...]，每个 .md 文件本身是一个 skill（root=父目录，files=[文件名]）。

    返回的每个 dict 含 ``root``（Path，用于 _resolve_skill_dir，不发往前端）。
    """
    _ensure_business_domains_loaded()
    try:
        from emsclaw_backend.deepagent.agents.business.registry import AgentRegistry
    except Exception as e:
        logger.warning("internal skills: AgentRegistry 不可用: %r", e)
        return []
    out: List[Dict[str, Any]] = []
    for agent in AgentRegistry.get_all():
        domain = agent.name
        try:
            paths = agent.get_skills() or []
        except Exception as e:
            logger.debug("internal skills: get_skills(%s) failed: %r", domain, e)
            continue
        for p in paths:
            path = _Path(p)
            if path.is_dir():
                for child in sorted(path.iterdir()):
                    if child.name.startswith("."):
                        continue
                    if not child.is_dir() or not (child / "SKILL.md").is_file():
                        continue
                    meta = _parse_skill_frontmatter(child)
                    files = [str(f.relative_to(child)) for f in child.rglob("*") if f.is_file()]
                    out.append({**meta, "files": files, "builtin": True, "domain": domain, "root": child})
            elif path.is_file() and path.suffix.lower() == ".md":
                meta = _parse_skill_frontmatter_file(path)
                out.append({**meta, "files": [path.name], "builtin": True, "domain": domain, "root": path.parent})
    return out


def _list_internal_skills() -> List[Dict[str, Any]]:
    """前端用：去掉 root 字段（绝对路径不外泄）。"""
    return [{k: v for k, v in s.items() if k != "root"} for s in _collect_internal_skills()]


def _internal_skill_root(skill_name: str) -> Optional[_Path]:
    """按名字查找内置 skill 的根目录（供 _resolve_skill_dir 用）。"""
    for s in _collect_internal_skills():
        if s["name"] == skill_name:
            root = s.get("root")
            if root is not None:
                return root
    return None


def _parse_skill_frontmatter(skill_dir: _Path) -> Dict[str, Any]:
    """从 SKILL.md 中解析 YAML front-matter 元数据。"""
    skill_md = skill_dir / "SKILL.md"
    result: Dict[str, Any] = {"name": skill_dir.name, "description": ""}
    if not skill_md.is_file():
        return result
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if match:
            fm = _yaml.safe_load(match.group(1))
            if isinstance(fm, dict):
                result["name"] = fm.get("name", skill_dir.name)
                result["description"] = fm.get("description", "")
    except Exception:
        pass
    return result


def _list_skill_dirs(base_dir: str, builtin: bool = False) -> List[Dict[str, Any]]:
    """列出指定目录中所有合法的 skill。"""
    base = _Path(base_dir)
    if not base.is_dir():
        return []
    skills = []
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if not (child / "SKILL.md").is_file():
            continue
        meta = _parse_skill_frontmatter(child)
        files = [str(f.relative_to(child)) for f in child.rglob("*") if f.is_file()]
        skills.append({**meta, "files": files, "builtin": builtin})
    return skills


def _resolve_skill_dir(skill_name: str) -> Optional[_Path]:
    """在 builtin + external + 内置（领域 Agent）三个来源中查找 skill 目录。

    builtin 优先（覆盖同名外置/内置）。返回 skill 的根目录路径，找不到返回 None。
    """
    for base in (_BUILTIN_SKILLS_DIR, _EXTERNAL_SKILLS_DIR):
        candidate = _Path(base) / skill_name
        if candidate.is_dir():
            return candidate
    # 内置（领域 Agent 内置 skills）--只读，不可屏蔽/删除
    return _internal_skill_root(skill_name)


class SkillBlockRequest(BaseModel):
    blocked: bool = Field(default=True)


@router.get("/skills", response_model=ApiResponse)
async def list_skills(current_user: User = Depends(require_user)) -> ApiResponse:
    """列出所有 skills（内置排前面，不可屏蔽/删除）+ 外置 skills + 领域 Agent 内置 skills。"""
    try:
        builtin = _list_skill_dirs(_BUILTIN_SKILLS_DIR, builtin=True)
        external = _list_skill_dirs(_EXTERNAL_SKILLS_DIR, builtin=False)
        internal = _list_internal_skills()
        # 去重：builtin/external 优先，同名内置跳过
        existing = {s["name"] for s in builtin + external}
        internal = [s for s in internal if s["name"] not in existing]

        async with AsyncSessionLocal() as session:
            q = select(BlockedSkill.skill_name).where(BlockedSkill.user_id == current_user.id)
            blocked_names: set = {name for (name,) in (await session.execute(q)).all()}

        for s in builtin:
            s["blocked"] = False
        for s in external:
            s["blocked"] = s["name"] in blocked_names
        for s in internal:
            s["blocked"] = False  # 领域 Agent 内置 skills 不可屏蔽

        return ApiResponse(data=builtin + external + internal)
    except Exception as exc:
        logger.exception("list_skills failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/skills/{skill_name}/block", response_model=ApiResponse)
async def toggle_block_skill(
    skill_name: str,
    body: SkillBlockRequest,
    current_user: User = Depends(require_user),
) -> ApiResponse:
    """屏蔽或取消屏蔽一个外置 skill。"""
    try:
        await _set_blocked(BlockedSkill, "skill_name", current_user.id, skill_name, body.blocked)
        return ApiResponse(data={"skill_name": skill_name, "blocked": body.blocked})
    except Exception as exc:
        logger.exception("toggle_block_skill failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/skills/{skill_name}", response_model=ApiResponse)
async def delete_skill(
    skill_name: str,
    current_user: User = Depends(require_user),
) -> ApiResponse:
    """彻底删除一个外置 skill 目录。"""
    try:
        skill_path = _Path(_EXTERNAL_SKILLS_DIR) / skill_name
        if not skill_path.is_dir():
            raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' 不存在")
        resolved = skill_path.resolve()
        base_resolved = _Path(_EXTERNAL_SKILLS_DIR).resolve()
        if not str(resolved).startswith(str(base_resolved)):
            raise HTTPException(status_code=403, detail="非法的 skill 路径")
        shutil.rmtree(resolved)
        await _delete_blocked(BlockedSkill, "skill_name", skill_name)
        return ApiResponse(data={"skill_name": skill_name, "deleted": True})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("delete_skill failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class SaveSkillRequest(BaseModel):
    skill_name: str = Field(..., description="要保存的 skill 名称")


@router.post("/{session_id}/skills/save", response_model=ApiResponse)
async def save_skill_from_session(
    session_id: str,
    body: SaveSkillRequest,
    current_user: User = Depends(require_user),
) -> ApiResponse:
    """把 skill 从会话 workspace 复制到永久 Skills 目录。"""
    from emsclaw_backend.deepagent.sessions import async_get_agent_session, AgentSessionNotFoundError
    try:
        session = await async_get_agent_session(session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无访问权限")

        skill_name = body.skill_name.strip()
        if not skill_name or "/" in skill_name or "\\" in skill_name:
            raise HTTPException(status_code=400, detail="非法的 skill 名称")

        # Agent 可能将 skill 写在多种位置，按优先级检查
        candidate_paths = [
            _Path(_WORKSPACE_DIR) / session_id / ".agents" / "skills" / skill_name,
            _Path(_WORKSPACE_DIR) / session_id / "skills" / skill_name,
            _Path(_WORKSPACE_DIR) / session_id / skill_name,
        ]
        src = next(
            (p for p in candidate_paths if p.is_dir() and (p / "SKILL.md").is_file()),
            None,
        )

        dst = _Path(_EXTERNAL_SKILLS_DIR) / skill_name

        if src is None:
            # Agent 可能直接编辑了 /skills/ 目录下的已有 skill（in-place 编辑），
            # 此时 workspace 里没有副本，但 /skills/ 已经是最新版本
            if dst.is_dir() and (dst / "SKILL.md").is_file():
                logger.info(
                    f"[Skills] Skill '{skill_name}' not in workspace but already exists "
                    f"in {dst}, treating as in-place update"
                )
                return ApiResponse(data={"skill_name": skill_name, "saved": True})
            raise HTTPException(
                status_code=404,
                detail=f"在会话 workspace 中找不到 Skill '{skill_name}' "
                       f"(已检查 .agents/skills/、skills/ 和 {skill_name}/)",
            )

        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

        logger.info(f"[Skills] Saved skill '{skill_name}' from session {session_id} to {dst}")
        return ApiResponse(data={"skill_name": skill_name, "saved": True})
    except AgentSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("save_skill_from_session failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/skills/{skill_name}/files", response_model=ApiResponse)
async def list_skill_files(
    skill_name: str,
    path: str = "",
    current_user: User = Depends(require_user),
) -> ApiResponse:
    """列出某个 skill（内置或外置）内部的文件结构。"""
    try:
        skill_path = _resolve_skill_dir(skill_name)
        if skill_path is None:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' 不存在")
        target = skill_path / path if path else skill_path
        target_resolved = target.resolve()
        if not str(target_resolved).startswith(str(skill_path.resolve())):
            raise HTTPException(status_code=403, detail="Invalid path")
        if not target_resolved.is_dir():
            raise HTTPException(status_code=404, detail="目录不存在")
        items = []
        for child in sorted(target_resolved.iterdir()):
            if child.name.startswith("."):
                continue
            rel = str(child.relative_to(skill_path))
            items.append({
                "name": child.name,
                "path": rel,
                "type": "directory" if child.is_dir() else "file",
            })
        return ApiResponse(data=items)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("list_skill_files failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class ReadSkillFileRequest(BaseModel):
    file: str


@router.post("/skills/{skill_name}/read", response_model=ApiResponse)
async def read_skill_file(
    skill_name: str,
    body: ReadSkillFileRequest,
    current_user: User = Depends(require_user),
) -> ApiResponse:
    """读取某个 skill（内置或外置）内的文件内容。"""
    try:
        skill_path = _resolve_skill_dir(skill_name)
        if skill_path is None:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' 不存在")
        file_path = (skill_path / body.file).resolve()
        if not str(file_path).startswith(str(skill_path.resolve())):
            raise HTTPException(status_code=403, detail="非法的文件路径")
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return ApiResponse(data={"file": body.file, "content": content})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("read_skill_file failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/skills/{skill_name}/download")
async def download_skill_file(
    skill_name: str,
    path: str = "",
    current_user: User = Depends(require_user),
) -> FileResponse:
    """下载 skill 内的某个文件（用于图片/PDF/不可预览文件的原始访问）。

    builtin 和 external 都支持；通过 ``?path=`` 指定相对路径，留空则下载 SKILL.md。
    """
    from fastapi import Query
    path = path or ""
    skill_path = _resolve_skill_dir(skill_name)
    if skill_path is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    target = (skill_path / path) if path else (skill_path / "SKILL.md")
    target_resolved = target.resolve()
    if not str(target_resolved).startswith(str(skill_path.resolve())):
        raise HTTPException(status_code=403, detail="非法的路径")
    if not target_resolved.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(
        path=str(target_resolved),
        filename=target_resolved.name,
        media_type="application/octet-stream",
    )
