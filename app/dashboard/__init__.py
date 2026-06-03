import atexit
import os
import subprocess
from pathlib import Path

from app import app
from config import DEBUG, VITE_BASE_API, DASHBOARD_PATH
from fastapi.staticfiles import StaticFiles

base_dir = Path(__file__).parent

# Phase 7: prefer the new NexusPanel dashboard (dashboard-v2) when it has been
# built. Falls back to the legacy build so the panel keeps working either way.
_v2_build = base_dir.parent / 'dashboard-v2' / 'build'
build_dir = _v2_build if (_v2_build / 'index.html').is_file() else base_dir / 'build'
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

    log.info("Serving NexusPanel dashboard from %s", build_dir)
    # Subscription page assets (graphical sub page, phase 8). Must be mounted
    # before the dashboard catch-all so the path is reachable.
    sub_static = base_dir.parent / 'templates' / 'subscription' / 'static'
    if sub_static.is_dir():
        app.mount(
            '/sub-assets',
            StaticFiles(directory=sub_static),
            name="subscription-assets",
        )
    app.mount(
        DASHBOARD_PATH,
        StaticFiles(directory=build_dir, html=True),
        name="dashboard"
    )
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
