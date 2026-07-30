"""Warn when sing-box Let's Encrypt certificates are close to expiry."""
import logging
from datetime import datetime, timedelta

from app.db import GetDB
from app.db.models import NodeSingBox

logger = logging.getLogger("shahkar-tls-expiry")

WARN_DAYS = 7


def _check_tls_expiry() -> None:
    threshold = datetime.utcnow() + timedelta(days=WARN_DAYS)
    with GetDB() as db:
        rows = (
            db.query(NodeSingBox)
            .filter(NodeSingBox.tls_expires_at.isnot(None))
            .all()
        )
        for cfg in rows:
            if cfg.tls_expires_at and cfg.tls_expires_at <= threshold:
                logger.warning(
                    "sing-box TLS on node %s expires at %s (LE target=%s kind=%s)",
                    cfg.node_id,
                    cfg.tls_expires_at.isoformat(),
                    cfg.tls_le_domain,
                    cfg.tls_le_kind,
                )


try:
    from app import scheduler

    scheduler.add_job(_check_tls_expiry, "cron", hour=4, minute=15, id="tls_expiry_check")
except Exception:
    pass
