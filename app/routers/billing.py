from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from app import billing, feature_flags
from app.billing.mrr import compute_mrr
from app.billing.payments import (
    approve_portal_payment,
    complete_payment,
    create_topup_payment,
    get_intent_for_admin,
    get_intent_for_admin_or_sudo,
    list_online_providers,
    list_portal_payments_for_admin,
    public_base_from_request,
    reject_portal_payment,
    set_payment_card,
    submit_card_payment,
)
from app.billing.usage_billing import usage_summary_for_admin
from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.rbac import require_permission
from app.utils import responses

router = APIRouter(
    tags=["Billing"],
    prefix="/api/billing",
    responses={401: responses._401, 403: responses._403},
)


def _require_billing_enabled():
    if not feature_flags.is_enabled("billing"):
        raise HTTPException(status_code=404, detail="Billing is disabled")


def _admin_id(db: Session, admin: Admin) -> int:
    dbadmin = crud.get_admin(db, admin.username)
    if dbadmin is None:
        raise HTTPException(
            status_code=400,
            detail="Billing requires a database-backed admin (env SUDOERS have no wallet)",
        )
    return dbadmin.id


class WalletResponse(BaseModel):
    admin_id: int
    balance: int
    model_config = ConfigDict(from_attributes=True)


class CreditRequest(BaseModel):
    username: str
    amount: int
    description: Optional[str] = None


class AdjustRequest(BaseModel):
    """Sudo wallet correction: set absolute balance or apply a signed delta."""

    username: str
    mode: str  # "set" | "delta"
    amount: int
    description: Optional[str] = None


class InvoiceCreate(BaseModel):
    username: Optional[str] = None
    amount: int
    plan_id: Optional[int] = None
    provider: Optional[str] = "manual"
    description: Optional[str] = None


class InvoiceResponse(BaseModel):
    id: int
    admin_id: int
    plan_id: Optional[int] = None
    amount: int
    status: str
    provider: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class TransactionResponse(BaseModel):
    id: int
    admin_id: int
    amount: int
    type: str
    description: Optional[str] = None
    reference: Optional[str] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


@router.get("/providers", response_model=List[str])
def list_providers(_: Admin = Depends(require_permission("billing:read"))):
    _require_billing_enabled()
    return billing.available_providers()


