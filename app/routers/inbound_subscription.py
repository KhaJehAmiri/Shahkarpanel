"""Per-inbound subscription domain/port/path settings (3x-ui-style, dashboard-facing).

Lets an admin pin an inbound to its own Listen Domain / Listen Port / URI
Path / Reverse Proxy URI, independent of every other inbound — the
differentiator requested when consolidating several 3x-ui panels (each on its
own domain) into a single NexusPanel instance without breaking any already
bookmarked subscription link.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.db import Session, get_db
from app.models.admin import Admin
from app.models.subscription_endpoint import (
    InboundSubscriptionSettingsModify,
    InboundSubscriptionSettingsResponse,
    SubscriptionSslStatusResponse,
)
from app.subscription.inbound_endpoint import (
    InboundSubscriptionAlreadyInherited,
    InboundSubscriptionConflict,
    clear_inbound_subscription_settings,
    get_inbound_subscription_settings,
    set_inbound_subscription_settings,
)
from app.utils import responses

logger = logging.getLogger("nexus-inbound-sub")

router = APIRouter(
    tags=["Inbound Subscription Settings"],
    prefix="/api/inbounds",
    responses={401: responses._401, 403: responses._403},
)


def _refresh_routes(*, ensure_ssl_host: str | None = None) -> None:
    try:
        from app.routers.subscription_endpoints import _refresh_routes as refresh_all

        refresh_all(ensure_ssl_host=ensure_ssl_host)
    except Exception:
        logger.exception("subscription route/nginx refresh failed")


@router.get("/{tag}/subscription-endpoint", response_model=InboundSubscriptionSettingsResponse)
def get_inbound_subscription_endpoint(
    tag: str,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    settings = get_inbound_subscription_settings(db, tag)
    return InboundSubscriptionSettingsResponse(
        inbound_tag=settings.inbound_tag,
        inherited=settings.inherited,
        override=settings.override,
        effective=settings.effective,
    )


@router.put("/{tag}/subscription-endpoint", response_model=InboundSubscriptionSettingsResponse)
def put_inbound_subscription_endpoint(
    tag: str,
    body: InboundSubscriptionSettingsModify,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    try:
        set_inbound_subscription_settings(
            db,
            tag,
            host=body.host,
            listen_port=body.listen_port,
            path_prefix=body.path_prefix,
            public_base_url=body.public_base_url,
            enabled=body.enabled,
        )
    except InboundSubscriptionAlreadyInherited:
        # Same domain+path as a shared panel endpoint — inheritance is the
        # correct outcome (path stays "sub"). Any dedicated override was
        # already cleared inside set_inbound_subscription_settings.
        _refresh_routes()
        settings = get_inbound_subscription_settings(db, tag)
        return InboundSubscriptionSettingsResponse(
            inbound_tag=settings.inbound_tag,
            inherited=settings.inherited,
            override=settings.override,
            effective=settings.effective,
        )
    except InboundSubscriptionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "already_inherited": False,
                "endpoint_slug": exc.endpoint_slug,
                "conflict_inbound_tag": exc.conflict_inbound_tag,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Auto-issue LE + :443 for the Listen Domain so p2/p3 don't fall through to srw1.
    _refresh_routes(ensure_ssl_host=(body.host or "").strip() or None)
    settings = get_inbound_subscription_settings(db, tag)
    return InboundSubscriptionSettingsResponse(
        inbound_tag=settings.inbound_tag,
        inherited=settings.inherited,
        override=settings.override,
        effective=settings.effective,
    )


@router.get(
    "/{tag}/subscription-endpoint/ssl",
    response_model=SubscriptionSslStatusResponse,
)
def get_inbound_subscription_ssl(
    tag: str,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    settings = get_inbound_subscription_settings(db, tag)
    ep = settings.override or settings.effective
    host = (ep.host if ep else None) or ""
    if not host:
        raise HTTPException(status_code=400, detail="No Listen Domain configured for this inbound")
    from app.services.edge_proxy import subscription_domain_ssl_status

    status = subscription_domain_ssl_status(host)
    return SubscriptionSslStatusResponse(ok=bool(status.get("https_ready")), **status)


@router.post(
    "/{tag}/subscription-endpoint/enable-ssl",
    response_model=SubscriptionSslStatusResponse,
)
def enable_inbound_subscription_ssl(
    tag: str,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Issue Let's Encrypt cert + publish :443 HTTPS vhost for this inbound's domain."""
    settings = get_inbound_subscription_settings(db, tag)
    ep = settings.override or settings.effective
    host = (ep.host if ep else None) or ""
    if not host:
        raise HTTPException(
            status_code=400,
            detail="Set a Listen Domain and save before enabling SSL",
        )
    from app.services.edge_proxy import ensure_subscription_domain_ssl

    result = ensure_subscription_domain_ssl(db, host)
    if not result.get("https_ready"):
        raise HTTPException(
            status_code=502,
            detail=result.get("message")
            or result.get("sync_message")
            or "SSL activation failed — check DNS A record and port 80 reachability",
        )
    return SubscriptionSslStatusResponse(
        host=result.get("host") or host,
        cert_present=bool(result.get("cert_present")),
        https_ready=bool(result.get("https_ready")),
        message=result.get("message") or "SSL active",
        ok=True,
        sync_applied=result.get("sync_applied"),
        sync_message=result.get("sync_message") or "",
    )


@router.delete("/{tag}/subscription-endpoint")
def delete_inbound_subscription_endpoint(
    tag: str,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    removed = clear_inbound_subscription_settings(db, tag)
    if not removed:
        raise HTTPException(status_code=404, detail="No per-inbound subscription override set")
    _refresh_routes()
    return {"ok": True}
