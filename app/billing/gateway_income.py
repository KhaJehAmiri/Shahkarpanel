"""Checkout income rollups from PaymentIntent rows (gateway + card)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app import platform_settings as ps
from app.db.models import Admin, PaymentIntent, Plan, User

# All customer checkout rails counted on the Overview Payments strip.
CHECKOUT_PROVIDERS = frozenset({"centralpay", "stripe", "demo", "card"})
# Kept for Billing income tab filters that still say "gateway".
GATEWAY_PROVIDERS = frozenset({"centralpay", "stripe", "demo"})
PORTAL_KINDS = frozenset({"portal_renew", "portal_purchase"})
ALL_KINDS = frozenset({"portal_renew", "portal_purchase", "topup"})
SUCCESS_STATUSES = frozenset({"completed"})
FAILED_STATUSES = frozenset({"failed", "rejected", "expired"})


def _day_bounds(now: Optional[datetime] = None) -> tuple[datetime, datetime, datetime, datetime]:
    """Return (today_start, yesterday_start, week_start, now)."""
    now = now or datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week = today - timedelta(days=6)
    return today, yesterday, week, now


def _sum_amount(rows: List[PaymentIntent]) -> int:
    return int(sum(int(r.amount or 0) for r in rows))


def _in_range(
    rows: List[PaymentIntent],
    start: datetime,
    end: Optional[datetime] = None,
    *,
    use_completed: bool = True,
) -> List[PaymentIntent]:
    out = []
    for r in rows:
        if use_completed:
            ts = r.completed_at or r.created_at
        else:
            ts = r.created_at or r.completed_at
        if ts is None:
            continue
        if ts < start:
            continue
        if end is not None and ts >= end:
            continue
        out.append(r)
    return out


def _kind_amount(rows: List[PaymentIntent], kind: str) -> int:
    return _sum_amount([x for x in rows if x.kind == kind])


def _period_bucket(success: List[PaymentIntent], failed: List[PaymentIntent]) -> Dict[str, int]:
    return {
        "success_count": len(success),
        "success_amount": _sum_amount(success),
        "failed_count": len(failed),
        "failed_amount": _sum_amount(failed),
        "renew_count": len([x for x in success if x.kind == "portal_renew"]),
        "renew_amount": _kind_amount(success, "portal_renew"),
        "purchase_count": len([x for x in success if x.kind == "portal_purchase"]),
        "purchase_amount": _kind_amount(success, "portal_purchase"),
        "topup_count": len([x for x in success if x.kind == "topup"]),
        "topup_amount": _kind_amount(success, "topup"),
    }


def _daily_series(
    success: List[PaymentIntent],
    failed: List[PaymentIntent],
    *,
    days: int = 14,
    today_start: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """One bucket per UTC day for Overview charts (oldest → newest)."""
    today_start = today_start or _day_bounds()[0]
    days = max(1, min(int(days or 14), 90))
    out: List[Dict[str, Any]] = []
    for i in range(days - 1, -1, -1):
        start = today_start - timedelta(days=i)
        end = start + timedelta(days=1)
        bucket = _period_bucket(
            _in_range(success, start, end),
            _in_range(failed, start, end, use_completed=False),
        )
        out.append(
            {
                "date": start.strftime("%Y-%m-%d"),
                "label": start.strftime("%m/%d"),
                **bucket,
            }
        )
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
        "username": username
        or extra.get("created_username")
        or extra.get("target_username")
        or extra.get("new_username"),
        "plan_id": intent.plan_id,
        "plan_name": plan_name,
        "reference": extra.get("centralpay_reference_id") or extra.get("stripe_session_id"),
        "card": extra.get("centralpay_card"),
        "created_at": intent.created_at,
        "completed_at": intent.completed_at,
    }


def _reseller_row(
    aid: int,
    admin: Optional[Admin],
    success: List[PaymentIntent],
    failed: List[PaymentIntent],
    today: datetime,
    yesterday: datetime,
    week: datetime,
) -> Dict[str, Any]:
    s_today = _in_range(success, today)
    s_yesterday = _in_range(success, yesterday, today)
    s_week = _in_range(success, week)
    f_today = _in_range(failed, today, use_completed=False)
    f_yesterday = _in_range(failed, yesterday, today, use_completed=False)
    f_week = _in_range(failed, week, use_completed=False)
    return {
        "admin_id": aid,
        "username": admin.username if admin else f"#{aid}",
        "is_sudo": bool(admin.is_sudo) if admin else False,
        "centralpay_enabled": bool(getattr(admin, "centralpay_enabled", False)) if admin else False,
        "card_enabled": bool(getattr(admin, "card_enabled", False)) if admin else False,
        "today": _sum_amount(s_today),
        "yesterday": _sum_amount(s_yesterday),
        "week": _sum_amount(s_week),
        "total": _sum_amount(success),
        "payments_count": len(success),
        "failed_count": len(failed),
        "failed_amount": _sum_amount(failed),
        "today_failed_count": len(f_today),
        "yesterday_failed_count": len(f_yesterday),
        "week_failed_count": len(f_week),
        "renew_amount": _kind_amount(success, "portal_renew"),
        "purchase_amount": _kind_amount(success, "portal_purchase"),
        "topup_amount": _kind_amount(success, "topup"),
        "by_provider": {
            p: _sum_amount([x for x in success if x.provider == p])
            for p in sorted({x.provider for x in success})
        },
        "by_kind": {
            k: _sum_amount([x for x in success if x.kind == k])
            for k in sorted({x.kind for x in success})
        },
        "periods": {
            "today": _period_bucket(s_today, f_today),
            "yesterday": _period_bucket(s_yesterday, f_yesterday),
            "week": _period_bucket(s_week, f_week),
            "total": _period_bucket(success, failed),
        },
    }


def compute_gateway_income(
    db: Session,
    *,
    admin_id: Optional[int] = None,
    provider: Optional[str] = None,
    include_payments: bool = True,
    payments_limit: int = 100,
    include_card: bool = True,
) -> Dict[str, Any]:
    """Roll up checkout payments: success / fail / renew / purchase by period.

    Includes card-to-card when ``include_card`` is True (Overview default).
    When ``admin_id`` is set, only that reseller's intents are included.
    """
    today, yesterday, week, _now = _day_bounds()
    providers = CHECKOUT_PROVIDERS if include_card else GATEWAY_PROVIDERS

    base = db.query(PaymentIntent).filter(
        PaymentIntent.kind.in_(tuple(ALL_KINDS)),
        PaymentIntent.provider.in_(tuple(providers)),
    )
    if admin_id is not None:
        base = base.filter(PaymentIntent.admin_id == admin_id)
    if provider:
        base = base.filter(PaymentIntent.provider == provider)

    success_q = base.filter(PaymentIntent.status.in_(tuple(SUCCESS_STATUSES)))
    failed_q = base.filter(PaymentIntent.status.in_(tuple(FAILED_STATUSES)))

    success = success_q.order_by(
        PaymentIntent.completed_at.desc().nullslast(), PaymentIntent.id.desc()
    ).all()
    failed = failed_q.order_by(
        PaymentIntent.created_at.desc().nullslast(), PaymentIntent.id.desc()
    ).all()

    s_today = _in_range(success, today)
    s_yesterday = _in_range(success, yesterday, today)
    s_week = _in_range(success, week)
    f_today = _in_range(failed, today, use_completed=False)
    f_yesterday = _in_range(failed, yesterday, today, use_completed=False)
    f_week = _in_range(failed, week, use_completed=False)

    by_provider: Dict[str, int] = {}
    by_kind: Dict[str, int] = {}
    for r in success:
        by_provider[r.provider] = by_provider.get(r.provider, 0) + int(r.amount or 0)
        by_kind[r.kind] = by_kind.get(r.kind, 0) + int(r.amount or 0)

    by_admin_success: Dict[int, List[PaymentIntent]] = {}
    by_admin_failed: Dict[int, List[PaymentIntent]] = {}
    for r in success:
        by_admin_success.setdefault(int(r.admin_id), []).append(r)
    for r in failed:
        by_admin_failed.setdefault(int(r.admin_id), []).append(r)

    if admin_id is None:
        # Always list every reseller (even with zero checkouts) so Overview
        # never looks "empty" when only master direct sales exist.
        for a in db.query(Admin).filter(Admin.is_sudo.is_(False)).all():
            by_admin_success.setdefault(int(a.id), [])
            by_admin_failed.setdefault(int(a.id), [])

    admin_ids = sorted(set(by_admin_success) | set(by_admin_failed))
    admins = {
        a.id: a for a in db.query(Admin).filter(Admin.id.in_(admin_ids)).all()
    } if admin_ids else {}

    resellers: List[Dict[str, Any]] = []
    for aid in admin_ids:
        resellers.append(
            _reseller_row(
                aid,
                admins.get(aid),
                by_admin_success.get(aid, []),
                by_admin_failed.get(aid, []),
                today,
                yesterday,
                week,
            )
        )
    resellers.sort(key=lambda x: (-int(x["total"]), -int(x.get("failed_count") or 0), x["username"]))

    recent = []
    if include_payments:
        # Prefer recent successes; pad with recent failures so the UI can show both.
        mixed = list(success[: max(1, min(payments_limit, 500))])
        if len(mixed) < payments_limit:
            mixed.extend(failed[: payments_limit - len(mixed)])
        for intent in mixed:
            recent.append(_payment_row(db, intent))

    periods = {
        "today": _period_bucket(s_today, f_today),
        "yesterday": _period_bucket(s_yesterday, f_yesterday),
        "week": _period_bucket(s_week, f_week),
        "total": _period_bucket(success, failed),
    }
    daily = _daily_series(success, failed, days=14, today_start=today)

    return {
        # Backward-compatible aliases (= successful checkout totals).
        "today": periods["today"]["success_amount"],
        "yesterday": periods["yesterday"]["success_amount"],
        "week": periods["week"]["success_amount"],
        "total": periods["total"]["success_amount"],
        "today_count": periods["today"]["success_count"],
        "yesterday_count": periods["yesterday"]["success_count"],
        "week_count": periods["week"]["success_count"],
        "payments_count": periods["total"]["success_count"],
        "currency_label": ps.get_str("billing.currency_label") or "",
        "by_provider": by_provider,
        "by_kind": by_kind,
        "today_by_kind": {
            k: _sum_amount([x for x in s_today if x.kind == k])
            for k in sorted({x.kind for x in s_today})
        },
        "yesterday_by_kind": {
            k: _sum_amount([x for x in s_yesterday if x.kind == k])
            for k in sorted({x.kind for x in s_yesterday})
        },
        "week_by_kind": {
            k: _sum_amount([x for x in s_week if x.kind == k])
            for k in sorted({x.kind for x in s_week})
        },
        "total_by_kind": by_kind,
        "periods": periods,
        "daily": daily,
        "resellers": resellers,
        "recent_payments": recent,
    }
