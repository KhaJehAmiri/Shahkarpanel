"""Admin CRUD for subscription endpoints."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.models.subscription_endpoint import (
    SubscriptionEndpointCreate,
    SubscriptionEndpointModify,
    SubscriptionEndpointResponse,
    SubscriptionTokenAliasCreate,
    SubscriptionTokenAliasResponse,
)
from app.utils import responses

router = APIRouter(
    tags=["Subscription Endpoints"],
    prefix="/api/subscription-endpoints",
    responses={401: responses._401, 403: responses._403},
)


@router.get("", response_model=List[SubscriptionEndpointResponse])
def list_endpoints(
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    # Fresh installs only seed Main (``sub``). Backfill JSON/Clash companions
    # so the UI matches migrated 3x-ui panels (Main + JSON + Clash tabs).
    try:
        from app.subscription.format_companions import ensure_all_format_companions

        n = ensure_all_format_companions(db)
        if n:
            from app import app as fastapi_app
            from app.routers import api_router
            from app.services.edge_proxy import sync_subscription_legacy_nginx
            from app.subscription.route_registry import refresh_subscription_routes

            refresh_subscription_routes(fastapi_app, api_router)
            try:
                sync_subscription_legacy_nginx(db)
            except Exception:
                pass
    except Exception:
        pass
    return crud.list_subscription_endpoints(db)


@router.get("/balance")
def panel_balance(
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """Panel picker stats for owner + reseller create/bulk-create flows.

    Includes ``p1…p9`` when present. For resellers on branding-only installs
    (no pN panels), also exposes their ``reseller-{tenant}`` domain endpoint so
    the UI can bind new users to the correct subscription host.
    """
    from app.subscription.panel_balance import (
        default_panel_for_create,
        panels_for_create,
    )

    rows = panels_for_create(db, admin)
    next_ep = default_panel_for_create(db, admin)
    return {
        "panels": rows,
        "next": (
            {
                "id": next_ep.id,
                "slug": next_ep.slug,
                "host": next_ep.host,
                "user_count": next(
                    (r["user_count"] for r in rows if r["id"] == next_ep.id),
                    0,
                ),
            }
            if next_ep
            else None
        ),
    }


@router.post("", response_model=SubscriptionEndpointResponse)
def create_endpoint(
    body: SubscriptionEndpointCreate,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    if crud.get_subscription_endpoint_by_slug(db, body.slug):
        raise HTTPException(status_code=409, detail="Slug already exists")
    data = body.model_dump()
    if hasattr(data.get("export_mode"), "value"):
        data["export_mode"] = data["export_mode"].value
    ep = crud.create_subscription_endpoint(db, data)
    _refresh_routes(ensure_ssl_host=(body.host or "").strip() or None)
    return ep


@router.get("/{endpoint_id}", response_model=SubscriptionEndpointResponse)
def get_endpoint(
    endpoint_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    ep = crud.get_subscription_endpoint(db, endpoint_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return ep


@router.put("/{endpoint_id}", response_model=SubscriptionEndpointResponse)
def update_endpoint(
    endpoint_id: int,
    body: SubscriptionEndpointModify,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    ep = crud.get_subscription_endpoint(db, endpoint_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    data = body.model_dump(exclude_unset=True)
    if "export_mode" in data and data["export_mode"] is not None:
        data["export_mode"] = data["export_mode"].value
    ep = crud.update_subscription_endpoint(db, ep, data)
    host = data.get("host", ep.host)
    _refresh_routes(ensure_ssl_host=(host or "").strip() or None)
    return ep


@router.delete("/{endpoint_id}")
def delete_endpoint(
    endpoint_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    ep = crud.get_subscription_endpoint(db, endpoint_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    if ep.slug == "default":
        raise HTTPException(status_code=400, detail="Cannot delete default endpoint")
    crud.remove_subscription_endpoint(db, ep)
    _refresh_routes()
    return {"ok": True}


@router.get("/{endpoint_id}/ssl", response_model=None)
def get_endpoint_ssl(
    endpoint_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    from app.models.subscription_endpoint import SubscriptionSslStatusResponse
    from app.services.edge_proxy import subscription_domain_ssl_status

    ep = crud.get_subscription_endpoint(db, endpoint_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    if not ep.host:
        raise HTTPException(status_code=400, detail="Endpoint has no host")
    status = subscription_domain_ssl_status(ep.host)
    return SubscriptionSslStatusResponse(ok=bool(status.get("https_ready")), **status)


@router.post("/{endpoint_id}/enable-ssl", response_model=None)
def enable_endpoint_ssl(
    endpoint_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    from app.models.subscription_endpoint import SubscriptionSslStatusResponse
    from app.services.edge_proxy import ensure_subscription_domain_ssl

    ep = crud.get_subscription_endpoint(db, endpoint_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    if not ep.host:
        raise HTTPException(status_code=400, detail="Endpoint has no host")
    result = ensure_subscription_domain_ssl(db, ep.host)
    if not result.get("https_ready"):
        raise HTTPException(
            status_code=502,
            detail=result.get("message")
            or result.get("sync_message")
            or "SSL activation failed",
        )
    return SubscriptionSslStatusResponse(
        host=result.get("host") or ep.host,
        cert_present=bool(result.get("cert_present")),
        https_ready=bool(result.get("https_ready")),
        message=result.get("message") or "SSL active",
        ok=True,
        sync_applied=result.get("sync_applied"),
        sync_message=result.get("sync_message") or "",
    )


@router.post("/aliases", response_model=SubscriptionTokenAliasResponse)
def create_alias(
    body: SubscriptionTokenAliasCreate,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    alias = crud.upsert_subscription_token_alias(
        db,
        token=body.token,
        user_id=body.user_id,
        endpoint_id=body.endpoint_id,
        source=body.source,
    )
    return alias


def _refresh_routes(*, ensure_ssl_host: str | None = None) -> None:
    """Hot-apply path mounts + nginx after endpoint CRUD.

    Always syncs legacy subscription nginx so domain/port/path edits take effect
    without a panel restart. SSL ensure is optional when a host is known.
    """
    try:
        from app import app
        from app.routers import api_router
        from app.subscription.route_registry import refresh_subscription_routes

        refresh_subscription_routes(app, api_router)
        from app.db import GetDB
        from app.services.edge_proxy import (
            ensure_subscription_domain_ssl,
            sync_subscription_legacy_nginx,
        )

        with GetDB() as db:
            # Path-only edits must rebuild nginx vhosts even when SSL is already OK.
            sync_subscription_legacy_nginx(db)
            host = (ensure_ssl_host or "").strip() or None
            if host:
                ensure_subscription_domain_ssl(db, host)
    except Exception:
        import logging

        logging.getLogger("nexus-sub-endpoints").exception(
            "subscription route/nginx refresh failed"
        )
