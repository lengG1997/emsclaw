import asyncio
import os
import shortuuid
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any
import time

from loguru import logger
from emsclaw_backend.deepagent.plan_types import PlanStep
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from emsclaw_backend.db.session import AsyncSessionLocal
from emsclaw_backend.db.models import Session as SessionRow

_BASE_WORKSPACE = os.environ.get("WORKSPACE_DIR", "/home/emsclaw")


def _render_planner_md(plan: List[PlanStep]) -> str:
    lines: list[str] = ["# Planner", ""]
    if not plan:
        lines.append("_No plan yet._")
        lines.append("")
        return "\n".join(lines)

    lines.append("## Steps")
    lines.append("")
    for step in plan:
        status = (step.get("status") or "pending").strip()
        checked = "x" if status == "completed" else " "
        tools = ", ".join(step.get("tools") or [])
        suffix = f" (tools: {tools})" if tools else ""
        lines.append(f"- [{checked}] {step['id']} [{status}] {step['content']}{suffix}")
    lines.append("")
    return "\n".join(lines)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


@dataclass
class AgentSession:
    session_id: str
    thread_id: str
    vm_root_dir: Path
    mode: str = "business"
    plan: List[PlanStep] = field(default_factory=list)
    user_id: Optional[str] = None
    model_config: Optional[Dict[str, Any]] = None

    _planner_md_digest: str = field(default="", repr=False)
    events: List[Dict[str, Any]] = field(default_factory=list)
    _is_cancelled: bool = field(default=False, init=False, repr=False)

    title: Optional[str] = None
    status: str = "pending"
    created_at: int = 0
    updated_at: int = 0
    unread_message_count: int = 0
    is_shared: bool = False
    latest_message: str = ""
    latest_message_at: int = 0
    pinned: bool = False
    source: Optional[str] = None

    _shell_sessions: Dict[str, Any] = field(default_factory=dict)

    def cancel(self) -> None:
        self._is_cancelled = True
        logger.info(f"Session {self.session_id} marked as cancelled")

    def reset_cancel(self) -> None:
        self._is_cancelled = False

    def is_cancelled(self) -> bool:
        return getattr(self, "_is_cancelled", False)

    def get_plan(self) -> List[PlanStep]:
        return list(self.plan)

    def set_plan(self, plan: List[PlanStep]) -> None:
        self.plan = list(plan)
        self._sync_planner_md()
        self._persist_update({"plan": self.plan})

    def _sync_planner_md(self) -> None:
        try:
            content = _render_planner_md(self.plan)
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if digest == self._planner_md_digest:
                return
            _atomic_write_text(self.vm_root_dir / "planner.md", content)
            self._planner_md_digest = digest
        except Exception:
            logger.exception("sync planner.md failed for session {}", self.session_id)

    def ls(self, path: str) -> List[Dict[str, object]]:
        """List files under the session workspace directory."""
        if not path.startswith("/"):
            raise ValueError("path must start with '/'")
        full_path = self.vm_root_dir / path.lstrip("/")
        items: List[Dict[str, object]] = []
        if full_path.is_dir():
            for entry in sorted(full_path.iterdir()):
                items.append({
                    "path": str(entry),
                    "is_dir": entry.is_dir(),
                })
        return items

    def _persist_update(self, update_dict: Dict[str, Any]) -> None:
        pass

    async def save(self):
        async with AsyncSessionLocal() as session:
            row = await session.get(SessionRow, self.session_id)
            now = int(time.time())
            if row is None:
                row = SessionRow(id=self.session_id, thread_id=self.thread_id, user_id=self.user_id or "",mode=self.mode,
                                 vm_root_dir=str(self.vm_root_dir),created_at=self.created_at, updated_at=now)
                session.add(row)
            row.mode=self.mode
            row.plan = list(self.plan)
            row.title = self.title or ""
            row.status = self.status
            row.updated_at = now
            row.unread_message_count = self.unread_message_count
            row.is_shared = self.is_shared
            row.latest_message = self.latest_message
            row.latest_message_at = self.latest_message_at
            row.model_config_ = self.model_config or {}
            row.events = list(self.events)
            row.pinned = self.pinned
            row.source = self.source or ""
            await session.commit()

class AgentSessionNotFoundError(KeyError):
    pass


_sessions_lock = asyncio.Lock()
_SESSION_CACHE_MAX = 200
_SESSION_CACHE_TTL = 3600
_sessions: Dict[str, AgentSession] = {}
_sessions_atime: Dict[str, float] = {}


def _evict_stale_sessions() -> None:
    """Remove expired entries when cache exceeds max size (called under lock)."""
    if len(_sessions) <= _SESSION_CACHE_MAX:
        return
    now = time.time()
    expired = [
        sid for sid, ts in _sessions_atime.items()
        if now - ts > _SESSION_CACHE_TTL
    ]
    for sid in expired:
        _sessions.pop(sid, None)
        _sessions_atime.pop(sid, None)
    if len(_sessions) > _SESSION_CACHE_MAX:
        oldest = sorted(_sessions_atime, key=_sessions_atime.get)
        for sid in oldest[: len(_sessions) - _SESSION_CACHE_MAX]:
            _sessions.pop(sid, None)
            _sessions_atime.pop(sid, None)


def _session_workspace(session_id: str) -> Path:
    """Return the workspace directory for a session: /home/emsclaw/{session_id}"""
    return Path(_BASE_WORKSPACE) / session_id


