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
    """The requested Listen Domain/URI Path exactly matches an existing endpoint
    that isn't dedicated to any single inbound (``export_mode="full"``, e.g. a
    panel-wide endpoint a 3x-ui migration created). Subscription serving is
    keyed purely on (host, path) -> one endpoint -> token/alias lookup, which
    never discriminates by inbound tag for a non-dedicated endpoint — so that
    endpoint ALREADY serves every inbound at that domain+path, including this
    one. Not a real conflict with another inbound, just a redundant no-op the
    admin doesn't need to (and can't, since host+path must stay unique) create.
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

        if not conflict.inbound_tag and not existing:
            # Brand-new override attempt (this inbound has no dedicated row
            # yet) on a (host, path) already served by a non-dedicated
            # endpoint (export_mode="full", e.g. a whole migrated 3x-ui
            # panel) — that endpoint already serves this exact domain+path
            # for EVERY inbound regardless of tag, since subscription serving
            # resolves purely by (host, path) and then by the requester's own
            # token, never by inbound. So this inbound is already served here
            # too; creating a row for the identical (host, path) is both
            # unnecessary and impossible (routing requires host+path to stay
            # unique). This is a real, common, legitimate setup (per 3x-ui:
            # one panel's domain+path is shared by ALL of its inbounds, with
            # users differentiated by their own token) — not an error, just a
            # no-op to explain.
            suggested_path = f"{prefix}-{tag}"[:64]
            raise InboundSubscriptionAlreadyInherited(
                f"Listen Domain '{host_label}' + URI Path '/{prefix}/' is already served by "
                f"subscription endpoint '{conflict.slug}', which isn't dedicated to a single "
                "inbound — it already works for every inbound sharing this domain+path "
                "(including this one), with each user told apart by their own token. No "
                "override is needed here, and one can't be created for the exact same "
                "domain+path. To give THIS inbound its own DEDICATED link that only lists "
                "its own configs, pick a different URI Path "
                f"(e.g. '{suggested_path}') and/or Listen Domain.",
                endpoint_slug=conflict.slug,
                conflict_inbound_tag=conflict.inbound_tag,
            )

        if not conflict.inbound_tag and existing:
            # This inbound ALREADY has a dedicated override and the admin is
            # trying to REPOINT it (e.g. change just the Listen Domain) to a
            # (host, path) a non-dedicated/shared endpoint already owns.
            # Unlike the brand-new case above, this is NOT a harmless no-op:
            # the admin's existing override is scoped to only THIS inbound
            # (export_mode="inbound_only"), which is meaningfully different
            # from the shared endpoint (which serves every inbound on that
            # panel) — silently treating this as "already covered" would
            # hide the fact that the requested change was rejected and the
            # OLD override is still the one in effect. Say so plainly.
            raise InboundSubscriptionConflict(
                f"Could not update this inbound's subscription settings: Listen Domain "
                f"'{host_label}' + URI Path '/{prefix}/' is already used by the shared "
                f"subscription endpoint '{conflict.slug}' (not dedicated to a single "
                f"inbound). Your existing override for '{tag}' — Listen Domain "
                f"'{existing.host or 'any domain'}', URI Path '/{existing.path_prefix}/' — "
                "was NOT changed and is still what's in effect. Pick a different URI Path "
                f"to keep a dedicated link on '{host_label}', or clear this inbound's "
                f"override entirely if you're fine switching to the shared "
                f"'{conflict.slug}' link (which shows every inbound on that domain, not "
                "just this one).",
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
