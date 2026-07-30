"""Gateway (PSP) income rollups from completed PaymentIntent rows."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import Admin, PaymentIntent, Plan, User
from app import platform_settings as ps

GATEWAY_PROVIDERS = frozenset({"centralpay", "stripe", "demo"})
PORTAL_KINDS = frozenset({"portal_renew", "portal_purchase"})
ALL_KINDS = frozenset({"portal_renew", "portal_purchase", "topup"})


def _day_bounds(now: Optional[datetime] = None) -> tuple[datetime, datetime, datetime, datetime]:
    """Return (today_start, yesterday_start, week_start, now)."""
    now = now or datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week = today - timedelta(days=6)
    return today, yesterday, week, now


def _sum_amount(rows: List[PaymentIntent]) -> int:
    return int(sum(int(r.amount or 0) for r in rows))


def _in_range(rows: List[PaymentIntent], start: datetime, end: Optional[datetime] = None) -> List[PaymentIntent]:
    out = []
    for r in rows:
        ts = r.completed_at or r.created_at
        if ts is None:
            continue
        if ts < start:
            continue
        if end is not None and ts >= end:
            continue
        out.append(r)
    return out


def _payment_row(db: Session, intent: PaymentIntent) -> Dict[str, Any]:
    username = None
    if intent.user_id:
        user = db.query(User).filter(User.id == intent.user_id).first()
        if user:
            username = user.username
    plan_name = None
    if intent.plan_id:
        plan = db.query(Plan).filter(Plan.id == intent.plan_id).first()
        if plan:
            plan_name = plan.name
    extra = intent.extra or {}
    return {
        "id": intent.id,
        "kind": intent.kind,
        "provider": intent.provider,
        "amount": int(intent.amount or 0),
        "status": intent.status,
        "admin_id": intent.admin_id,
        "username": username or extra.get("created_username") or extra.get("target_username") or extra.get("new_username"),
        "plan_id": intent.plan_id,
        "plan_name": plan_name,
        "reference": extra.get("centralpay_reference_id") or extra.get("stripe_session_id"),
        "card": extra.get("centralpay_card"),
        "created_at": intent.created_at,
        "completed_at": intent.completed_at,
    }


def compute_gateway_income(
    db: Session,
    *,
    admin_id: Optional[int] = None,
    provider: Optional[str] = None,
    include_payments: bool = True,
    payments_limit: int = 100,
) -> Dict[str, Any]:
    """Roll up completed gateway payments: today / yesterday / week / total.

    When ``admin_id`` is set, only that reseller's intents are included.
    """
    today, yesterday, week, _now = _day_bounds()

    q = db.query(PaymentIntent).filter(
        PaymentIntent.status == "completed",
        PaymentIntent.kind.in_(tuple(ALL_KINDS)),
        PaymentIntent.provider.in_(tuple(GATEWAY_PROVIDERS)),
    )
    if admin_id is not None:
        q = q.filter(PaymentIntent.admin_id == admin_id)
    if provider:
        q = q.filter(PaymentIntent.provider == provider)

    rows = q.order_by(PaymentIntent.completed_at.desc().nullslast(), PaymentIntent.id.desc()).all()

    today_rows = _in_range(rows, today)
    yesterday_rows = _in_range(rows, yesterday, today)
    week_rows = _in_range(rows, week)

    by_provider: Dict[str, int] = {}
    by_kind: Dict[str, int] = {}
    for r in rows:
        by_provider[r.provider] = by_provider.get(r.provider, 0) + int(r.amount or 0)
        by_kind[r.kind] = by_kind.get(r.kind, 0) + int(r.amount or 0)

    # Per-reseller breakdown (sudo view) — include opted-in gateway resellers even at 0.
    by_admin: Dict[int, List[PaymentIntent]] = {}
    for r in rows:
        by_admin.setdefault(int(r.admin_id), []).append(r)

    if admin_id is None:
        opted = (
            db.query(Admin)
            .filter(
                Admin.is_sudo.is_(False),
                Admin.centralpay_enabled.is_(True),
            )
            .all()
        )
        for a in opted:
            by_admin.setdefault(int(a.id), [])

    admin_ids = list(by_admin.keys())
    admins = {
        a.id: a
        for a in db.query(Admin).filter(Admin.id.in_(admin_ids)).all()
    } if admin_ids else {}

    resellers: List[Dict[str, Any]] = []
    for aid, arows in by_admin.items():
        admin = admins.get(aid)
        resellers.append({
            "admin_id": aid,
            "username": admin.username if admin else f"#{aid}",
            "is_sudo": bool(admin.is_sudo) if admin else False,
            "centralpay_enabled": bool(getattr(admin, "centralpay_enabled", False)) if admin else False,
            "card_enabled": bool(getattr(admin, "card_enabled", False)) if admin else False,
            "today": _sum_amount(_in_range(arows, today)),
            "yesterday": _sum_amount(_in_range(arows, yesterday, today)),
            "week": _sum_amount(_in_range(arows, week)),
            "total": _sum_amount(arows),
            "payments_count": len(arows),
            "by_provider": {
                p: _sum_amount([x for x in arows if x.provider == p])
                for p in sorted({x.provider for x in arows})
            },
            "by_kind": {
                k: _sum_amount([x for x in arows if x.kind == k])
                for k in sorted({x.kind for x in arows})
            },
        })
    resellers.sort(key=lambda x: (-int(x["total"]), x["username"]))

    recent = []
    if include_payments:
        for intent in rows[: max(1, min(payments_limit, 500))]:
            recent.append(_payment_row(db, intent))

    return {
        "today": _sum_amount(today_rows),
        "yesterday": _sum_amount(yesterday_rows),
        "week": _sum_amount(week_rows),
        "total": _sum_amount(rows),
        "today_count": len(today_rows),
        "yesterday_count": len(yesterday_rows),
        "week_count": len(week_rows),
        "payments_count": len(rows),
        "currency_label": ps.get_str("billing.currency_label") or "",
        "by_provider": by_provider,
        "by_kind": by_kind,
        "today_by_kind": {
            k: _sum_amount([x for x in today_rows if x.kind == k])
            for k in sorted({x.kind for x in today_rows})
        },
        "yesterday_by_kind": {
            k: _sum_amount([x for x in yesterday_rows if x.kind == k])
            for k in sorted({x.kind for x in yesterday_rows})
        },
        "week_by_kind": {
            k: _sum_amount([x for x in week_rows if x.kind == k])
            for k in sorted({x.kind for x in week_rows})
        },
        "total_by_kind": by_kind,
        "resellers": resellers,
        "recent_payments": recent,
    }
