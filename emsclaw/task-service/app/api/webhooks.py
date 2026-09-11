"""Webhook CRUD and test API."""
import time
from typing import List

import shortuuid
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task, Webhook
from app.db.session import get_session
from app.models.webhook import (
    WEBHOOK_TYPES,
    WebhookCreate,
    WebhookOut,
    WebhookUpdate,
    webhook_doc_to_out,
)
from app.services.webhook_sender import send_test_message

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("", response_model=WebhookOut)
async def create_webhook(body: WebhookCreate, session: AsyncSession = Depends(get_session)) -> WebhookOut:
    if body.type not in WEBHOOK_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid type. Must be one of: {', '.join(sorted(WEBHOOK_TYPES))}")
    if not body.url.strip():
        raise HTTPException(status_code=400, detail="URL is required")
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    now = int(time.time())
    wid = shortuuid.uuid()
    row = Webhook(
        id=wid,
        name=body.name.strip(),
        type=body.type,
        url=body.url.strip(),
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    logger.info(f"Webhook created: {wid} type={body.type}")
    return webhook_doc_to_out(row)


@router.get("", response_model=List[WebhookOut])
async def list_webhooks(session: AsyncSession = Depends(get_session)) -> List[WebhookOut]:
    q = select(Webhook).order_by(Webhook.created_at.desc())
    rows = (await session.execute(q)).scalars().all()
    return [webhook_doc_to_out(r) for r in rows]


@router.get("/{webhook_id}", response_model=WebhookOut)
async def get_webhook(webhook_id: str, session: AsyncSession = Depends(get_session)) -> WebhookOut:
    row = await session.get(Webhook, webhook_id)
    if not row:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return webhook_doc_to_out(row)


@router.put("/{webhook_id}", response_model=WebhookOut)
async def update_webhook(webhook_id: str, body: WebhookUpdate, session: AsyncSession = Depends(get_session)) -> WebhookOut:
    row = await session.get(Webhook, webhook_id)
    if not row:
        raise HTTPException(status_code=404, detail="Webhook not found")
    row.updated_at = int(time.time())
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="Name is required")
        row.name = body.name.strip()
    if body.type is not None:
        if body.type not in WEBHOOK_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid type. Must be one of: {', '.join(sorted(WEBHOOK_TYPES))}")
        row.type = body.type
    if body.url is not None:
        if not body.url.strip():
            raise HTTPException(status_code=400, detail="URL is required")
        row.url = body.url.strip()
    await session.commit()
    return webhook_doc_to_out(row)


@router.delete("/{webhook_id}")
async def delete_webhook(webhook_id: str, session: AsyncSession = Depends(get_session)) -> None:
    row = await session.get(Webhook, webhook_id)
    if not row:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await session.delete(row)
    # $pull: remove this webhook_id from every task.webhook_ids JSONB list.
    # Fetch candidate tasks and reassign filtered lists (must reassign whole list).
    tasks = (await session.execute(select(Task))).scalars().all()
    for t in tasks:
        ids = t.webhook_ids or []
        if webhook_id in ids:
            t.webhook_ids = [w for w in ids if w != webhook_id]
    await session.commit()
    logger.info(f"Webhook deleted: {webhook_id}, cleaned from tasks")


class TestWebhookBody(BaseModel):
    webhook_id: str = ""
    webhook_name: str = ""


@router.post("/{webhook_id}/test")
async def test_webhook(webhook_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    row = await session.get(Webhook, webhook_id)
    if not row:
        raise HTTPException(status_code=404, detail="Webhook not found")
    ok, message = await send_test_message(
        webhook_type=row.type or "feishu",
        webhook_url=row.url or "",
        webhook_name=row.name or "",
    )
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message}
