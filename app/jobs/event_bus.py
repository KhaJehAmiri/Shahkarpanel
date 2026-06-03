from datetime import datetime as dt
from datetime import timedelta as td

from app import logger, scheduler
from app.db import GetDB
from app.events import Event, subscribe
from config import EVENTS_RETENTION_DAYS


def _persist_event(event: Event) -> None:
    """Record every published event in the durable audit log."""
    from app.db.models import Event as EventModel

    with GetDB() as db:
        db.add(EventModel(type=event.type.value, payload=event.payload or None))
        db.commit()


# Register the persistence subscriber once, at import time.
subscribe(_persist_event)


def cleanup_events() -> None:
    if EVENTS_RETENTION_DAYS <= 0:
        return

    from app.db.models import Event as EventModel

    cutoff = dt.utcnow() - td(days=EVENTS_RETENTION_DAYS)
    with GetDB() as db:
        deleted = (
            db.query(EventModel)
            .filter(EventModel.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
    if deleted:
        logger.debug("Pruned %d expired events from the audit log", deleted)


from app.ha import run_if_leader  # noqa: E402

scheduler.add_job(
    run_if_leader(cleanup_events),
    "interval",
    hours=6,
    start_date=dt.utcnow() + td(minutes=2),
    coalesce=True,
    max_instances=1,
)
