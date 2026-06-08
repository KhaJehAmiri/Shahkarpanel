from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app import billing, feature_flags
from app.billing.mrr import compute_mrr
from app.billing.payments import (
    complete_payment,
    create_topup_payment,
    get_intent_for_admin,
    list_online_providers,
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


class InvoiceCreate(BaseModel):
    username: Optional[str] = None
    amount: int
    plan_id: Optional[int] = None
    provider: Optional[str] = "manual"


class InvoiceResponse(BaseModel):
    id: int
    admin_id: int
    plan_id: Optional[int] = None
    amount: int
    status: str
    provider: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class TransactionResponse(BaseModel):
    id: int
    admin_id: int
    amount: int
    type: str
    description: Optional[str] = None
    reference: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


@router.get("/providers", response_model=List[str])
def list_providers(_: Admin = Depends(require_permission("billing:read"))):
    _require_billing_enabled()
    return billing.available_providers()


@router.get("/payment-providers", response_model=List[str])
def list_payment_providers(_: Admin = Depends(require_permission("billing:read"))):
    """Online PSPs available for self-service top-up (excludes manual)."""
    _require_billing_enabled()
    return list_online_providers()


@router.get("/wallet", response_model=WalletResponse)
def my_wallet(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    _require_billing_enabled()
    return billing.get_or_create_wallet(db, _admin_id(db, admin))


@router.post("/credit", response_model=WalletResponse)
def add_credit(
    body: CreditRequest,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Top up an admin's wallet. Sudo only."""
    _require_billing_enabled()
    target = crud.get_admin(db, body.username)
    if target is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    billing.add_transaction(
        db, target.id, body.amount, type="credit", description=body.description
    )
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
    return billing.create_invoice(
        db, target.id, body.amount, plan_id=body.plan_id, provider=body.provider
    )


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


@router.post("/invoices/{invoice_id}/pay", response_model=InvoiceResponse)
def pay_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Confirm payment of an invoice. Sudo only (manual confirmation)."""
    _require_billing_enabled()
    from app.db.models import Invoice

    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return billing.pay_invoice(db, invoice)


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


class TopUpRequest(BaseModel):
    amount: int
    provider: str = "demo"


class PaymentCreateResponse(BaseModel):
    payment_id: int
    kind: str
    amount: int
    provider: str
    status: str
    instructions: Optional[str] = None
    confirm_token: Optional[str] = None
    checkout_url: Optional[str] = None


class PaymentCompleteBody(BaseModel):
    confirm_token: Optional[str] = None


class PaymentResponse(BaseModel):
    payment_id: int
    kind: str
    amount: int
    provider: str
    status: str
    completed_at: Optional[datetime] = None


@router.post("/topup", response_model=PaymentCreateResponse)
def topup_wallet(
    body: TopUpRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    """Reseller self-service wallet top-up via an online payment provider."""
    _require_billing_enabled()
    admin_id = _admin_id(db, admin)
    intent, payload = create_topup_payment(db, admin_id, body.amount, body.provider)
    return PaymentCreateResponse(
        payment_id=intent.id,
        kind=intent.kind,
        amount=intent.amount,
        provider=intent.provider,
        status=intent.status,
        instructions=payload.get("instructions"),
        confirm_token=payload.get("confirm_token"),
        checkout_url=payload.get("checkout_url"),
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
    intent = complete_payment(db, intent, body.model_dump(exclude_unset=True))
    return PaymentResponse(
        payment_id=intent.id,
        kind=intent.kind,
        amount=intent.amount,
        provider=intent.provider,
        status=intent.status,
        completed_at=intent.completed_at,
    )


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


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Stripe Checkout completion webhook (no auth — verified by signature when configured)."""
    import hashlib
    import hmac
    import json

    from app import platform_settings as ps
    from app.billing.payments import complete_payment
    from app.db.models import PaymentIntent

    if not ps.get_bool("payment.stripe_enabled"):
        raise HTTPException(status_code=404, detail="Stripe disabled")

    body = await request.body()
    sig = request.headers.get("stripe-signature", "")
    webhook_secret = ps.get_str("payment.stripe_webhook_secret")
    if webhook_secret and sig:
        try:
            parts = dict(p.split("=", 1) for p in sig.split(",") if "=" in p)
            timestamp = parts.get("t", "")
            v1 = parts.get("v1", "")
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
