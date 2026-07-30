"""Hide or remap the default /dashboard/ mount when a custom DASHBOARD_PATH is set."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse

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
    """PWA / bookmarks may still open /dashboard/ — send them to the real path."""
    if uses_custom_dashboard_path():
        path = request.url.path
        if path == "/dashboard" or path.startswith("/dashboard/"):
            dest = custom_dashboard_path()
            # Preserve hash is client-only; keep query string.
            if request.url.query:
                dest = f"{dest}?{request.url.query}"
            # Sub-path under /dashboard/... → map onto custom root (SPA).
            return RedirectResponse(url=dest, status_code=302)
    return await call_next(request)
