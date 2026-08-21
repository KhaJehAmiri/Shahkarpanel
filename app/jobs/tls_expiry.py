"""Keep sing-box TLS metadata current and warn before certificates expire."""
import logging
from datetime import datetime, timedelta

from app.db import GetDB
from app.db.models import Node, NodeSingBox

logger = logging.getLogger("shahkar-tls-expiry")

WARN_DAYS = 7
REFRESH_HOURS = 6


def _refresh_node_tls_metadata() -> None:
    """Re-read every node's certificate so share links match reality.

    ``tls_trusted`` decides whether hy2/tuic/anytls links carry ``insecure=1``.
    Without this sweep the flag only ever changes when an admin opens the node
    TLS page, so a node that gained a real certificate keeps advertising
    skip-verify links (and a node that lost one keeps advertising strict ones).
    """
    from app.singbox.tls import refresh_node_tls

    with GetDB() as db:
        nodes = db.query(Node).join(NodeSingBox, NodeSingBox.node_id == Node.id).all()
        for dbnode in nodes:
            try:
                refresh_node_tls(db, dbnode)
            except Exception as exc:  # noqa: BLE001 - one bad node must not stop the sweep
                logger.warning("TLS refresh failed for node %s: %s", dbnode.id, exc)


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

    scheduler.add_job(
        _refresh_node_tls_metadata,
        "interval",
        hours=REFRESH_HOURS,
        id="tls_metadata_refresh",
        coalesce=True,
    )
    scheduler.add_job(_check_tls_expiry, "cron", hour=4, minute=15, id="tls_expiry_check")
except Exception:
    pass
