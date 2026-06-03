from datetime import datetime as dt
from datetime import timedelta as td

from app import logger, scheduler
from config import BACKUP_INTERVAL_HOURS


def scheduled_backup() -> None:
    from app.backup import create_backup

    try:
        create_backup()
    except Exception:
        logger.exception("Scheduled backup failed")


if BACKUP_INTERVAL_HOURS > 0:
    logger.info("Scheduled backups enabled (every %d hour(s))", BACKUP_INTERVAL_HOURS)
    from app.ha import run_if_leader

    scheduler.add_job(
        run_if_leader(scheduled_backup),
        "interval",
        hours=BACKUP_INTERVAL_HOURS,
        start_date=dt.utcnow() + td(minutes=5),
        coalesce=True,
        max_instances=1,
    )
