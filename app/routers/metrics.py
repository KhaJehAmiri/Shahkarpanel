from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST

from app import feature_flags
from app.db import Session, get_db
from app.metrics import render_metrics
from app.models.admin import Admin
from config import METRICS_TOKEN

router = APIRouter(tags=["Metrics"], prefix="/api")


def _authorize(request: Request, db: Session) -> None:
    """Allow METRICS_TOKEN or sudo admin bearer token (header only — not query)."""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()

    if METRICS_TOKEN and token == METRICS_TOKEN:
        return

    admin = Admin.get_admin(token, db) if token else None
    if not admin or not admin.is_sudo:
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(request: Request, db: Session = Depends(get_db)):
    """Prometheus metrics endpoint. Gated by the `prometheus_metrics` flag."""
    if not feature_flags.is_enabled("prometheus_metrics"):
        raise HTTPException(status_code=404, detail="Metrics endpoint is disabled")

    _authorize(request, db)
    return PlainTextResponse(render_metrics(), media_type=CONTENT_TYPE_LATEST)