async def async_create_agent_session(
    mode: str = "business",
    user_id: Optional[str] = None,
    model_config: Optional[Dict[str, Any]] = None,
    source: Optional[str] = None,
) -> AgentSession:
    session_id = shortuuid.uuid()
    thread_id = session_id

    vm_root = _session_workspace(session_id)
    vm_root.mkdir(parents=True, exist_ok=True)
    vm_root.chmod(0o777)

    now = int(time.time())
    session = AgentSession(
        session_id=session_id,
        thread_id=thread_id,
        vm_root_dir=vm_root,
        mode=mode,
        user_id=user_id,
        model_config=model_config,
        created_at=now,
        updated_at=now,
        source=source,
    )

    async with AsyncSessionLocal() as s:
        row = SessionRow(id=session_id,thread_id=thread_id,user_id=user_id or "",mode=mode,vm_root_dir=str(vm_root),
                         created_at=now, updated_at=now,status="pending",events=[],plan=[],source=source or "")
        s.add(row)
        await s.commit()

    async with _sessions_lock:
        _sessions[session_id] = session
        _sessions_atime[session_id] = time.time()
        _evict_stale_sessions()

    logger.info(f"Created session {session_id} (workspace={vm_root}, user={user_id})")
    return session


async def async_get_agent_session(session_id: str) -> AgentSession:
    async with _sessions_lock:
        session = _sessions.get(session_id)
        if session:
            _sessions_atime[session_id] = time.time()

    if session:
        return session

    async with AsyncSessionLocal() as session:
        row = await session.get(SessionRow, session_id)

    if not row:
        raise AgentSessionNotFoundError(f"session {session_id} not found")

    vm_root = Path(row.vm_root_dir or str(_session_workspace(session_id)))
    vm_root.mkdir(parents=True, exist_ok=True)
    vm_root.chmod(0o777)

    session = AgentSession(
        session_id=session_id,
        thread_id=row.thread_id,
        vm_root_dir=vm_root,
        mode=row.mode or "business",
        user_id=row.user_id or None,
        model_config=row.model_config_,  # ⚠️ 带下划线
        plan=row.plan or [],
        events=row.events or [],
        title=row.title or None,
        status=row.status or "pending",
        created_at=row.created_at or 0,
        updated_at=row.updated_at or 0,
        unread_message_count=row.unread_message_count or 0,
        is_shared=row.is_shared or False,
        latest_message=row.latest_message or "",
        latest_message_at=row.latest_message_at or 0,
        pinned=row.pinned or False,
        source=row.source or None,
    )

    async with _sessions_lock:
        _sessions[session_id] = session
        _sessions_atime[session_id] = time.time()

    return session


async def async_list_agent_sessions(user_id: Optional[str] = None) -> List[AgentSession]:
    sessions: List[AgentSession] = []

    async with _sessions_lock:
        cached_snapshot=dict(_sessions)
    async with AsyncSessionLocal() as s:
        q=select(SessionRow).where(SessionRow.source != "task")
        if user_id:
            q=q.where(SessionRow.user_id==user_id)
        q= q.order_by(SessionRow.updated_at.desc())
        rows=(await s.execute(q)).scalars().all()

        for row in rows:
            cached = cached_snapshot.get(row.id)
            if cached:
                sessions.append(cached)
                continue
            vm_root = Path(row.vm_root_dir or str(_session_workspace(row.id)))
            session = AgentSession(
                session_id=row.id,
                thread_id=row.thread_id,
                vm_root_dir=vm_root,
                mode=row.mode or "business",
                user_id=row.user_id or None,
                model_config=row.model_config_,  # ⚠️ 带下划线
                title=row.title or None,
                status=row.status or "pending",
                created_at=row.created_at or 0,
                updated_at=row.updated_at or 0,
                unread_message_count=row.unread_message_count or 0,
                is_shared=row.is_shared or False,
                latest_message=row.latest_message or "",
                latest_message_at=row.latest_message_at or 0,
                pinned=row.pinned or False,
                source=row.source or None,
                # events / plan 故意不传：列表视图不加载，保持原行为
            )
            sessions.append(session)

    return sessions


async def async_delete_agent_session(session_id: str) -> None:
    async with AsyncSessionLocal() as session:
        res = await session.execute(delete(SessionRow).where(SessionRow.id == session_id))
        await session.commit()
    if res.rowcount == 0:
        raise AgentSessionNotFoundError(f"session {session_id} not found")

    async with _sessions_lock:
        _sessions.pop(session_id, None)
        _sessions_atime.pop(session_id, None)

    workspace = Path(_BASE_WORKSPACE) / session_id
    if workspace.is_dir():
        import shutil
        try:
            shutil.rmtree(workspace)
            logger.info(f"[Session] Deleted workspace: {workspace}")
        except Exception as exc:
            logger.warning(f"[Session] Failed to delete workspace {workspace}: {exc}")


def create_agent_session(*args, **kwargs):
    raise RuntimeError("Use async_create_agent_session")

def get_agent_session(session_id: str):
    raise RuntimeError("Use async_get_agent_session")

def list_agent_sessions():
    raise RuntimeError("Use async_list_agent_sessions")

def delete_agent_session(session_id: str):
    raise RuntimeError("Use async_delete_agent_session")
