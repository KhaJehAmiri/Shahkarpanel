"""Serve the NexusPanel UI from dashboard-next static export only."""

import logging
from pathlib import Path

from app import app
from config import DASHBOARD_PATH
from fastapi.staticfiles import StaticFiles

log = logging.getLogger("uvicorn.error")

_base = Path(__file__).parent.parent
_next_out = _base / "dashboard-next" / "out"
_dashboard_dir = _next_out / "dashboard"


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

    if (_next_out / "index.html").is_file():
        _ensure_spa_fallback(_next_out)
        log.info("Serving subscription UI from %s", _next_out / "subscribe")
        app.mount(
            "/subscribe",
            StaticFiles(directory=_next_out / "subscribe", html=True),
            name="next-subscribe",
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
