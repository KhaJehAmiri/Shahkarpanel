"""Reseller wholesale plan tariffs — owned by platform, managed under Resellers.

Completely separate from master retail ``Plan`` rows. Sudo defines any mix of
volume + unlimited tariffs here; when a reseller creates an account or their
customer buys/renews a matching commercial plan, ``price`` is debited from the
reseller wallet (type=plan_sale).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.db.models import Admin, Plan, ResellerPlanTariff


class ResellerTariffError(Exception):
    def __init__(self, message: str, *, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def normalize_data_limit(data_limit) -> Optional[int]:
    """None = unlimited; otherwise positive bytes."""
    if data_limit is None:
        return None
    try:
        n = int(data_limit)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return n


def is_unlimited_data_limit(data_limit) -> bool:
    return normalize_data_limit(data_limit) is None


def list_tariffs(db: Session, *, enabled_only: bool = False) -> List[ResellerPlanTariff]:
    q = db.query(ResellerPlanTariff).order_by(
        ResellerPlanTariff.duration_days.asc().nullslast(),
        ResellerPlanTariff.data_limit.asc().nullslast(),
        ResellerPlanTariff.id.asc(),
    )
    if enabled_only:
        q = q.filter(ResellerPlanTariff.enabled.is_(True))
    return q.all()


def get_tariff(db: Session, tariff_id: int) -> Optional[ResellerPlanTariff]:
    return db.query(ResellerPlanTariff).filter(ResellerPlanTariff.id == tariff_id).first()


def create_tariff(
    db: Session,
    *,
    name: str,
    price: int,
    data_limit: Optional[int] = None,
    duration_days: Optional[int] = None,
    enabled: bool = True,
) -> ResellerPlanTariff:
    name = (name or "").strip()
    if not name:
        raise ResellerTariffError("Name is required")
    row = ResellerPlanTariff(
        name=name[:128],
        price=max(0, int(price or 0)),
        data_limit=normalize_data_limit(data_limit),
        duration_days=int(duration_days) if duration_days not in (None, "") else None,
        enabled=bool(enabled),
        created_at=datetime.utcnow(),
    )
    if row.duration_days is not None and row.duration_days <= 0:
        row.duration_days = None
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_tariff(
    db: Session,
    row: ResellerPlanTariff,
    *,
    name: Optional[str] = None,
    price: Optional[int] = None,
    data_limit: Any = ...,
    duration_days: Any = ...,
    enabled: Optional[bool] = None,
) -> ResellerPlanTariff:
    if name is not None:
        name = name.strip()
        if not name:
            raise ResellerTariffError("Name is required")
        row.name = name[:128]
    if price is not None:
        row.price = max(0, int(price))
    if data_limit is not ...:
        row.data_limit = normalize_data_limit(data_limit)
    if duration_days is not ...:
        if duration_days in (None, ""):
            row.duration_days = None
        else:
            d = int(duration_days)
            row.duration_days = d if d > 0 else None
    if enabled is not None:
        row.enabled = bool(enabled)
    db.commit()
    db.refresh(row)
    return row


def delete_tariff(db: Session, row: ResellerPlanTariff) -> None:
    db.delete(row)
    db.commit()


def tariff_to_dict(row: ResellerPlanTariff) -> Dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "price": int(row.price or 0),
        "data_limit": row.data_limit,
        "duration_days": row.duration_days,
        "enabled": bool(row.enabled),
        "created_at": row.created_at,
        "is_unlimited": is_unlimited_data_limit(row.data_limit),
    }


def match_tariff(
    db: Session,
    *,
    data_limit=None,
    duration_days: Optional[int] = None,
) -> Optional[ResellerPlanTariff]:
    """Find best enabled wholesale tariff for the given limits."""
    want_dl = normalize_data_limit(data_limit)
    want_dur = int(duration_days) if duration_days not in (None, "") else None
    if want_dur is not None and want_dur <= 0:
        want_dur = None

    rows = list_tariffs(db, enabled_only=True)
    same_volume = [t for t in rows if normalize_data_limit(t.data_limit) == want_dl]
    if not same_volume:
        return None

    if want_dur is not None:
        exact = [t for t in same_volume if t.duration_days == want_dur]
        if exact:
            return sorted(exact, key=lambda t: (int(t.price or 0), t.id))[0]
        # No exact duration — do not silently pick another duration.
        return None

    # No duration requested: prefer tariffs without duration, else cheapest.
    open_ended = [t for t in same_volume if t.duration_days is None]
    pool = open_ended or same_volume
    return sorted(pool, key=lambda t: (int(t.price or 0), t.id))[0]


def match_tariff_for_plan(db: Session, plan: Plan) -> Optional[ResellerPlanTariff]:
    return match_tariff(
        db,
        data_limit=getattr(plan, "data_limit", None),
        duration_days=getattr(plan, "duration_days", None),
    )


def prepare_reseller_tariff_charge(
    db: Session,
    admin: Optional[Admin],
    *,
    data_limit=None,
    duration_days: Optional[int] = None,
    commercial_plan: Optional[Plan] = None,
    count: int = 1,
) -> Tuple[Optional[ResellerPlanTariff], int]:
    """Validate wallet for ``count`` matching wholesale tariffs.

    Returns ``(tariff, unit_price)``. No matching tariff / sudo / billing off →
    ``(None, 0)``. Insufficient balance → ``ResellerTariffError`` 402.
    """
    if admin is None or getattr(admin, "is_sudo", False):
        return None, 0
    if count < 1:
        return None, 0

    from app import feature_flags

    if not feature_flags.is_enabled("billing"):
        return None, 0

    if commercial_plan is not None:
        tariff = match_tariff_for_plan(db, commercial_plan)
    else:
        tariff = match_tariff(db, data_limit=data_limit, duration_days=duration_days)

    if tariff is None:
        return None, 0

    price = int(tariff.price or 0)
    if price <= 0:
        return tariff, 0

    from app.billing import get_or_create_wallet

    total = price * int(count)
    wallet = get_or_create_wallet(db, admin.id)
    if int(wallet.balance or 0) < total:
        raise ResellerTariffError(
            f"Insufficient wallet balance — need {total} for {count}× «{tariff.name}», "
            f"have {wallet.balance}",
            status_code=402,
        )
    return tariff, price


def charge_reseller_tariff(
    db: Session,
    admin: Admin,
    *,
    tariff: ResellerPlanTariff,
    unit_price: int,
    usernames: Sequence[str],
    event: str = "create",
):
    if not usernames or unit_price <= 0:
        return None
    if admin is None or getattr(admin, "is_sudo", False):
        return None

    from app.billing import add_transaction

    n = len(usernames)
    total = unit_price * n
    sample = usernames[0] if n == 1 else f"{usernames[0]} +{n - 1} more"
    label = {
        "create": "Reseller tariff create",
        "portal_purchase": "Reseller tariff portal purchase",
        "portal_renew": "Reseller tariff portal renew",
    }.get(event, f"Reseller tariff {event}")
    return add_transaction(
        db,
        admin.id,
        -total,
        type="plan_sale",
        description=f"{label} ×{n} — {tariff.name} ({sample})",
        reference=f"reseller_tariff_{event}:tariff:{tariff.id}:n:{n}:user:{usernames[0]}",
    )


def charge_portal_plan_tariff(
    db: Session,
    *,
    reseller_admin_id: Optional[int],
    commercial_plan: Plan,
    username: str,
    event: str,
):
    """Debit matching wholesale tariff after portal buy/renew (reseller only)."""
    if not reseller_admin_id:
        return None
    from app.db import crud

    admin = crud.get_admin_by_id(db, int(reseller_admin_id))
    if admin is None or getattr(admin, "is_sudo", False):
        return None

    tariff, unit = prepare_reseller_tariff_charge(
        db, admin, commercial_plan=commercial_plan, count=1
    )
    if tariff is None or unit <= 0:
        return None
    return charge_reseller_tariff(
        db, admin, tariff=tariff, unit_price=unit, usernames=[username], event=event
    )
