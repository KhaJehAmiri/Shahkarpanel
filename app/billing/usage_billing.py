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
    """Whole GB units for display (floor). Charging uses byte-proportional cost."""
    n = int(byte_count or 0)
    if n <= 0:
        return 0
    return n // GB


def align_billing_tick(dt: datetime) -> datetime:
    """Second-resolution watermark so pay-as-you-go can settle near-realtime."""
    return dt.replace(microsecond=0)


def align_hour(dt: datetime) -> datetime:
    """Deprecated hour bucket — kept for callers; prefer align_billing_tick."""
    return datetime.fromisoformat(dt.strftime("%Y-%m-%dT%H:00:00"))


def billing_lookback_seconds() -> int:
    return max(15, int(ps.get_int("billing.job_interval_seconds", 30) or 30))


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
    """Sum user traffic on each node, split by node ownership.

    Panel-local / unknown-node rows (``node_id IS NULL``) are billed at the
    full shared-node rate — an inner join previously dropped them entirely,
    so pay-as-you-go never saw most traffic.
    """
    rows = (
        db.query(NodeUserUsage.used_traffic, Node)
        .join(User, NodeUserUsage.user_id == User.id)
        .outerjoin(Node, NodeUserUsage.node_id == Node.id)
        .filter(
            User.admin_id == admin_id,
            # Volume-capped only — unlimited monthly traffic is wholesale-prepaid.
            User.data_limit.isnot(None),
            User.data_limit > 0,
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
        if node is not None and node_owned_by_reseller(node, admin_id, tenant_id):
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
        admin = db.query(Admin).filter(Admin.id == admin_id).first()
        current_usage = int(admin.users_usage or 0) if admin else 0
        row = UsageBillingCheckpoint(
            admin_id=admin_id,
            last_billed_at=align_billing_tick(datetime.utcnow())
            - timedelta(seconds=billing_lookback_seconds()),
            last_billed_users_usage=current_usage,
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
    """Charge proportional to bytes (floor), not ceil-to-1GB."""
    rate = int(rate_per_gb or 0)
    if rate <= 0:
        return 0
    owned_rate = billing.effective_rate(rate, discount_percent)
    owned = (int(split.owned_bytes) * int(owned_rate)) // GB
    foreign = (int(split.foreign_bytes) * rate) // GB
    return owned + foreign


def apply_prepaid_cover(split: UsageSplit, prepaid_remaining: int) -> Tuple[UsageSplit, int]:
    """Cover usage from prepaid package bytes first (foreign before owned)."""
    prepaid = max(0, int(prepaid_remaining or 0))
    if prepaid <= 0 or split.total_bytes <= 0:
        return split, 0

    foreign = int(split.foreign_bytes)
    owned = int(split.owned_bytes)
    cover_foreign = min(foreign, prepaid)
    remain = prepaid - cover_foreign
    cover_owned = min(owned, remain)
    covered = cover_foreign + cover_owned
    return (
        UsageSplit(
            owned_bytes=owned - cover_owned,
            foreign_bytes=foreign - cover_foreign,
        ),
        covered,
    )


def wallet_is_low(balance: Optional[int], threshold: Optional[int] = None) -> bool:
    if balance is None:
        return False
    limit = threshold if threshold is not None else ps.get_int("billing.wallet_low_threshold", 10000)
    return balance < limit


def ownership_ratio_split(
    db: Session,
    admin_id: int,
    tenant_id: Optional[int],
    delta_bytes: int,
) -> UsageSplit:
    """Attribute a users_usage delta to owned vs shared using a recent ratio.

    Falls back to all-shared (full rate) when no NodeUserUsage breakdown exists
    — typical for panel-local traffic recorded with node_id NULL.
    """
    delta = max(0, int(delta_bytes or 0))
    if delta <= 0:
        return UsageSplit()

    until = align_billing_tick(datetime.utcnow())
    since = until - timedelta(hours=24)
    ratio = aggregate_reseller_usage(db, admin_id, tenant_id, since, until)
    total = ratio.total_bytes
    if total <= 0:
        return UsageSplit(owned_bytes=0, foreign_bytes=delta)

    owned = (delta * int(ratio.owned_bytes)) // total
    foreign = delta - owned
    return UsageSplit(owned_bytes=owned, foreign_bytes=foreign)


def unbilled_usage_split(db: Session, dbadmin: Admin) -> Tuple[UsageSplit, int, int]:
    """Return (split, current_users_usage, last_billed_users_usage)."""
    checkpoint = get_or_create_checkpoint(db, dbadmin.id)
    current = int(dbadmin.users_usage or 0)
    last = int(getattr(checkpoint, "last_billed_users_usage", 0) or 0)
    if current < last:
        # Admin usage was reset — restart watermark without charging the drop.
        last = current
    delta = max(0, current - last)
    return ownership_ratio_split(db, dbadmin.id, dbadmin.tenant_id, delta), current, last


def resolve_usage_rate_per_gb(dbadmin: Admin, rate_per_gb: Optional[int] = None) -> int:
    """Effective PAYG rate for a reseller (override or platform default)."""
    if rate_per_gb is not None:
        return int(rate_per_gb)
    from app.billing.traffic_packages import effective_usage_rate_per_gb

    return effective_usage_rate_per_gb(dbadmin)


def usage_summary_for_admin(
    db: Session,
    dbadmin: Admin,
    *,
    rate_per_gb: Optional[int] = None,
) -> dict:
    rate = resolve_usage_rate_per_gb(dbadmin, rate_per_gb)
    checkpoint = get_or_create_checkpoint(db, dbadmin.id)
    until = align_billing_tick(datetime.utcnow())
    split, current_usage, last_usage = unbilled_usage_split(db, dbadmin)
    discount = resolve_discount_percent(db, dbadmin)
    prepaid = int(getattr(dbadmin, "prepaid_traffic_remaining", 0) or 0)
    overflow, covered = apply_prepaid_cover(split, prepaid)
    wallet = billing.get_or_create_wallet(db, dbadmin.id)
    # Platform owner (sudo) never pays PAYG / packages — job already skips them;
    # keep traffic visible but never mark wallet blocked or estimate a charge.
    subject = not bool(getattr(dbadmin, "is_sudo", False))
    estimated = (
        compute_charge(overflow, rate, discount) if subject and rate > 0 else 0
    )
    currency = (ps.get_setting("billing.currency_label") or "").strip() or None
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
        "wallet_low": subject and wallet_is_low(wallet.balance),
        "wallet_low_threshold": ps.get_int("billing.wallet_low_threshold", 10000),
        "wallet_blocked": bool(
            subject and rate > 0 and estimated > 0 and wallet.balance < estimated
        ),
        "currency_label": currency,
        "prepaid_traffic_remaining": prepaid,
        "package_covered_bytes": covered if subject else 0,
        "overflow_owned_bytes": overflow.owned_bytes if subject else 0,
        "overflow_foreign_bytes": overflow.foreign_bytes if subject else 0,
        "users_usage": current_usage,
        "last_billed_users_usage": last_usage,
        "subject_to_usage_billing": subject,
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
    """Bill unbilled usage for one reseller from Admin.users_usage deltas.

    ``users_usage`` is incremented only for volume-capped accounts (see
    ``record_usages``). Unlimited monthly/wholesale accounts are charged at
    create/renew and must not generate pay-as-you-go debits.
    """
    if getattr(dbadmin, "is_sudo", False):
        return None, UsageSplit()

    rate = resolve_usage_rate_per_gb(dbadmin, rate_per_gb)
    if rate <= 0:
        return None, UsageSplit()

    now = now or datetime.utcnow()
    until = align_billing_tick(now)
    checkpoint = get_or_create_checkpoint(db, dbadmin.id)

    db.refresh(dbadmin)
    split, current_usage, last_usage = unbilled_usage_split(db, dbadmin)
    # Keep last_billed_users_usage coherent after a reset detected above.
    if current_usage < int(getattr(checkpoint, "last_billed_users_usage", 0) or 0):
        checkpoint.last_billed_users_usage = current_usage

    discount = resolve_discount_percent(db, dbadmin)
    prepaid = int(getattr(dbadmin, "prepaid_traffic_remaining", 0) or 0)
    overflow, covered = apply_prepaid_cover(split, prepaid)
    cost = compute_charge(overflow, rate, discount)

    if cost <= 0:
        if covered > 0:
            dbadmin.prepaid_traffic_remaining = max(0, prepaid - covered)
            checkpoint.last_billed_users_usage = current_usage
            checkpoint.last_billed_at = until
            db.commit()
            return None, split
        if split.total_bytes <= 0:
            checkpoint.last_billed_users_usage = current_usage
            checkpoint.last_billed_at = until
            db.commit()
            return None, split
        # Sub-GB overflow leftovers: advance time watermark only; keep byte watermark
        # so the bytes remain billable once they accumulate to >= 1 charge unit.
        checkpoint.last_billed_at = until
        db.commit()
        return None, split

    wallet = billing.get_or_create_wallet(db, dbadmin.id)
    if wallet.balance < cost:
        _log_low_balance_event(db, dbadmin, cost, wallet.balance)
        logger.warning(
            'Usage billing held for "%s": need %s, balance %s '
            "(unbilled %s bytes, package cover pending %s, checkpoint unchanged)",
            dbadmin.username,
            cost,
            wallet.balance,
            split.total_bytes,
            covered,
        )
        db.commit()
        return None, split

    if covered > 0:
        dbadmin.prepaid_traffic_remaining = max(0, prepaid - covered)

    checkpoint.last_billed_users_usage = current_usage
    checkpoint.last_billed_at = until
    owned_gb = round(overflow.owned_bytes / GB, 4)
    foreign_gb = round(overflow.foreign_bytes / GB, 4)
    covered_gb = round(covered / GB, 4)
    tx = billing.add_transaction(
        db,
        dbadmin.id,
        -cost,
        type="usage_billing",
        description=(
            f"Usage billing: {owned_gb} GB own + {foreign_gb} GB shared "
            f"(package covered {covered_gb} GB) "
            f"({last_usage}→{current_usage} bytes, {until:%Y-%m-%d %H:%M:%S} UTC)"
        ),
        reference=f"usage:{last_usage}:{current_usage}:{until.isoformat()}",
    )
    if wallet_is_low(wallet.balance):
        _log_low_balance_event(db, dbadmin, 0, wallet.balance)
    return tx, split


def resellers_with_unpaid_usage(db: Session) -> set[int]:
    """Admin ids whose unbilled GB charge exceeds their current wallet balance."""
    from app import feature_flags

    if not feature_flags.is_enabled("billing"):
        return set()

    blocked: set[int] = set()
    admins = db.query(Admin).filter(Admin.is_sudo.is_(False)).all()
    for dbadmin in admins:
        rate = resolve_usage_rate_per_gb(dbadmin)
        if rate <= 0:
            continue
        split, _, _ = unbilled_usage_split(db, dbadmin)
        if split.total_bytes <= 0:
            continue
        discount = resolve_discount_percent(db, dbadmin)
        prepaid = int(getattr(dbadmin, "prepaid_traffic_remaining", 0) or 0)
        overflow, _ = apply_prepaid_cover(split, prepaid)
        cost = compute_charge(overflow, rate, discount)
        if cost <= 0:
            continue
        wallet = billing.get_or_create_wallet(db, dbadmin.id)
        if wallet.balance < cost:
            blocked.add(dbadmin.id)
    return blocked


def run_usage_billing() -> int:
    """Bill all non-sudo database-backed admins. Returns count of charges posted."""
    from app import feature_flags
    from app.db import GetDB

    if not feature_flags.is_enabled("billing"):
        return 0

    charged = 0
    with GetDB() as db:
        admins = db.query(Admin).filter(Admin.is_sudo.is_(False)).all()
        for dbadmin in admins:
            if resolve_usage_rate_per_gb(dbadmin) <= 0:
                continue
            tx, _ = bill_reseller_usage(db, dbadmin)
            if tx is not None:
                charged += 1
                logger.info(
                    'Usage billing charged "%s" %s minor units',
                    dbadmin.username,
                    -tx.amount,
                )
    return charged
