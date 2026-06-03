import logging

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from config import ALLOWED_ORIGINS, DOCS, LOG_JSON, XRAY_SUBSCRIPTION_PATH
from app.utils.logging import RequestContextMiddleware, setup_structured_logging

__version__ = "0.8.4"
PRODUCT_NAME = "NexusPanel"

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)
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
