"""Register subscription routers for each configured path prefix."""
from __future__ import annotations

import logging
from typing import Set

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

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


def _relative_sub_path(path: str) -> str:
    """Strip the default ``/sub`` prefix if FastAPI already baked it into path."""
    default = "/" + XRAY_SUBSCRIPTION_PATH.strip("/")
    if path == default:
        return "/"
    if path.startswith(default + "/"):
        return path[len(default) :] or "/"
    return path


def _clone_subscription_router(path_prefix: str) -> APIRouter:
    """Build an independent subscription router for a non-default path prefix.

    Route objects must not be shared with the default ``/sub`` router — Starlette
    binds them on first include, so appending the same instances left ``/info``
    (and ``/json`` / ``/clash``) registered in logs but unreachable.

    After the default router is included, ``APIRoute.path`` may already contain
    ``/sub/...``; strip that so we mount ``/info/{token}`` not ``/info/sub/{token}``.
    """
    from app.routers import subscription as sub_mod

    router = APIRouter(tags=["Subscription"], prefix=f"/{path_prefix}")
    for route in sub_mod.router.routes:
        if not isinstance(route, APIRoute):
            continue
        # Unique name avoids collisions with the default /sub routes in OpenAPI.
        name = route.name
        if name:
            name = f"{path_prefix}:{name}"
        rel_path = _relative_sub_path(route.path)
        router.add_api_route(
            path=rel_path,
            endpoint=route.endpoint,
            response_model=route.response_model,
            status_code=route.status_code,
            tags=list(route.tags or []) or None,
            dependencies=list(route.dependencies or []),
            summary=route.summary,
            description=route.description,
            response_description=route.response_description,
            responses=dict(route.responses or {}),
            deprecated=route.deprecated,
            methods=list(route.methods or []),
            operation_id=None,
            response_model_include=route.response_model_include,
            response_model_exclude=route.response_model_exclude,
            response_model_by_alias=route.response_model_by_alias,
            response_model_exclude_unset=route.response_model_exclude_unset,
            response_model_exclude_defaults=route.response_model_exclude_defaults,
            response_model_exclude_none=route.response_model_exclude_none,
            include_in_schema=route.include_in_schema,
            response_class=route.response_class,
            name=name,
            callbacks=route.callbacks,
            openapi_extra=route.openapi_extra,
            generate_unique_id_function=route.generate_unique_id_function,
        )
    return router


def _unmount_prefix(app: FastAPI, prefix: str) -> None:
    """Drop live routes for a path prefix that no enabled endpoint uses anymore."""
    default = XRAY_SUBSCRIPTION_PATH.strip("/")
    if prefix == default:
        return
    root = f"/{prefix}"
    name_prefix = f"{prefix}:"
    kept = []
    removed = 0
    for route in list(app.router.routes):
        path = getattr(route, "path", None) or ""
        name = getattr(route, "name", None) or ""
        # Only remove routes we mounted (named ``{prefix}:…``) under ``/{prefix}/…``.
        if name.startswith(name_prefix) and (path == root or path.startswith(root + "/")):
            removed += 1
            continue
        kept.append(route)
    if removed:
        app.router.routes[:] = kept
        logger.info("Unregistered subscription routes at /%s/ (%s routes)", prefix, removed)
    _registered_prefixes.discard(prefix)


def _mount_prefix(app: FastAPI, api_router: APIRouter, prefix: str) -> None:
    """Mount a path prefix on the live app (api_router alone is too late after include)."""
    if prefix in _registered_prefixes:
        return
    default = XRAY_SUBSCRIPTION_PATH.strip("/")
    _registered_prefixes.add(prefix)
    if prefix == default:
        return
    extra = _clone_subscription_router(prefix)
    # Prefer app mount; api_router is already included at import time.
    app.include_router(extra)
    logger.info("Registered subscription routes at /%s/", prefix)


def register_extra_subscription_routes(app: FastAPI, api_router: APIRouter) -> None:
    """Mount subscription routers for legacy 3x-ui path prefixes (json, clash, info, …)."""
    global _registered_prefixes
    default = XRAY_SUBSCRIPTION_PATH.strip("/")
    _registered_prefixes.add(default)

    for prefix in sorted(_load_path_prefixes()):
        _mount_prefix(app, api_router, prefix)


def refresh_subscription_routes(app: FastAPI, api_router: APIRouter) -> None:
    """Re-scan DB: mount new prefixes and drop orphans after path/domain edits."""
    wanted = _load_path_prefixes()
    default = XRAY_SUBSCRIPTION_PATH.strip("/")
    for prefix in list(_registered_prefixes):
        if prefix != default and prefix not in wanted:
            _unmount_prefix(app, prefix)
    for prefix in sorted(wanted):
        if prefix not in _registered_prefixes:
            _mount_prefix(app, api_router, prefix)
            if prefix != default:
                logger.info("Registered new subscription routes at /%s/", prefix)
