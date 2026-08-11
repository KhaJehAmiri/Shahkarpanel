"""Public storefront + reseller acquisition APIs."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.db import Session, get_db
from app.db.models import Admin as DbAdmin
from app.login_limit import enforce_login_rate_limit, record_login_failure
from app.models.admin import Admin
from app.rbac import require_permission
from app import storefront as sf
from app.utils import responses
from config import LOGIN_MAX_ATTEMPTS, LOGIN_MAX_WINDOW_SECONDS

router = APIRouter(tags=["Storefront"], prefix="/api")


class PublicPlan(BaseModel):
    id: int
    name: str
    price: int = 0
    data_limit: Optional[int] = None
    duration_days: Optional[int] = None
    device_limit: Optional[int] = None


class PublicBranding(BaseModel):
    panel_title: Optional[str] = None
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    primary_color: Optional[str] = None
    support_url: Optional[str] = None
    domain: Optional[str] = None
    panel_url: Optional[str] = None


class StorefrontResponse(BaseModel):
    storefront_enabled: bool = True
    signup_enabled: bool = False
    reseller_apply_enabled: bool = False
    tenant_slug: Optional[str] = None
    ref: Optional[str] = None
    headline: str = ""
    tagline: str = ""
    currency_label: str = ""
    branding: PublicBranding
    plans: List[PublicPlan] = []


class RegisterBody(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=4, max_length=128)
    contact: Optional[str] = Field(default=None, max_length=256)
    tenant: Optional[str] = None
    ref: Optional[str] = None


class RegisterResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    portal_url: str = "/portal/"


class ResellerApplyBody(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=4, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=128)
    contact: Optional[str] = Field(default=None, max_length=256)
    message: Optional[str] = Field(default=None, max_length=1000)
    tenant: Optional[str] = None
    ref: Optional[str] = None


class ResellerApplyResponse(BaseModel):
    status: str
    username: Optional[str] = None
    id: Optional[int] = None
    role: Optional[str] = None
    dashboard_url: Optional[str] = None
    message: str = ""


class ApplicationRow(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    contact: Optional[str] = None
    message: Optional[str] = None
    status: str
    parent_admin_id: Optional[int] = None
    invite_code: Optional[str] = None
    created_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    reject_reason: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class RejectBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=256)


class StorefrontMineUpdate(BaseModel):
    public_signup_enabled: Optional[bool] = None
    reseller_apply_enabled: Optional[bool] = None
    storefront_headline: Optional[str] = Field(default=None, max_length=256)
    storefront_tagline: Optional[str] = Field(default=None, max_length=512)


class StorefrontMineResponse(BaseModel):
    invite_code: str
    public_signup_enabled: bool
    reseller_apply_enabled: bool
    storefront_headline: Optional[str] = None
    storefront_tagline: Optional[str] = None
    tenant_slug: Optional[str] = None
    storefront_enabled: bool = True
    effective_signup_enabled: bool = False
    effective_reseller_apply_enabled: bool = False
    links: Dict[str, str]
    branding: Dict[str, Any]


def _ctx(
    db: Session,
    request: Request,
    *,
    tenant: Optional[str] = None,
    domain: Optional[str] = None,
    ref: Optional[str] = None,
):
    return sf.resolve_context(db, request, tenant=tenant, domain=domain, ref=ref)


@router.get("/public/storefront", response_model=StorefrontResponse)
def get_storefront(
    request: Request,
    tenant: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
    ref: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Public white-label landing payload (branding + plans + feature flags)."""
    ctx = _ctx(db, request, tenant=tenant, domain=domain, ref=ref)
    return sf.storefront_payload(db, ctx)


