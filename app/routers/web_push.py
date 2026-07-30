"""Admin Web Push subscribe / public VAPID key."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import web_push
from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.rbac import require_permission
from config import DASHBOARD_PATH

router = APIRouter(tags=["web-push"], prefix="/api")


class PushSubscribeBody(BaseModel):
    endpoint: str = Field(..., min_length=8, max_length=2048)
    keys: dict
    expirationTime: Optional[float] = None


def _db_admin_id(db: Session, admin: Admin) -> int:
    dbadmin = crud.get_admin(db, admin.username)
    if dbadmin is None:
        raise HTTPException(status_code=400, detail="Admin not found in database")
    return int(dbadmin.id)


@router.get("/push/vapid-public-key")
def vapid_public_key(_: Admin = Depends(require_permission("billing:read"))):
    """Public VAPID key for PushManager.subscribe (authenticated admins)."""
    try:
        return {"publicKey": web_push.public_vapid_key()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Push unavailable: {exc}") from exc


@router.post("/push/subscribe")
def push_subscribe(
    body: PushSubscribeBody,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    keys = body.keys or {}
    p256dh = str(keys.get("p256dh") or "")
    auth = str(keys.get("auth") or "")
    try:
        web_push.upsert_subscription(
            db,
            admin_id=_db_admin_id(db, admin),
            endpoint=body.endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=(request.headers.get("user-agent") or "")[:512],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/push/unsubscribe")
def push_unsubscribe(
    body: PushSubscribeBody,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    web_push.delete_subscription(
        db, admin_id=_db_admin_id(db, admin), endpoint=body.endpoint
    )
    return {"ok": True}


@router.post("/push/test")
def push_test(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    aid = _db_admin_id(db, admin)
    n = web_push.send_to_admin_ids(
        db,
        [aid],
        title="Shahkar",
        body="اعلان آزمایشی — نوتیفیکیشن و بج آیکون فعال است",
        url=f"{DASHBOARD_PATH.rstrip('/')}/#/billing?billingTab=orders",
        tag="push-test",
        count=max(1, web_push.count_awaiting_card_for_admin(db, aid)),
    )
    return {"ok": True, "sent": n, "count": web_push.count_awaiting_card_for_admin(db, aid)}


@router.get("/push/badge")
def push_badge_count(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    """Unread card approvals waiting for this admin — home-screen badge."""
    aid = _db_admin_id(db, admin)
    return {"count": web_push.count_awaiting_card_for_admin(db, aid)}


@router.post("/push/badge/clear")
def push_badge_clear(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    """Client acknowledges opening the app; returns fresh awaiting count (not forced to 0)."""
    aid = _db_admin_id(db, admin)
    # Badge reflects real queue — clearing only makes sense when queue is empty.
    # Still return current count so the client can setAppBadge accurately.
    return {"count": web_push.count_awaiting_card_for_admin(db, aid)}
