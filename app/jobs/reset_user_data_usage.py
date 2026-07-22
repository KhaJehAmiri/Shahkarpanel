from datetime import datetime, timedelta

from sqlalchemy import and_, or_

from app import logger, scheduler, xray
from app.db import GetDB, crud
from app.db.models import User
from app.models.user import UserDataLimitResetStrategy, UserStatus

reset_strategy_to_days = {
    UserDataLimitResetStrategy.day.value: 1,
    UserDataLimitResetStrategy.week.value: 7,
    UserDataLimitResetStrategy.month.value: 30,
    UserDataLimitResetStrategy.year.value: 365,
}


def reset_user_data_usage():
    """Reset periodic traffic quotas without scanning the whole user table.

    Candidates are filtered in SQL by reset strategy; a single core sync runs
    after the batch so high-volume panels do not schedule N reconciles.
    """
    now = datetime.utcnow()
    reset_count = 0
    need_core_sync = False

    with GetDB() as db:
        strategies = list(reset_strategy_to_days.keys())
        q = (
            db.query(User)
            .filter(
                User.status.in_([UserStatus.active, UserStatus.limited]),
                User.data_limit_reset_strategy.in_(strategies),
            )
            .yield_per(500)
        )
        for user in q:
            num_days = reset_strategy_to_days.get(user.data_limit_reset_strategy)
            if not num_days:
                continue
            last_reset = user.last_traffic_reset_time
            if last_reset is None:
                continue
            if (now - last_reset).days < num_days:
                continue
            crud.reset_user_data_usage(db, user)
            reset_count += 1
            if user.status == UserStatus.active:
                need_core_sync = True
            logger.info('User data usage reset for User "%s"', user.username)

    if need_core_sync:
        try:
            xray.operations.sync_core_users_async()
        except Exception:
            logger.exception("post-reset core sync failed")
    if reset_count:
        logger.info("Periodic usage reset finished for %s user(s)", reset_count)


from app.ha import run_if_leader  # noqa: E402

scheduler.add_job(run_if_leader(reset_user_data_usage), 'interval', coalesce=True, hours=1)
