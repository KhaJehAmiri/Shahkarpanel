"""Hide the default /dashboard/ mount when a custom DASHBOARD_PATH is configured."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from config import DASHBOARD_PATH

_DEFAULT = "/dashboard/"


def _norm(path: str) -> str:
    p = (path or _DEFAULT).strip()
    if not p.startswith("/"):
        p = f"/{p}"
    if not p.endswith("/"):
        p = f"{p}/"
    return p


def custom_dashboard_path() -> str:
    return _norm(DASHBOARD_PATH)


def uses_custom_dashboard_path() -> bool:
    return custom_dashboard_path().rstrip("/") != _DEFAULT.rstrip("/")


async def hide_default_dashboard_middleware(request: Request, call_next):
    if uses_custom_dashboard_path():
        path = request.url.path
        if path == "/dashboard" or path.startswith("/dashboard/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
    return await call_next(request)
