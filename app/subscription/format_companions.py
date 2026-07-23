"""Ensure Main / JSON / Clash subscription endpoint trios (3x-ui parity).

Fresh installs only seed ``default`` with path ``sub``. Migrated 3x-ui panels
also get companion rows for ``json`` + ``clash`` path prefixes. This module
backfills those companions for any panel-wide (``export_mode=full``) main
endpoint so the Subscription Endpoints UI shows all three channels.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.db import crud
from app.db.models import SubscriptionEndpoint
from app.models.subscription_endpoint import SubscriptionExportMode

# Same defaults 3x-ui uses when subJsonPath / subClashPath are unset.
_FORMAT_COMPANIONS: tuple[tuple[str, str, str], ...] = (
    ("json", "v2ray-json", "-json"),
    ("clash", "clash-meta", "-clash"),
)


def _is_main_panel_endpoint(ep: SubscriptionEndpoint) -> bool:
    slug = (ep.slug or "").strip()
    if not slug or slug.endswith("-json") or slug.endswith("-clash"):
        return False
    if ep.inbound_tag:
        return False
    mode = (ep.export_mode or SubscriptionExportMode.full.value)
    if hasattr(mode, "value"):
        mode = mode.value
    return str(mode) == SubscriptionExportMode.full.value


def ensure_format_companions_for_endpoint(
    db: Session,
    main: SubscriptionEndpoint,
    *,
    commit: bool = True,
) -> list[SubscriptionEndpoint]:
    """Create missing ``{slug}-json`` / ``{slug}-clash`` rows mirroring ``main``."""
    if not _is_main_panel_endpoint(main):
        return []

    created: list[SubscriptionEndpoint] = []
    main_path = (main.path_prefix or "sub").strip("/") or "sub"

    for path_prefix, format_default, suffix in _FORMAT_COMPANIONS:
        if path_prefix == main_path:
            continue
        slug = f"{main.slug}{suffix}"
        existing = crud.get_subscription_endpoint_by_slug(db, slug)
        if existing is not None:
            # Keep host/port/enabled in sync with main when branding updates.
            patch = {
                "host": main.host,
                "listen_port": main.listen_port,
                "public_base_url": main.public_base_url or "",
                "enabled": bool(main.enabled) and bool(main.host or main.slug == "default"),
                "format_default": format_default,
                "path_prefix": path_prefix,
                "export_mode": SubscriptionExportMode.full.value,
                "inbound_tag": None,
                "legacy_panel_id": main.legacy_panel_id,
            }
            # default companions stay enabled even without a host (panel IP /sub).
            if main.slug == "default":
                patch["enabled"] = bool(main.enabled)
            crud.update_subscription_endpoint(db, existing, patch)
            continue

        conflict = crud.get_subscription_endpoint_by_host_path(
            db, main.host, path_prefix
        )
        if conflict is not None:
            continue

        enabled = bool(main.enabled)
        if main.slug != "default" and not (main.host or "").strip():
            enabled = False

        payload = {
            "slug": slug,
            "host": main.host,
            "path_prefix": path_prefix,
            "public_base_url": main.public_base_url or "",
            "listen_port": main.listen_port,
            "inbound_tag": None,
            "export_mode": SubscriptionExportMode.full.value,
            "format_default": format_default,
            "legacy_panel_id": main.legacy_panel_id,
            "enabled": enabled,
        }
        created.append(crud.create_subscription_endpoint(db, payload))

    if commit:
        db.commit()
    return created


def ensure_all_format_companions(db: Session) -> int:
    """Backfill JSON/Clash companions for every panel-wide main endpoint."""
    created = 0
    mains = [
        ep
        for ep in crud.list_subscription_endpoints(db, enabled_only=False)
        if _is_main_panel_endpoint(ep)
    ]
    for main in mains:
        db.refresh(main)
        created += len(ensure_format_companions_for_endpoint(db, main, commit=False))
    db.commit()
    return created
