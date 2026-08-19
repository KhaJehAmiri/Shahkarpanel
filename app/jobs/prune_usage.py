"""Drop old hourly per-user usage rows so Postgres cannot grow without bound.

``node_user_usages`` / ``node_user_protocol_usages`` were written every 15s
and never pruned. At 20–30k users that is hundreds of MB and a SUM over
30 days on Overview every 20s.
"""
from datetime import datetime, timedelta

from app import logger, scheduler
from app.db import GetDB
from app.db.models import NodeUserProtocolUsage, NodeUserUsage
from app.ha import run_if_leader
from config import JOB_USAGE_RETENTION_DAYS

_BATCH = 8000


def _delete_older_than(model, cutoff: datetime) -> int:
    deleted = 0
    with GetDB() as db:
        while True:
            ids = [
                row[0]
                for row in db.query(model.id)
                .filter(model.created_at < cutoff)
                .limit(_BATCH)
                .all()
            ]
            if not ids:
                break
            n = (
                db.query(model)
                .filter(model.id.in_(ids))
                .delete(synchronize_session=False)
            )
            db.commit()
            deleted += int(n or 0)
            if len(ids) < _BATCH:
                break
    return deleted


def prune_usage_history() -> None:
    days = int(JOB_USAGE_RETENTION_DAYS or 0)
    if days <= 0:
        return
    cutoff = datetime.utcnow() - timedelta(days=days)
    proto = _delete_older_than(NodeUserProtocolUsage, cutoff)
    hourly = _delete_older_than(NodeUserUsage, cutoff)
    if proto or hourly:
        logger.info(
            "pruned usage history older than %sd: protocol=%s node_user=%s",
            days,
            proto,
            hourly,
        )


scheduler.add_job(
    run_if_leader(prune_usage_history),
    "interval",
    hours=6,
    start_date=datetime.utcnow() + timedelta(minutes=3),
    coalesce=True,
    max_instances=1,
    id="prune_usage_history",
    replace_existing=True,
)
