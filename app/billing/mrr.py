"""Owner MRR / revenue analytics (phase 5)."""
from datetime import datetime, timedelta
from typing import Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Admin, Transaction, Wallet

# Platform revenue: charges debited from reseller wallets.
REVENUE_TYPES = frozenset({"usage_billing", "plan_sale", "portal_renew", "invoice"})


def compute_mrr(db: Session, *, days: int = 30) -> Dict:
    since = datetime.utcnow() - timedelta(days=days)

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
            Transaction.type.in_(REVENUE_TYPES),
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

    wallet_float = (
        db.query(func.coalesce(func.sum(Wallet.balance), 0))
        .join(Admin, Wallet.admin_id == Admin.id)
        .filter(Admin.is_sudo.is_(False))
        .scalar()
    )
    active_resellers = (
        db.query(func.count(Admin.id))
        .filter(Admin.is_sudo.is_(False), Admin.role == "reseller")
        .scalar()
    )
    sub_resellers = (
        db.query(func.count(Admin.id))
        .filter(Admin.parent_admin_id.isnot(None))
        .scalar()
    )

    top_resellers: List[Dict] = []
    if by_reseller:
        admin_rows = {
            a.id: a.username
            for a in db.query(Admin).filter(Admin.id.in_(by_reseller.keys())).all()
        }
        ranked = sorted(by_reseller.items(), key=lambda x: x[1], reverse=True)[:10]
        top_resellers = [
            {"admin_id": aid, "username": admin_rows.get(aid, f"#{aid}"), "revenue": rev}
            for aid, rev in ranked
        ]

    return {
        "period_days": days,
        "total_revenue": total_revenue,
        "mrr_estimate": total_revenue,
        "by_type": by_type,
        "wallet_float": int(wallet_float or 0),
        "active_resellers": int(active_resellers or 0),
        "sub_resellers": int(sub_resellers or 0),
        "top_resellers": top_resellers,
    }
