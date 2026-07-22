"""White-label tenants & branding API (phase 6)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, field_validator
import re

from app import feature_flags, tenant as tenant_svc
from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.rbac import require_permission
from app.utils import responses

router = APIRouter(
    tags=["Tenants"],
    prefix="/api",
    responses={401: responses._401, 403: responses._403},
)


def _require_tenants_enabled():
    if not feature_flags.is_enabled("tenants"):
        raise HTTPException(status_code=404, detail="Tenants are disabled")


def _require_white_label_enabled():
    if not feature_flags.is_enabled("white_label"):
        raise HTTPException(status_code=404, detail="White-label branding is disabled")


class TenantCreate(BaseModel):
    name: str
    slug: Optional[str] = None
    owner_username: Optional[str] = None
    max_users: Optional[int] = None
    max_nodes: Optional[int] = None
    byo_node_discount_percent: int = 0


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    max_users: Optional[int] = None
    max_nodes: Optional[int] = None
    byo_node_discount_percent: Optional[int] = None


class TenantResponse(BaseModel):
    id: int
    slug: str
    name: str
    enabled: bool
    owner_admin_id: Optional[int] = None
    max_users: Optional[int] = None
    max_nodes: Optional[int] = None
    byo_node_discount_percent: int
    model_config = ConfigDict(from_attributes=True)


class BrandingUpdate(BaseModel):
    panel_title: Optional[str] = None
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    primary_color: Optional[str] = None
    support_url: Optional[str] = None
    sub_profile_title: Optional[str] = None
    domain: Optional[str] = None
    panel_url: Optional[str] = None

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: Optional[str]):
        if value is None:
            return None
        host = str(value).strip().lower()
        if not host:
            return None
        if "://" in host:
            from urllib.parse import urlparse
            host = (urlparse(host).hostname or "").strip().lower()
        # Custom panel hostname only — not a free-text label.
        if " " in host or not re.fullmatch(
            r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+",
            host,
        ):
            raise ValueError(
                "domain must be a hostname like panel.example.com (leave blank if unused)"
            )
        return host

    @field_validator("panel_url")
    @classmethod
    def validate_panel_url(cls, value: Optional[str]):
        if value is None:
            return None
        url = str(value).strip()
        if not url:
            return None
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if not parsed.hostname:
            raise ValueError("panel_url must be a valid URL like https://panel.example.com")
        return url.rstrip("/")


class BrandingResponse(BaseModel):
    panel_title: Optional[str] = None
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    primary_color: Optional[str] = None
    support_url: Optional[str] = None
    sub_profile_title: Optional[str] = None
    domain: Optional[str] = None
    panel_url: Optional[str] = None


# --------------------------------------------------------------------------- #
# Tenant CRUD (sudo owner only)
# --------------------------------------------------------------------------- #
@router.get("/tenants", response_model=List[TenantResponse])
def list_tenants(db: Session = Depends(get_db), _: Admin = Depends(Admin.check_sudo_admin)):
    _require_tenants_enabled()
    return tenant_svc.list_tenants(db)


@router.post("/tenants", response_model=TenantResponse)
def create_tenant(
    body: TenantCreate,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_tenants_enabled()
    owner_id = None
    if body.owner_username:
        owner = crud.get_admin(db, body.owner_username)
        if owner is None:
            raise HTTPException(status_code=404, detail="Owner admin not found")
        owner_id = owner.id
    t = tenant_svc.create_tenant(
        db,
        name=body.name,
        slug=body.slug,
        owner_admin_id=owner_id,
        max_users=body.max_users,
        max_nodes=body.max_nodes,
        byo_node_discount_percent=body.byo_node_discount_percent,
    )
    # Bind the owner admin to the tenant so they're scoped to it.
    if owner_id is not None:
        owner = crud.get_admin(db, body.owner_username)
        owner.tenant_id = t.id
        db.commit()
    return t


@router.patch("/tenants/{tenant_id}", response_model=TenantResponse)
def update_tenant(
    tenant_id: int,
    body: TenantUpdate,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_tenants_enabled()
    t = tenant_svc.get_tenant(db, tenant_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant_svc.update_tenant(db, t, **body.model_dump(exclude_unset=True))


@router.delete("/tenants/{tenant_id}")
def delete_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_tenants_enabled()
    t = tenant_svc.get_tenant(db, tenant_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant_svc.delete_tenant(db, t)
    return {}


# --------------------------------------------------------------------------- #
# Branding
# --------------------------------------------------------------------------- #
@router.get("/branding", response_model=BrandingResponse)
def public_branding(
    request: Request,
    tenant: Optional[str] = Query(default=None, description="tenant slug"),
    domain: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Resolve effective branding for the dashboard/subscription. Public: no auth
    so the login page and subscription pages can theme themselves."""
    tenant_id = None
    host = (domain or (request.headers.get("host") or "").split(":")[0] or "").strip().lower()
    if tenant:
        t = tenant_svc.get_tenant_by_slug(db, tenant)
        tenant_id = t.id if t else None
    elif host:
        from app.db.models import BrandingSettings
        row = (
            db.query(BrandingSettings)
            .filter(BrandingSettings.domain == host)
            .first()
        )
        tenant_id = row.tenant_id if row else None
    return BrandingResponse(**tenant_svc.resolve_branding(db, tenant_id))


@router.get("/branding/mine", response_model=BrandingResponse)
def my_branding(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("system:read")),
):
    _require_white_label_enabled()
    tenant_id = tenant_svc.admin_tenant_id(db, admin)
    return BrandingResponse(**tenant_svc.resolve_branding(db, tenant_id))


@router.put("/branding/mine", response_model=BrandingResponse)
def update_my_branding(
    body: BrandingUpdate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """A reseller edits their own tenant's brand; the sudo owner edits the
    global default (tenant_id = None)."""
    _require_white_label_enabled()
    tenant_id = tenant_svc.admin_tenant_id(db, admin)
    if not admin.is_sudo and tenant_id is None:
        raise HTTPException(
            status_code=400,
            detail="Reseller has no tenant — contact the platform owner",
        )
    tenant_svc.set_branding(
        db,
        tenant_id,
        allow_global=bool(admin.is_sudo and tenant_id is None),
        **body.model_dump(exclude_unset=True),
    )
    return BrandingResponse(**tenant_svc.resolve_branding(db, tenant_id))
