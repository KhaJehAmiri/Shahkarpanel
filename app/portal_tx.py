"""Portal payment transactions — message-style details for UI and push."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

# Iran Standard Time (no DST)
_TEHRAN = timezone(timedelta(hours=3, minutes=30))

PROVIDER_LABELS_FA = {
    "card": "کارت‌به‌کارت",
    "centralpay": "درگاه پرداخت",
    "stripe": "Stripe",
    "demo": "آزمایشی",
}

KIND_LABELS_FA = {
    "portal_renew": "تمدید اشتراک",
    "portal_purchase": "خرید اکانت",
}

STATUS_LABELS_FA = {
    "pending": "در انتظار پرداخت",
    "awaiting_review": "در انتظار تأیید",
    "completed": "تأیید / موفق",
    "rejected": "رد شده",
    "failed": "ناموفق",
    "cancelled": "لغو شده",
    "expired": "منقضی‌شده",
}


def _digits_fa(s: str) -> str:
    return s.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def format_amount_fa(amount: int) -> str:
    n = int(amount or 0)
    raw = f"{n:,}".replace(",", "٬")
    return _digits_fa(raw)


def provider_label_fa(provider: str) -> str:
    return PROVIDER_LABELS_FA.get((provider or "").strip().lower(), provider or "—")


def kind_label_fa(kind: str, action: Optional[str] = None) -> str:
    if action == "purchase" or kind == "portal_purchase":
        return KIND_LABELS_FA["portal_purchase"]
    if action == "renew" or kind == "portal_renew":
        return KIND_LABELS_FA["portal_renew"]
    return KIND_LABELS_FA.get(kind or "", kind or "تراکنش")


def status_label_fa(status: str) -> str:
    return STATUS_LABELS_FA.get((status or "").strip().lower(), status or "—")


def _to_tehran(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_TEHRAN)


def format_datetime_fa(dt: Optional[datetime]) -> Tuple[str, str]:
    """Return (date, time) in Persian digits, Asia/Tehran."""
    local = _to_tehran(dt)
    if local is None:
        return "—", "—"
    date_s = _digits_fa(local.strftime("%Y/%m/%d"))
    time_s = _digits_fa(local.strftime("%H:%M"))
    return date_s, time_s


def intent_account_name(intent) -> str:
    extra = intent.extra or {}
    return str(
        extra.get("new_username")
        or extra.get("created_username")
        or extra.get("target_username")
        or ""
    ).strip()


def build_tx_message(
    intent,
    *,
    plan_name: Optional[str] = None,
    event: Optional[str] = None,
) -> Tuple[str, str, List[str]]:
    """Build (title, body, detail_lines) for push + portal message UI.

    event: approved | rejected | submitted | completed | None (derive from status)
    """
    status = (intent.status or "").strip().lower()
    if event is None:
        if status == "completed":
            event = "approved" if intent.provider == "card" else "completed"
        elif status == "rejected":
            event = "rejected"
        elif status == "awaiting_review":
            event = "submitted"
        elif status == "expired":
            event = "expired"
        else:
            event = status or "pending"

    if event == "approved":
        title = "تراکنش تأیید شد"
    elif event == "rejected":
        title = "تراکنش رد شد"
    elif event == "submitted":
        title = "تراکنش ثبت شد"
    elif event == "completed":
        title = "تراکنش موفق"
    elif event == "failed":
        title = "تراکنش ناموفق"
    elif event == "expired":
        title = "تراکنش منقضی شد"
    else:
        title = "تراکنش شما"

    extra = intent.extra or {}
    action = extra.get("action")
    amount_s = format_amount_fa(int(intent.amount or 0))
    method = provider_label_fa(intent.provider or "")
    kind = kind_label_fa(intent.kind or "", action)
    account = intent_account_name(intent)
    when = intent.completed_at or intent.created_at
    if event == "submitted" and extra.get("submitted_at"):
        try:
            when = datetime.fromisoformat(str(extra["submitted_at"]).replace("Z", "+00:00"))
        except Exception:
            pass
    if event == "rejected" and extra.get("rejected_at"):
        try:
            when = datetime.fromisoformat(str(extra["rejected_at"]).replace("Z", "+00:00"))
        except Exception:
            pass
    date_s, time_s = format_datetime_fa(when if isinstance(when, datetime) else intent.created_at)
    st_label = status_label_fa(status)

    lines: List[str] = [
        f"مبلغ: {amount_s} تومان",
        f"روش پرداخت: {method}",
        f"نوع: {kind}",
    ]
    if plan_name:
        lines.append(f"پلن: {plan_name}")
    if account:
        lines.append(f"اکانت: {account}")
    lines.append(f"تاریخ: {date_s}")
    lines.append(f"ساعت: {time_s}")
    lines.append(f"وضعیت: {st_label}")
    if event == "rejected" and extra.get("reject_reason"):
        lines.append(f"دلیل: {extra['reject_reason']}")

    body = "\n".join(lines)
    return title, body, lines


def attach_tx_message(intent, *, plan_name: Optional[str] = None, event: Optional[str] = None) -> dict:
    """Persist message snapshot on intent.extra for the transactions feed."""
    title, body, lines = build_tx_message(intent, plan_name=plan_name, event=event)
    extra = dict(intent.extra or {})
    extra["tx_title"] = title
    extra["tx_body"] = body
    extra["tx_lines"] = lines
    extra["tx_event"] = event or intent.status
    intent.extra = extra
    return extra


def list_transactions_for_portal_user(db: Session, owner, *, limit: int = 50) -> List[Any]:
    """Payment intents belonging to this portal login (own + child accounts)."""
    from app.db.models import PaymentIntent
    from app.portal import list_owned_accounts

    owned = list_owned_accounts(db, owner)
    ids = sorted({int(u.id) for u in owned})
    if not ids:
        return []
    q = (
        db.query(PaymentIntent)
        .filter(
            PaymentIntent.kind.in_(("portal_renew", "portal_purchase")),
            PaymentIntent.user_id.in_(ids),
        )
        .order_by(PaymentIntent.id.desc())
        .limit(max(1, min(int(limit), 200)))
    )
    return q.all()


def get_tx_read_ids(owner) -> Set[int]:
    raw = getattr(owner, "portal_tx_reads", None) or []
    out: Set[int] = set()
    if not isinstance(raw, (list, tuple)):
        return out
    for item in raw:
        try:
            out.add(int(item))
        except (TypeError, ValueError):
            continue
    return out


def sync_portal_unread_from_txs(db: Session, owner, intents: Optional[List[Any]] = None) -> int:
    """Keep users.portal_unread aligned with unread transaction messages."""
    if intents is None:
        intents = list_transactions_for_portal_user(db, owner, limit=50)
    reads = get_tx_read_ids(owner)
    unread = sum(1 for i in intents if int(i.id) not in reads)
    owner.portal_unread = max(0, int(unread))
    db.add(owner)
    db.commit()
    return int(owner.portal_unread)


def mark_transaction_read(db: Session, owner, payment_id: int) -> dict:
    """Mark one payment intent as read for this portal login. Returns counts."""
    from app.db.models import PaymentIntent
    from app.portal import list_owned_accounts

    owned_ids = {int(u.id) for u in list_owned_accounts(db, owner)}
    intent = db.query(PaymentIntent).filter(PaymentIntent.id == int(payment_id)).first()
    if intent is None or intent.kind not in ("portal_renew", "portal_purchase"):
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Transaction not found")
    extra = intent.extra or {}
    allowed = int(intent.user_id or 0) in owned_ids or int(extra.get("portal_user_id") or 0) == int(
        owner.id
    )
    if not allowed:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Transaction not found")

    reads = get_tx_read_ids(owner)
    pid = int(intent.id)
    if pid not in reads:
        reads.add(pid)
        # Cap stored ids to keep JSON small
        ordered = sorted(reads, reverse=True)[:300]
        owner.portal_tx_reads = ordered
        db.add(owner)
        db.commit()
        db.refresh(owner)

    intents = list_transactions_for_portal_user(db, owner, limit=50)
    reads = get_tx_read_ids(owner)
    unread = sum(1 for i in intents if int(i.id) not in reads)
    read_n = sum(1 for i in intents if int(i.id) in reads)
    owner.portal_unread = max(0, int(unread))
    db.add(owner)
    db.commit()
    return {
        "id": pid,
        "unread": False,
        "unread_count": unread,
        "read_count": read_n,
    }
