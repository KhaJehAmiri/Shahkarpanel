from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import billing, feature_flags, xray
from app.billing.payments import (
    complete_payment,
    create_portal_payment,
    get_intent_for_user,
    list_online_providers,
    set_payment_card,
    submit_card_payment,
)
from app.billing.providers import portal_payment_methods
from app.dependencies import (
    get_subscription_context,
    get_validated_sub,
    resolve_sub_ctx,
)
from app.subscription.endpoint_resolver import SubscriptionRequestContext
from app.db import crud, get_db
from app.db.models import User
from app.login_limit import enforce_login_rate_limit
from app.models.portal_user import (
    PortalAccountCreateBody,
    PortalAccountRenewBody,
    PortalAccountSummary,
    PortalBootstrapBody,
    PortalBootstrapResponse,
    PortalCompleteSetupBody,
    PortalConfigs,
    PortalDailyUsage,
    PortalLinkItem,
    PortalNodeLink,
    PortalOrder,
    PortalPasswordBody,
    PortalPlan,
    PortalProfile,
    PortalRenewResponse,
    PortalSubTokenBody,
    PortalSubTokenResponse,
    PortalSubUrl,
    PortalToken,
    PortalTransaction,
    PortalTxReadResponse,
    PortalTxSummary,
    PortalUsageDay,
)
from app.models.user import UserResponse
from app.portal import (
    apply_plan_to_user,
    assert_can_add_account,
    create_account_from_plan,
    create_user_order,
    delete_owned_account,
    get_owned_account,
    list_owned_accounts,
    mark_order_applied,
)
from app import tenant as tenant_svc
from app.subscription.guards import subscription_access
from app.subscription.public_url import list_user_subscription_urls, public_subscription_url
from app.subscription.share import collect_v2ray_share_link_items, collect_v2ray_share_links
from app.tenant.plan_ops import assert_plan_for_user, get_plans_for_portal_user
from app.utils import responses
from app.utils.device_limit import account_is_online, count_online_devices
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
    # Invalidate tokens issued before the last password / setup change.
    # JWT ``iat`` is an integer second; DB reset_at has sub-second precision.
    # Comparing float(iat) < reset_at.timestamp() rejects tokens minted in the
    # same second as complete-setup (classic post-setup 401 on /me).
    reset_at = getattr(dbuser, "portal_password_reset_at", None)
    iat = payload.get("iat")
    if reset_at is not None and iat is not None:
        try:
            if int(float(iat)) < int(reset_at.timestamp()):
                raise HTTPException(status_code=401, detail="Session expired — sign in again")
        except HTTPException:
            raise
        except (TypeError, ValueError, AttributeError, OverflowError):
            pass
    return dbuser


def _portal_profile(
    dbuser: User,
    support_url: Optional[str] = None,
    *,
    owner: Optional[User] = None,
    live_devices: bool = False,
) -> PortalProfile:
    user = UserResponse.model_validate(dbuser, context={"skip_default_links": True})
    is_login = bool(dbuser.portal_enabled and getattr(dbuser, "hashed_portal_password", None))
    if owner is not None:
        is_login = dbuser.id == owner.id
    return PortalProfile(
        username=user.username,
        status=user.status.value,
        used_traffic=user.used_traffic,
        overage_traffic=int(getattr(user, "overage_traffic", 0) or 0),
        lifetime_used_traffic=int(getattr(user, "lifetime_used_traffic", 0) or 0),
        data_limit=user.data_limit,
        expire=user.expire,
        device_limit=getattr(dbuser, "device_limit", None),
        online_devices=count_online_devices(dbuser, live=live_devices),
        subscription_url=user.subscription_url,
        public_subscription_url=user.public_subscription_url,
        client_subscription_url=getattr(user, "client_subscription_url", "") or "",
        portal_url="/portal/",
        sub_token=getattr(dbuser, "sub_token", None),
        online=account_is_online(dbuser),
        online_at=getattr(user, "online_at", None),
        created_at=getattr(user, "created_at", None),
        note=getattr(dbuser, "note", None),
        support_url=support_url,
        is_portal_login=is_login,
        is_owned=True,
        must_change_credentials=bool(getattr(dbuser, "must_change_credentials", False)),
    )


