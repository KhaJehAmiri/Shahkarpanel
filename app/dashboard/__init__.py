"""Serve the NexusPanel UI from dashboard-next static export only."""

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


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    path = _favicon_path()
    if path is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404)
    return FileResponse(path)


@app.on_event("startup")
def startup() -> None:
    _require_build()
    if not (_dashboard_dir / "index.html").is_file():
        return

    _ensure_spa_fallback(_dashboard_dir)
    log.info("Serving NexusPanel dashboard from %s (dashboard-next)", _dashboard_dir)

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
