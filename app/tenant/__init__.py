"""White-label reseller tenants (phase 6).

A *tenant* is a reseller workspace that lives inside a single panel install: it
scopes admins, users, plans and nodes and carries its own brand. This module
holds the pure CRUD/scoping/branding helpers; HTTP wiring lives in
``app.routers.tenant``.

Design notes
------------
* The platform *owner* (a sudo admin) has ``tenant_id = None`` and sees
  everything. A reseller admin has ``tenant_id`` set and is confined to it.
* Branding resolves per-tenant with a global fallback so the dashboard and the
  subscription layer can theme themselves without a separate service.
"""
import re
from typing import List, Optional

from app.db import Session
from app.db.models import Admin, BrandingSettings, Node, Tenant, User

__all__ = [
    "slugify",
    "create_tenant",
    "get_tenant",
    "get_tenant_by_slug",
    "list_tenants",
    "update_tenant",
    "delete_tenant",
    "admin_tenant_id",
    "scope_users_query",
    "scope_nodes_query",
    "get_branding",
    "set_branding",
    "resolve_branding",
    "tenant_owned_node_ids",
]


_slug_re = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    slug = _slug_re.sub("-", (value or "").strip().lower()).strip("-")
    return slug or "tenant"


# --------------------------------------------------------------------------- #
# Tenant CRUD
# --------------------------------------------------------------------------- #
def create_tenant(
    db: Session,
    name: str,
    slug: Optional[str] = None,
    owner_admin_id: Optional[int] = None,
    max_users: Optional[int] = None,
    max_nodes: Optional[int] = None,
    byo_node_discount_percent: int = 0,
) -> Tenant:
    base = slugify(slug or name)
    candidate, n = base, 1
    while db.query(Tenant).filter(Tenant.slug == candidate).first() is not None:
        n += 1
        candidate = f"{base}-{n}"

    tenant = Tenant(
        slug=candidate,
        name=name,
        owner_admin_id=owner_admin_id,
        max_users=max_users,
        max_nodes=max_nodes,
        byo_node_discount_percent=_clamp_percent(byo_node_discount_percent),
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


def _clamp_percent(value: Optional[int]) -> int:
    if value is None:
        return 0
    return max(0, min(100, int(value)))


def get_tenant(db: Session, tenant_id: int) -> Optional[Tenant]:
    return db.query(Tenant).filter(Tenant.id == tenant_id).first()


def get_tenant_by_slug(db: Session, slug: str) -> Optional[Tenant]:
    return db.query(Tenant).filter(Tenant.slug == slug).first()


def list_tenants(db: Session) -> List[Tenant]:
    return db.query(Tenant).order_by(Tenant.id).all()


def update_tenant(db: Session, tenant: Tenant, **fields) -> Tenant:
    for key in ("name", "enabled", "max_users", "max_nodes", "owner_admin_id"):
        if key in fields and fields[key] is not None:
            setattr(tenant, key, fields[key])
    if "byo_node_discount_percent" in fields and fields["byo_node_discount_percent"] is not None:
        tenant.byo_node_discount_percent = _clamp_percent(fields["byo_node_discount_percent"])
    db.commit()
    db.refresh(tenant)
    return tenant


def delete_tenant(db: Session, tenant: Tenant) -> None:
    db.delete(tenant)
    db.commit()


# --------------------------------------------------------------------------- #
# Scoping
# --------------------------------------------------------------------------- #
def admin_tenant_id(db: Session, admin) -> Optional[int]:
    """Return the tenant id an admin is confined to, or None for the owner."""
    if getattr(admin, "is_sudo", False):
        return None
    dbadmin = db.query(Admin).filter(Admin.username == admin.username).first()
    return getattr(dbadmin, "tenant_id", None) if dbadmin else None


def scope_users_query(query, tenant_id: Optional[int]):
    """Limit a User query to a tenant via the owning admin's tenant_id."""
    if tenant_id is None:
        return query
    return query.join(Admin, User.admin_id == Admin.id).filter(Admin.tenant_id == tenant_id)


def scope_nodes_query(query, tenant_id: Optional[int]):
    if tenant_id is None:
        return query
    return query.filter(Node.tenant_id == tenant_id)


def tenant_owned_node_ids(db: Session, tenant_id: int) -> set:
    rows = db.query(Node.id).filter(Node.tenant_id == tenant_id).all()
    return {r[0] for r in rows}


# --------------------------------------------------------------------------- #
# Branding
# --------------------------------------------------------------------------- #
def get_branding(db: Session, tenant_id: Optional[int]) -> Optional[BrandingSettings]:
    return (
        db.query(BrandingSettings)
        .filter(BrandingSettings.tenant_id.is_(None) if tenant_id is None
                else BrandingSettings.tenant_id == tenant_id)
        .first()
    )


def set_branding(db: Session, tenant_id: Optional[int], **fields) -> BrandingSettings:
    row = get_branding(db, tenant_id)
    if row is None:
        row = BrandingSettings(tenant_id=tenant_id)
        db.add(row)
    for key in (
        "panel_title", "logo_url", "favicon_url", "primary_color",
        "support_url", "sub_profile_title", "domain",
    ):
        if key in fields:
            setattr(row, key, fields[key])
    db.commit()
    db.refresh(row)
    return row


def _branding_dict(row: Optional[BrandingSettings]) -> dict:
    if row is None:
        return {}
    return {
        "panel_title": row.panel_title,
        "logo_url": row.logo_url,
        "favicon_url": row.favicon_url,
        "primary_color": row.primary_color,
        "support_url": row.support_url,
        "sub_profile_title": row.sub_profile_title,
        "domain": row.domain,
    }


def resolve_branding(db: Session, tenant_id: Optional[int]) -> dict:
    """Resolve effective branding: tenant value -> global default -> env/app default.

    Returns a plain dict suitable for the dashboard theme and subscription
    headers. Never returns None values for the core fields.
    """
    from app import PRODUCT_NAME
    from config import SUB_PROFILE_TITLE, SUB_SUPPORT_URL

    base = {
        "panel_title": PRODUCT_NAME,
        "logo_url": None,
        "favicon_url": None,
        "primary_color": "#5b8cff",
        "support_url": SUB_SUPPORT_URL,
        "sub_profile_title": SUB_PROFILE_TITLE,
        "domain": None,
    }

    layers = [_branding_dict(get_branding(db, None))]
    if tenant_id is not None:
        layers.append(_branding_dict(get_branding(db, tenant_id)))

    for layer in layers:
        for key, value in layer.items():
            if value:
                base[key] = value
    return base