@router.get("/payment-providers", response_model=List[str])
def list_payment_providers(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    """Providers available for reseller self-service wallet top-up (gateway + card)."""
    _require_billing_enabled()
    from app.billing.providers import topup_providers_for_admin

    dbadmin = crud.get_admin(db, admin.username)
    return topup_providers_for_admin(dbadmin)


@router.get("/wallet", response_model=WalletResponse)
def my_wallet(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    _require_billing_enabled()
    dbadmin = crud.get_admin(db, admin.username)
    if dbadmin is None:
        if admin.is_sudo:
            return WalletResponse(admin_id=0, balance=0)
        raise HTTPException(
            status_code=400,
            detail="Billing requires a database-backed admin (env SUDOERS have no wallet)",
        )
    return billing.get_or_create_wallet(db, dbadmin.id)


def _after_wallet_topup(db: Session, target) -> None:
    """Catch up held GB charges and restore capped users after a balance change."""
    reactivated: list[int] = []
    try:
        from app.billing.usage_billing import bill_reseller_usage
        from app.quota import enforce_reseller_traffic_caps

        bill_reseller_usage(db, target)
        _newly, reactivated = enforce_reseller_traffic_caps(db)
    except Exception:
        pass
    if reactivated:
        try:
            from app.quota import restore_users_everywhere

            restore_users_everywhere(reactivated)
        except Exception:
            pass


@router.post("/credit", response_model=WalletResponse)
def add_credit(
    body: CreditRequest,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Top up an admin's wallet. Sudo only."""
    _require_billing_enabled()
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    target = crud.get_admin(db, body.username)
    if target is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    billing.add_transaction(
        db,
        target.id,
        body.amount,
        type="credit",
        description=body.description or f"Manual credit by master ({body.amount})",
    )
    _after_wallet_topup(db, target)
    return billing.get_or_create_wallet(db, target.id)


@router.post("/adjust", response_model=WalletResponse)
def adjust_wallet(
    body: AdjustRequest,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Set absolute balance or apply a signed delta. Sudo only.

    ``mode=set`` writes a ledger delta so ``balance == sum(transactions)`` stays true.
    ``mode=delta`` credits (positive) or debits (negative) by ``amount``.
    """
    _require_billing_enabled()
    mode = (body.mode or "").strip().lower()
    if mode not in ("set", "delta"):
        raise HTTPException(status_code=400, detail="mode must be 'set' or 'delta'")
    target = crud.get_admin(db, body.username)
    if target is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    if target.is_sudo:
        raise HTTPException(status_code=400, detail="Cannot adjust a sudo wallet")

    wallet = billing.get_or_create_wallet(db, target.id)
    if mode == "set":
        if body.amount < 0:
            raise HTTPException(status_code=400, detail="set amount must be >= 0")
        delta = int(body.amount) - int(wallet.balance)
        if delta == 0:
            return wallet
        tx_type = "credit" if delta > 0 else "debit"
        desc = body.description or f"Manual balance set to {body.amount} by master"
    else:
        delta = int(body.amount)
        if delta == 0:
            raise HTTPException(status_code=400, detail="delta amount must be non-zero")
        tx_type = "credit" if delta > 0 else "debit"
        desc = body.description or f"Manual wallet {tx_type} by master ({delta})"

    billing.add_transaction(
        db,
        target.id,
        delta,
        type=tx_type,
        description=desc,
        skip_commission=True,
    )
    _after_wallet_topup(db, target)
    return billing.get_or_create_wallet(db, target.id)


@router.post("/invoices", response_model=InvoiceResponse)
def create_invoice(
    body: InvoiceCreate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:write")),
):
    _require_billing_enabled()
    # Non-sudo admins can only invoice themselves.
    if body.username and not admin.is_sudo and body.username != admin.username:
        raise HTTPException(status_code=403, detail="Cannot invoice other admins")
    target_username = body.username or admin.username
    target = crud.get_admin(db, target_username)
    if target is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    invoice = billing.create_invoice(
        db,
        target.id,
        body.amount,
        plan_id=body.plan_id,
        provider=body.provider,
        description=body.description,
    )
    try:
        from app.web_push import notify_invoice_created

        notify_invoice_created(db, invoice)
    except Exception:
        pass
    return invoice


@router.get("/invoices", response_model=List[InvoiceResponse])
def list_invoices(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    _require_billing_enabled()
    from app.db.models import Invoice

    query = db.query(Invoice)
    if not admin.is_sudo:
        query = query.filter(Invoice.admin_id == _admin_id(db, admin))
    return query.order_by(Invoice.id.desc()).limit(100).all()


class AttentionCounts(BaseModel):
    orders: int = 0
    invoices: int = 0


@router.get("/attention-counts", response_model=AttentionCounts)
def billing_attention_counts(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    """Sidebar badge counts: card orders awaiting review + unpaid invoices."""
    _require_billing_enabled()
    from sqlalchemy import and_, func, or_

    from app.db.models import Invoice, PaymentIntent

    dbadmin = crud.get_admin(db, admin.username)
    scope = dbadmin if dbadmin is not None else admin
    is_sudo = bool(getattr(scope, "is_sudo", False))
    admin_pk = getattr(scope, "id", None)

    orders_q = db.query(func.count(PaymentIntent.id)).filter(
        PaymentIntent.provider == "card",
        PaymentIntent.status == "awaiting_review",
    )
    if is_sudo:
        orders_q = orders_q.filter(
            or_(
                PaymentIntent.kind.in_(("portal_renew", "portal_purchase")),
                PaymentIntent.kind == "topup",
            )
        )
    elif admin_pk is not None:
        orders_q = orders_q.filter(
            PaymentIntent.kind.in_(("portal_renew", "portal_purchase")),
            PaymentIntent.admin_id == int(admin_pk),
        )
    else:
        orders_q = orders_q.filter(PaymentIntent.id == -1)

    invoices_q = db.query(func.count(Invoice.id)).filter(Invoice.status == "pending")
    if not is_sudo:
        if admin_pk is None:
            invoices_q = invoices_q.filter(Invoice.id == -1)
        else:
            invoices_q = invoices_q.filter(Invoice.admin_id == int(admin_pk))

    return AttentionCounts(
        orders=int(orders_q.scalar() or 0),
        invoices=int(invoices_q.scalar() or 0),
    )


@router.post("/invoices/{invoice_id}/pay", response_model=InvoiceResponse)
def pay_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    """Pay a pending invoice from the reseller wallet.

    Resellers may pay their own invoices; sudo may pay any invoice
    (still debits that reseller's wallet).
    """
    _require_billing_enabled()
    from app.db.models import Invoice

    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if not admin.is_sudo:
        if invoice.admin_id != _admin_id(db, admin):
            raise HTTPException(status_code=403, detail="Cannot pay another admin's invoice")
    provider = "wallet" if not admin.is_sudo else (invoice.provider or "manual")
    try:
        return billing.pay_invoice(db, invoice, provider_name=provider)
    except billing.InsufficientWalletBalance as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/transactions", response_model=List[TransactionResponse])
def list_my_transactions(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    _require_billing_enabled()
    return billing.list_transactions(db, _admin_id(db, admin))


class UsageSummaryResponse(BaseModel):
    rate_per_gb: int
    discount_percent: int
    period_since: datetime
    period_until: datetime
    owned_bytes: int
    foreign_bytes: int
    owned_gb: int
    foreign_gb: int
    estimated_cost: int
    wallet_balance: int
    wallet_low: bool
    wallet_low_threshold: int
    wallet_blocked: bool = False
    currency_label: Optional[str] = None
    prepaid_traffic_remaining: int = 0
    package_covered_bytes: int = 0
    overflow_owned_bytes: int = 0
    overflow_foreign_bytes: int = 0


class TrafficPackageCreate(BaseModel):
    name: str
    bytes: Optional[int] = None
    price: Optional[int] = None
    enabled: bool = True


class TrafficPackageModify(BaseModel):
    name: Optional[str] = None
    bytes: Optional[int] = None
    price: Optional[int] = None
    enabled: Optional[bool] = None


class TrafficPackageResponse(BaseModel):
    id: int
    name: str
    bytes: int
    price: int
    enabled: bool
    created_at: Optional[datetime] = None
    catalog_price: Optional[int] = None
    catalog_bytes: Optional[int] = None
    overridden: Optional[bool] = None
    price_overridden: Optional[bool] = None
    bytes_overridden: Optional[bool] = None
    model_config = ConfigDict(from_attributes=True)


class PackageOverrideItem(BaseModel):
    package_id: int
    price: Optional[int] = None
    bytes: Optional[int] = None


class ResellerPricingUpdate(BaseModel):
    """null usage_rate_per_gb clears the admin override (use platform default)."""

    usage_rate_per_gb: Optional[int] = None
    packages: Optional[List[PackageOverrideItem]] = None


class ResellerPricingPackage(BaseModel):
    id: int
    name: str
    enabled: bool
    catalog_price: int
    catalog_bytes: int
    price: int
    bytes: int
    price_overridden: bool = False
    bytes_overridden: bool = False
    overridden: bool = False
    created_at: Optional[datetime] = None


class ResellerPricingResponse(BaseModel):
    username: str
    usage_rate_per_gb: Optional[int] = None
    effective_usage_rate_per_gb: int
    platform_usage_rate_per_gb: int
    packages: List[ResellerPricingPackage]


class TrafficCreditRequest(BaseModel):
    username: str
    bytes: int
    description: Optional[str] = None


class TrafficPurchaseResponse(BaseModel):
    id: int
    admin_id: int
    package_id: Optional[int] = None
    bytes: int
    price_paid: int
    source: str
    created_by_admin_id: Optional[int] = None
    created_at: Optional[datetime] = None
    prepaid_traffic_remaining: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


def _map_package_error(exc: Exception) -> HTTPException:
    from app.billing.traffic_packages import TrafficPackageError

    if isinstance(exc, TrafficPackageError):
        return HTTPException(status_code=exc.status_code, detail=exc.message)
    return HTTPException(status_code=400, detail=str(exc))


def _after_traffic_credit(db: Session, target) -> None:
    """Re-run billing/caps after prepaid traffic increases."""
    _after_wallet_topup(db, target)


@router.get("/traffic-packages", response_model=List[TrafficPackageResponse])
def list_traffic_packages(
    enabled_only: bool = False,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    _require_billing_enabled()
    from app.billing.traffic_packages import list_packages, list_packages_for_admin

    # Resellers only see enabled catalog entries with effective price/bytes.
    if not admin.is_sudo:
        dbadmin = crud.get_admin(db, admin.username)
        if dbadmin is None:
            raise HTTPException(
                status_code=400,
                detail="Billing requires a database-backed admin",
            )
        offers = list_packages_for_admin(db, dbadmin, enabled_only=True)
        return [
            TrafficPackageResponse(
                id=o["id"],
                name=o["name"],
                bytes=o["bytes"],
                price=o["price"],
                enabled=o["enabled"],
                created_at=o.get("created_at"),
                catalog_price=o["catalog_price"],
                catalog_bytes=o["catalog_bytes"],
                overridden=o["overridden"],
                price_overridden=o["price_overridden"],
                bytes_overridden=o["bytes_overridden"],
            )
            for o in offers
        ]
    return list_packages(db, enabled_only=enabled_only)


@router.get("/reseller-pricing/{username}", response_model=ResellerPricingResponse)
def get_reseller_traffic_pricing(
    username: str,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_billing_enabled()
    from app.billing.traffic_packages import get_reseller_pricing

    target = crud.get_admin(db, username)
    if target is None or target.is_sudo:
        raise HTTPException(status_code=404, detail="Reseller not found")
    return get_reseller_pricing(db, target)


@router.put("/reseller-pricing/{username}", response_model=ResellerPricingResponse)
def put_reseller_traffic_pricing(
    username: str,
    body: ResellerPricingUpdate,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_billing_enabled()
    from app.billing.traffic_packages import TrafficPackageError, set_reseller_pricing

    target = crud.get_admin(db, username)
    if target is None or target.is_sudo:
        raise HTTPException(status_code=404, detail="Reseller not found")

    dumped = body.model_dump(exclude_unset=True)
    clear_usage_rate = "usage_rate_per_gb" in dumped and dumped["usage_rate_per_gb"] is None
    packages = None
    if "packages" in dumped and body.packages is not None:
        packages = [p.model_dump() for p in body.packages]

    try:
        return set_reseller_pricing(
            db,
            target,
            usage_rate_per_gb=dumped.get("usage_rate_per_gb"),
            clear_usage_rate=clear_usage_rate,
            packages=packages,
        )
    except TrafficPackageError as exc:
        raise _map_package_error(exc) from exc


@router.post("/traffic-packages", response_model=TrafficPackageResponse)
def create_traffic_package(
    body: TrafficPackageCreate,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_billing_enabled()
    from app.billing.traffic_packages import TrafficPackageError, create_package

    try:
        return create_package(
            db,
            name=body.name,
            bytes=body.bytes,
            price=body.price,
            enabled=body.enabled,
        )
    except TrafficPackageError as exc:
        raise _map_package_error(exc) from exc


@router.put("/traffic-packages/{package_id}", response_model=TrafficPackageResponse)
def modify_traffic_package(
    package_id: int,
    body: TrafficPackageModify,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_billing_enabled()
    from app.billing.traffic_packages import TrafficPackageError, get_package, update_package

    pkg = get_package(db, package_id)
    if pkg is None:
        raise HTTPException(status_code=404, detail="Traffic package not found")
    try:
        return update_package(db, pkg, **body.model_dump(exclude_unset=True))
    except TrafficPackageError as exc:
        raise _map_package_error(exc) from exc


@router.delete("/traffic-packages/{package_id}")
def remove_traffic_package(
    package_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_billing_enabled()
    from app.billing.traffic_packages import delete_package, get_package

    pkg = get_package(db, package_id)
    if pkg is None:
        raise HTTPException(status_code=404, detail="Traffic package not found")
    delete_package(db, pkg)
    return {"detail": "Traffic package removed"}


@router.post("/traffic-packages/credit", response_model=TrafficPurchaseResponse)
def credit_traffic_package(
    body: TrafficCreditRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    """Sudo: grant prepaid traffic bytes to a reseller without wallet debit."""
    _require_billing_enabled()
    from app.billing.traffic_packages import TrafficPackageError, credit_traffic

    target = crud.get_admin(db, body.username)
    if target is None or target.is_sudo:
        raise HTTPException(status_code=404, detail="Reseller not found")
    actor = crud.get_admin(db, admin.username)
    try:
        purchase = credit_traffic(
            db,
            admin_id=target.id,
            bytes=body.bytes,
            created_by_admin_id=actor.id if actor else None,
            description=body.description,
        )
    except TrafficPackageError as exc:
        raise _map_package_error(exc) from exc
    db.refresh(target)
    _after_traffic_credit(db, target)
    return TrafficPurchaseResponse(
        id=purchase.id,
        admin_id=purchase.admin_id,
        package_id=purchase.package_id,
        bytes=purchase.bytes,
        price_paid=purchase.price_paid,
        source=purchase.source,
        created_by_admin_id=purchase.created_by_admin_id,
        created_at=purchase.created_at,
        prepaid_traffic_remaining=int(target.prepaid_traffic_remaining or 0),
    )


@router.get("/traffic-packages/purchases", response_model=List[TrafficPurchaseResponse])
def list_traffic_purchases(
    username: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    _require_billing_enabled()
    from app.billing.traffic_packages import list_purchases

    admin_id: Optional[int] = None
    if admin.is_sudo:
        if username:
            target = crud.get_admin(db, username)
            if target is None:
                raise HTTPException(status_code=404, detail="Admin not found")
            admin_id = target.id
        # else: sudo sees all purchases when username omitted
    else:
        admin_id = _admin_id(db, admin)

    rows = list_purchases(db, admin_id=admin_id, limit=limit)
    return rows


@router.post("/traffic-packages/{package_id}/purchase", response_model=TrafficPurchaseResponse)
def purchase_traffic_package(
    package_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    """Reseller: buy a catalog package with wallet balance."""
    _require_billing_enabled()
    from app.billing.traffic_packages import TrafficPackageError, purchase_package

    if admin.is_sudo:
        raise HTTPException(status_code=400, detail="Sudo accounts cannot purchase traffic packages")
    admin_id = _admin_id(db, admin)
    actor = crud.get_admin(db, admin.username)
    try:
        purchase = purchase_package(
            db,
            admin_id=admin_id,
            package_id=package_id,
            created_by_admin_id=actor.id if actor else admin_id,
        )
    except TrafficPackageError as exc:
        raise _map_package_error(exc) from exc

    target = crud.get_admin(db, admin.username)
    if target is not None:
        db.refresh(target)
        _after_traffic_credit(db, target)
        prepaid = int(target.prepaid_traffic_remaining or 0)
    else:
        prepaid = None
    return TrafficPurchaseResponse(
        id=purchase.id,
        admin_id=purchase.admin_id,
        package_id=purchase.package_id,
        bytes=purchase.bytes,
        price_paid=purchase.price_paid,
        source=purchase.source,
        created_by_admin_id=purchase.created_by_admin_id,
        created_at=purchase.created_at,
        prepaid_traffic_remaining=prepaid,
    )


class TopUpRequest(BaseModel):
    amount: int
    provider: str  # card | centralpay | stripe (demo only when explicitly enabled)
    card_id: Optional[str] = None


class PaymentCardOut(BaseModel):
    id: str = ""
    number: str = ""
    holder: str = ""
    bank: str = ""


class PaymentCreateResponse(BaseModel):
    payment_id: int
    kind: str
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
    cards: List[PaymentCardOut] = []


class PaymentCompleteBody(BaseModel):
    confirm_token: Optional[str] = None


class PaymentResponse(BaseModel):
    payment_id: int
    kind: str
    amount: int
    provider: str
    status: str
    completed_at: Optional[datetime] = None


class PaymentCardSelect(BaseModel):
    card_id: str


@router.post("/topup", response_model=PaymentCreateResponse)
def topup_wallet(
    body: TopUpRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    """Reseller self-service wallet top-up via gateway or platform card-to-card."""
    _require_billing_enabled()
    if admin.is_sudo:
        raise HTTPException(status_code=400, detail="Platform owner wallet is managed manually")
    admin_id = _admin_id(db, admin)
    intent, payload = create_topup_payment(
        db,
        admin_id,
        body.amount,
        body.provider,
        public_base=public_base_from_request(request),
        card_id=body.card_id,
    )
    cards_raw = payload.get("cards") or []
    return PaymentCreateResponse(
        payment_id=intent.id,
        kind=intent.kind,
        amount=intent.amount,
        provider=intent.provider,
        status=intent.status,
        instructions=payload.get("instructions"),
        confirm_token=payload.get("confirm_token"),
        checkout_url=payload.get("checkout_url"),
        card_id=payload.get("card_id") or (intent.extra or {}).get("card_id"),
        card_number=payload.get("card_number"),
        card_holder=payload.get("card_holder"),
        card_bank=payload.get("card_bank"),
        cards=[PaymentCardOut(**c) for c in cards_raw if isinstance(c, dict)],
    )


@router.post("/payments/{payment_id}/complete", response_model=PaymentResponse)
def complete_wallet_payment(
    payment_id: int,
    body: PaymentCompleteBody,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    """Confirm an online top-up (demo gateway or PSP callback)."""
    _require_billing_enabled()
    intent = get_intent_for_admin(db, payment_id, _admin_id(db, admin))
    if intent.kind != "topup":
        raise HTTPException(status_code=400, detail="Not a top-up payment")
    if intent.provider == "card":
        raise HTTPException(
            status_code=400,
            detail="Card top-ups must be submitted for review, then approved by the platform owner",
        )
    if intent.provider == "demo":
        from app import platform_settings as ps

        if not ps.get_bool("payment.demo_enabled", False):
            raise HTTPException(status_code=403, detail="Demo gateway is disabled")
    intent = complete_payment(db, intent, body.model_dump(exclude_unset=True))
    return PaymentResponse(
        payment_id=intent.id,
        kind=intent.kind,
        amount=intent.amount,
        provider=intent.provider,
        status=intent.status,
        completed_at=intent.completed_at,
    )


class PortalPaymentRow(BaseModel):
    id: int
    kind: str = "portal_renew"
    status: str
    provider: str
    amount: int
    plan_id: Optional[int] = None
    plan_name: Optional[str] = None
    user_id: Optional[int] = None
    username: Optional[str] = None
    admin_id: Optional[int] = None
    admin_username: Optional[str] = None
    user_note: Optional[str] = None
    has_receipt: bool = False
    receipt_name: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class PortalPaymentRejectBody(BaseModel):
    reason: Optional[str] = None


def _portal_payment_row(db: Session, intent) -> PortalPaymentRow:
    plan = crud.get_plan_by_id(db, intent.plan_id) if intent.plan_id else None
    user = crud.get_user_by_id(db, intent.user_id) if intent.user_id else None
    owner = crud.get_admin_by_id(db, intent.admin_id) if intent.admin_id else None
    extra = intent.extra or {}
    row = PortalPaymentRow(
        id=intent.id,
        kind=intent.kind or "portal_renew",
        status=intent.status,
        provider=intent.provider,
        amount=intent.amount,
        plan_id=intent.plan_id,
        plan_name=plan.name if plan else None,
        user_id=intent.user_id,
        username=user.username if user else None,
        admin_id=intent.admin_id,
        admin_username=owner.username if owner else None,
        user_note=extra.get("user_note"),
        has_receipt=bool(extra.get("receipt_relpath")),
        receipt_name=extra.get("receipt_name"),
        created_at=intent.created_at,
        completed_at=intent.completed_at,
    )
    if not row.user_note:
        if intent.kind == "topup":
            row.user_note = "wallet top-up"
            if not row.username and owner is not None:
                row.username = owner.username
        else:
            action = extra.get("action") or intent.kind
            uname = extra.get("new_username") or extra.get("created_username") or extra.get("target_username")
            row.user_note = f"{action}" + (f" · {uname}" if uname else "")
    elif intent.kind == "topup" and not row.username and owner is not None:
        row.username = owner.username
    return row


@router.put("/payments/{payment_id}/card", response_model=PaymentCreateResponse)
def select_wallet_topup_card(
    payment_id: int,
    body: PaymentCardSelect,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    """Switch which platform card a pending top-up should use (before receipt submit)."""
    _require_billing_enabled()
    from app.billing.providers import list_platform_cards, public_card_payload

    intent = get_intent_for_admin(db, payment_id, _admin_id(db, admin))
    if intent.kind != "topup":
        raise HTTPException(status_code=400, detail="Not a top-up payment")
    intent = set_payment_card(db, intent, body.card_id)
    extra = intent.extra or {}
    cards = [PaymentCardOut(**public_card_payload(c)) for c in list_platform_cards()]
    return PaymentCreateResponse(
        payment_id=intent.id,
        kind=intent.kind,
        amount=intent.amount,
        provider=intent.provider,
        status=intent.status,
        card_id=extra.get("card_id"),
        card_number=extra.get("card_number"),
        card_holder=extra.get("card_holder"),
        card_bank=extra.get("card_bank"),
        cards=cards,
    )


@router.post("/payments/{payment_id}/submit")
def submit_wallet_card_topup(
    payment_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
    note: Optional[str] = Form(None),
    receipt: UploadFile = File(...),
):
    """Reseller submits card-transfer receipt for wallet top-up review."""
    _require_billing_enabled()
    intent = get_intent_for_admin(db, payment_id, _admin_id(db, admin))
    if intent.kind != "topup":
        raise HTTPException(status_code=400, detail="Not a top-up payment")
    if intent.provider != "card":
        raise HTTPException(status_code=400, detail="Not a card top-up")
    from app.billing.receipts import save_receipt

    meta = save_receipt(intent.id, receipt)
    intent = submit_card_payment(db, intent, note=note, receipt_meta=meta)
    return {
        "payment_id": intent.id,
        "status": intent.status,
        "detail": "Top-up submitted for review",
        "has_receipt": True,
    }


@router.get("/portal-payments", response_model=List[PortalPaymentRow])
def list_portal_payments(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    """Portal purchases + (for sudo) reseller card top-ups awaiting review."""
    _require_billing_enabled()
    dbadmin = crud.get_admin(db, admin.username)
    if dbadmin is None and not admin.is_sudo:
        raise HTTPException(status_code=400, detail="Admin not found in database")
    scope = dbadmin if dbadmin is not None else admin
    intents = list_portal_payments_for_admin(db, scope, status=status)
    return [_portal_payment_row(db, intent) for intent in intents]


@router.get("/portal-payments/{payment_id}/receipt")
def portal_payment_receipt(
    payment_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    """Download the uploaded card-transfer receipt for a portal payment or top-up."""
    _require_billing_enabled()
    dbadmin = crud.get_admin(db, admin.username)
    scope = dbadmin if dbadmin is not None else admin
    intent = get_intent_for_admin_or_sudo(db, payment_id, scope)
    if intent.kind == "topup" and not getattr(scope, "is_sudo", False):
        # Reseller may download their own top-up receipt; others cannot.
        if intent.admin_id != getattr(scope, "id", None):
            raise HTTPException(status_code=404, detail="Payment not found")
    extra = intent.extra or {}
    rel = extra.get("receipt_relpath")
    if not rel:
        raise HTTPException(status_code=404, detail="No receipt uploaded")
    from app.billing.receipts import receipt_media_type, receipt_response_headers, resolve_receipt_path

    path = resolve_receipt_path(str(rel))
    media = receipt_media_type(path, extra.get("receipt_content_type"))
    filename = extra.get("receipt_name") or path.name
    return FileResponse(
        path,
        media_type=media,
        filename=filename,
        # Force download — never execute inline in the admin browser.
        content_disposition_type="attachment",
        headers=receipt_response_headers(),
    )


@router.post("/portal-payments/{payment_id}/approve", response_model=PortalPaymentRow)
def approve_portal_purchase(
    payment_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:write")),
):
    """Approve a card-to-card portal purchase or reseller wallet top-up."""
    _require_billing_enabled()
    dbadmin = crud.get_admin(db, admin.username)
    scope = dbadmin if dbadmin is not None else admin
    intent = get_intent_for_admin_or_sudo(db, payment_id, scope)
    intent = approve_portal_payment(db, intent, reviewer=scope)
    try:
        from app.portal_push import notify_portal_payment
        from app.web_push import notify_admin_badge_sync, notify_topup_result

        if intent.kind in ("portal_renew", "portal_purchase"):
            notify_portal_payment(db, intent, approved=True)
        elif intent.kind == "topup":
            notify_topup_result(db, intent, approved=True)
        # Refresh reviewer badge (sudo or reseller who cleared the queue item).
        rid = getattr(scope, "id", None)
        if rid:
            notify_admin_badge_sync(db, int(rid))
    except Exception:
        pass
    return _portal_payment_row(db, intent)


@router.post("/portal-payments/{payment_id}/reject", response_model=PortalPaymentRow)
def reject_portal_purchase(
    payment_id: int,
    body: PortalPaymentRejectBody,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:write")),
):
    """Reject a pending card-to-card portal purchase or wallet top-up."""
    _require_billing_enabled()
    dbadmin = crud.get_admin(db, admin.username)
    scope = dbadmin if dbadmin is not None else admin
    intent = get_intent_for_admin_or_sudo(db, payment_id, scope)
    intent = reject_portal_payment(db, intent, reason=body.reason, reviewer=scope)
    try:
        from app.portal_push import notify_portal_payment
        from app.web_push import notify_admin_badge_sync, notify_topup_result

        if intent.kind in ("portal_renew", "portal_purchase"):
            notify_portal_payment(db, intent, approved=False)
        elif intent.kind == "topup":
            notify_topup_result(db, intent, approved=False, reason=body.reason)
        rid = getattr(scope, "id", None)
        if rid:
            notify_admin_badge_sync(db, int(rid))
    except Exception:
        pass
    return _portal_payment_row(db, intent)


class MrrResellerRow(BaseModel):
    admin_id: int
    username: str
    revenue: int


class MrrResponse(BaseModel):
    period_days: int
    total_revenue: int
    mrr_estimate: int
    by_type: dict
    wallet_float: int
    active_resellers: int
    sub_resellers: int
    top_resellers: List[MrrResellerRow]


@router.get("/mrr", response_model=MrrResponse)
def owner_mrr(
    days: int = 30,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Platform owner revenue dashboard (MRR-style rollup)."""
    _require_billing_enabled()
    if days < 1 or days > 365:
        raise HTTPException(status_code=422, detail="days must be 1–365")
    return compute_mrr(db, days=days)


class GatewayIncomeResellerRow(BaseModel):
    admin_id: int
    username: str
    is_sudo: bool = False
    centralpay_enabled: bool = False
    card_enabled: bool = False
    today: int
    yesterday: int
    week: int
    total: int
    payments_count: int
    by_provider: Dict[str, int] = {}
    by_kind: Dict[str, int] = {}


class GatewayIncomePaymentRow(BaseModel):
    id: int
    kind: str
    provider: str
    amount: int
    status: str
    admin_id: int
    username: Optional[str] = None
    plan_id: Optional[int] = None
    plan_name: Optional[str] = None
    reference: Optional[Any] = None
    card: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class GatewayIncomeResponse(BaseModel):
    today: int
    yesterday: int
    week: int
    total: int
    today_count: int = 0
    yesterday_count: int = 0
    week_count: int = 0
    payments_count: int
    currency_label: str = ""
    by_provider: Dict[str, int] = {}
    by_kind: Dict[str, int] = {}
    today_by_kind: Dict[str, int] = {}
    yesterday_by_kind: Dict[str, int] = {}
    week_by_kind: Dict[str, int] = {}
    total_by_kind: Dict[str, int] = {}
    resellers: List[GatewayIncomeResellerRow] = []
    recent_payments: List[GatewayIncomePaymentRow] = []


@router.get("/gateway-income", response_model=GatewayIncomeResponse)
def gateway_income(
    provider: Optional[str] = None,
    username: Optional[str] = None,
    payments_limit: int = 100,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    """Gateway (CentralPay/Stripe/demo) cash collected — today / yesterday / week / total.

    Sudo sees all resellers; a reseller sees only their own traffic — and only
    when the master has enabled CentralPay for that reseller.
    """
    _require_billing_enabled()
    from app.billing.gateway_income import compute_gateway_income
    from app.billing.providers import admin_may_use_centralpay

    if payments_limit < 1 or payments_limit > 500:
        raise HTTPException(status_code=422, detail="payments_limit must be 1–500")

    admin_id: Optional[int] = None
    if admin.is_sudo:
        if username:
            target = crud.get_admin(db, username.strip())
            if target is None:
                raise HTTPException(status_code=404, detail="Admin not found")
            admin_id = target.id
    else:
        dbadmin = crud.get_admin(db, admin.username)
        if dbadmin is None or not admin_may_use_centralpay(dbadmin):
            raise HTTPException(
                status_code=403,
                detail="Gateway income is only available when CentralPay is enabled for your account",
            )
        admin_id = _admin_id(db, admin)

    return compute_gateway_income(
        db,
        admin_id=admin_id,
        provider=(provider or "").strip() or None,
        include_payments=True,
        payments_limit=payments_limit,
    )


class MyCardItem(BaseModel):
    id: str = ""
    number: str = ""
    holder: str = ""
    bank: str = ""
    enabled: bool = True


class MyCardSettings(BaseModel):
    """Reseller (or sudo) card-to-card settings for their own portal customers."""

    card_enabled: bool = False
    card_number: str = ""
    card_holder: str = ""
    card_bank: str = ""
    cards: List[MyCardItem] = []
    # Sudo uses platform settings — surface that for the UI.
    uses_platform_settings: bool = False


class MyCardSettingsUpdate(BaseModel):
    card_enabled: bool = False
    # Legacy single-card fields (used when ``cards`` is omitted).
    card_number: str = ""
    card_holder: str = ""
    card_bank: str = ""
    cards: Optional[List[MyCardItem]] = None


def _my_card_settings_response(*, enabled: bool, cards: list, uses_platform: bool) -> MyCardSettings:
    from app.billing.providers import enabled_payment_cards, public_card_payload

    items = [
        MyCardItem(
            id=c.get("id") or "",
            number=c.get("number") or "",
            holder=c.get("holder") or "",
            bank=c.get("bank") or "",
            enabled=bool(c.get("enabled", True)),
        )
        for c in cards
    ]
    first = enabled_payment_cards(cards)
    mirror = first[0] if first else (cards[0] if cards else None)
    pub = public_card_payload(mirror) if mirror else {"number": "", "holder": "", "bank": ""}
    return MyCardSettings(
        card_enabled=bool(enabled),
        card_number=pub.get("number") or "",
        card_holder=pub.get("holder") or "",
        card_bank=pub.get("bank") or "",
        cards=items,
        uses_platform_settings=uses_platform,
    )


@router.get("/my-card-settings", response_model=MyCardSettings)
def get_my_card_settings(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    """Current admin's card-to-card config (reseller self-service; sudo = platform)."""
    _require_billing_enabled()
    from app import platform_settings as ps
    from app.billing.providers import load_admin_cards_raw, load_platform_cards_raw

    if admin.is_sudo:
        cards = load_platform_cards_raw()
        return _my_card_settings_response(
            enabled=bool(ps.get_bool("payment.card_enabled")),
            cards=cards,
            uses_platform=True,
        )
    dbadmin = crud.get_admin(db, admin.username)
    if dbadmin is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    cards = load_admin_cards_raw(dbadmin)
    return _my_card_settings_response(
        enabled=bool(getattr(dbadmin, "card_enabled", False)),
        cards=cards,
        uses_platform=False,
    )


@router.put("/my-card-settings", response_model=MyCardSettings)
def put_my_card_settings(
    body: MyCardSettingsUpdate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:write")),
):
    """Save card-to-card details for this admin's portal customers (supports multiple cards)."""
    _require_billing_enabled()
    from app.billing.providers import (
        enabled_payment_cards,
        legacy_cards_from_scalars,
        normalize_payment_cards,
        reload_providers,
        save_admin_cards,
        save_platform_cards,
    )

    if body.cards is not None:
        cards_in = [c.model_dump() if hasattr(c, "model_dump") else c.dict() for c in body.cards]
        cards = normalize_payment_cards(cards_in)
    else:
        cards = legacy_cards_from_scalars(body.card_number, body.card_holder, body.card_bank)

    if body.card_enabled and not enabled_payment_cards(cards):
        raise HTTPException(
            status_code=422,
            detail="At least one card number is required when card payment is enabled",
        )

    if admin.is_sudo:
        saved = save_platform_cards(bool(body.card_enabled), cards)
        reload_providers()
        return _my_card_settings_response(
            enabled=bool(body.card_enabled),
            cards=saved,
            uses_platform=True,
        )

    dbadmin = crud.get_admin(db, admin.username)
    if dbadmin is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    saved = save_admin_cards(dbadmin, bool(body.card_enabled), cards)
    db.commit()
    db.refresh(dbadmin)
    return _my_card_settings_response(
        enabled=bool(dbadmin.card_enabled),
        cards=saved,
        uses_platform=False,
    )


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Stripe Checkout completion webhook — signature required when Stripe is on."""
    import hashlib
    import hmac
    import json

    from app import platform_settings as ps
    from app.billing.payments import complete_payment
    from app.db.models import PaymentIntent

    if not ps.get_bool("payment.stripe_enabled"):
        raise HTTPException(status_code=404, detail="Stripe disabled")

    webhook_secret = (ps.get_str("payment.stripe_webhook_secret") or "").strip()
    if not webhook_secret:
        # Fail closed: never accept unsigned Stripe events in production.
        raise HTTPException(
            status_code=503,
            detail="Stripe webhook secret is not configured",
        )

    body = await request.body()
    sig = request.headers.get("stripe-signature", "")
    if not sig:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")
    try:
        parts = dict(p.split("=", 1) for p in sig.split(",") if "=" in p)
        timestamp = parts.get("t", "")
        v1 = parts.get("v1", "")
        if not timestamp or not v1:
            raise HTTPException(status_code=400, detail="Invalid Stripe-Signature header")
        signed = f"{timestamp}.{body.decode()}"
        expected = hmac.new(
            webhook_secret.encode(),
            signed.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, v1):
            raise HTTPException(status_code=400, detail="Invalid signature")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Signature verification failed")

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if event.get("type") != "checkout.session.completed":
        return {"received": True}

    session = event.get("data", {}).get("object", {})
    pid = session.get("metadata", {}).get("payment_intent_id")
    if not pid:
        return {"received": True}

    intent = db.query(PaymentIntent).filter(PaymentIntent.id == int(pid)).first()
    if intent is None or intent.status == "completed":
        return {"received": True}

    complete_payment(
        db,
        intent,
        {"stripe_webhook": "checkout.session.completed", "session_id": session.get("id")},
    )
    return {"received": True}


@router.get("/return/centralpay")
def centralpay_return(
    orderId: int,
    db: Session = Depends(get_db),
):
    """CentralPay browser return — verify deposit, complete intent, redirect UI."""
    from fastapi.responses import RedirectResponse

    from app import platform_settings as ps
    from app.db.models import PaymentIntent
    from config import PANEL_PUBLIC_ADDRESS

    def _panel_base() -> str:
        addr = (PANEL_PUBLIC_ADDRESS or "").strip().rstrip("/")
        if addr.startswith("http://") or addr.startswith("https://"):
            return addr
        if addr:
            return f"https://{addr}"
        return ""

    def _dest(kind: Optional[str], ok: bool) -> str:
        flag = "ok" if ok else "fail"
        path = f"/dashboard/#/billing?pay={flag}" if kind == "topup" else f"/portal/?pay={flag}"
        base = _panel_base()
        # Absolute URL so a reverse-proxy return host does not keep the browser
        # on the relay domain (e.g. bot.ajor.store).
        return f"{base}{path}" if base else path

    if not (ps.get_str("payment.centralpay_api_key") or "").strip():
        return RedirectResponse(_dest(None, False), status_code=302)

    from app.billing.providers import CentralPayProvider

    intent_id = CentralPayProvider.intent_id_from_order_id(int(orderId))
    intent = db.query(PaymentIntent).filter(PaymentIntent.id == int(intent_id)).first()
    if intent is None or intent.provider != "centralpay":
        return RedirectResponse(_dest(None, False), status_code=302)

    if intent.status == "completed":
        return RedirectResponse(_dest(intent.kind, True), status_code=302)

    try:
        complete_payment(
            db,
            intent,
            {"centralpay_return": True, "orderId": int(orderId)},
        )
        return RedirectResponse(_dest(intent.kind, True), status_code=302)
    except HTTPException:
        return RedirectResponse(_dest(intent.kind, False), status_code=302)
    except Exception:
        return RedirectResponse(_dest(intent.kind, False), status_code=302)


@router.get("/usage", response_model=UsageSummaryResponse)
def usage_summary(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    """Unbilled traffic split (own vs shared nodes) and estimated GB charge."""
    _require_billing_enabled()
    dbadmin = crud.get_admin(db, admin.username)
    if dbadmin is None:
        raise HTTPException(status_code=400, detail="Admin not found in database")
    return usage_summary_for_admin(db, dbadmin)