def _account_summary(dbuser: User, *, owner: User) -> PortalAccountSummary:
    user = UserResponse.model_validate(dbuser, context={"skip_default_links": True})
    return PortalAccountSummary(
        username=user.username,
        status=user.status.value,
        used_traffic=user.used_traffic,
        data_limit=user.data_limit,
        expire=user.expire,
        online=account_is_online(dbuser),
        online_devices=count_online_devices(dbuser, live=False),
        is_portal_login=dbuser.id == owner.id,
        public_subscription_url=user.public_subscription_url or "",
        created_at=getattr(user, "created_at", None),
    )


def _resolve_support_url(db: Session, dbuser: User) -> Optional[str]:
    tenant_id = None
    if dbuser.admin_id:
        dbadmin = crud.get_admin_by_id(db, dbuser.admin_id)
        if dbadmin:
            tenant_id = dbadmin.tenant_id
    branding = tenant_svc.resolve_branding(db, tenant_id)
    url = (branding or {}).get("support_url") or None
    return url if url else None


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


@router.post("/bootstrap", response_model=PortalBootstrapResponse)
def portal_bootstrap(
    body: PortalBootstrapBody,
    request: Request,
    db: Session = Depends(get_db),
    sub_ctx: SubscriptionRequestContext = Depends(get_subscription_context),
):
    """Prepare portal login from a subscription token (public, token = ownership proof).

    Sets portal_enabled and initial password = username when needed, and marks
    ``must_change_credentials`` so the user must rename + set a real password.

    Accepts the same tokens as the subscribe page: ``sub_token``, legacy aliases
    (including reseller branding hosts), and JWT sub links.
    """
    _require_user_portal()
    token = (body.token or "").strip()
    if not token:
        raise HTTPException(status_code=404, detail="Subscription not found")
    sub_ctx = resolve_sub_ctx(sub_ctx, request, db)
    try:
        dbuser = get_validated_sub(token, request, db, sub_ctx)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Subscription not found") from None
    # Child accounts owned by another portal login cannot bootstrap as portal login
    if getattr(dbuser, "portal_owner_user_id", None):
        owner = crud.get_user_by_id(db, dbuser.portal_owner_user_id)
        if owner and owner.portal_enabled:
            dbuser = owner
    crud.ensure_portal_bootstrap(db, dbuser)
    return PortalBootstrapResponse(
        username=dbuser.username,
        must_change_credentials=bool(dbuser.must_change_credentials),
        portal_url="/portal/",
    )


