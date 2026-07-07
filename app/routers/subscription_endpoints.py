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
    return crud.list_subscription_endpoints(db)


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
    _refresh_routes()
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
    _refresh_routes()
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


def _refresh_routes() -> None:
    try:
        from app import app
        from app.routers import api_router
        from app.subscription.route_registry import refresh_subscription_routes

        refresh_subscription_routes(app, api_router)
        from app.services.edge_proxy import sync_subscription_legacy_nginx
        from app.db import GetDB

        with GetDB() as db:
            sync_subscription_legacy_nginx(db)
    except Exception:
        pass
