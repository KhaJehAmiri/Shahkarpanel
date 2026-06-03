import atexit
import os
import subprocess
from pathlib import Path

from app import app
from config import DEBUG, VITE_BASE_API, DASHBOARD_PATH
from fastapi.staticfiles import StaticFiles

base_dir = Path(__file__).parent

# Phase 9: prefer Next.js static export (dashboard-next/out/dashboard) when built.
# Falls back to dashboard-v2, then legacy dashboard build.
_next_dashboard = base_dir.parent / 'dashboard-next' / 'out' / 'dashboard'
_v2_build = base_dir.parent / 'dashboard-v2' / 'build'
_legacy_build = base_dir / 'build'

if (_next_dashboard / 'index.html').is_file():
    build_dir = _next_dashboard
    statics_dir = None  # Next.js uses /_next/ for assets
elif (_v2_build / 'index.html').is_file():
    build_dir = _v2_build
    statics_dir = build_dir / 'statics'
else:
    build_dir = _legacy_build
    statics_dir = build_dir / 'statics'


def build():
    proc = subprocess.Popen(
        ['npm', 'run', 'build', '--',  '--outDir', build_dir, '--assetsDir', 'statics'],
        env={**os.environ, 'VITE_BASE_API': VITE_BASE_API},
        cwd=base_dir
    )
    proc.wait()
    with open(build_dir / 'index.html', 'r') as file:
        html = file.read()
    with open(build_dir / '404.html', 'w') as file:
        file.write(html)


def run_dev():
    proc = subprocess.Popen(
        ['npm', 'run', 'dev', '--', '--host', '0.0.0.0', '--clearScreen', 'false', '--base', os.path.join(DASHBOARD_PATH, '')],
        env={**os.environ, 'VITE_BASE_API': VITE_BASE_API},
        cwd=base_dir
    )

    atexit.register(proc.terminate)


def run_build():
    import logging
    log = logging.getLogger("uvicorn.error")
    if not (build_dir / 'index.html').is_file():
        log.error(
            "Dashboard build missing at %s — API will start but /dashboard/ will not work. "
            "Fix: ./build_dashboard.sh && docker compose up -d --build",
            build_dir,
        )
        return

    # SPA fallback for deep links (Starlette serves 404.html in html mode).
    fallback = build_dir / '404.html'
    if not fallback.is_file():
        try:
            fallback.write_text((build_dir / 'index.html').read_text())
        except OSError:
            pass

    using_next = (_next_dashboard / 'index.html').is_file()
    log.info(
        "Serving NexusPanel dashboard from %s (%s)",
        build_dir,
        "Next.js" if using_next else "Vite/legacy",
    )

    # Subscription page assets (graphical sub page, phase 8). Must be mounted
    # before the dashboard catch-all so the path is reachable.
    sub_static = base_dir.parent / 'templates' / 'subscription' / 'static'
    if sub_static.is_dir():
        app.mount(
            '/sub-assets',
            StaticFiles(directory=sub_static),
            name="subscription-assets",
        )

    # Phase 9: serve the Next.js static export. When the build is present,
    # /subscribe/ becomes the canonical subscription page; /sub/<token>/ HTML
    # responses redirect into it. The Next.js bundle is fully static (no Node).
    next_build = base_dir.parent / 'dashboard-next' / 'out'
    if (next_build / 'index.html').is_file():
        log.info("Serving NexusPanel Next.js bundle from %s", next_build)
        app.mount(
            '/subscribe',
            StaticFiles(directory=next_build / 'subscribe', html=True),
            name="next-subscribe",
        )
        next_chunks = next_build / '_next'
        if next_chunks.is_dir():
            app.mount(
                '/_next',
                StaticFiles(directory=next_chunks),
                name="next-chunks",
            )
        next_fonts = next_build / 'fonts'
        if next_fonts.is_dir():
            app.mount(
                '/fonts',
                StaticFiles(directory=next_fonts),
                name="next-fonts",
            )

    app.mount(
        DASHBOARD_PATH,
        StaticFiles(directory=build_dir, html=True),
        name="dashboard"
    )
    if statics_dir and statics_dir.is_dir():
        app.mount(
            '/statics/',
            StaticFiles(directory=statics_dir, html=True),
            name="statics"
        )


@app.on_event("startup")
def startup():
    if DEBUG:
        run_dev()
    else:
        run_build()
