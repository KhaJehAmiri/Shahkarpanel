"""Per-inbound subscription domain/port/path settings (3x-ui-style, dashboard-facing).

Lets an admin pin an inbound to its own Listen Domain / Listen Port / URI
Path / Reverse Proxy URI, independent of every other inbound — the
differentiator requested when consolidating several 3x-ui panels (each on its
own domain) into a single NexusPanel instance without breaking any already
bookmarked subscription link.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.db import Session, get_db
from app.models.admin import Admin
from app.models.subscription_endpoint import (
    InboundSubscriptionSettingsModify,
    InboundSubscriptionSettingsResponse,
)
from app.subscription.inbound_endpoint import (
    InboundSubscriptionAlreadyInherited,
    InboundSubscriptionConflict,
    clear_inbound_subscription_settings,
    get_inbound_subscription_settings,
    set_inbound_subscription_settings,
)
from app.utils import responses

router = APIRouter(
    tags=["Inbound Subscription Settings"],
    prefix="/api/inbounds",
    responses={401: responses._401, 403: responses._403},
)


def _refresh_routes() -> None:
    try:
        from app import app as fastapi_app
        from app.routers import api_router
        from app.subscription.route_registry import refresh_subscription_routes

        refresh_subscription_routes(fastapi_app, api_router)
        from app.services.edge_proxy import sync_subscription_legacy_nginx
        from app.db import GetDB

        with GetDB() as db:
            sync_subscription_legacy_nginx(db)
    except Exception:
        pass


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
    except InboundSubscriptionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "already_inherited": isinstance(exc, InboundSubscriptionAlreadyInherited),
                "endpoint_slug": exc.endpoint_slug,
                "conflict_inbound_tag": exc.conflict_inbound_tag,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _refresh_routes()
    settings = get_inbound_subscription_settings(db, tag)
    return InboundSubscriptionSettingsResponse(
        inbound_tag=settings.inbound_tag,
        inherited=settings.inherited,
        override=settings.override,
        effective=settings.effective,
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
