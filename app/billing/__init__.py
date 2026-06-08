"""Billing core: wallets, transactions and invoices.

Money is stored in integer minor units (e.g. cents) to avoid float rounding.
A wallet balance is the running sum of its transactions: credits are positive,
charges (paying an invoice) are negative.
"""
from datetime import datetime
from typing import List, Optional

from app.db import Session
from app.db.models import Invoice, Transaction, Wallet

from .providers import available_providers, get_provider, register_provider
from .usage_billing import (
    aggregate_reseller_usage,
    bill_reseller_usage,
    compute_charge,
    run_usage_billing,
    traffic_to_gb_units,
    usage_summary_for_admin,
    wallet_is_low,
)

__all__ = [
    "get_or_create_wallet",
    "add_transaction",
    "create_invoice",
    "pay_invoice",
    "list_transactions",
    "effective_rate",
    "usage_cost",
    "get_provider",
    "available_providers",
    "register_provider",
    "aggregate_reseller_usage",
    "bill_reseller_usage",
    "compute_charge",
    "run_usage_billing",
    "traffic_to_gb_units",
    "usage_summary_for_admin",
    "wallet_is_low",
]


def get_or_create_wallet(db: Session, admin_id: int) -> Wallet:
    wallet = db.query(Wallet).filter(Wallet.admin_id == admin_id).first()
    if wallet is None:
        wallet = Wallet(admin_id=admin_id, balance=0)
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
    return wallet


def add_transaction(
    db: Session,
    admin_id: int,
    amount: int,
    type: str,
    description: Optional[str] = None,
    reference: Optional[str] = None,
    *,
    skip_commission: bool = False,
) -> Transaction:
    """Append a ledger entry and adjust the wallet balance atomically."""
    wallet = get_or_create_wallet(db, admin_id)
    tx = Transaction(
        admin_id=admin_id,
        amount=amount,
        type=type,
        description=description,
        reference=reference,
    )
    db.add(tx)
    wallet.balance += amount
    db.commit()
    db.refresh(tx)
    if not skip_commission and amount < 0 and type not in ("commission", "invoice"):
        from app.billing.commission import credit_parent_commission

        credit_parent_commission(
            db,
            admin_id,
            amount,
            tx_type=type,
            description=description or type,
            reference=reference or str(tx.id),
        )
    return tx


def create_invoice(
    db: Session,
    admin_id: int,
    amount: int,
    plan_id: Optional[int] = None,
    provider: Optional[str] = None,
) -> Invoice:
    invoice = Invoice(
        admin_id=admin_id,
        amount=amount,
        plan_id=plan_id,
        provider=provider,
        status="pending",
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def pay_invoice(db: Session, invoice: Invoice, provider_name: Optional[str] = None) -> Invoice:
    """Mark an invoice paid and record the corresponding charge."""
    if invoice.status == "paid":
        return invoice

    invoice.status = "paid"
    invoice.paid_at = datetime.utcnow()
    if provider_name:
        invoice.provider = provider_name
    db.commit()
    db.refresh(invoice)

    add_transaction(
        db,
        invoice.admin_id,
        -invoice.amount,
        type="invoice",
        description=f"Invoice #{invoice.id}",
        reference=str(invoice.id),
    )
    return invoice


def list_transactions(db: Session, admin_id: int, limit: int = 50) -> List[Transaction]:
    return (
        db.query(Transaction)
        .filter(Transaction.admin_id == admin_id)
        .order_by(Transaction.created_at.desc())
        .limit(limit)
        .all()
    )


# --------------------------------------------------------------------------- #
# Phase 6: "bring your own node" pricing
# --------------------------------------------------------------------------- #
def effective_rate(base_rate: int, discount_percent: int) -> int:
    """Apply a reseller's BYO-node discount to a base per-unit rate.

    ``base_rate`` is the owner's usage rate in minor units; ``discount_percent``
    (0-100) is shaved off when the traffic is served on the reseller's own
    nodes (their infra cost to the owner is ~zero). Rounds half down to stay
    conservative for the owner. Never returns negative.
    """
    pct = max(0, min(100, int(discount_percent or 0)))
    return max(0, (int(base_rate) * (100 - pct)) // 100)


def usage_cost(
    base_rate: int,
    owned_units: int,
    foreign_units: int,
    discount_percent: int,
) -> int:
    """Total cost for usage split between a reseller's own nodes and the
    owner's nodes.

    ``owned_units`` is traffic served on the reseller's provisioned nodes
    (discounted); ``foreign_units`` is traffic on the owner's shared nodes
    (full rate). Units are whatever ``base_rate`` is priced per (e.g. GB).
    """
    owned = max(0, int(owned_units)) * effective_rate(base_rate, discount_percent)
    foreign = max(0, int(foreign_units)) * int(base_rate)
    return owned + foreign
