"""Least-loaded subscription panel balancer (p1…p9 / srw1…).

New accounts (owner + reseller) are bound to the enabled panel endpoint that
currently has the fewest users — no hard caps, just spread.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.db import crud
from app.db.models import SubscriptionEndpoint, SubscriptionTokenAlias

_PANEL_SLUG_RE = re.compile(r"^p\d+$", re.I)
_USERNAME_PANEL_RE = re.compile(r"^(p\d+)_", re.I)


def list_balance_panels(db: Session) -> list[SubscriptionEndpoint]:
    """Main panel endpoints eligible for load-balancing (p1, p2, … — not -json/-clash)."""
    out: list[SubscriptionEndpoint] = []
    for ep in crud.list_subscription_endpoints(db, enabled_only=True):
        if not ep.enabled:
            continue
        if ep.inbound_tag:
            continue
        slug = (ep.slug or "").strip()
        if not slug or slug == "default":
            continue
        if slug.endswith("-json") or slug.endswith("-clash"):
            continue
        if _PANEL_SLUG_RE.match(slug):
            out.append(ep)
    return sorted(out, key=lambda e: e.slug)


def panel_user_count(db: Session, endpoint_id: int) -> int:
    return (
        db.query(SubscriptionTokenAlias)
        .filter(SubscriptionTokenAlias.endpoint_id == endpoint_id)
        .count()
    )


def pick_least_loaded_panel(db: Session) -> Optional[SubscriptionEndpoint]:
    panels = list_balance_panels(db)
    if not panels:
        return None
    scored = [(panel_user_count(db, ep.id), ep.id, ep) for ep in panels]
    scored.sort(key=lambda row: (row[0], row[1]))
    return scored[0][2]


def panel_counts(db: Session) -> list[dict]:
    return [
        {
            "id": ep.id,
            "slug": ep.slug,
            "host": ep.host,
            "legacy_panel_id": ep.legacy_panel_id,
            "user_count": panel_user_count(db, ep.id),
        }
        for ep in list_balance_panels(db)
    ]


def reseller_branding_panel(db: Session, admin) -> Optional[SubscriptionEndpoint]:
    """Reseller branding subscription endpoint (``reseller-{tenant_id}``), if any."""
    if admin is None or getattr(admin, "is_sudo", False):
        return None
    tenant_id = getattr(admin, "tenant_id", None)
    if tenant_id is None:
        return None
    try:
        from app.tenant.subscription_domain import get_reseller_subscription_endpoint

        return get_reseller_subscription_endpoint(db, int(tenant_id))
    except Exception:
        return None


def panels_for_create(db: Session, admin=None) -> list[dict]:
    """Panels shown in create/bulk-create pickers for this admin.

    Owner installs use ``p1…p9``. Resellers on branding-only installs (no pN
    panels) still need their domain endpoint listed — otherwise the UI says
    «no panels / no inbound» and new users never bind to the reseller domain.
    """
    rows = panel_counts(db)
    brand = reseller_branding_panel(db, admin)
    if brand is None:
        return rows
    if any(int(r["id"]) == int(brand.id) for r in rows):
        return rows
    return [
        {
            "id": brand.id,
            "slug": brand.slug,
            "host": brand.host,
            "legacy_panel_id": brand.legacy_panel_id,
            "user_count": panel_user_count(db, brand.id),
        },
        *rows,
    ]


def default_panel_for_create(db: Session, admin=None) -> Optional[SubscriptionEndpoint]:
    """Least-loaded pN panel, else the reseller branding endpoint."""
    ep = pick_least_loaded_panel(db)
    if ep is not None:
        return ep
    return reseller_branding_panel(db, admin)


def endpoint_for_panel_slug(db: Session, slug: str) -> Optional[SubscriptionEndpoint]:
    slug = (slug or "").strip()
    if not slug:
        return None
    ep = crud.get_subscription_endpoint_by_slug(db, slug)
    if ep and ep.enabled:
        return ep
    for ep in list_balance_panels(db):
        if (ep.legacy_panel_id or "").strip().lower() == slug.lower():
            return ep
    return None


def ensure_panel_username(username: str, panel_slug: str, *, max_len: int = 32) -> str:
    """Force ``pN_…`` username shape used by migrated panels / filters."""
    username = (username or "").strip()
    panel_slug = (panel_slug or "").strip()
    if not username or not panel_slug:
        return username
    if _USERNAME_PANEL_RE.match(username):
        # Keep an explicit panel prefix the caller already chose.
        return username[:max_len]
    prefix = f"{panel_slug}_"
    room = max_len - len(prefix)
    if room < 3:
        return username[:max_len]
    core = username[:room]
    return f"{prefix}{core}"


def alias_token_for_username(username: str, panel_slug: str) -> str:
    prefix = f"{panel_slug}_"
    if username.startswith(prefix) and len(username) > len(prefix):
        return username[len(prefix) :]
    return username


def resolve_panel_for_create(
    db: Session,
    *,
    endpoint_id: Optional[int] = None,
    username: Optional[str] = None,
    username_prefix: Optional[str] = None,
    admin=None,
) -> Tuple[Optional[SubscriptionEndpoint], str]:
    """Pick panel + final username for a new account.

    Priority:
      1. Explicit ``endpoint_id``
      2. ``pN_`` already present in username / prefix
      3. Least-loaded enabled pN panel
      4. Reseller branding domain (when admin is a reseller)
    """
    username = (username or "").strip()

    if endpoint_id is not None:
        ep = crud.get_subscription_endpoint(db, endpoint_id)
        if ep is None or not ep.enabled:
            raise ValueError("Selected subscription panel endpoint was not found or is disabled")
        if _PANEL_SLUG_RE.match((ep.slug or "").strip()):
            return ep, ensure_panel_username(username, ep.slug)
        return ep, username

    m = _USERNAME_PANEL_RE.match(username or "")
    if not m and username_prefix:
        m = re.match(r"^(p\d+)_?", username_prefix.strip(), re.I)
    if m:
        ep = endpoint_for_panel_slug(db, m.group(1).lower())
        if ep is not None:
            return ep, ensure_panel_username(username, ep.slug)

    ep = default_panel_for_create(db, admin)
    if ep is None:
        return None, username
    if _PANEL_SLUG_RE.match((ep.slug or "").strip()):
        return ep, ensure_panel_username(username, ep.slug)
    return ep, username


def bind_user_to_panel(
    db: Session,
    *,
    user_id: int,
    username: str,
    endpoint: SubscriptionEndpoint,
    source: str = "auto-balance",
    commit: bool = True,
) -> SubscriptionTokenAlias:
    token = alias_token_for_username(username, endpoint.slug)
    return crud.upsert_subscription_token_alias(
        db,
        token=token,
        user_id=user_id,
        endpoint_id=endpoint.id,
        source=source,
        commit=commit,
    )
