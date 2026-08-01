"""Compatibility wrappers — reseller wholesale tariffs live in reseller_tariffs.

Master retail ``Plan`` rows are never used as reseller wholesale prices.
Sudo defines tariffs under Resellers → Tariffs (volume or unlimited).
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

from app.billing.reseller_tariffs import (
    ResellerTariffError,
    charge_portal_plan_tariff,
    charge_reseller_tariff,
    is_unlimited_data_limit,
    match_tariff,
    prepare_reseller_tariff_charge,
)
from app.db import Session, crud
from app.db.models import Admin, Plan, ResellerPlanTariff

# Back-compat alias used by older imports / HTTP mappers.
UnlimitedCreateChargeError = ResellerTariffError


def get_configured_unlimited_plan_ids():
    """Deprecated — tariffs are no longer Plan ids."""
    return []


def is_reseller_unlimited_tariff_id(plan_id: Optional[int]) -> bool:
    return False


def list_unlimited_tariff_plans(db: Session):
    from app.billing.reseller_tariffs import list_tariffs

    return list_tariffs(db, enabled_only=True)


def get_reseller_unlimited_tariff_plan(db: Session):
    rows = list_unlimited_tariff_plans(db)
    return rows[0] if rows else None


def prepare_unlimited_create_charge(
    db: Session,
    admin: Optional[Admin],
    *,
    data_limit,
    count: int = 1,
    plan_id: Optional[int] = None,
    duration_days: Optional[int] = None,
    commercial_plan: Optional[Plan] = None,
) -> Tuple[Optional[ResellerPlanTariff], int]:
    if commercial_plan is None and plan_id is not None:
        commercial_plan = crud.get_plan_by_id(db, int(plan_id))
    return prepare_reseller_tariff_charge(
        db,
        admin,
        data_limit=data_limit if commercial_plan is None else commercial_plan.data_limit,
        duration_days=(
            duration_days
            if commercial_plan is None
            else getattr(commercial_plan, "duration_days", None)
        ),
        commercial_plan=commercial_plan,
        count=count,
    )


def charge_unlimited_creates(
    db: Session,
    admin: Admin,
    *,
    plan,  # ResellerPlanTariff or legacy Plan
    unit_price: int,
    usernames: Sequence[str],
    event: str = "create",
):
    if isinstance(plan, ResellerPlanTariff):
        return charge_reseller_tariff(
            db, admin, tariff=plan, unit_price=unit_price, usernames=usernames, event=event
        )
    # Legacy Plan object — ignore; tariffs are separate.
    return None


def assert_reseller_can_cover_unlimited(
    db: Session,
    admin: Optional[Admin],
    *,
    data_limit,
    count: int = 1,
    plan_id: Optional[int] = None,
    duration_days: Optional[int] = None,
    commercial_plan: Optional[Plan] = None,
):
    return prepare_unlimited_create_charge(
        db,
        admin,
        data_limit=data_limit,
        count=count,
        plan_id=plan_id,
        duration_days=duration_days,
        commercial_plan=commercial_plan,
    )


def charge_portal_unlimited_tariff(
    db: Session,
    *,
    reseller_admin_id: Optional[int],
    commercial_plan: Plan,
    username: str,
    event: str,
):
    """Debit matching wholesale tariff (volume or unlimited) for portal events."""
    return charge_portal_plan_tariff(
        db,
        reseller_admin_id=reseller_admin_id,
        commercial_plan=commercial_plan,
        username=username,
        event=event,
    )


# Re-export helpers used elsewhere
__all__ = [
    "UnlimitedCreateChargeError",
    "ResellerTariffError",
    "is_unlimited_data_limit",
    "match_tariff",
    "prepare_unlimited_create_charge",
    "charge_unlimited_creates",
    "assert_reseller_can_cover_unlimited",
    "charge_portal_unlimited_tariff",
    "get_configured_unlimited_plan_ids",
    "is_reseller_unlimited_tariff_id",
    "list_unlimited_tariff_plans",
    "get_reseller_unlimited_tariff_plan",
]
