from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import billing, feature_flags, xray
from app.billing.payments import (
    complete_payment,
    create_portal_payment,
    get_intent_for_user,
    list_online_providers,
)
from app.db import crud, get_db
from app.db.models import User
from app.login_limit import enforce_login_rate_limit
from app.models.portal_user import (
    PortalOrder,
    PortalPlan,
    PortalProfile,
    PortalRenewResponse,
    PortalToken,
)
from app.models.user import UserResponse
from app.portal import apply_plan_to_user, create_user_order, mark_order_applied
from app import tenant as tenant_svc
from app.tenant.plan_ops import assert_plan_for_user, get_plans_for_user_reseller
from app.utils import responses
from app.utils.jwt import create_portal_token, get_portal_payload
from config import LOGIN_MAX_ATTEMPTS, LOGIN_MAX_WINDOW_SECONDS

router = APIRouter(
    tags=["Portal"],
    prefix="/api/portal",
    responses={401: responses._401},
)


def _require_user_portal():
    if not feature_flags.is_enabled("user_portal"):
        raise HTTPException(status_code=404, detail="User portal is disabled")


def _require_billing():
    if not feature_flags.is_enabled("billing"):
        raise HTTPException(status_code=404, detail="Billing is disabled")


def get_current_portal_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    _require_user_portal()
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = get_portal_payload(auth[7:])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    dbuser = crud.get_user(db, payload["username"])
    if not dbuser or not dbuser.portal_enabled:
        raise HTTPException(status_code=401, detail="Portal access disabled")
    return dbuser


def _portal_profile(dbuser: User) -> PortalProfile:
    user = UserResponse.model_validate(dbuser)
    return PortalProfile(
        username=user.username,
        status=user.status.value,
        used_traffic=user.used_traffic,
        data_limit=user.data_limit,
        expire=user.expire,
        subscription_url=user.subscription_url,
        public_subscription_url=user.public_subscription_url,
        portal_url="/portal/",
    )


@router.post("/token", response_model=PortalToken)
def portal_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Authenticate an end-user and issue a portal JWT."""
    _require_user_portal()
    enforce_login_rate_limit(
        request,
        max_attempts=LOGIN_MAX_ATTEMPTS,
        window_seconds=LOGIN_MAX_WINDOW_SECONDS,
    )
    dbuser = crud.verify_portal_user(db, form_data.username, form_data.password)
    if not dbuser:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return PortalToken(access_token=create_portal_token(dbuser.username))


@router.get("/me", response_model=PortalProfile)
def portal_me(dbuser: User = Depends(get_current_portal_user)):
    """Current user's subscription profile."""
    return _portal_profile(dbuser)


