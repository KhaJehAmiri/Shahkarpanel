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
    "branding_for_user",
    "subscription_brand_title",
    "tenant_owned_node_ids",
    "ensure_reseller_tenants",
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


def ensure_reseller_tenants(db: Session) -> int:
    """Backfill tenants for legacy reseller/support admins missing tenant_id."""
    legacy = (
        db.query(Admin)
        .filter(
            Admin.is_sudo.is_(False),
            Admin.tenant_id.is_(None),
            Admin.role.in_(("reseller", "support")),
        )
        .all()
    )
    count = 0
    for admin in legacy:
        tenant = create_tenant(
            db,
            name=admin.username,
            slug=admin.username,
            owner_admin_id=admin.id,
            max_users=getattr(admin, "max_users", None),
            max_nodes=getattr(admin, "max_nodes", None),
        )
        admin.tenant_id = tenant.id
        db.commit()
        count += 1
    return count


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


def set_branding(
    db: Session,
    tenant_id: Optional[int],
    *,
    allow_global: bool = False,
    **fields,
) -> BrandingSettings:
    if tenant_id is None and not allow_global:
        raise ValueError("Cannot write global branding without allow_global=True")
    row = get_branding(db, tenant_id)
    if row is None:
        row = BrandingSettings(tenant_id=tenant_id)
        db.add(row)

    # Validate subscription listen port before commit so a VPN-port clash
    # (e.g. 2082 Reality) never leaves branding stuck on a broken SSL URL.
    if "sub_port" in fields or "domain" in fields:
        from app.tenant.subscription_domain import (
            assert_subscription_listen_port_available,
            domain_from_branding,
            normalize_sub_port,
        )

        next_port = fields["sub_port"] if "sub_port" in fields else getattr(row, "sub_port", None)
        next_domain = fields["domain"] if "domain" in fields else getattr(row, "domain", None)
        probe = {"domain": next_domain}
        host = domain_from_branding(probe, allow_panel_url=False)
        if host:
            assert_subscription_listen_port_available(
                db,
                normalize_sub_port(next_port, default=443),
                host=host,
            )

    for key in (
        "panel_title", "logo_url", "favicon_url", "primary_color",
        "support_url", "sub_profile_title", "domain", "panel_url",
        "sub_path", "sub_port",
    ):
        if key in fields:
            setattr(row, key, fields[key])
    db.commit()
    db.refresh(row)
    # Keep subscription links + nginx in sync only when domain routing fields
    # change. Title/logo/color updates must succeed for resellers with no
    # custom domain (and must not collide with another endpoint via panel_url).
    domain_touch = bool({"domain", "sub_path", "sub_port"} & fields.keys())
    if domain_touch:
        try:
            from app.tenant.subscription_domain import sync_branding_subscription_domain

            sync_branding_subscription_domain(db, tenant_id)
        except ValueError:
            raise
        except Exception:
            pass
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
        "panel_url": getattr(row, "panel_url", None),
        "sub_path": getattr(row, "sub_path", None),
        "sub_port": getattr(row, "sub_port", None),
    }


def resolve_branding(db: Session, tenant_id: Optional[int]) -> dict:
    """Resolve effective branding: tenant value -> global default -> env/app default.

    Returns a plain dict suitable for the dashboard theme and subscription
    headers. Never returns None values for the core fields.
    """
    from app import PRODUCT_NAME
    from config import PANEL_DEFAULT_LANG, PANEL_TITLE, PRIMARY_COLOR, SUB_PROFILE_TITLE, SUB_SUPPORT_URL

    base = {
        "panel_title": PANEL_TITLE or PRODUCT_NAME,
        "logo_url": None,
        "favicon_url": None,
        "primary_color": PRIMARY_COLOR or "#5b8cff",
        "support_url": SUB_SUPPORT_URL,
        "sub_profile_title": SUB_PROFILE_TITLE,
        "domain": None,
        "panel_url": None,
        "sub_path": None,
        "sub_port": None,
    }

    layers = [_branding_dict(get_branding(db, None))]
    if tenant_id is not None:
        layers.append(_branding_dict(get_branding(db, tenant_id)))

    for layer in layers:
        for key, value in layer.items():
            # sub_port is an int — treat any non-None as set (including unusual ports).
            if key == "sub_port":
                if value is not None:
                    base[key] = value
            elif value:
                base[key] = value
    return base


def branding_for_user(db: Session, dbuser) -> dict:
    """Resolve branding for a subscription user via their owning admin's tenant."""
    tenant_id = None
    admin_id = getattr(dbuser, "admin_id", None)
    if admin_id is not None:
        admin = db.query(Admin).filter(Admin.id == admin_id).first()
        if admin is not None:
            tenant_id = admin.tenant_id
    return resolve_branding(db, tenant_id)


def subscription_brand_title(branding: dict) -> str:
    """Title clients show for a subscription profile."""
    return (
        (branding.get("sub_profile_title") or "").strip()
        or (branding.get("panel_title") or "").strip()
        or ""
    )
