"""Unauthenticated liveness / readiness probes for ops (LB, Docker, uptime).

Intentionally minimal: no version, no dependency names, no error details.
Status is conveyed by HTTP code only (200 vs 503).
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from config import REDIS_URL

router = APIRouter(tags=["Health"], prefix="/api")


def _db_ok() -> bool:
    try:
        from sqlalchemy import text

        from app.db import GetDB

        with GetDB() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _redis_ok() -> bool:
    if not REDIS_URL:
        return True
    try:
        import redis

        client = redis.from_url(REDIS_URL, socket_connect_timeout=1.5, socket_timeout=1.5)
        try:
            return bool(client.ping())
        finally:
            try:
                client.close()
            except Exception:
                pass
    except Exception:
        return False


@router.get("/health")
def liveness(response: Response):
    """Process is up. Body is opaque; use the status code."""
    response.headers["Cache-Control"] = "no-store"
    return JSONResponse({"ok": True})


@router.get("/health/ready")
def readiness(response: Response):
    """Dependencies reachable. 200 = ready, 503 = not ready. No internals leaked."""
    response.headers["Cache-Control"] = "no-store"
    if _db_ok() and _redis_ok():
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False}, status_code=503)