@router.post("/complete-setup", response_model=PortalToken)
def portal_complete_setup(
    body: PortalCompleteSetupBody,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Forced first-login: change VPN username and portal password, return new JWT."""
    try:
        updated = crud.complete_portal_setup(
            db,
            dbuser,
            new_username=body.new_username,
            new_password=body.new_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PortalToken(access_token=create_portal_token(updated.username))


@router.get("/me", response_model=PortalProfile)
def portal_me(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Current user's subscription profile."""
    return _portal_profile(dbuser, support_url=_resolve_support_url(db, dbuser))


@router.get("/plans", response_model=List[PortalPlan])
def portal_plans(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Enabled commercial plans available for renewal / purchase."""
    _require_billing()
    return get_plans_for_portal_user(db, dbuser, enabled_only=True)


class RenewBody(BaseModel):
    plan_id: int
    username: Optional[str] = None


@router.post("/renew", response_model=PortalRenewResponse)
def portal_renew(
    body: RenewBody,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Renew an owned account (defaults to the portal login account)."""
    _require_billing()
    plan = crud.get_plan_by_id(db, body.plan_id)
    if not plan or not plan.enabled:
        raise HTTPException(status_code=404, detail="Plan not found")

    target = get_owned_account(db, dbuser, body.username or dbuser.username)
    assert_plan_for_user(db, dbuser.admin_id, plan)

    price = int(plan.price or 0)
    if price > 0:
        from app.billing.providers import portal_payment_methods

        billing_admin = crud.get_admin_by_id(db, dbuser.admin_id) if dbuser.admin_id else None
        if portal_payment_methods(billing_admin).get("methods"):
            raise HTTPException(
                status_code=402,
                detail="Use payment methods in the shop to purchase this plan",
            )
        if not dbuser.admin_id:
            raise HTTPException(
                status_code=402,
                detail="Use online payment for this plan",
            )
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
            description=f"Portal renewal for {target.username} — {plan.name}",
            reference=f"user:{target.id}:plan:{plan.id}",
        )

    order = create_user_order(db, target, plan, status="paid")
    target = apply_plan_to_user(db, target, plan)
    mark_order_applied(db, order)

    from app.models.user import UserStatus
    if target.status in (UserStatus.active, UserStatus.on_hold):
        xray.operations.sync_core_users()

    user = UserResponse.model_validate(target)
    return PortalRenewResponse(
        detail="Subscription renewed successfully",
        order_id=order.id,
        status=order.status,
        new_expire=user.expire,
        new_data_limit=user.data_limit,
    )


@router.get("/payment-providers", response_model=List[str])
def portal_payment_providers(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Online gateway PSPs for direct plan purchase."""
    _require_billing()
    from app.billing.payments import _billing_admin_id
    from app.billing.providers import filter_providers_for_admin

    billing_admin_id = _billing_admin_id(db, dbuser)
    dbadmin = crud.get_admin_by_id(db, billing_admin_id)
    return filter_providers_for_admin(list_online_providers(), dbadmin)


@router.get("/payment-methods")
def portal_payment_methods_endpoint(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Checkout methods configured for the portal (gateway and/or card-to-card)."""
    _require_billing()
    from app.billing.payments import _billing_admin_id

    billing_admin_id = _billing_admin_id(db, dbuser)
    dbadmin = crud.get_admin_by_id(db, billing_admin_id)
    return portal_payment_methods(dbadmin)


class PortalPaymentCardOut(BaseModel):
    id: str = ""
    number: str = ""
    holder: str = ""
    bank: str = ""


class PortalPaymentCreate(BaseModel):
    plan_id: int
    provider: str  # card | centralpay | stripe (demo only when explicitly enabled)
    action: str = "renew"  # renew | purchase
    username: Optional[str] = None
    new_username: Optional[str] = None
    card_id: Optional[str] = None


class PortalPaymentCreateResponse(BaseModel):
    payment_id: int
    amount: int
    provider: str
    status: str
    instructions: Optional[str] = None
    confirm_token: Optional[str] = None
    checkout_url: Optional[str] = None
    card_id: Optional[str] = None
    card_number: Optional[str] = None
    card_holder: Optional[str] = None
    card_bank: Optional[str] = None
    cards: List[PortalPaymentCardOut] = []
    action: str = "renew"
    username: Optional[str] = None


class PortalPaymentCompleteBody(BaseModel):
    confirm_token: Optional[str] = None


class PortalPaymentCompleteResponse(BaseModel):
    payment_id: int
    status: str
    detail: str
    new_expire: Optional[int] = None
    new_data_limit: Optional[int] = None
    username: Optional[str] = None


class PortalCardSubmitBody(BaseModel):
    note: Optional[str] = None


class PortalCardSelect(BaseModel):
    card_id: str


@router.post("/payments", response_model=PortalPaymentCreateResponse)
def portal_create_payment(
    body: PortalPaymentCreate,
    request: Request,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Start checkout for renew or new-account purchase."""
    _require_billing()
    from app.billing.payments import public_base_from_request

    intent, payload = create_portal_payment(
        db,
        dbuser,
        body.plan_id,
        body.provider,
        action=body.action,
        target_username=body.username,
        new_username=body.new_username,
        public_base=public_base_from_request(request),
        card_id=body.card_id,
    )
    extra = intent.extra or {}
    cards_raw = payload.get("cards") or []
    return PortalPaymentCreateResponse(
        payment_id=intent.id,
        amount=intent.amount,
        provider=intent.provider,
        status=intent.status,
        instructions=payload.get("instructions"),
        confirm_token=payload.get("confirm_token"),
        checkout_url=payload.get("checkout_url"),
        card_id=payload.get("card_id") or extra.get("card_id"),
        card_number=payload.get("card_number"),
        card_holder=payload.get("card_holder"),
        card_bank=payload.get("card_bank"),
        cards=[PortalPaymentCardOut(**c) for c in cards_raw if isinstance(c, dict)],
        action=str(extra.get("action") or body.action),
        username=extra.get("new_username") or extra.get("target_username"),
    )


@router.post("/payments/{payment_id}/complete", response_model=PortalPaymentCompleteResponse)
def portal_complete_payment(
    payment_id: int,
    body: PortalPaymentCompleteBody,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Confirm gateway payment (renew or purchase)."""
    _require_billing()
    intent = get_intent_for_user(db, payment_id, dbuser.id)
    if intent.kind not in ("portal_renew", "portal_purchase"):
        raise HTTPException(status_code=400, detail="Not a portal payment")
    if intent.provider == "card":
        raise HTTPException(
            status_code=400,
            detail="Card payments must be submitted for review, then approved by your provider",
        )
    if intent.provider == "demo":
        from app import platform_settings as ps

        if not ps.get_bool("payment.demo_enabled", False):
            raise HTTPException(status_code=403, detail="Demo gateway is disabled")
    intent = complete_payment(db, intent, body.model_dump(exclude_unset=True))
    extra = intent.extra or {}
    uname = extra.get("created_username") or extra.get("target_username") or dbuser.username
    target = crud.get_user(db, uname) or dbuser
    user = UserResponse.model_validate(target)
    return PortalPaymentCompleteResponse(
        payment_id=intent.id,
        status=intent.status,
        detail="Purchase completed" if intent.kind == "portal_purchase" else "Subscription renewed successfully",
        new_expire=user.expire,
        new_data_limit=user.data_limit,
        username=user.username,
    )


@router.put("/payments/{payment_id}/card", response_model=PortalPaymentCreateResponse)
def portal_select_payment_card(
    payment_id: int,
    body: PortalCardSelect,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Switch which card a pending portal payment should use (swipe UI)."""
    _require_billing()
    from app.billing.payments import _billing_admin_id
    from app.billing.providers import list_cards_for_admin, public_card_payload

    intent = get_intent_for_user(db, payment_id, dbuser.id)
    if intent.kind not in ("portal_renew", "portal_purchase"):
        raise HTTPException(status_code=400, detail="Not a portal payment")
    intent = set_payment_card(db, intent, body.card_id)
    extra = intent.extra or {}
    billing_admin_id = _billing_admin_id(db, dbuser)
    dbadmin = crud.get_admin_by_id(db, billing_admin_id)
    cards = [PortalPaymentCardOut(**public_card_payload(c)) for c in list_cards_for_admin(dbadmin)]
    return PortalPaymentCreateResponse(
        payment_id=intent.id,
        amount=intent.amount,
        provider=intent.provider,
        status=intent.status,
        card_id=extra.get("card_id"),
        card_number=extra.get("card_number"),
        card_holder=extra.get("card_holder"),
        card_bank=extra.get("card_bank"),
        cards=cards,
        action=str(extra.get("action") or "renew"),
        username=extra.get("new_username") or extra.get("target_username"),
    )


@router.post("/payments/{payment_id}/submit")
def portal_submit_card_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
    note: Optional[str] = Form(None),
    receipt: UploadFile = File(...),
):
    """User confirms card transfer with receipt — waits for admin/reseller approval."""
    _require_billing()
    intent = get_intent_for_user(db, payment_id, dbuser.id)
    if intent.kind not in ("portal_renew", "portal_purchase"):
        raise HTTPException(status_code=400, detail="Not a portal payment")
    from app.billing.receipts import save_receipt

    meta = save_receipt(intent.id, receipt)
    intent = submit_card_payment(db, intent, note=note, receipt_meta=meta)
    return {
        "payment_id": intent.id,
        "status": intent.status,
        "detail": "Purchase submitted for review",
        "has_receipt": True,
        "action": (intent.extra or {}).get("action"),
        "username": (intent.extra or {}).get("new_username")
        or (intent.extra or {}).get("target_username"),
    }


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


class PortalPushSubscribeBody(BaseModel):
    endpoint: str
    keys: dict
    expirationTime: Optional[float] = None


@router.get("/push/vapid-public-key")
def portal_vapid_public_key(dbuser: User = Depends(get_current_portal_user)):
    from app.web_push import public_vapid_key

    try:
        return {"publicKey": public_vapid_key()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Push unavailable: {exc}") from exc


@router.post("/push/subscribe")
def portal_push_subscribe(
    body: PortalPushSubscribeBody,
    request: Request,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    from app import portal_push

    keys = body.keys or {}
    try:
        portal_push.upsert_subscription(
            db,
            user_id=int(dbuser.id),
            endpoint=body.endpoint,
            p256dh=str(keys.get("p256dh") or ""),
            auth=str(keys.get("auth") or ""),
            user_agent=(request.headers.get("user-agent") or "")[:512],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/push/unsubscribe")
def portal_push_unsubscribe(
    body: PortalPushSubscribeBody,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    from app import portal_push

    portal_push.delete_subscription(
        db, user_id=int(dbuser.id), endpoint=body.endpoint
    )
    return {"ok": True}


@router.get("/push/badge")
def portal_push_badge(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Home-screen badge = unread transaction messages (Telegram/X style)."""
    from app import portal_tx

    intents = portal_tx.list_transactions_for_portal_user(db, dbuser, limit=50)
    reads = portal_tx.get_tx_read_ids(dbuser)
    unread = sum(1 for i in intents if int(i.id) not in reads)
    try:
        if int(getattr(dbuser, "portal_unread", 0) or 0) != unread:
            dbuser.portal_unread = unread
            db.add(dbuser)
            db.commit()
    except Exception:
        pass
    return {"count": unread}


@router.post("/push/badge/clear")
def portal_push_badge_clear(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Do not wipe unread messages — only return the live unread count.

    Opening the app must not mark everything read; that happens when the user
    opens a transaction detail.
    """
    return portal_push_badge(db=db, dbuser=dbuser)


@router.get("/orders", response_model=List[PortalOrder])
def portal_orders(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Purchase history for this portal login (own + purchased accounts)."""
    _require_billing()
    orders = []
    for account in list_owned_accounts(db, dbuser):
        orders.extend(crud.list_user_orders(db, account.id))
    orders.sort(key=lambda o: o.created_at or datetime.min, reverse=True)
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


@router.get("/transactions", response_model=List[PortalTransaction])
def portal_transactions(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Message-style payment transactions (card + gateway) for this portal login."""
    _require_billing()
    from app import portal_tx

    intents = portal_tx.list_transactions_for_portal_user(db, dbuser, limit=50)
    reads = portal_tx.get_tx_read_ids(dbuser)
    out: List[PortalTransaction] = []
    for intent in intents:
        extra = intent.extra or {}
        plan = crud.get_plan_by_id(db, intent.plan_id) if intent.plan_id else None
        plan_name = extra.get("plan_name") or (plan.name if plan else None)
        title, body, lines = portal_tx.build_tx_message(intent, plan_name=plan_name)
        # Prefer persisted snapshot (matches notification) when present
        if extra.get("tx_title") and extra.get("tx_body"):
            title = str(extra["tx_title"])
            body = str(extra["tx_body"])
            if isinstance(extra.get("tx_lines"), list) and extra["tx_lines"]:
                lines = [str(x) for x in extra["tx_lines"]]
        when = intent.completed_at or intent.created_at
        date_s, time_s = portal_tx.format_datetime_fa(when)
        pid = int(intent.id)
        out.append(
            PortalTransaction(
                id=pid,
                kind=intent.kind or "",
                kind_label=portal_tx.kind_label_fa(intent.kind or "", extra.get("action")),
                provider=intent.provider or "",
                provider_label=portal_tx.provider_label_fa(intent.provider or ""),
                amount=int(intent.amount or 0),
                amount_label=portal_tx.format_amount_fa(int(intent.amount or 0)),
                status=intent.status or "",
                status_label=portal_tx.status_label_fa(intent.status or ""),
                plan_id=intent.plan_id,
                plan_name=plan_name,
                account=portal_tx.intent_account_name(intent) or None,
                title=title,
                body=body,
                lines=lines,
                date=date_s,
                time=time_s,
                created_at=intent.created_at,
                completed_at=intent.completed_at,
                unread=pid not in reads,
            )
        )
    # Keep home-screen badge aligned with unread messages
    try:
        unread_n = sum(1 for t in out if t.unread)
        if int(getattr(dbuser, "portal_unread", 0) or 0) != unread_n:
            dbuser.portal_unread = unread_n
            db.add(dbuser)
            db.commit()
    except Exception:
        pass
    return out


@router.get("/transactions/summary", response_model=PortalTxSummary)
def portal_transactions_summary(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    _require_billing()
    from app import portal_tx

    intents = portal_tx.list_transactions_for_portal_user(db, dbuser, limit=50)
    reads = portal_tx.get_tx_read_ids(dbuser)
    unread = sum(1 for i in intents if int(i.id) not in reads)
    read_n = sum(1 for i in intents if int(i.id) in reads)
    return PortalTxSummary(unread_count=unread, read_count=read_n)


@router.post("/transactions/{payment_id}/read", response_model=PortalTxReadResponse)
def portal_transaction_mark_read(
    payment_id: int,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Open detail → mark transaction message as read."""
    _require_billing()
    from app import portal_tx

    result = portal_tx.mark_transaction_read(db, dbuser, payment_id)
    return PortalTxReadResponse(**result)


@router.post("/rotate-sub", response_model=PortalSubTokenResponse)
def portal_rotate_sub(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Generate a new random subscription id (old link stops working)."""
    dbuser = crud.rotate_user_sub_link(db, dbuser)
    profile = _portal_profile(dbuser, support_url=_resolve_support_url(db, dbuser))
    return PortalSubTokenResponse(
        detail="Subscription id rotated",
        sub_token=dbuser.sub_token or "",
        subscription_url=profile.subscription_url,
        public_subscription_url=profile.public_subscription_url,
    )


@router.post("/sub-token", response_model=PortalSubTokenResponse)
def portal_set_sub_token(
    body: PortalSubTokenBody,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Set a custom subscription id, or auto-generate when token is omitted."""
    try:
        if body.token:
            dbuser = crud.set_user_sub_token(db, dbuser, body.token)
            detail = "Subscription id updated"
        else:
            dbuser = crud.rotate_user_sub_link(db, dbuser)
            detail = "Subscription id rotated"
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    profile = _portal_profile(dbuser, support_url=_resolve_support_url(db, dbuser))
    return PortalSubTokenResponse(
        detail=detail,
        sub_token=dbuser.sub_token or "",
        subscription_url=profile.subscription_url,
        public_subscription_url=profile.public_subscription_url,
    )


@router.post("/password")
def portal_change_password(
    body: PortalPasswordBody,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Change portal login password (requires current password).

    Setting a password bumps ``portal_password_reset_at``, which invalidates
    every token issued earlier — including the caller's. A fresh token is
    returned so the current session survives the change instead of dropping
    into a half-loaded 401 state.
    """
    from app.models.admin import pwd_context

    if not dbuser.hashed_portal_password or not pwd_context.verify(
        body.current_password, dbuser.hashed_portal_password
    ):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    try:
        crud.set_portal_password(db, dbuser, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "detail": "Password updated",
        "access_token": create_portal_token(dbuser.username),
        "token_type": "bearer",
    }


@router.get("/configs", response_model=PortalConfigs)
def portal_configs(
    request: Request,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Share links, format URLs and protocol nodes for the logged-in user."""
    user = UserResponse.model_validate(dbuser, context={"skip_default_links": True})
    access = subscription_access(user)
    pub_url = public_subscription_url(user, request) or (user.public_subscription_url or "")
    from app.subscription.userinfo import subscription_client_import_url
    from app.tenant import subscription_brand_title

    tenant_id = None
    if dbuser.admin_id:
        dbadmin = crud.get_admin_by_id(db, dbuser.admin_id)
        if dbadmin:
            tenant_id = dbadmin.tenant_id
    branding = tenant_svc.resolve_branding(db, tenant_id)
    brand = subscription_brand_title(branding) or None
    client_url = subscription_client_import_url(pub_url, user, brand=brand) if pub_url else ""

    if not access["config_available"]:
        return PortalConfigs(
            config_available=False,
            block_reason=access.get("block_reason"),
            public_subscription_url="",
            client_subscription_url="",
        )

    sub_urls_raw = list_user_subscription_urls(user, request)
    sub_urls = [
        PortalSubUrl(
            label=str(u.get("label") or u.get("slug") or ""),
            slug=str(u.get("slug") or ""),
            url=str(u.get("url") or ""),
            import_url=u.get("import_url"),
            export_mode=u.get("export_mode"),
            recommended=bool(u.get("recommended", False)),
        )
        for u in sub_urls_raw
        if u.get("url")
    ]

    link_items = [
        PortalLinkItem.model_validate(item)
        for item in collect_v2ray_share_link_items(user, reverse=False)
    ]
    links = collect_v2ray_share_links(user, reverse=False)

    wg_nodes: List[PortalNodeLink] = []
    sb_nodes: List[PortalNodeLink] = []
    try:
        from app.routers.subscription import _attach_subscription_share_links

        payload: dict = {}
        _attach_subscription_share_links(db, dbuser, payload)

        from app.routers.subscription import _wireguard_user_settings
        from app.subscription.region_display import node_config_remark
        from app.subscription.wireguard import user_config as wg_user_config
        from app.subscription.wireguard import user_xray_wg_conf
        from app.wireguard.sync import plain_wg_enabled
        from app.wireguard.xray_native import xray_native_wg_enabled

        wg_settings = _wireguard_user_settings(dbuser)
        nodes_by_id = {
            int(n.id): n
            for n in crud.get_wireguard_nodes(db)
            if n.wireguard is not None
        }

        for n in payload.get("wireguard_nodes") or []:
            # Prefer plain .conf / conf URI for app QR + download — never WireGuard Xray.
            uri = (
                n.get("wireguard_plain_uri")
                or n.get("wireguard_uri")
                or n.get("wireguard_direct_uri")
            )
            # Skip Finalmask / Xray-only share links (wireguard://…fm=).
            if uri and ("fm=" in str(uri) or "fm%3D" in str(uri).lower()):
                uri = n.get("wireguard_plain_uri") or n.get("wireguard_direct_uri")

            node_id = int(n.get("id") or 0)
            dbnode = nodes_by_id.get(node_id)
            conf_text = None
            if wg_settings and dbnode is not None and dbnode.wireguard is not None:
                cfg = dbnode.wireguard
                if plain_wg_enabled(cfg):
                    conf_text = wg_user_config(wg_settings, dbnode, variant="plain", db=db)
                elif xray_native_wg_enabled(cfg):
                    conf_text = user_xray_wg_conf(
                        wg_settings,
                        dbnode,
                        db=db,
                        remark=node_config_remark(dbnode, "WireGuard"),
                    )

            # Official WireGuard Android/iOS only import wg-quick INI — not wireguard://.
            # Prefer conf for link so QR + download work in the stock app.
            export = (conf_text or "").strip() or None
            if not export and not uri:
                continue
            wg_nodes.append(
                PortalNodeLink(
                    id=node_id,
                    name=str(n.get("name") or ""),
                    address=str(n.get("address") or ""),
                    region=n.get("region"),
                    region_flag=n.get("region_flag"),
                    region_name=n.get("region_name"),
                    latency_ms=n.get("latency_ms"),
                    link=export or uri,
                    conf=export,
                    protocol="wireguard",
                )
            )
        for n in payload.get("singbox_nodes") or []:
            region = n.get("region")
            region_flag = n.get("region_flag")
            region_name = n.get("region_name")
            latency_ms = n.get("latency_ms")
            base = dict(
                id=int(n.get("id") or 0),
                name=str(n.get("name") or ""),
                address=str(n.get("address") or ""),
                region=region,
                region_flag=region_flag,
                region_name=region_name,
                latency_ms=latency_ms,
            )
            # One card per available protocol (same node can expose hy2 + tuic + anytls).
            for key, proto in (
                ("hysteria2_link", "hysteria2"),
                ("tuic_link", "tuic"),
                ("anytls_link", "anytls"),
            ):
                link = n.get(key)
                if not link:
                    continue
                sb_nodes.append(
                    PortalNodeLink(
                        **base,
                        link=link,
                        protocol=proto,
                    )
                )
    except Exception:
        pass

    return PortalConfigs(
        config_available=True,
        public_subscription_url=pub_url,
        client_subscription_url=client_url or "",
        subscription_urls=sub_urls,
        link_items=link_items,
        links=links,
        wireguard_nodes=wg_nodes,
        singbox_nodes=sb_nodes,
    )


@router.get("/usage/daily", response_model=PortalDailyUsage)
def portal_daily_usage(
    days: int = 14,
    username: Optional[str] = None,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Daily traffic buckets for the usage chart."""
    target = get_owned_account(db, dbuser, username or dbuser.username)
    series = crud.get_user_daily_usages(db, target, days=days)
    rows = [
        PortalUsageDay(
            date=d.date if hasattr(d, "date") else str(getattr(d, "day", "")),
            used_traffic=int(getattr(d, "used_traffic", 0) or 0),
        )
        for d in series
    ]
    total = sum(r.used_traffic for r in rows)
    return PortalDailyUsage(username=target.username, days=rows, total=total)


@router.get("/accounts", response_model=List[PortalAccountSummary])
def portal_list_accounts(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """All VPN accounts owned by this portal login (self + purchased)."""
    return [_account_summary(u, owner=dbuser) for u in list_owned_accounts(db, dbuser)]


@router.get("/accounts/{username}", response_model=PortalProfile)
def portal_get_account(
    username: str,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    target = get_owned_account(db, dbuser, username)
    return _portal_profile(target, support_url=_resolve_support_url(db, dbuser), owner=dbuser)


@router.post("/accounts", response_model=PortalProfile)
def portal_create_account(
    body: PortalAccountCreateBody,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Create a new VPN account from a free plan (paid plans use /payments action=purchase)."""
    _require_billing()
    plan = crud.get_plan_by_id(db, body.plan_id)
    if not plan or not plan.enabled:
        raise HTTPException(status_code=404, detail="Plan not found")
    assert_plan_for_user(db, dbuser.admin_id, plan)
    price = int(plan.price or 0)
    if price > 0:
        raise HTTPException(
            status_code=402,
            detail="Paid plans require checkout via /api/portal/payments with action=purchase",
        )
    assert_can_add_account(db, dbuser)
    created = create_account_from_plan(db, dbuser, plan, body.username)
    order = create_user_order(db, created, plan, status="paid")
    mark_order_applied(db, order)
    return _portal_profile(created, owner=dbuser)


@router.post("/accounts/{username}/renew", response_model=PortalRenewResponse)
def portal_renew_account(
    username: str,
    body: PortalAccountRenewBody,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    """Renew a specific owned account (free plans only when payment methods are configured)."""
    return portal_renew(
        RenewBody(plan_id=body.plan_id, username=username),
        db=db,
        dbuser=dbuser,
    )


@router.delete("/accounts/{username}")
def portal_delete_account(
    username: str,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    delete_owned_account(db, dbuser, username)
    return {"detail": "Account deleted", "username": username}


@router.get("/accounts/{username}/configs", response_model=PortalConfigs)
def portal_account_configs(
    username: str,
    request: Request,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    target = get_owned_account(db, dbuser, username)
    return portal_configs(request=request, db=db, dbuser=target)


@router.post("/accounts/{username}/rotate-sub", response_model=PortalSubTokenResponse)
def portal_account_rotate_sub(
    username: str,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    target = get_owned_account(db, dbuser, username)
    target = crud.rotate_user_sub_link(db, target)
    profile = _portal_profile(target, support_url=_resolve_support_url(db, dbuser), owner=dbuser)
    return PortalSubTokenResponse(
        detail="Subscription id rotated",
        sub_token=target.sub_token or "",
        subscription_url=profile.subscription_url,
        public_subscription_url=profile.public_subscription_url,
    )


@router.post("/accounts/{username}/sub-token", response_model=PortalSubTokenResponse)
def portal_account_set_sub_token(
    username: str,
    body: PortalSubTokenBody,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_portal_user),
):
    target = get_owned_account(db, dbuser, username)
    try:
        if body.token:
            target = crud.set_user_sub_token(db, target, body.token)
            detail = "Subscription id updated"
        else:
            target = crud.rotate_user_sub_link(db, target)
            detail = "Subscription id rotated"
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    profile = _portal_profile(target, support_url=_resolve_support_url(db, dbuser), owner=dbuser)
    return PortalSubTokenResponse(
        detail=detail,
        sub_token=target.sub_token or "",
        subscription_url=profile.subscription_url,
        public_subscription_url=profile.public_subscription_url,
    )
