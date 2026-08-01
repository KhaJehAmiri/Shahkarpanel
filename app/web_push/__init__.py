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


def panel_url(route: str = "billing", query: str = "") -> str:
    """Absolute panel path with hash route (works with custom DASHBOARD_PATH)."""
    from app.middleware.dashboard_path import custom_dashboard_path

    base = custom_dashboard_path().rstrip("/")
    frag = f"#/{route.lstrip('/')}"
    q = (query or "").strip()
    if q:
        frag += q if q.startswith("?") else f"?{q}"
    return f"{base}/{frag}"


def count_pending_invoices_for_admin(db: Session, admin_id: int) -> int:
    from app.db.models import Admin, Invoice

    admin = db.query(Admin).filter(Admin.id == int(admin_id)).first()
    q = db.query(Invoice).filter(Invoice.status == "pending")
    if admin is None or not bool(getattr(admin, "is_sudo", False)):
        q = q.filter(Invoice.admin_id == int(admin_id))
    return q.count()


def count_awaiting_card_for_admin(db: Session, admin_id: int) -> int:
    """How many card payments wait for this admin (orders queue only)."""
    from sqlalchemy import and_, or_

    from app.db.models import Admin, PaymentIntent

    admin = db.query(Admin).filter(Admin.id == int(admin_id)).first()
    q = db.query(PaymentIntent).filter(
        PaymentIntent.provider == "card",
        PaymentIntent.status == "awaiting_review",
    )
    if admin is not None and bool(getattr(admin, "is_sudo", False)):
        # Master: own portal card orders + reseller wallet top-ups only.
        sudo_ids = [int(r[0]) for r in db.query(Admin.id).filter(Admin.is_sudo.is_(True)).all()]
        q = q.filter(
            or_(
                and_(
                    PaymentIntent.kind.in_(("portal_renew", "portal_purchase")),
                    PaymentIntent.admin_id.in_(sudo_ids or [-1]),
                ),
                PaymentIntent.kind == "topup",
            )
        )
    else:
        # Reseller reviews only their portal card purchases (not their own top-ups).
        q = q.filter(
            PaymentIntent.admin_id == int(admin_id),
            PaymentIntent.kind.in_(("portal_renew", "portal_purchase")),
        )
    return q.count()


def count_attention_for_admin(db: Session, admin_id: int) -> int:
    """Home-screen badge = awaiting card orders + unpaid invoices (matches sidebar)."""
    return count_awaiting_card_for_admin(db, admin_id) + count_pending_invoices_for_admin(
        db, admin_id
    )