@router.get("/plans", response_model=List[PortalPlan])
def portal_plans(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Enabled commercial plans available for renewal."""
    _require_billing()
    if not dbuser.admin_id:
        return []
    return get_plans_for_user_reseller(db, dbuser.admin_id, enabled_only=True)


class RenewBody(BaseModel):
    plan_id: int


@router.post("/renew", response_model=PortalRenewResponse)
def portal_renew(
    body: RenewBody,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Purchase a plan: debits the owning reseller's wallet and renews immediately."""
    _require_billing()
    plan = crud.get_plan_by_id(db, body.plan_id)
    if not plan or not plan.enabled:
        raise HTTPException(status_code=404, detail="Plan not found")

    if not dbuser.admin_id:
        raise HTTPException(status_code=400, detail="User has no owning reseller")
    assert_plan_for_user(db, dbuser.admin_id, plan)

    price = int(plan.price or 0)
    if price > 0:
        wallet = billing.get_or_create_wallet(db, dbuser.admin_id)
        if wallet.balance < price:
            raise HTTPException(
                status_code=402,
                detail="Reseller wallet has insufficient balance — contact your provider",
            )
        billing.add_transaction(
            db,
            dbuser.admin_id,
            -price,
            type="portal_renew",
            description=f"Portal renewal for {dbuser.username} — {plan.name}",
            reference=f"user:{dbuser.id}:plan:{plan.id}",
        )

    order = create_user_order(db, dbuser, plan, status="paid")
    dbuser = apply_plan_to_user(db, dbuser, plan)
    mark_order_applied(db, order)

    from app.models.user import UserStatus
    if dbuser.status in (UserStatus.active, UserStatus.on_hold):
        xray.operations.sync_core_users()

    user = UserResponse.model_validate(dbuser)
    return PortalRenewResponse(
        detail="Subscription renewed successfully",
        order_id=order.id,
        status=order.status,
        new_expire=user.expire,
        new_data_limit=user.data_limit,
    )


@router.get("/payment-providers", response_model=List[str])
def portal_payment_providers(
    _: User = Depends(get_current_portal_user),
):
    """Online PSPs for direct plan purchase (no reseller wallet debit)."""
    _require_billing()
    return list_online_providers()


class PortalPaymentCreate(BaseModel):
    plan_id: int
    provider: str = "demo"


class PortalPaymentCreateResponse(BaseModel):
    payment_id: int
    amount: int
    provider: str
    status: str
    instructions: Optional[str] = None
    confirm_token: Optional[str] = None


class PortalPaymentCompleteBody(BaseModel):
    confirm_token: Optional[str] = None


class PortalPaymentCompleteResponse(BaseModel):
    payment_id: int
    status: str
    detail: str
    new_expire: Optional[int] = None
    new_data_limit: Optional[int] = None


@router.post("/payments", response_model=PortalPaymentCreateResponse)
def portal_create_payment(
    body: PortalPaymentCreate,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Start a direct plan purchase via PSP (bypasses reseller wallet)."""
    _require_billing()
    intent, payload = create_portal_payment(db, dbuser, body.plan_id, body.provider)
    return PortalPaymentCreateResponse(
        payment_id=intent.id,
        amount=intent.amount,
        provider=intent.provider,
        status=intent.status,
        instructions=payload.get("instructions"),
        confirm_token=payload.get("confirm_token"),
    )


@router.post("/payments/{payment_id}/complete", response_model=PortalPaymentCompleteResponse)
def portal_complete_payment(
    payment_id: int,
    body: PortalPaymentCompleteBody,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Confirm PSP payment and renew the subscription."""
    _require_billing()
    intent = get_intent_for_user(db, payment_id, dbuser.id)
    if intent.kind != "portal_renew":
        raise HTTPException(status_code=400, detail="Not a renewal payment")
    intent = complete_payment(db, intent, body.model_dump(exclude_unset=True))
    dbuser = crud.get_user(db, dbuser.username)
    user = UserResponse.model_validate(dbuser)
    return PortalPaymentCompleteResponse(
        payment_id=intent.id,
        status=intent.status,
        detail="Subscription renewed successfully",
        new_expire=user.expire,
        new_data_limit=user.data_limit,
    )


@router.get("/branding")
def portal_branding(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Branding for the end-user portal (resolved via owning reseller)."""
    from app import platform_settings

    tenant_id = None
    if dbuser.admin_id:
        dbadmin = crud.get_admin_by_id(db, dbuser.admin_id)
        if dbadmin:
            tenant_id = dbadmin.tenant_id
    branding = dict(tenant_svc.resolve_branding(db, tenant_id))
    # The portal renders plan prices; tell it what label to use ("تومان", "USD", …).
    branding["currency_label"] = platform_settings.get_setting("billing.currency_label") or ""
    return branding


@router.get("/orders", response_model=List[PortalOrder])
def portal_orders(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Purchase history for the current user."""
    _require_billing()
    orders = crud.list_user_orders(db, dbuser.id)
    result = []
    for o in orders:
        plan = crud.get_plan_by_id(db, o.plan_id)
        result.append(
            PortalOrder(
                id=o.id,
                plan_id=o.plan_id,
                plan_name=plan.name if plan else f"#{o.plan_id}",
                amount=o.amount,
                status=o.status,
                created_at=o.created_at,
                paid_at=o.paid_at,
                applied_at=o.applied_at,
            )
        )
    return result
