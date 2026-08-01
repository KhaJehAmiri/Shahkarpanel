"""Owner MRR / revenue analytics (phase 5)."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import platform_settings as ps
from app.db.models import Admin, Transaction, Wallet

# Platform revenue: charges debited from reseller wallets.
REVENUE_TYPES = frozenset({
    "usage_billing",
    "plan_sale",
    "portal_renew",
    "invoice",
    "traffic_package",
})


def _day_start(dt: Optional[datetime] = None) -> datetime:
    now = dt or datetime.utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def compute_mrr(db: Session, *, days: int = 30) -> Dict[str, Any]:
    days = max(1, min(int(days or 30), 365))
    since = datetime.utcnow() - timedelta(days=days)
    today = _day_start()

    rows = (
        db.query(
            Transaction.type,
            Transaction.admin_id,
            func.sum(Transaction.amount).label("total"),
        )
        .join(Admin, Transaction.admin_id == Admin.id)
        .filter(
            Admin.is_sudo.is_(False),
            Transaction.created_at >= since,
            Transaction.amount < 0,
            Transaction.type.in_(tuple(REVENUE_TYPES)),
        )
        .group_by(Transaction.type, Transaction.admin_id)
        .all()
    )

    by_type: Dict[str, int] = {}
    by_reseller: Dict[int, int] = {}
    total_revenue = 0
    for tx_type, admin_id, total in rows:
        amount = abs(int(total or 0))
        by_type[tx_type] = by_type.get(tx_type, 0) + amount
        by_reseller[admin_id] = by_reseller.get(admin_id, 0) + amount
        total_revenue += amount

    # Daily revenue series (UTC days) for charts — portable across dialects.
    day_map: Dict[str, int] = {}
    tx_days = (
        db.query(Transaction.created_at, Transaction.amount)
        .join(Admin, Transaction.admin_id == Admin.id)
        .filter(
            Admin.is_sudo.is_(False),
            Transaction.created_at >= today - timedelta(days=13),
            Transaction.amount < 0,
            Transaction.type.in_(tuple(REVENUE_TYPES)),
        )
        .all()
    )
    for created_at, amount in tx_days:
        if created_at is None:
            continue
        key = created_at.strftime("%Y-%m-%d")
        day_map[key] = day_map.get(key, 0) + abs(int(amount or 0))

    daily: List[Dict[str, Any]] = []
    for i in range(13, -1, -1):
        start = today - timedelta(days=i)
        key = start.strftime("%Y-%m-%d")
        daily.append({
            "date": key,
            "label": start.strftime("%m/%d"),
            "revenue": day_map.get(key, 0),
        })

    wallet_float = (
        db.query(func.coalesce(func.sum(Wallet.balance), 0))
        .join(Admin, Wallet.admin_id == Admin.id)
        .filter(Admin.is_sudo.is_(False))
        .scalar()
    )

    resellers = (
        db.query(Admin)
        .filter(Admin.is_sudo.is_(False))
        .order_by(Admin.username.asc())
        .all()
    )
    wallets = {
        w.admin_id: int(w.balance or 0)
        for w in db.query(Wallet).filter(Wallet.admin_id.in_([a.id for a in resellers] or [-1])).all()
    }

    active_resellers = len(resellers)
    sub_resellers = sum(1 for a in resellers if a.parent_admin_id is not None)

    reseller_rows: List[Dict[str, Any]] = []
    for a in resellers:
        rev = int(by_reseller.get(a.id, 0))
        reseller_rows.append({
            "admin_id": a.id,
            "username": a.username,
            "revenue": rev,
            "wallet_balance": wallets.get(a.id, 0),
            "prepaid_traffic_remaining": int(getattr(a, "prepaid_traffic_remaining", 0) or 0),
            "role": a.role or "reseller",
            "is_sub": a.parent_admin_id is not None,
        })
    reseller_rows.sort(key=lambda x: (-x["revenue"], -x["wallet_balance"], x["username"]))

    top_resellers = [
        {"admin_id": r["admin_id"], "username": r["username"], "revenue": r["revenue"]}
        for r in reseller_rows
        if r["revenue"] > 0
    ][:10]

    return {
        "period_days": days,
        "total_revenue": total_revenue,
        "mrr_estimate": total_revenue,
        "by_type": by_type,
        "wallet_float": int(wallet_float or 0),
        "active_resellers": int(active_resellers or 0),
        "sub_resellers": int(sub_resellers or 0),
        "top_resellers": top_resellers,
        "resellers": reseller_rows,
        "daily": daily,
        "currency_label": (ps.get_str("billing.currency_label") or "").strip(),
    }
