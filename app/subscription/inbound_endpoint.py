"""Per-inbound subscription domain/port/path bindings (dashboard-facing).

Exposes the same four settings 3x-ui shows per-inbound ("Listen Domain",
"Listen Port", "URI Path", "Reverse Proxy URI") as an explicit override on top
of ``SubscriptionEndpoint`` — the model already carries all four concepts
(``host``, ``listen_port``, ``path_prefix``, ``public_base_url``), scoped to a
single inbound via ``inbound_tag`` + ``export_mode="inbound_only"``. This
module is the single place that creates/updates/removes that override so the
dashboard, the API router, and tests share one code path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import SubscriptionEndpoint
from app.models.subscription_endpoint import SubscriptionExportMode

_SLUG_MAX = 64
_SLUG_PREFIX = "ib-"


class InboundSubscriptionConflict(ValueError):
    """Raised when the requested host/path is already owned by another endpoint."""

    def __init__(self, message: str, *, endpoint_slug: Optional[str] = None, conflict_inbound_tag: Optional[str] = None):
        super().__init__(message)
        self.endpoint_slug = endpoint_slug
        self.conflict_inbound_tag = conflict_inbound_tag


class InboundSubscriptionAlreadyInherited(InboundSubscriptionConflict):
    """The requested Listen Domain/URI Path exactly matches a shared panel
    endpoint (``export_mode="full"``, e.g. from 3x-ui migration). That route
    already serves every inbound — including this one. Any dedicated override
    for this inbound was cleared; the caller should treat this as success with
    inheritance (path stays ``sub``).
    """


def _slug_for_inbound(inbound_tag: str) -> str:
    import hashlib

    raw = f"{_SLUG_PREFIX}{inbound_tag}"
    if len(raw) <= _SLUG_MAX:
        return raw
    digest = hashlib.sha1(inbound_tag.encode()).hexdigest()[:10]
    return f"{_SLUG_PREFIX}{inbound_tag[: _SLUG_MAX - len(_SLUG_PREFIX) - 11]}_{digest}"[:_SLUG_MAX]


@dataclass(frozen=True)
class InboundSubscriptionSettings:
    inbound_tag: str
    override: Optional[SubscriptionEndpoint]
    effective: Optional[SubscriptionEndpoint]
    inherited: bool


def get_inbound_subscription_settings(db: Session, inbound_tag: str) -> InboundSubscriptionSettings:
    from app.db import crud
    from app.subscription.endpoint_resolver import resolve_endpoint_for_inbound_tag

    tag = (inbound_tag or "").strip()
    override = crud.get_subscription_endpoint_by_inbound_tag(db, tag)
    effective = override or resolve_endpoint_for_inbound_tag(db, tag) or crud.get_default_subscription_endpoint(db)
    return InboundSubscriptionSettings(
        inbound_tag=tag,
        override=override,
        effective=effective,
        inherited=override is None,
    )


def set_inbound_subscription_settings(
    db: Session,
    inbound_tag: str,
    *,
    host: Optional[str],
    listen_port: Optional[int],
    path_prefix: str,
    public_base_url: str = "",
    enabled: bool = True,
) -> SubscriptionEndpoint:
    """Create or update the per-inbound override. Purely additive: never touches
    other ``SubscriptionEndpoint`` rows (e.g. the panel-wide endpoint a 3x-ui
    migration created), so existing subscription links keep resolving exactly
    as before.

    If the requested host+path matches a shared panel endpoint, any dedicated
    override is removed and ``InboundSubscriptionAlreadyInherited`` is raised
    so the API can return success with inheritance (URI Path stays ``sub``).
    """
    from app.db import crud

    tag = (inbound_tag or "").strip()
    if not tag:
        raise ValueError("inbound_tag is required")

    prefix = (path_prefix or "").strip().strip("/")
    if not prefix:
        raise ValueError("path_prefix (URI Path) is required")

    host_norm = (host or "").strip().lower().split(":")[0] or None

    existing = crud.get_subscription_endpoint_by_inbound_tag(db, tag)
    # Updating an override: blank Listen Domain means "keep current domain",
    # not "switch to any-domain/default routing" (which would collide with the
    # shared ``default`` endpoint at host=NULL + path=/sub/).
    if existing and not host_norm and existing.host:
        host_norm = existing.host

    conflict = crud.get_subscription_endpoint_by_host_path(db, host_norm, prefix, enabled_only=False)
    if conflict and (not existing or conflict.id != existing.id):
        host_label = host_norm or "any domain"

        if not conflict.inbound_tag:
            # Same domain+path as a shared panel endpoint — keep /sub/ via
            # inheritance instead of inventing sub-<inboundTag>.
            if existing:
                crud.remove_subscription_endpoint(db, existing)
            raise InboundSubscriptionAlreadyInherited(
                f"Listen Domain '{host_label}' + URI Path '/{prefix}/' is already served by "
                f"subscription endpoint '{conflict.slug}'. This inbound inherits that shared "
                "route (no dedicated override). To give THIS inbound its own dedicated link "
                "that only lists its configs, use a different Listen Domain and/or URI Path.",
                endpoint_slug=conflict.slug,
                conflict_inbound_tag=conflict.inbound_tag,
            )

        raise InboundSubscriptionConflict(
            f"Could not {'update' if existing else 'save'} this inbound's subscription "
            f"settings: Listen Domain '{host_label}' + URI Path '/{prefix}/' is already "
            f"used by subscription endpoint '{conflict.slug}', which is dedicated to "
            f"inbound '{conflict.inbound_tag}'. "
            + (
                f"Your existing override for '{tag}' — Listen Domain "
                f"'{existing.host or 'any domain'}', URI Path '/{existing.path_prefix}/' — "
                "was NOT changed. "
                if existing
                else ""
            )
            + "Pick a different Listen Domain or URI Path for this inbound.",
            endpoint_slug=conflict.slug,
            conflict_inbound_tag=conflict.inbound_tag,
        )

    data = {
        "slug": existing.slug if existing else _slug_for_inbound(tag),
        "host": host_norm,
        "path_prefix": prefix,
        "public_base_url": (public_base_url or "").strip().rstrip("/"),
        "listen_port": listen_port,
        "inbound_tag": tag,
        "export_mode": SubscriptionExportMode.inbound_only.value,
        "enabled": enabled,
    }
    if existing:
        return crud.update_subscription_endpoint(db, existing, data)
    return crud.create_subscription_endpoint(db, data)


def clear_inbound_subscription_settings(db: Session, inbound_tag: str) -> bool:
    from app.db import crud

    tag = (inbound_tag or "").strip()
    existing = crud.get_subscription_endpoint_by_inbound_tag(db, tag)
    if not existing:
        return False
    crud.remove_subscription_endpoint(db, existing)
    return True
