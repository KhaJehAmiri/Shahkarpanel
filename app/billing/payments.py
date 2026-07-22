"""Payment intent orchestration: top-up and portal direct pay."""
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import billing, xray
from app.billing.providers import available_providers, get_provider, provider_supports_intent
from app.db.models import PaymentIntent, Plan, User
from app.models.user import UserStatus
from app.portal import apply_plan_to_user, create_user_order, mark_order_applied
from app.tenant.plan_ops import assert_plan_for_user
from app import platform_settings as ps
from config import PORTAL_DIRECT_PAYMENT


def _validate_amount(amount: int) -> int:
    value = int(amount)
    min_amt = ps.get_int("payment.min_amount", 100)
    max_amt = ps.get_int("payment.max_amount", 100_000_000)
    if value < min_amt:
        raise HTTPException(
            status_code=422,
            detail=f"Minimum payment amount is {min_amt}",
        )
    if value > max_amt:
        raise HTTPException(
            status_code=422,
            detail=f"Maximum payment amount is {max_amt}",
        )
    return value


def _require_provider(name: str) -> None:
    if not provider_supports_intent(name):
        raise HTTPException(status_code=422, detail=f"Provider '{name}' is not available")


def create_topup_payment(
    db: Session,
    admin_id: int,
    amount: int,
    provider: str,
) -> tuple[PaymentIntent, dict]:
    _require_provider(provider)
    value = _validate_amount(amount)
    intent = PaymentIntent(
        kind="topup",
        admin_id=admin_id,
        amount=value,
        provider=provider,
        status="pending",
    )
    db.add(intent)
    db.commit()
    db.refresh(intent)
    instructions = get_provider(provider).create_payment(intent)
    db.commit()
    db.refresh(intent)
    return intent, instructions


def create_portal_payment(
    db: Session,
    dbuser: User,
    plan_id: int,
    provider: str,
) -> tuple[PaymentIntent, dict]:
    if not PORTAL_DIRECT_PAYMENT:
        raise HTTPException(status_code=404, detail="Direct portal payment is disabled")
    _require_provider(provider)

    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan or not plan.enabled:
        raise HTTPException(status_code=404, detail="Plan not found")
    if not dbuser.admin_id:
        raise HTTPException(status_code=400, detail="User has no owning reseller")
    assert_plan_for_user(db, dbuser.admin_id, plan)

    price = int(plan.price or 0)
    if price <= 0:
        raise HTTPException(status_code=422, detail="Use renew for free plans")

    intent = PaymentIntent(
        kind="portal_renew",
        admin_id=dbuser.admin_id,
        user_id=dbuser.id,
        plan_id=plan.id,
        amount=price,
        provider=provider,
        status="pending",
    )
    db.add(intent)
    db.commit()
    db.refresh(intent)
    instructions = get_provider(provider).create_payment(intent)
    db.commit()
    db.refresh(intent)
    return intent, instructions


def _apply_topup(db: Session, intent: PaymentIntent) -> None:
    billing.add_transaction(
        db,
        intent.admin_id,
        intent.amount,
        type="topup",
        description=f"Wallet top-up via {intent.provider}",
        reference=f"payment:{intent.id}",
    )
    # Wallet credit can clear insolvency caps — restore users onto live cores.
    try:
        from app.billing.usage_billing import bill_reseller_usage
        from app.db import crud
        from app.quota import enforce_reseller_traffic_caps, restore_users_everywhere

        admin = crud.get_admin_by_id(db, intent.admin_id)
        if admin is not None:
            bill_reseller_usage(db, admin)
        _newly, reactivated = enforce_reseller_traffic_caps(db)
        if reactivated:
            # Commit first so restore sees restored statuses; caller commits too.
            db.commit()
            restore_users_everywhere(reactivated)
    except Exception:
        pass


def _apply_portal_renew(db: Session, intent: PaymentIntent) -> User:
    dbuser = db.query(User).filter(User.id == intent.user_id).first()
    plan = db.query(Plan).filter(Plan.id == intent.plan_id).first()
    if dbuser is None or plan is None:
        raise HTTPException(status_code=404, detail="Payment target not found")

    order = create_user_order(db, dbuser, plan, status="paid")
    dbuser = apply_plan_to_user(db, dbuser, plan)
    mark_order_applied(db, order)

    if dbuser.status in (UserStatus.active, UserStatus.on_hold):
        xray.operations.sync_core_users()
    return dbuser


def complete_payment(
    db: Session,
    intent: PaymentIntent,
    payload: dict,
) -> PaymentIntent:
    if intent.status == "completed":
        return intent
    if intent.status != "pending":
        raise HTTPException(status_code=409, detail="Payment is not pending")

    provider = get_provider(intent.provider)
    if not provider.verify(intent, payload):
        raise HTTPException(status_code=400, detail="Payment verification failed")

    if intent.kind == "topup":
        _apply_topup(db, intent)
    elif intent.kind == "portal_renew":
        _apply_portal_renew(db, intent)
    else:
        raise HTTPException(status_code=400, detail="Unknown payment kind")

    intent.status = "completed"
    intent.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(intent)
    return intent


def get_intent_for_admin(db: Session, payment_id: int, admin_id: int) -> PaymentIntent:
    intent = db.query(PaymentIntent).filter(PaymentIntent.id == payment_id).first()
    if intent is None or intent.admin_id != admin_id:
        raise HTTPException(status_code=404, detail="Payment not found")
    return intent


def get_intent_for_user(db: Session, payment_id: int, user_id: int) -> PaymentIntent:
    intent = db.query(PaymentIntent).filter(PaymentIntent.id == payment_id).first()
    if intent is None or intent.user_id != user_id:
        raise HTTPException(status_code=404, detail="Payment not found")
    return intent


def list_online_providers() -> list[str]:
    return available_providers(online_only=True)
