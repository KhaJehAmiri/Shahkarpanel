"""Serve the Shahkar UI from dashboard-next static export only."""

import logging
from pathlib import Path

from app import app
from config import DASHBOARD_PATH
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

log = logging.getLogger("uvicorn.error")

_base = Path(__file__).parent.parent
_next_out = _base / "dashboard-next" / "out"
_dashboard_dir = _next_out / "dashboard"
_public_dir = _base / "dashboard-next" / "public"
_brand_dir = _next_out / "brand"
if not _brand_dir.is_dir():
    _brand_dir = _base / "dashboard-next" / "public" / "brand"


def _require_build() -> None:
    if (_dashboard_dir / "index.html").is_file():
        return
    log.error(
        "Dashboard build missing at %s — /dashboard/ will not work. "
        "Run: ./build_dashboard.sh",
        _dashboard_dir,
    )


def _ensure_spa_fallback(directory: Path) -> None:
    fallback = directory / "404.html"
    if fallback.is_file():
        return
    index = directory / "index.html"
    if index.is_file():
        try:
            fallback.write_text(index.read_text())
        except OSError:
            pass


def _favicon_path() -> Path | None:
    for candidate in (
        _next_out / "favicon.ico",
        _brand_dir / "favicon.ico",
        _base / "dashboard-next" / "public" / "favicon.ico",
    ):
        if candidate.is_file():
            return candidate
    return None


def _pwa_file(name: str) -> Path | None:
    for candidate in (_next_out / name, _public_dir / name):
        if candidate.is_file():
            return candidate
    return None


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    path = _favicon_path()
    if path is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404)
    return FileResponse(path)


@app.get("/portal/sw.js", include_in_schema=False)
async def portal_service_worker():
    path = _pwa_file("portal-sw.js")
    if path is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404)
    from fastapi.responses import Response

    return Response(
        content=path.read_text(encoding="utf-8"),
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/portal/",
            "Cache-Control": "no-cache",
        },
    )


@app.get("/portal/manifest.webmanifest", include_in_schema=False)
async def portal_web_manifest():
    """Installable user portal PWA (separate from admin dashboard)."""
    from fastapi.responses import JSONResponse

    body = {
        "id": "/portal/",
        "name": "Shahkar",
        "short_name": "Shahkar",
        "description": "خرید، تمدید و دریافت کانفیگ",
        "start_url": "/portal/?source=pwa",
        "scope": "/portal/",
        "display": "standalone",
        "display_override": ["standalone", "minimal-ui"],
        "background_color": "#0b1220",
        "theme_color": "#0b1220",
        "orientation": "portrait-primary",
        "lang": "fa",
        "dir": "rtl",
        "categories": ["utilities"],
        "prefer_related_applications": False,
        "icons": [
            {
                "src": "/brand/pwa-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": "/brand/pwa-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": "/brand/pwa-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "maskable",
            },
            {
                "src": "/brand/pwa-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }
    return JSONResponse(
        content=body,
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    path = _pwa_file("sw.js")
    if path is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404)
    # Inject real dashboard path so notification clicks open the panel.
    from app.middleware.dashboard_path import custom_dashboard_path

    text = path.read_text(encoding="utf-8")
    dash = custom_dashboard_path().rstrip("/") + "/"
    text = text.replace("__DASHBOARD_PATH__", dash)
    text = text.replace("/dashboard/#/billing", f"{dash}#/billing")
    from fastapi.responses import Response

    return Response(
        content=text,
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache",
        },
    )


@app.get("/manifest.webmanifest", include_in_schema=False)
async def web_manifest():
    """Dynamic manifest so start_url matches DASHBOARD_PATH (custom secret path)."""
    from app.middleware.dashboard_path import custom_dashboard_path
    from fastapi.responses import JSONResponse

    dash = custom_dashboard_path()
    body = {
        "id": f"{dash.rstrip('/')}/",
        "name": "Shahkar",
        "short_name": "Shahkar",
        "description": "Shahkar control plane",
        "start_url": f"{dash}?source=pwa",
        "scope": dash,
        "display": "standalone",
        "display_override": ["standalone", "minimal-ui", "browser"],
        "background_color": "#0b1220",
        "theme_color": "#0b1220",
        "orientation": "any",
        "lang": "fa",
        "dir": "rtl",
        "categories": ["business", "utilities"],
        "prefer_related_applications": False,
        "icons": [
            {
                "src": "/brand/pwa-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": "/brand/pwa-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": "/brand/pwa-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "maskable",
            },
            {
                "src": "/brand/pwa-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
            {
                "src": "/brand/apple-touch-icon.png",
                "sizes": "180x180",
                "type": "image/png",
                "purpose": "any",
            },
        ],
    }
    return JSONResponse(
        content=body,
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@app.on_event("startup")
def startup() -> None:
    _require_build()
    if not (_dashboard_dir / "index.html").is_file():
        return

    _ensure_spa_fallback(_dashboard_dir)
    log.info("Serving Shahkar dashboard from %s (dashboard-next)", _dashboard_dir)

    sub_static = _base / "templates" / "subscription" / "static"
    if sub_static.is_dir():
        app.mount(
            "/sub-assets",
            StaticFiles(directory=sub_static),
            name="subscription-assets",
        )

    brand_dir = _next_out / "brand"
    if not brand_dir.is_dir():
        brand_dir = _base / "dashboard-next" / "public" / "brand"
    if brand_dir.is_dir():
        app.mount("/brand", StaticFiles(directory=brand_dir), name="brand-assets")

    if (_next_out / "index.html").is_file():
        _ensure_spa_fallback(_next_out)
        log.info("Serving subscription UI from %s", _next_out / "subscribe")
        app.mount(
            "/subscribe",
            StaticFiles(directory=_next_out / "subscribe", html=True),
            name="next-subscribe",
        )
        portal_dir = _next_out / "portal"
        if portal_dir.is_dir():
            _ensure_spa_fallback(portal_dir)
            log.info("Serving user portal from %s", portal_dir)
            app.mount(
                "/portal",
                StaticFiles(directory=portal_dir, html=True),
                name="next-portal",
            )
        next_chunks = _next_out / "_next"
        if next_chunks.is_dir():
            app.mount(
                "/_next",
                StaticFiles(directory=next_chunks),
                name="next-chunks",
            )
        next_fonts = _next_out / "fonts"
        if next_fonts.is_dir():
            app.mount(
                "/fonts",
                StaticFiles(directory=next_fonts),
                name="next-fonts",
            )

    app.mount(
        DASHBOARD_PATH,
        StaticFiles(directory=_dashboard_dir, html=True),
        name="dashboard",
    )
