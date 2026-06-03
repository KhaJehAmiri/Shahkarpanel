from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app import billing, feature_flags
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
