import logging
import warnings

# APScheduler still imports pkg_resources; silence the setuptools deprecation noise.
warnings.filterwarnings(
    "ignore",
    message=".*pkg_resources is deprecated.*",
    category=UserWarning,
)

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRoute

from starlette.exceptions import HTTPException as StarletteHTTPException

from config import ALLOWED_ORIGINS, CORS_ALLOW_CREDENTIALS, DOCS, LOG_JSON, XRAY_SUBSCRIPTION_PATH
from app.utils.logging import RequestContextMiddleware, setup_structured_logging

def _read_version() -> str:
    from pathlib import Path

    vf = Path(__file__).resolve().parents[1] / "VERSION"
    if vf.is_file():
        return vf.read_text(encoding="utf-8").strip()
    return "0.9.0"


__version__ = _read_version()
PRODUCT_NAME = "NexusPanel"


def panel_version() -> str:
    """Installed panel version (reads VERSION file each call — safe after in-dashboard git pull)."""
    return _read_version()

app = FastAPI(
    title="NexusPanel API",
    description="NexusPanel — professional proxy management platform powered by Xray",
    version=__version__,
    docs_url="/docs" if DOCS else None,
    redoc_url="/redoc" if DOCS else None,
)

scheduler = BackgroundScheduler(
    {"apscheduler.job_defaults.max_instances": 20}, timezone="UTC"
)
logger = logging.getLogger("uvicorn.error")

if ALLOWED_ORIGINS:
    _cors_credentials = CORS_ALLOW_CREDENTIALS and "*" not in ALLOWED_ORIGINS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=_cors_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
app.add_middleware(RequestContextMiddleware)

from app.middleware.dashboard_path import hide_default_dashboard_middleware  # noqa: E402

app.middleware("http")(hide_default_dashboard_middleware)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response
from app import dashboard, jobs, routers, telegram  # noqa
from app.routers import api_router  # noqa

app.include_router(api_router)


def use_route_names_as_operation_ids(app: FastAPI) -> None:
    for route in app.routes:
        if isinstance(route, APIRoute):
            route.operation_id = route.name


use_route_names_as_operation_ids(app)


@app.on_event("startup")
def on_startup():
    setup_structured_logging(LOG_JSON)
    try:
        from app.db.base import engine
        from app.tracing import setup_tracing
        setup_tracing(app, engine)
    except Exception:
        logger.exception("Failed to set up tracing")
    paths = [f"{r.path}/" for r in app.routes]
    paths.append("/api/")
    if f"/{XRAY_SUBSCRIPTION_PATH}/" in paths:
        raise ValueError(
            f"you can't use /{XRAY_SUBSCRIPTION_PATH}/ as subscription path it reserved for {app.title}"
        )
    try:
        from app.ha import start as ha_start
        ha_start()
    except Exception:
        logger.exception("Failed to start HA leader election")
    try:
        from app.db import GetDB
        from app.tenant import ensure_reseller_tenants
        with GetDB() as db:
            n = ensure_reseller_tenants(db)
            if n:
                logger.info("Backfilled tenant_id for %s legacy reseller/support admin(s)", n)
    except Exception:
        logger.exception("Failed to backfill reseller tenants")
    scheduler.start()


@app.on_event("shutdown")
def on_shutdown():
    scheduler.shutdown()
    try:
        from app.ha import stop as ha_stop
        ha_stop()
    except Exception:
        pass


@app.exception_handler(RequestValidationError)
def validation_exception_handler(request: Request, exc: RequestValidationError):
    details = {}
    for error in exc.errors():
        details[error["loc"][-1]] = error.get("msg")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder({"detail": details}),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code != 404:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    path = request.url.path
    accept = request.headers.get("accept", "")
    if path.startswith("/api") or "application/json" in accept:
        return JSONResponse(status_code=404, content={"detail": exc.detail})
    try:
        from app.templates import render_template
        return HTMLResponse(render_template("errors/404.html"), status_code=404)
    except Exception:
        return JSONResponse(status_code=404, content={"detail": exc.detail})
