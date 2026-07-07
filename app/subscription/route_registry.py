"""Register subscription routers for each configured path prefix."""
from __future__ import annotations

import logging
from typing import Set

from fastapi import APIRouter, FastAPI

from config import XRAY_SUBSCRIPTION_PATH

logger = logging.getLogger("uvicorn.error")
_registered_prefixes: Set[str] = set()


def _load_path_prefixes() -> set[str]:
    from app.db import GetDB, crud

    prefixes = {XRAY_SUBSCRIPTION_PATH.strip("/")}
    try:
        with GetDB() as db:
            for ep in crud.list_subscription_endpoints(db, enabled_only=True):
                p = (ep.path_prefix or "").strip().strip("/")
                if p:
                    prefixes.add(p)
    except Exception:
        logger.exception("Failed to load subscription path prefixes from DB")
    return prefixes


def _clone_subscription_router(path_prefix: str) -> APIRouter:
    """Build a subscription router for a non-default path prefix."""
    from app.routers import subscription as sub_mod

    router = APIRouter(tags=["Subscription"], prefix=f"/{path_prefix}")
    for route in sub_mod.router.routes:
        router.routes.append(route)
    return router


def register_extra_subscription_routes(app: FastAPI, api_router: APIRouter) -> None:
    """Mount subscription routers for legacy 3x-ui path prefixes (json, clash, sub-vpn, …)."""
    global _registered_prefixes
    default = XRAY_SUBSCRIPTION_PATH.strip("/")
    _registered_prefixes.add(default)

    for prefix in _load_path_prefixes():
        if prefix in _registered_prefixes:
            continue
        _registered_prefixes.add(prefix)
        extra = _clone_subscription_router(prefix)
        api_router.include_router(extra)
        logger.info("Registered subscription routes at /%s/", prefix)


def refresh_subscription_routes(app: FastAPI, api_router: APIRouter) -> None:
    """Re-scan DB and register any new path prefixes (after endpoint CRUD or migration)."""
    default = XRAY_SUBSCRIPTION_PATH.strip("/")
    for prefix in _load_path_prefixes():
        if prefix not in _registered_prefixes:
            _registered_prefixes.add(prefix)
            if prefix != default:
                extra = _clone_subscription_router(prefix)
                api_router.include_router(extra)
                app.include_router(extra)
                logger.info("Registered new subscription routes at /%s/", prefix)
