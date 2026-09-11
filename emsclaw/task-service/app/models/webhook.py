"""Webhook models for notification channels (Feishu, DingTalk, WeCom)."""
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


class WebhookCreate(BaseModel):
    name: str = Field(..., description="Webhook display name")
    type: str = Field(..., description="feishu | dingtalk | wecom")
    url: str = Field(..., description="Webhook URL")


class WebhookUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    url: Optional[str] = None


class WebhookOut(BaseModel):
    id: str
    name: str
    type: str
    url: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


WEBHOOK_TYPES = {"feishu", "dingtalk", "wecom"}


def _epoch_to_dt(ts: Any) -> Optional[datetime]:
    """Convert an epoch-second int (or falsy) to an aware UTC datetime."""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _row_id(row: Any) -> str:
    """Return a row's id as a plain string (already a str for ORM rows)."""
    rid = getattr(row, "id", None)
    if rid is None:
        return ""
    if hasattr(rid, "hex"):
        return str(rid)
    return str(rid)


def webhook_doc_to_out(doc: Any) -> WebhookOut:
    """Convert a Webhook ORM row (or compatible mapping) to WebhookOut."""
    if isinstance(doc, dict):
        wid = doc.get("_id", doc.get("id"))
        if hasattr(wid, "hex"):
            wid = str(wid)
        return WebhookOut(
            id=str(wid) if wid is not None else "",
            name=doc.get("name", ""),
            type=doc.get("type", "feishu"),
            url=doc.get("url", ""),
            created_at=doc.get("created_at"),
            updated_at=doc.get("updated_at"),
        )
    # ORM row path: id is already a string; timestamps are epoch-second ints.
    return WebhookOut(
        id=_row_id(doc),
        name=getattr(doc, "name", "") or "",
        type=getattr(doc, "type", "feishu") or "feishu",
        url=getattr(doc, "url", "") or "",
        created_at=_epoch_to_dt(getattr(doc, "created_at", None)),
        updated_at=_epoch_to_dt(getattr(doc, "updated_at", None)),
    )