def send_to_admin_ids(
    db: Session,
    admin_ids: Iterable[int],
    *,
    title: str,
    body: str,
    url: Optional[str] = None,
    tag: str = "sk-push",
    count: Optional[int] = None,
) -> int:
    """Send a notification to all browser subscriptions for the given admins.

    ``count`` is the home-screen app badge number (Telegram-style). When omitted,
    each admin gets their own attention count (orders + invoices).
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
    subject = resolve_vapid_subject()
    claims = {"sub": subject}
    rows: List[Any] = (
        db.query(AdminPushSubscription)
        .filter(AdminPushSubscription.admin_id.in_(list(ids)))
        .all()
    )
    by_admin: dict[int, list] = {}
    for sub in rows:
        by_admin.setdefault(int(sub.admin_id), []).append(sub)

    target_url = url or panel_url("billing")
    sent = 0
    stale = []
    for aid, subs in by_admin.items():
        badge = int(count) if count is not None else count_attention_for_admin(db, aid)
        payload = {
            "title": title,
            "body": body,
            "url": target_url,
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
    """Push notify who must review this card payment.

    - Portal purchase/renew: owning reseller (or sudos when owner is sudo).
    - Wallet top-up: all platform sudos (never the reseller who submitted).
    """
    from app.db.models import Admin

    try:
        targets: Set[int] = set()
        kind = getattr(intent, "kind", None) or ""
        if kind == "topup":
            for row in db.query(Admin.id).filter(Admin.is_sudo.is_(True)).all():
                targets.add(int(row[0] if isinstance(row, tuple) else row.id))
            owner = None
            if getattr(intent, "admin_id", None):
                owner = db.query(Admin).filter(Admin.id == int(intent.admin_id)).first()
            amount = int(intent.amount or 0)
            who = (owner.username if owner else None) or f"#{intent.id}"
            title = "شارژ کیف‌پول نماینده"
            body = f"مبلغ {amount:,} — {who} در انتظار تأیید"
            url = panel_url("billing", "billingTab=orders")
            tag = f"card-topup-{intent.id}"
        else:
            owner = None
            if getattr(intent, "admin_id", None):
                owner = db.query(Admin).filter(Admin.id == int(intent.admin_id)).first()
                if owner is not None:
                    targets.add(int(owner.id))
            if owner is None or bool(getattr(owner, "is_sudo", False)):
                for row in db.query(Admin.id).filter(Admin.is_sudo.is_(True)).all():
                    targets.add(int(row[0] if isinstance(row, tuple) else row.id))
            extra = intent.extra or {}
            uname = (
                extra.get("new_username")
                or extra.get("target_username")
                or extra.get("created_username")
                or ""
            )
            amount = int(intent.amount or 0)
            title = "سفارش جدید — پرداخت کارت‌به‌کارت"
            body = f"مبلغ {amount:,} — {uname or f'#{intent.id}'} در انتظار تأیید"
            url = panel_url("billing", "billingTab=orders")
            tag = f"card-payment-{intent.id}"
        if not targets:
            return
        send_to_admin_ids(
            db,
            targets,
            title=title,
            body=body,
            url=url,
            tag=tag,
        )
    except Exception as exc:
        log.warning("card payment push notify failed: %s", exc)


def notify_topup_result(
    db: Session,
    intent,
    *,
    approved: bool,
    reason: Optional[str] = None,
) -> None:
    """Notify the reseller who submitted a wallet top-up (approve / reject)."""
    try:
        if getattr(intent, "kind", None) != "topup":
            return
        aid = getattr(intent, "admin_id", None)
        if not aid:
            return
        amount = int(intent.amount or 0)
        if approved:
            title = "شارژ کیف‌پول تأیید شد"
            body = f"مبلغ {amount:,} به کیف‌پول شما اضافه شد"
        else:
            title = "شارژ کیف‌پول رد شد"
            why = (reason or "").strip()
            body = f"مبلغ {amount:,} تأیید نشد"
            if why:
                body = f"{body} — {why}"
        send_to_admin_ids(
            db,
            [int(aid)],
            title=title,
            body=body,
            url=panel_url("billing", "billingTab=transactions"),
            tag=f"topup-result-{intent.id}-{'ok' if approved else 'no'}",
        )
    except Exception as exc:
        log.warning("topup result push failed: %s", exc)


def notify_invoice_created(db: Session, invoice) -> None:
    """Notify the reseller when a new unpaid invoice is issued."""
    try:
        aid = getattr(invoice, "admin_id", None)
        if not aid:
            return
        amount = int(invoice.amount or 0)
        note = (getattr(invoice, "description", None) or "").strip()
        title = "فاکتور جدید"
        body = f"مبلغ {amount:,} — فاکتور #{invoice.id}"
        if note:
            body = f"{body} — {note}"
        send_to_admin_ids(
            db,
            [int(aid)],
            title=title,
            body=body,
            url=panel_url("billing", "billingTab=invoices"),
            tag=f"invoice-{invoice.id}",
        )
    except Exception as exc:
        log.warning("invoice push notify failed: %s", exc)


def notify_admin_badge_sync(db: Session, admin_id: int) -> None:
    """Refresh home-screen badge after approve/reject without a noisy toast."""
    try:
        n = count_attention_for_admin(db, admin_id)
        # Silent badge-only update via a short notification that OS still delivers.
        if n <= 0:
            title = "شاهکار"
            body = "صف مالی به‌روز شد — مورد معلقی نیست"
        else:
            title = "شاهکار"
            body = f"{n} مورد نیازمند توجه در بخش مالی"
        send_to_admin_ids(
            db,
            [int(admin_id)],
            title=title,
            body=body,
            url=panel_url("billing"),
            tag="sk-badge-sync",
            count=n,
        )
    except Exception as exc:
        log.warning("admin badge sync failed: %s", exc)
