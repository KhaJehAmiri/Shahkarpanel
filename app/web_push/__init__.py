"""Browser Web Push for admin/reseller panel (card payment alerts)."""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from typing import Any, Iterable, List, Optional, Set

from sqlalchemy.orm import Session

log = logging.getLogger("uvicorn.error")

VAPID_PUBLIC_KEY = "push.vapid_public_key"
VAPID_PRIVATE_KEY = "push.vapid_private_key"
VAPID_SUBJECT = "push.vapid_subject"


def _ps():
    from app import platform_settings as ps

    return ps


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _default_vapid_subject() -> str:
    """Apple rejects mailto:…@*.local — prefer a public https origin."""
    try:
        from config import PANEL_PUBLIC_ADDRESS

        base = (PANEL_PUBLIC_ADDRESS or "").strip().rstrip("/")
        if base.startswith("https://"):
            return base
        if base.startswith("http://"):
            # Push services require https subject when possible.
            return "https://" + base[len("http://") :]
    except Exception:
        pass
    return "mailto:noreply@example.com"


def resolve_vapid_subject() -> str:
    """Return a VAPID subject that Apple / Mozilla accept."""
    ps = _ps()
    sub = (ps.get_str(VAPID_SUBJECT) or "").strip()
    bad = (
        not sub
        or sub.endswith(".local")
        or "@shahkar.local" in sub
        or sub == "mailto:admin@shahkar.local"
    )
    if bad:
        sub = _default_vapid_subject()
        try:
            ps.set_setting(VAPID_SUBJECT, sub)
        except Exception:
            pass
    return sub


def ensure_vapid_keys() -> tuple[str, str]:
    """Return (public, private) VAPID keys; generate once if missing."""
    ps = _ps()
    pub = (ps.get_str(VAPID_PUBLIC_KEY) or "").strip()
    priv = (ps.get_str(VAPID_PRIVATE_KEY) or "").strip()
    # Always heal invalid Apple-rejected subjects.
    resolve_vapid_subject()
    if pub and priv:
        return pub, priv

    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    priv_raw = key.private_numbers().private_value.to_bytes(32, "big")
    from cryptography.hazmat.primitives import serialization

    pub_raw = key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    pub_b64 = _b64url(pub_raw)
    priv_b64 = _b64url(priv_raw)
    ps.set_setting(VAPID_PUBLIC_KEY, pub_b64)
    ps.set_setting(VAPID_PRIVATE_KEY, priv_b64)
    if not (ps.get_str(VAPID_SUBJECT) or "").strip():
        ps.set_setting(VAPID_SUBJECT, _default_vapid_subject())
    return pub_b64, priv_b64


def public_vapid_key() -> str:
    pub, _ = ensure_vapid_keys()
    return pub


