"""Resolve subscription endpoints from incoming requests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.models import SubscriptionEndpoint
from app.models.subscription_endpoint import SubscriptionExportMode

# 3x-ui path aliases → client config format
PATH_FORMAT_ALIASES: dict[str, str] = {
    "json": "v2ray-json",
    "clash": "clash-meta",
}


@dataclass(frozen=True)
class SubscriptionRequestContext:
    endpoint: Optional[SubscriptionEndpoint]
    path_prefix: str
    inbound_filter: Optional[str]
    format_default: Optional[str]

    @property
    def export_mode(self) -> str:
        if self.endpoint and self.endpoint.export_mode:
            return self.endpoint.export_mode
        return SubscriptionExportMode.full.value


def request_host(request: Request) -> str:
    host = (request.headers.get("host") or "").strip().lower()
    return host.split(":")[0] if host else ""


def path_prefix_from_request(request: Request) -> str:
    parts = request.url.path.strip("/").split("/")
    return parts[0] if parts else ""


def resolve_subscription_endpoint(
    db: Session,
    *,
    host: str,
    path_prefix: str,
) -> Optional[SubscriptionEndpoint]:
    from app.db import crud

    prefix = (path_prefix or "").strip().strip("/")
    if not prefix:
        return None
    host_norm = (host or "").strip().lower().split(":")[0] or None
    if host_norm:
        ep = crud.get_subscription_endpoint_by_host_path(db, host_norm, prefix)
        if ep:
            return ep
    return crud.get_subscription_endpoint_by_host_path(db, None, prefix)


def _panel_prefix_candidates(ep: SubscriptionEndpoint) -> set[str]:
    from app.migration.three_x_ui import _TAG_SAFE

    candidates: set[str] = set()
    for raw in (ep.slug, ep.legacy_panel_id):
        if not raw:
            continue
        candidates.add(_TAG_SAFE.sub("-", raw.strip()).strip("-") or raw)
    return candidates


def resolve_endpoint_for_inbound_tag(
    db: Session, inbound_tag: Optional[str]
) -> Optional[SubscriptionEndpoint]:
    """Which endpoint governs subscription links for users of ``inbound_tag``.

    Resolution order (most to least specific):
    1. An explicit per-inbound override (``inbound_tag`` set, ``export_mode=inbound_only``) —
       set from the dashboard's per-inbound "Subscription" settings.
    2. A panel-wide endpoint created by 3x-ui migration, matched by tag prefix
       (migrated tags are ``"{panel_slug}-{original_tag}"`` — see
       ``app.migration.three_x_ui._slugify_tag``). This is what lets a migrated
       panel's inbounds automatically keep their original domain/port/path with
       zero manual reconfiguration.
    3. ``None`` — caller should fall back to the global default endpoint.
    """
    from app.db import crud

    tag = (inbound_tag or "").strip()
    if not tag:
        return None

    override = crud.get_subscription_endpoint_by_inbound_tag(db, tag)
    if override:
        return override

    for ep in crud.list_subscription_endpoints(db, enabled_only=True):
        if ep.inbound_tag or ep.slug == "default":
            continue
        candidates = _panel_prefix_candidates(ep)
        if any(tag == c or tag.startswith(f"{c}-") for c in candidates):
            return ep
    return None


def panel_endpoint_ids_for_subscription(
    db: Session, endpoint: Optional[SubscriptionEndpoint]
) -> list[int]:
    """Panel-wide endpoint IDs that may hold legacy token aliases for an inbound override."""
    from app.db import crud

    if not endpoint or not endpoint.inbound_tag:
        return []
    tag = endpoint.inbound_tag.strip()
    ids: list[int] = []
    for ep in crud.list_subscription_endpoints(db, enabled_only=True):
        if ep.inbound_tag or ep.slug == "default":
            continue
        candidates = _panel_prefix_candidates(ep)
        if any(tag == c or tag.startswith(f"{c}-") for c in candidates):
            ids.append(ep.id)
    return ids


def build_subscription_context(request: Request, db: Session) -> SubscriptionRequestContext:
    prefix = path_prefix_from_request(request)
    endpoint = resolve_subscription_endpoint(db, host=request_host(request), path_prefix=prefix)

    inbound_filter: Optional[str] = None
    export_mode = SubscriptionExportMode.full.value
    format_default: Optional[str] = PATH_FORMAT_ALIASES.get(prefix)

    if endpoint:
        export_mode = endpoint.export_mode or export_mode
        if endpoint.format_default:
            format_default = endpoint.format_default
        if export_mode == SubscriptionExportMode.inbound_only.value and endpoint.inbound_tag:
            inbound_filter = endpoint.inbound_tag

    return SubscriptionRequestContext(
        endpoint=endpoint,
        path_prefix=prefix,
        inbound_filter=inbound_filter,
        format_default=format_default,
    )
