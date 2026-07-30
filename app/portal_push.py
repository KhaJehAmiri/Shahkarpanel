"""Web Push for portal end-users (payment status, renewals) + app badge."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Iterable, List, Optional, Set

from sqlalchemy.orm import Session

log = logging.getLogger("uvicorn.error")


def _ps():
    from app import platform_settings as ps

    return ps


def upsert_subscription(
    db: Session,
    *,
    user_id: int,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: Optional[str] = None,
) -> Any:
    from app.db.models import PortalPushSubscription

    endpoint = (endpoint or "").strip()
    p256dh = (p256dh or "").strip()
    auth = (auth or "").strip()
    if not endpoint or not p256dh or not auth:
        raise ValueError("Invalid push subscription")
    row = (
        db.query(PortalPushSubscription)
        .filter(PortalPushSubscription.endpoint == endpoint)
        .first()
    )
    now = datetime.utcnow()
    if row is None:
        row = PortalPushSubscription(
            user_id=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=(user_agent or "")[:512] or None,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.user_id = user_id
        row.p256dh = p256dh
        row.auth = auth
        row.user_agent = (user_agent or row.user_agent or "")[:512] or None
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return row


def delete_subscription(db: Session, *, user_id: int, endpoint: str) -> bool:
    from app.db.models import PortalPushSubscription

    row = (
        db.query(PortalPushSubscription)
        .filter(
            PortalPushSubscription.user_id == user_id,
            PortalPushSubscription.endpoint == (endpoint or "").strip(),
        )
        .first()
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def get_portal_unread(db: Session, user_id: int) -> int:
    from app.db.models import User

    row = db.query(User.portal_unread).filter(User.id == int(user_id)).first()
    if row is None:
        return 0
    val = row[0] if isinstance(row, tuple) else row
    try:
        return max(0, int(val or 0))
    except (TypeError, ValueError):
        return 0


def bump_portal_unread(db: Session, user_id: int, delta: int = 1) -> int:
    from app.db.models import User

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        return 0
    cur = int(getattr(user, "portal_unread", 0) or 0)
    user.portal_unread = max(0, cur + int(delta))
    db.commit()
    return int(user.portal_unread)


def clear_portal_unread(db: Session, user_id: int) -> int:
    from app.db.models import User

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        return 0
    user.portal_unread = 0
    db.commit()
    return 0


def _send_one(sub, payload: dict, vapid_claims: dict, vapid_private: str) -> str:
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=vapid_private,
            vapid_claims=vapid_claims,
            ttl=60 * 60 * 12,
        )
        return "ok"
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            return "gone"
        return "error"
    except Exception:
        return "error"


def send_to_user_ids(
    db: Session,
    user_ids: Iterable[int],
    *,
    title: str,
    body: str,
    url: str = "/portal/?tab=history",
    tag: str = "portal",
    count: Optional[int] = None,
    bump: bool = True,
) -> int:
    from app.db.models import PortalPushSubscription
    from app.web_push import ensure_vapid_keys

    ids: Set[int] = {int(u) for u in user_ids if u}
    if not ids:
        return 0
    try:
        _, priv = ensure_vapid_keys()
    except Exception as exc:
        log.warning("portal push skipped: %s", exc)
        return 0
    from app.web_push import resolve_vapid_subject

    subject = resolve_vapid_subject()
    claims = {"sub": subject}

    rows: List[Any] = (
        db.query(PortalPushSubscription)
        .filter(PortalPushSubscription.user_id.in_(list(ids)))
        .all()
    )
    by_user: dict[int, list] = {}
    for sub in rows:
        by_user.setdefault(int(sub.user_id), []).append(sub)

    sent = 0
    stale = []
    for uid, subs in by_user.items():
        badge = count
        if badge is None:
            if bump:
                badge = bump_portal_unread(db, uid, 1)
            else:
                badge = get_portal_unread(db, uid)
        payload = {
            "title": title,
            "body": body,
            "url": url,
            "tag": tag,
            "count": max(0, int(badge or 0)),
        }
        for sub in subs:
            result = _send_one(sub, payload, claims, priv)
            if result == "ok":
                sent += 1
            elif result == "gone":
                stale.append(sub)
    # Users with no subscription still get unread bumped when bump=True & count is None
    if bump and count is None:
        for uid in ids:
            if uid not in by_user:
                bump_portal_unread(db, uid, 1)
    for sub in stale:
        try:
            db.delete(sub)
        except Exception:
            pass
    if stale:
        db.commit()
    return sent


def notify_portal_payment(
    db: Session,
    intent,
    *,
    approved: Optional[bool] = None,
    event: Optional[str] = None,
) -> None:
    """Best-effort push to the portal user with a detailed transaction message."""
    try:
        extra = intent.extra or {}
        uid = extra.get("portal_user_id") or getattr(intent, "user_id", None)
        if not uid:
            return
        # Resolve plan name for the message
        plan_name = extra.get("plan_name")
        if not plan_name and getattr(intent, "plan_id", None):
            try:
                from app.db import crud

                plan = crud.get_plan_by_id(db, intent.plan_id)
                if plan:
                    plan_name = plan.name
            except Exception:
                pass

        if event is None:
            if approved is True:
                event = "approved"
            elif approved is False:
                event = "rejected"
            else:
                event = None

        from app.portal_tx import attach_tx_message, build_tx_message

        title, body, _lines = build_tx_message(intent, plan_name=plan_name, event=event)
        # Keep snapshot in sync with what we push
        try:
            attach_tx_message(intent, plan_name=plan_name, event=event)
            db.commit()
        except Exception:
            pass

        tag = f"pay-{event or intent.status}-{intent.id}"
        send_to_user_ids(
            db,
            [int(uid)],
            title=title,
            body=body,
            url="/portal/?tab=history&pay=status",
            tag=tag,
            bump=True,
        )
    except Exception as exc:
        log.warning("portal payment push failed: %s", exc)