def upsert_subscription(
    db: Session,
    *,
    admin_id: int,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: Optional[str] = None,
) -> Any:
    from app.db.models import AdminPushSubscription

    endpoint = (endpoint or "").strip()
    p256dh = (p256dh or "").strip()
    auth = (auth or "").strip()
    if not endpoint or not p256dh or not auth:
        raise ValueError("Invalid push subscription")
    row = (
        db.query(AdminPushSubscription)
        .filter(AdminPushSubscription.endpoint == endpoint)
        .first()
    )
    now = datetime.utcnow()
    if row is None:
        row = AdminPushSubscription(
            admin_id=admin_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=(user_agent or "")[:512] or None,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.admin_id = admin_id
        row.p256dh = p256dh
        row.auth = auth
        row.user_agent = (user_agent or row.user_agent or "")[:512] or None
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return row


def delete_subscription(db: Session, *, admin_id: int, endpoint: str) -> bool:
    from app.db.models import AdminPushSubscription

    endpoint = (endpoint or "").strip()
    row = (
        db.query(AdminPushSubscription)
        .filter(
            AdminPushSubscription.admin_id == admin_id,
            AdminPushSubscription.endpoint == endpoint,
        )
        .first()
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def _send_one(sub, payload: dict, vapid_claims: dict, vapid_private: str) -> str:
    """Return 'ok', 'gone', or 'error'."""
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
        log.warning("web push failed admin=%s status=%s: %s", sub.admin_id, status, exc)
        if status in (404, 410):
            return "gone"
        return "error"
    except Exception as exc:
        log.warning("web push error admin=%s: %s", sub.admin_id, exc)
        return "error"


def count_awaiting_card_for_admin(db: Session, admin_id: int) -> int:
    """How many card payments wait for this admin (app icon badge)."""
    from app.db.models import PaymentIntent

    return (
        db.query(PaymentIntent)
        .filter(
            PaymentIntent.admin_id == int(admin_id),
            PaymentIntent.provider == "card",
            PaymentIntent.status == "awaiting_review",
        )
        .count()
    )


def send_to_admin_ids(
    db: Session,
    admin_ids: Iterable[int],
    *,
    title: str,
    body: str,
    url: str = "/dashboard/#/billing",
    tag: str = "card-payment",
    count: Optional[int] = None,
) -> int:
    """Send a notification to all browser subscriptions for the given admins.

    ``count`` is the home-screen app badge number (Telegram-style). When omitted,
    each admin gets their own awaiting-review count.
    """
    from app.db.models import AdminPushSubscription

    ids: Set[int] = {int(a) for a in admin_ids if a}
    if not ids:
        return 0
    try:
        _, priv = ensure_vapid_keys()
    except Exception as exc:
        log.warning("web push skipped (no VAPID): %s", exc)
        return 0
    ps = _ps()
    subject = resolve_vapid_subject()
    claims = {"sub": subject}
    rows: List[Any] = (
        db.query(AdminPushSubscription)
        .filter(AdminPushSubscription.admin_id.in_(list(ids)))
        .all()
    )
    # Group subscriptions by admin so each gets the correct badge count.
    by_admin: dict[int, list] = {}
    for sub in rows:
        by_admin.setdefault(int(sub.admin_id), []).append(sub)

    sent = 0
    stale = []
    for aid, subs in by_admin.items():
        badge = int(count) if count is not None else count_awaiting_card_for_admin(db, aid)
        payload = {
            "title": title,
            "body": body,
            "url": url,
            "tag": tag,
            "count": max(0, badge),
        }
        for sub in subs:
            result = _send_one(sub, payload, claims, priv)
            if result == "ok":
                sent += 1
            elif result == "gone":
                stale.append(sub)
    for sub in stale:
        try:
            db.delete(sub)
        except Exception:
            pass
    if stale:
        db.commit()
    return sent


def notify_card_payment_submitted(db: Session, intent) -> None:
    """Push to the owning reseller only (or sudos when the owner is sudo).

    Reseller customers must not notify the master — only that reseller.
    Includes Telegram-style home-screen badge count.
    """
    from app.db.models import Admin

    try:
        targets: Set[int] = set()
        owner = None
        if getattr(intent, "admin_id", None):
            owner = db.query(Admin).filter(Admin.id == int(intent.admin_id)).first()
            if owner is not None:
                targets.add(int(owner.id))
        if owner is None or bool(getattr(owner, "is_sudo", False)):
            for row in db.query(Admin.id).filter(Admin.is_sudo.is_(True)).all():
                targets.add(int(row[0] if isinstance(row, tuple) else row.id))
        if not targets:
            return
        extra = intent.extra or {}
        uname = (
            extra.get("new_username")
            or extra.get("target_username")
            or extra.get("created_username")
            or ""
        )
        amount = int(intent.amount or 0)
        title = "پرداخت کارت‌به‌کارت جدید"
        body = f"مبلغ {amount:,} — {uname or f'#{intent.id}'} در انتظار تأیید"
        send_to_admin_ids(
            db,
            targets,
            title=title,
            body=body,
            url="/dashboard/#/billing?billingTab=orders",
            tag=f"card-payment-{intent.id}",
        )
    except Exception as exc:
        log.warning("card payment push notify failed: %s", exc)


def notify_admin_badge_sync(db: Session, admin_id: int) -> None:
    """Refresh home-screen badge after approve/reject (silent-ish status ping)."""
    try:
        n = count_awaiting_card_for_admin(db, admin_id)
        if n <= 0:
            title = "صف تأیید خالی شد"
            body = "پرداخت معلقی باقی نمانده"
        else:
            title = "صف تأیید به‌روز شد"
            body = f"{n} پرداخت در انتظار تأیید"
        send_to_admin_ids(
            db,
            [int(admin_id)],
            title=title,
            body=body,
            url="/dashboard/#/billing?billingTab=orders",
            tag="sk-badge-sync",
            count=n,
        )
    except Exception as exc:
        log.warning("admin badge sync failed: %s", exc)
