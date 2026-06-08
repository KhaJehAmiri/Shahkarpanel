"""Sub-reseller commission on downstream spend."""
from sqlalchemy.orm import Session

from app.db.models import Admin


def credit_parent_commission(
    db: Session,
    admin_id: int,
    debit_amount: int,
    *,
    tx_type: str,
    description: str,
    reference: str,
) -> None:
    """When a child reseller is charged, credit their parent a commission %."""
    if debit_amount >= 0:
        return
    child = db.query(Admin).filter(Admin.id == admin_id).first()
    if child is None or not child.parent_admin_id:
        return
    pct = int(child.commission_percent or 0)
    if pct <= 0:
        from app import platform_settings as ps

        pct = ps.get_int("reseller.default_commission_percent", 0)
    if pct <= 0:
        return
    commission = abs(int(debit_amount)) * pct // 100
    if commission <= 0:
        return
    from app.billing import add_transaction

    add_transaction(
        db,
        child.parent_admin_id,
        commission,
        type="commission",
        description=f"Commission ({pct}%) from {child.username} — {description}",
        reference=reference,
        skip_commission=True,
    )
