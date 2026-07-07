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


def effective_backup_interval_hours() -> int:
    from app.utils.runtime_settings import backup_interval_hours

    return backup_interval_hours()


def reschedule_backup_job() -> None:
    """Apply current backup interval to the scheduler."""
    from app.ha import run_if_leader

    hours = effective_backup_interval_hours()
    try:
        scheduler.remove_job("scheduled_backup")
    except Exception:
        pass
    if hours <= 0:
        logger.info("Scheduled backups disabled")
        return
    scheduler.add_job(
        run_if_leader(scheduled_backup),
        "interval",
        hours=hours,
        start_date=dt.utcnow() + td(minutes=5),
        coalesce=True,
        max_instances=1,
        id="scheduled_backup",
        replace_existing=True,
    )
    logger.info("Scheduled backups enabled (every %d hour(s))", hours)


if BACKUP_INTERVAL_HOURS > 0 or effective_backup_interval_hours() > 0:
    reschedule_backup_job()