@router.post("/public/register", response_model=RegisterResponse)
def public_register(
    body: RegisterBody,
    request: Request,
    db: Session = Depends(get_db),
):
    """Self-service end-user signup under the resolved reseller/platform."""
    enforce_login_rate_limit(
        request,
        max_attempts=LOGIN_MAX_ATTEMPTS,
        window_seconds=LOGIN_MAX_WINDOW_SECONDS,
    )
    # Public signup: count every attempt (abuse), keyed by real client IP.
    record_login_failure(request, window_seconds=LOGIN_MAX_WINDOW_SECONDS)
    ctx = _ctx(db, request, tenant=body.tenant, ref=body.ref)
    return sf.register_customer(
        db,
        ctx,
        username=body.username,
        password=body.password,
        contact=body.contact,
    )


@router.post("/public/reseller-apply", response_model=ResellerApplyResponse)
def public_reseller_apply(
    body: ResellerApplyBody,
    request: Request,
    db: Session = Depends(get_db),
):
    """Become a reseller / sub-reseller (invite auto-creates; else pending)."""
    enforce_login_rate_limit(
        request,
        max_attempts=LOGIN_MAX_ATTEMPTS,
        window_seconds=LOGIN_MAX_WINDOW_SECONDS,
    )
    record_login_failure(request, window_seconds=LOGIN_MAX_WINDOW_SECONDS)
    ctx = _ctx(db, request, tenant=body.tenant, ref=body.ref)
    return sf.apply_reseller(
        db,
        ctx,
        username=body.username,
        password=body.password,
        display_name=body.display_name,
        contact=body.contact,
        message=body.message,
    )


@router.get("/storefront/mine", response_model=StorefrontMineResponse)
def get_my_storefront(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("system:read")),
):
    return sf.mine_storefront(db, admin)


@router.put("/storefront/mine", response_model=StorefrontMineResponse)
def put_my_storefront(
    body: StorefrontMineUpdate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("system:read")),
):
    return sf.update_mine_storefront(db, admin, body.model_dump(exclude_unset=True))


@router.post("/storefront/mine/rotate-invite", response_model=StorefrontMineResponse)
def rotate_my_invite(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("system:read")),
):
    row = db.query(DbAdmin).filter(DbAdmin.username == admin.username).first()
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Admin not found")
    sf.rotate_invite_code(db, row)
    return sf.mine_storefront(db, row)


@router.get(
    "/storefront/applications",
    response_model=List[ApplicationRow],
    responses={401: responses._401, 403: responses._403},
)
def list_reseller_applications(
    status: Optional[str] = Query(default="pending"),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    row = db.query(DbAdmin).filter(DbAdmin.username == admin.username).first()
    if row is None and admin.is_sudo:
        # env sudo may not be a DB row — synthesize for list filter
        class _Sudo:
            is_sudo = True
            id = 0

        return sf.list_applications(db, _Sudo(), status=status)  # type: ignore[arg-type]
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Admin not found")
    return sf.list_applications(db, row, status=status)


@router.post("/storefront/applications/{app_id}/approve", response_model=ResellerApplyResponse)
def approve_reseller_application(
    app_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    row = db.query(DbAdmin).filter(DbAdmin.username == admin.username).first()
    actor = row
    if actor is None and admin.is_sudo:
        class _Sudo:
            is_sudo = True
            id = 0
            username = admin.username

        actor = _Sudo()  # type: ignore[assignment]
    if actor is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Admin not found")
    return sf.approve_application(db, actor, app_id)  # type: ignore[arg-type]


@router.post("/storefront/applications/{app_id}/reject", response_model=ResellerApplyResponse)
def reject_reseller_application(
    app_id: int,
    body: RejectBody = RejectBody(),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    row = db.query(DbAdmin).filter(DbAdmin.username == admin.username).first()
    actor = row
    if actor is None and admin.is_sudo:
        class _Sudo:
            is_sudo = True
            id = 0
            username = admin.username

        actor = _Sudo()  # type: ignore[assignment]
    if actor is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Admin not found")
    return sf.reject_application(db, actor, app_id, reason=body.reason)  # type: ignore[arg-type]
