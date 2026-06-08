"""Periodic GB usage billing with BYO-node discount split."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app import billing, logger
from app.db.models import (
    Admin,
    Event,
    Node,
    NodeUserUsage,
    Transaction,
    UsageBillingCheckpoint,
    User,
)
from app.tenant import get_tenant
from app import platform_settings as ps

GB = 1024 ** 3


@dataclass
class UsageSplit:
    owned_bytes: int = 0
    foreign_bytes: int = 0

    @property
    def owned_gb(self) -> int:
        return traffic_to_gb_units(self.owned_bytes)

    @property
    def foreign_gb(self) -> int:
        return traffic_to_gb_units(self.foreign_bytes)

    @property
    def total_bytes(self) -> int:
        return self.owned_bytes + self.foreign_bytes


def traffic_to_gb_units(byte_count: int) -> int:
    """Billable whole GB units (round up partial GB)."""
    n = int(byte_count or 0)
    if n <= 0:
        return 0
    return (n + GB - 1) // GB


def align_hour(dt: datetime) -> datetime:
    return datetime.fromisoformat(dt.strftime("%Y-%m-%dT%H:00:00"))


def node_owned_by_reseller(
    node: Node,
    admin_id: int,
    tenant_id: Optional[int],
) -> bool:
    if tenant_id is not None and node.tenant_id == tenant_id:
        return True
    return node.owner_admin_id == admin_id


def aggregate_reseller_usage(
    db: Session,
    admin_id: int,
    tenant_id: Optional[int],
    since: datetime,
    until: datetime,
) -> UsageSplit:
    """Sum user traffic on each node, split by node ownership."""
    rows = (
        db.query(NodeUserUsage.used_traffic, Node)
        .join(User, NodeUserUsage.user_id == User.id)
        .join(Node, NodeUserUsage.node_id == Node.id)
        .filter(
            User.admin_id == admin_id,
            NodeUserUsage.created_at > since,
            NodeUserUsage.created_at <= until,
        )
        .all()
    )
    split = UsageSplit()
    for used, node in rows:
        traffic = int(used or 0)
        if traffic <= 0:
            continue
        if node_owned_by_reseller(node, admin_id, tenant_id):
            split.owned_bytes += traffic
        else:
            split.foreign_bytes += traffic
    return split


def resolve_discount_percent(db: Session, dbadmin: Admin) -> int:
    if dbadmin.tenant_id is None:
        return 0
    tenant = get_tenant(db, dbadmin.tenant_id)
    return tenant.byo_node_discount_percent if tenant else 0


def get_or_create_checkpoint(db: Session, admin_id: int) -> UsageBillingCheckpoint:
    row = (
        db.query(UsageBillingCheckpoint)
        .filter(UsageBillingCheckpoint.admin_id == admin_id)
        .first()
    )
    if row is None:
        row = UsageBillingCheckpoint(
            admin_id=admin_id,
            last_billed_at=align_hour(datetime.utcnow()) - timedelta(hours=1),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def compute_charge(
    split: UsageSplit,
    rate_per_gb: int,
    discount_percent: int,
) -> int:
    return billing.usage_cost(
        base_rate=rate_per_gb,
        owned_units=split.owned_gb,
        foreign_units=split.foreign_gb,
        discount_percent=discount_percent,
    )


def wallet_is_low(balance: Optional[int], threshold: Optional[int] = None) -> bool:
    if balance is None:
        return False
    limit = threshold if threshold is not None else ps.get_int("billing.wallet_low_threshold", 10000)
    return balance < limit


def usage_summary_for_admin(
    db: Session,
    dbadmin: Admin,
    *,
    rate_per_gb: Optional[int] = None,
) -> dict:
    rate = int(rate_per_gb if rate_per_gb is not None else ps.get_int("billing.usage_rate_per_gb", 0))
    checkpoint = get_or_create_checkpoint(db, dbadmin.id)
    until = align_hour(datetime.utcnow())
    split = aggregate_reseller_usage(
        db,
        dbadmin.id,
        dbadmin.tenant_id,
        checkpoint.last_billed_at,
        until,
    )
    discount = resolve_discount_percent(db, dbadmin)
    wallet = billing.get_or_create_wallet(db, dbadmin.id)
    estimated = compute_charge(split, rate, discount) if rate > 0 else 0
    return {
        "rate_per_gb": rate,
        "discount_percent": discount,
        "period_since": checkpoint.last_billed_at,
        "period_until": until,
        "owned_bytes": split.owned_bytes,
        "foreign_bytes": split.foreign_bytes,
        "owned_gb": split.owned_gb,
        "foreign_gb": split.foreign_gb,
        "estimated_cost": estimated,
        "wallet_balance": wallet.balance,
        "wallet_low": wallet_is_low(wallet.balance),
        "wallet_low_threshold": ps.get_int("billing.wallet_low_threshold", 10000),
    }


def _log_low_balance_event(db: Session, dbadmin: Admin, needed: int, balance: int) -> None:
    db.add(
        Event(
            type="wallet.low_balance",
            payload={
                "admin_id": dbadmin.id,
                "username": dbadmin.username,
                "balance": balance,
                "needed": needed,
            },
        )
    )
    db.commit()


def bill_reseller_usage(
    db: Session,
    dbadmin: Admin,
    *,
    rate_per_gb: Optional[int] = None,
    now: Optional[datetime] = None,
) -> Tuple[Optional[Transaction], UsageSplit]:
    """Bill unbilled hourly usage for one reseller. Returns (tx or None, split)."""
    rate = int(rate_per_gb if rate_per_gb is not None else ps.get_int("billing.usage_rate_per_gb", 0))
    if rate <= 0:
        return None, UsageSplit()

    now = now or datetime.utcnow()
    until = align_hour(now)
    checkpoint = get_or_create_checkpoint(db, dbadmin.id)
    since = checkpoint.last_billed_at
    if until <= since:
        return None, UsageSplit()

    split = aggregate_reseller_usage(db, dbadmin.id, dbadmin.tenant_id, since, until)
    discount = resolve_discount_percent(db, dbadmin)
    cost = compute_charge(split, rate, discount)

    checkpoint.last_billed_at = until

    if cost <= 0:
        db.commit()
        return None, split

    wallet = billing.get_or_create_wallet(db, dbadmin.id)
    if wallet.balance < cost:
        _log_low_balance_event(db, dbadmin, cost, wallet.balance)
        logger.warning(
            'Usage billing skipped for "%s": need %s, balance %s',
            dbadmin.username,
            cost,
            wallet.balance,
        )
        db.commit()
        return None, split

    tx = billing.add_transaction(
        db,
        dbadmin.id,
        -cost,
        type="usage_billing",
        description=(
            f"Usage billing: {split.owned_gb} GB own nodes + "
            f"{split.foreign_gb} GB shared ({since:%Y-%m-%d %H:00}–{until:%H:00} UTC)"
        ),
        reference=f"usage:{since.isoformat()}:{until.isoformat()}",
    )
    if wallet_is_low(wallet.balance):
        _log_low_balance_event(db, dbadmin, 0, wallet.balance)
    return tx, split


def run_usage_billing() -> int:
    """Bill all non-sudo database-backed admins. Returns count of charges posted."""
    from app import feature_flags
    from app.db import GetDB

    if not feature_flags.is_enabled("billing"):
        return 0
    if ps.get_int("billing.usage_rate_per_gb", 0) <= 0:
        return 0

    charged = 0
    with GetDB() as db:
        admins = db.query(Admin).filter(Admin.is_sudo.is_(False)).all()
        for dbadmin in admins:
            tx, _ = bill_reseller_usage(db, dbadmin)
            if tx is not None:
                charged += 1
                logger.info(
                    'Usage billing charged "%s" %s minor units',
                    dbadmin.username,
                    -tx.amount,
                )
    return charged
